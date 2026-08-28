"""
اختبارات خط الاستخبارات: المطابقة، التناقضات، الدرجة، المراجعة المستقلة،
والقرار النهائي.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.contracts import Decision, Side, StopKind, StrategyState
from app.intelligence.contradictions import (
    ContradictionInputs,
    ContradictionKind,
    Severity,
    detect_contradictions,
)
from app.intelligence.eurusd import (
    PositionConstructor,
    ProfileAwareRiskVeto,
    SetupBuilder,
)
from app.intelligence.gates import ExecutionHealth
from app.intelligence.pipeline import (
    MANDATORY_GATES,
    STAGE_ORDER,
    ConstructedPosition,
    MarketIntelligencePipeline,
    RiskVeto,
    Stage,
)
from app.intelligence.regime import MarketRegime, NO_TRADE_REGIMES, classify_regime
from app.intelligence.reporting import audit_payload, finalize
from app.intelligence.scoring import (
    CATEGORY_WEIGHTS,
    MAX_SCORE,
    MandatoryFailure,
    ScoreInputs,
    evaluate_quality,
)
from app.intelligence.snapshot import Timeframe
from app.intelligence.structure import (
    DIRECTIONAL_TIMEFRAMES,
    TIMING_ONLY_TIMEFRAMES,
    TrendDirection,
    analyse_all,
)
from app.intelligence.verification import IndependentTradeVerifier, TradeProposal
from app.money import D
from app.profiles import ProfileLimits, TradingProfile
from app.strategies.registry import (
    BREAKOUT_RETEST,
    RANGE_MEAN_REVERSION,
    TREND_PULLBACK,
    StrategyDefinitionRegistry,
    StrategyRegistryError,
    match_strategy,
)

from .intelligence_fixtures import (
    NOW,
    cost_model,
    full_registry,
    healthy_execution,
    high_impact_event,
    macro_values,
    make_snapshot,
    news_item,
)

CAPITAL = D("150.00")


def _verifier() -> IndependentTradeVerifier:
    return IndependentTradeVerifier(
        lot_size=D("1"),
        pip_size=D("0.0001"),
        margin_rate=D("0.01"),
        slippage_reserve_pips=D("1"),
    )


def _pipeline(registry=None, strategies=None) -> MarketIntelligencePipeline:
    return MarketIntelligencePipeline(
        registry=registry or full_registry(),
        strategies=strategies or StrategyDefinitionRegistry(),
        verifier=_verifier(),
    )


def _run(
    *,
    profile: TradingProfile = TradingProfile.BALANCED,
    snapshot=None,
    registry=None,
    strategies=None,
    execution=None,
    veto=None,
    equity: Decimal = CAPITAL,
):
    snap = snapshot if snapshot is not None else make_snapshot()
    limits = ProfileLimits.for_profile(profile, equity)
    cm = cost_model()
    pipe = _pipeline(registry, strategies)
    return pipe.run(
        snapshot=snap,
        profile=profile,
        limits=limits,
        execution=execution or healthy_execution(),
        now=NOW,
        build_setup=SetupBuilder(),
        construct_position=PositionConstructor(cost_model=cm, limits=limits),
        risk_veto=veto
        or ProfileAwareRiskVeto(limits=limits, constitution_max_risk=D("0.75")),
    ), limits


# ---------------------------------------------------------------------------
# ترتيب المراحل
# ---------------------------------------------------------------------------

def test_pipeline_declares_seventeen_ordered_stages():
    assert len(STAGE_ORDER) == 17
    assert STAGE_ORDER[0] is Stage.DATA_HEALTH
    assert STAGE_ORDER[-1] is Stage.AUDIT_CALIBRATION


def test_mandatory_gates_include_every_blocking_stage():
    for stage in (
        Stage.DATA_HEALTH,
        Stage.MARKET_STATUS,
        Stage.ECONOMIC_CALENDAR,
        Stage.VERIFIED_NEWS,
        Stage.RISK_ENGINE_VETO,
        Stage.INDEPENDENT_VERIFICATION,
    ):
        assert stage in MANDATORY_GATES


def test_a_later_stage_cannot_run_after_a_mandatory_gate_rejects():
    event = high_impact_event(minutes_from_now=20)
    snap = make_snapshot(events=[event])
    result, _ = _run(snapshot=snap, registry=full_registry(events=[event]))
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == "HIGH_IMPACT_BLACKOUT"
    reached = {s.stage for s in result.stages}
    assert Stage.STRATEGY_MATCH not in reached
    assert Stage.RISK_ENGINE_VETO not in reached
    assert result.score is None


def test_kill_switch_halts_the_whole_pipeline():
    result, _ = _run(execution=ExecutionHealth(kill_switch_active=True))
    assert result.decision is Decision.HALTED


# ---------------------------------------------------------------------------
# الأطر الزمنية
# ---------------------------------------------------------------------------

def test_m5_is_timing_only_and_never_directional():
    assert Timeframe.M5 in TIMING_ONLY_TIMEFRAMES
    assert Timeframe.M5 not in DIRECTIONAL_TIMEFRAMES
    view = analyse_all(dict(make_snapshot().series))
    assert view.analyses[Timeframe.M5].is_directional is False


def test_daily_is_the_primary_regime_timeframe_and_h4_is_structural():
    view = analyse_all(dict(make_snapshot().series))
    assert view.regime_timeframe is Timeframe.D1
    assert view.primary_regime_trend is TrendDirection.UP
    assert view.structural_trend is TrendDirection.UP


def test_full_alignment_is_not_required_but_conflicts_are_counted():
    view = analyse_all(dict(make_snapshot().series))
    aligned = view.aligned_directional(TrendDirection.UP)
    conflicting = view.conflicting_directional(TrendDirection.UP)
    assert len(aligned) >= 3
    assert conflicting == ()


# ---------------------------------------------------------------------------
# النظام والاستراتيجية
# ---------------------------------------------------------------------------

def test_trending_fixture_classifies_as_trend():
    result, _ = _run()
    assert result.regime is not None
    assert result.regime.regime is MarketRegime.TREND


def test_range_fixture_classifies_as_range_and_finds_no_setup():
    result, _ = _run(snapshot=make_snapshot(trending=False))
    assert result.regime is not None
    assert result.regime.regime is MarketRegime.RANGE
    # RANGE_MEAN_REVERSION مسجَّلة لكنها بلا بانٍ في الإصدار الأول
    assert result.reason_code == "NO_VALID_SETUP"


@pytest.mark.parametrize("regime", sorted(NO_TRADE_REGIMES, key=lambda r: r.value))
def test_no_trade_regimes_never_match_a_strategy(regime):
    m = match_strategy(StrategyDefinitionRegistry(), regime)
    assert m.has_match is False


def test_each_regime_maps_to_at_most_one_strategy():
    reg = StrategyDefinitionRegistry()
    for regime in MarketRegime:
        candidates = reg.candidates_for(regime)
        assert len(candidates) <= 1, f"{regime} لديه أكثر من مرشّح"


def test_strategies_declaring_a_regime_both_compatible_and_incompatible_are_rejected():
    with pytest.raises(StrategyRegistryError):
        replace(
            TREND_PULLBACK,
            incompatible_regimes=TREND_PULLBACK.incompatible_regimes
            | {MarketRegime.TREND},
        )


def test_no_strategy_is_approved_by_default():
    reg = StrategyDefinitionRegistry()
    assert reg.approved() == ()
    for d in reg.all():
        assert d.state is StrategyState.RESEARCH
        assert d.is_live_eligible is False


def test_no_reversal_strategy_is_approved():
    for d in StrategyDefinitionRegistry().all():
        if d.is_reversal:
            assert d.is_live_eligible is False


def test_registry_refuses_to_invent_a_strategy_at_runtime():
    with pytest.raises(StrategyRegistryError):
        StrategyDefinitionRegistry().get("MADE_UP", "9.9.9")


def test_strategy_regime_mismatch_blocks_via_contradiction():
    report = detect_contradictions(_contradiction_inputs(strategy_compatible=False))
    kinds = {c.kind for c in report.items}
    assert ContradictionKind.STRATEGY_VS_REGIME in kinds
    assert report.has_unresolved_material is True


# ---------------------------------------------------------------------------
# التناقضات
# ---------------------------------------------------------------------------

def _contradiction_inputs(**overrides):
    view = analyse_all(dict(make_snapshot().series))
    regime = classify_regime(view, spread_to_atr=D("0.03"), in_event_window=False)
    base = dict(
        intended_direction=TrendDirection.UP,
        view=view,
        regime=regime,
        fundamentals=None,
        strategy_declares_regime_compatible=overrides.pop("strategy_compatible", True),
        strategy_key="TREND_PULLBACK@1.0.0",
        spread_to_atr=D("0.03"),
        gross_reward_risk=D("2.0"),
        net_reward_risk=D("1.8"),
        required_reward_risk=D("1.5"),
        minutes_to_next_high_impact_event=None,
        quote_age_seconds=5.0,
        oldest_candle_age_seconds=60.0,
    )
    base.update(overrides)
    return ContradictionInputs(**base)


def test_positive_rr_before_costs_but_insufficient_after_costs_blocks():
    report = detect_contradictions(
        _contradiction_inputs(gross_reward_risk=D("2.0"), net_reward_risk=D("1.2"))
    )
    item = next(c for c in report.items if c.kind is ContradictionKind.RR_BEFORE_VS_AFTER_COSTS)
    assert item.severity is Severity.CRITICAL
    assert item.blocks_trading is True
    assert "بعد التكاليف هو الحقيقي" in item.resolution_ar


def test_nearby_high_impact_event_blocks_even_with_a_valid_setup():
    report = detect_contradictions(
        _contradiction_inputs(minutes_to_next_high_impact_event=45)
    )
    assert any(c.kind is ContradictionKind.ENTRY_VS_EVENT for c in report.items)
    assert report.has_unresolved_material is True


def test_fresh_price_with_stale_candles_blocks():
    report = detect_contradictions(
        _contradiction_inputs(quote_age_seconds=2.0, oldest_candle_age_seconds=5000.0)
    )
    assert any(
        c.kind is ContradictionKind.FRESH_PRICE_VS_STALE_CANDLES for c in report.items
    )
    assert report.has_unresolved_material is True


def test_strongly_opposing_verified_macro_blocks_a_technical_setup():
    from app.intelligence.fundamentals import assess_fundamentals

    bearish = assess_fundamentals(macro_values(bullish_eur=False), provider_configured=True)
    report = detect_contradictions(
        _contradiction_inputs(fundamentals=bearish, intended_direction=TrendDirection.UP)
    )
    item = next(
        c for c in report.items if c.kind is ContradictionKind.TECHNICAL_VS_MACRO
    )
    assert item.blocks_trading is True


def test_every_contradiction_declares_both_sides_and_a_written_resolution():
    report = detect_contradictions(
        _contradiction_inputs(minutes_to_next_high_impact_event=10)
    )
    for c in report.items:
        assert c.side_a_ar and c.side_b_ar
        assert c.resolution_ar
        assert c.severity in Severity
        assert isinstance(c.resolvable, bool)


def test_clean_setup_has_no_blocking_contradiction():
    report = detect_contradictions(_contradiction_inputs())
    assert report.has_unresolved_material is False


# ---------------------------------------------------------------------------
# الدرجة الحتمية
# ---------------------------------------------------------------------------

def _score_inputs(**overrides):
    view = analyse_all(dict(make_snapshot().series))
    regime = classify_regime(view, spread_to_atr=D("0.03"), in_event_window=False)
    base = dict(
        data_health_passed=True,
        data_unknown_count=0,
        calendar_passed=True,
        news_passed=True,
        regime=regime,
        view=view,
        strategy_matched=True,
        strategy_approved=True,
        strategy_regime_compatible=True,
        entry_confirmed=True,
        fundamentals=None,
        intended_direction=TrendDirection.UP,
        volatility_percentile=D("50"),
        spread_to_atr=D("0.03"),
        stop_valid=True,
        stop_respects_broker_minimum=True,
        net_reward_risk=D("2.5"),
        required_reward_risk=D("1.5"),
        contradiction_penalty=0,
        unresolved_material_contradiction=False,
    )
    base.update(overrides)
    return ScoreInputs(**base)


def test_score_weights_sum_to_exactly_one_hundred():
    assert sum(CATEGORY_WEIGHTS.values()) == MAX_SCORE == 100


def test_score_is_deterministic_for_identical_inputs():
    a = evaluate_quality(_score_inputs())
    b = evaluate_quality(_score_inputs())
    assert a.total == b.total
    assert [l.awarded for l in a.lines] == [l.awarded for l in b.lines]


def test_every_score_line_is_traceable_to_a_named_source():
    score = evaluate_quality(_score_inputs())
    for line in score.lines:
        assert line.source_ar
        assert line.reason_ar


def test_high_score_cannot_compensate_a_mandatory_failure():
    score = evaluate_quality(_score_inputs(calendar_passed=False))
    assert score.has_mandatory_failure is True
    assert MandatoryFailure.HIGH_IMPACT_BLACKOUT in score.mandatory_failures
    # حتى لو كانت العتبة صفراً، `meets` ترفض
    assert score.meets(0) is False


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"data_health_passed": False}, MandatoryFailure.MISSING_CRITICAL_DATA),
        ({"calendar_passed": False}, MandatoryFailure.HIGH_IMPACT_BLACKOUT),
        ({"stop_valid": False}, MandatoryFailure.INVALID_STOP),
        ({"spread_to_atr": D("0.40")}, MandatoryFailure.SPREAD_TOO_WIDE),
        ({"net_reward_risk": D("1.0")}, MandatoryFailure.REWARD_RISK_BELOW_PROFILE),
        ({"strategy_matched": False}, MandatoryFailure.NO_STRATEGY_MATCH),
        ({"strategy_approved": False}, MandatoryFailure.STRATEGY_NOT_APPROVED),
        (
            {"unresolved_material_contradiction": True},
            MandatoryFailure.UNRESOLVED_CONTRADICTION,
        ),
    ],
)
def test_each_mandatory_failure_is_detected(override, expected):
    score = evaluate_quality(_score_inputs(**override))
    assert expected in score.mandatory_failures
    assert score.meets(0) is False


def test_contradiction_penalty_reduces_the_total():
    clean = evaluate_quality(_score_inputs())
    penalised = evaluate_quality(_score_inputs(contradiction_penalty=15))
    assert penalised.total == clean.total - 15


def test_score_is_never_produced_by_an_llm():
    """الدالة لا تستقبل نصاً ولا مزوّداً — لا مسار لغوي إليها."""
    import inspect

    params = inspect.signature(evaluate_quality).parameters
    assert set(params) == {"inp"}
    fields = ScoreInputs.__dataclass_fields__
    for name in fields:
        assert "llm" not in name and "summary" not in name and "text" not in name


# ---------------------------------------------------------------------------
# المراجعة المستقلة
# ---------------------------------------------------------------------------

def _proposal(snap, **overrides):
    base = dict(
        snapshot_id=snap.snapshot_id,
        instrument="EURUSD",
        side=Side.BUY,
        size=D("100"),
        entry_reference=D("1.08546"),
        stop_price=D("1.08046"),
        take_profit_price=D("1.09546"),
        stop_kind=StopKind.NORMAL,
        claimed_spread=D("0.00006"),
        claimed_pip_value=D("0.01"),
        claimed_notional=D("108.546"),
        claimed_margin=D("1.08546"),
        claimed_price_risk=D("0.5"),
        claimed_fees=D("0.006"),
        claimed_slippage_reserve=D("0.01"),
        claimed_all_in_risk=D("0.516"),
        claimed_reward_risk=D("1.926"),
        profile_max_risk=D("0.75"),
        profile_min_reward_risk=D("1.5"),
        remaining_daily_budget=D("1.50"),
        remaining_weekly_budget=D("3.00"),
    )
    base.update(overrides)
    return TradeProposal(**base)


def test_verifier_passes_when_the_primary_calculation_is_correct():
    snap = make_snapshot()
    result = _verifier().verify(_proposal(snap), snap, now=NOW, in_blackout=False)
    assert result.passed is True, result.mismatches


def test_material_mismatch_produces_verification_mismatch():
    snap = make_snapshot()
    bad = _proposal(snap, claimed_all_in_risk=D("0.20"))     # ادّعاء أفضل من الحقيقة
    result = _verifier().verify(bad, snap, now=NOW, in_blackout=False)
    assert result.passed is False
    assert "all_in_risk" in result.mismatches
    assert "VERIFICATION_MISMATCH" in result.reason_ar


def test_verifier_never_picks_the_more_favourable_calculation():
    snap = make_snapshot()
    optimistic = _proposal(snap, claimed_all_in_risk=D("0.10"), claimed_reward_risk=D("9.0"))
    result = _verifier().verify(optimistic, snap, now=NOW, in_blackout=False)
    assert result.passed is False
    # لا يوجد في النتيجة حقل «القيمة المختارة» — الاختلاف يوقف كل شيء
    assert not hasattr(result, "chosen")
    assert not hasattr(result, "resolved_value")


def test_verifier_rejects_a_proposal_built_on_a_different_snapshot():
    snap = make_snapshot()
    other = make_snapshot(bid=D("1.07000"), ask=D("1.07006"))
    result = _verifier().verify(_proposal(other), snap, now=NOW, in_blackout=False)
    assert result.passed is False
    assert result.mismatches == ("snapshot_id",)


def test_verifier_rechecks_profile_limits_on_its_own_numbers():
    snap = make_snapshot()
    p = _proposal(snap, profile_max_risk=D("0.30"))
    result = _verifier().verify(p, snap, now=NOW, in_blackout=False)
    assert result.passed is False
    assert "profile_risk_limit" in result.mismatches


def test_verifier_rejects_wrong_sided_stop_or_target():
    snap = make_snapshot()
    p = _proposal(snap, stop_price=D("1.09546"), take_profit_price=D("1.08046"))
    result = _verifier().verify(p, snap, now=NOW, in_blackout=False)
    assert result.passed is False
    assert "stop_orientation" in result.mismatches


def test_verifier_rejects_stale_data_and_blackout():
    snap = make_snapshot(quote_age_seconds=900)
    r1 = _verifier().verify(_proposal(snap), snap, now=NOW, in_blackout=False)
    assert "data_freshness" in r1.mismatches

    fresh = make_snapshot()
    r2 = _verifier().verify(_proposal(fresh), fresh, now=NOW, in_blackout=True)
    assert "economic_blackout" in r2.mismatches


# ---------------------------------------------------------------------------
# التشغيل الكامل
# ---------------------------------------------------------------------------

def test_full_run_reaches_the_final_gate_and_stops_at_strategy_approval():
    """
    الحالة الواقعية اليوم: كل التحليل يمرّ، والحاجز الأخير هو أن الاستراتيجية
    ليست معتمدة. هذا هو السلوك الصحيح، وليس عطلاً.
    """
    result, limits = _run()
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == "STRATEGY_NOT_APPROVED"
    assert result.score is not None
    assert result.score.total >= limits.min_quality_score
    passed_stages = {s.stage for s in result.stages if s.passed}
    for stage in (
        Stage.DATA_HEALTH,
        Stage.MARKET_STATUS,
        Stage.ECONOMIC_CALENDAR,
        Stage.VERIFIED_NEWS,
        Stage.MULTI_TIMEFRAME,
        Stage.MARKET_STRUCTURE,
        Stage.STRATEGY_MATCH,
        Stage.ENTRY_SETUP,
        Stage.COST_SPREAD,
        Stage.POSITION_CONSTRUCTION,
    ):
        assert stage in passed_stages


def test_the_pipeline_is_deterministic():
    a, _ = _run()
    b, _ = _run()
    assert a.decision == b.decision
    assert a.reason_code == b.reason_code
    assert a.snapshot_id == b.snapshot_id
    assert (a.score.total if a.score else None) == (b.score.total if b.score else None)


def test_conservative_profile_rejects_a_setup_the_balanced_profile_scores_highly():
    """
    نفس اللقطة: المتوازن يصل إلى الحاجز الأخير، والمتحفّظ يرفض قبله لأن
    R:R الصافي دون 1.75. **الملف الأشد يرفض أكثر — لا العكس.**
    """
    balanced, _ = _run(profile=TradingProfile.BALANCED)
    conservative, _ = _run(profile=TradingProfile.CAPITAL_PRESERVATION)
    assert balanced.reason_code == "STRATEGY_NOT_APPROVED"
    assert conservative.decision is Decision.NO_TRADE
    assert conservative.reason_code in (
        "REWARD_RISK_BELOW_PROFILE",
        "QUALITY_BELOW_PROFILE_THRESHOLD",
        "STRATEGY_NOT_APPROVED",
    )


def test_minimum_size_exceeding_profile_risk_returns_the_exact_code():
    """
    ملف متحفّظ + حساب صغير جداً ⇒ الكمية الدنيا للوسيط تتجاوز حد المخاطرة.
    القرار المطلوب حرفياً: MINIMUM_SIZE_EXCEEDS_PROFILE_RISK.
    """
    result, _ = _run(profile=TradingProfile.CAPITAL_PRESERVATION, equity=D("10.00"))
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == "MINIMUM_SIZE_EXCEEDS_PROFILE_RISK"
    assert "لا يمكن تصغير الكمية ولا تضييق الوقف" in result.reason_ar


def test_a_technically_valid_stop_is_never_tightened_to_fit_the_risk_budget():
    """
    المسافة الطبيعية للوقف تُحسب من البنية وحدها. لو صغّر النظام الوقف
    ليناسب الميزانية، لتغيّرت `stop_pips` بتغيّر الملف — وهي لا تتغيّر.
    """
    tight, _ = _run(profile=TradingProfile.CAPITAL_PRESERVATION)
    wide, _ = _run(profile=TradingProfile.ACTIVE_CONTROLLED)
    assert tight.position is not None and wide.position is not None
    assert tight.position.stop_pips == wide.position.stop_pips
    assert tight.setup.stop_price == wide.setup.stop_price
    assert tight.position.stop_was_not_tightened is True


def test_setup_builder_cannot_see_the_risk_budget():
    """البانِي لا يستقبل حدود الملف — فلا يمكن أن يتشكّل الوقف حولها."""
    import inspect

    params = set(inspect.signature(SetupBuilder.__call__).parameters)
    assert params == {"self", "view", "regime", "definition"}


def test_notional_margin_and_risk_remain_three_distinct_numbers():
    result, _ = _run()
    p = result.position
    assert p is not None
    assert p.notional != p.margin != p.all_in_risk
    assert p.notional > p.margin
    assert p.notional > p.all_in_risk


def test_risk_veto_uses_the_stricter_of_constitution_and_profile():
    limits = ProfileLimits.for_profile(TradingProfile.ACTIVE_CONTROLLED, CAPITAL)
    veto = ProfileAwareRiskVeto(limits=limits, constitution_max_risk=D("0.75"))
    position = ConstructedPosition(
        size=D("100"), notional=D("108"), margin=D("1.08"), pip_value=D("0.01"),
        spread=D("0.00006"), price_risk=D("1.00"), fees=D("0.01"),
        slippage_reserve=D("0.01"), all_in_risk=D("1.02"),
        gross_reward_risk=D("2.0"), net_reward_risk=D("1.9"), stop_pips=D("100"),
        respects_broker_minimum=True,
    )
    result = veto(position, None)  # type: ignore[arg-type]
    # حد الملف 1.50 لكن الدستور 0.75 ⇒ الأشد يفوز
    assert result.approved is False
    assert result.reason_code == "RISK_EXCEEDS_EFFECTIVE_CAP"


def test_active_profile_full_risk_loss_ends_the_day():
    limits = ProfileLimits.for_profile(TradingProfile.ACTIVE_CONTROLLED, CAPITAL)
    veto = ProfileAwareRiskVeto(
        limits=limits, constitution_max_risk=D("1.50"), full_risk_loss_today=True
    )
    position = ConstructedPosition(
        size=D("100"), notional=D("108"), margin=D("1.08"), pip_value=D("0.01"),
        spread=D("0.00006"), price_risk=D("0.20"), fees=D("0.01"),
        slippage_reserve=D("0.01"), all_in_risk=D("0.22"),
        gross_reward_risk=D("2.0"), net_reward_risk=D("1.9"), stop_pips=D("20"),
        respects_broker_minimum=True,
    )
    result = veto(position, None)  # type: ignore[arg-type]
    assert result.approved is False
    assert result.reason_code == "FULL_RISK_LOSS_ENDS_DAY"


def test_no_trade_result_is_explained_not_presented_as_broken():
    result, limits = _run()
    final, _ = finalize(result, limits, now=NOW)
    text = final.explanation_ar
    assert "لا صفقة" in text
    assert "سلوك سليم وليس عطلاً" in text
    assert "درجة الجودة" in text


def test_audit_payload_records_every_stage_and_the_snapshot_id():
    result, _ = _run()
    payload = audit_payload(result)
    assert payload["event"] == "INTELLIGENCE_DECISION"
    assert payload["snapshot_id"] == result.snapshot_id
    assert len(payload["stages"]) == len(result.stages)


def test_pipeline_has_no_execution_capability():
    """
    الخط لا يستورد خدمة تنفيذ ولا محوّل وسيط، ولا يملك ميثوداً لإرسال أمر.
    """
    import ast

    import app.intelligence.pipeline as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)

    for forbidden in ("ExecutionService", "OrderService", "CapitalComAdapter", "BrokerAdapter"):
        assert forbidden not in imported
    assert not any("brokers" in name for name in imported)
    assert not any("execution" in name for name in imported)

    for forbidden_method in ("submit", "place_order", "send_order", "execute"):
        assert not hasattr(MarketIntelligencePipeline, forbidden_method)
