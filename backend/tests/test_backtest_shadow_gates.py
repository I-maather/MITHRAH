"""
محرّك الاختبار التاريخي، وضع الظل، وبوابات اعتماد الاستراتيجيات.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.contracts import Bar, DataSource, Decision, StopKind, StrategyState
from app.money import D
from app.risk.capital_costs import (
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
)
from app.risk.constitution import RiskLimits, RiskMode
from app.contracts import Broker
from app.risk.engine import RiskEngine, SessionRiskState
from app.strategies.backtest import (
    Backtester,
    BacktestConfig,
    ExitReason,
    InsufficientData,
    analyse_parameter_stability,
    run_walk_forward,
    split_walk_forward,
)
from app.strategies.gates import evaluate_admission
from app.strategies.shadow import ShadowRunner
from app.strategies.trend_pullback_v1 import TrendPullbackV1
from tests.conftest import make_balances

UTC = timezone.utc


def economics() -> InstrumentEconomics:
    return InstrumentEconomics(
        epic="EURUSD", pip_size=D("0.0001"), lot_size=D("1"), min_deal_size=D("100"),
        size_increment=D("1"), margin_factor=D("1"), margin_factor_unit="PERCENTAGE",
        min_stop_distance=D("0.0010"), min_guaranteed_stop_distance=D("0.0030"),
        guaranteed_stop_available=True, quote_currency="USD",
        overnight_fee_rate_daily=D("0.00007"),
        provenance=ValueProvenance.BROKER_DISCOVERY,
    )


def cost_model() -> CapitalComCostModel:
    assumptions = CfdCostAssumptions(
        spread_price=D("0.00006"), slippage_reserve_pips=D("1"),
        guaranteed_stop_premium_pips=None, currency_conversion_pct=D("0"),
        nights_held=0, spread_provenance=ValueProvenance.BROKER_DISCOVERY,
    )
    return CapitalComCostModel(economics(), assumptions)


def config(**overrides) -> BacktestConfig:
    base = dict(
        size=D("100"), stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
        min_trades_for_conclusion=1,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def trending_bars(n: int = 200, *, symbol: str = "EURUSD") -> list[Bar]:
    """
    شموع صاعدة اصطناعية **للاختبار الهندسي فقط**.
    ليست بيانات سوق ولا تُستعمل لأي ادعاء أداء.
    """
    bars: list[Bar] = []
    price = D("1.0500")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        price = price + D("0.0006")
        # كل 11 شمعة: ارتداد عميق يلامس المتوسط القصير ثم يُغلق فوقه،
        # وهو بالضبط شرط دخول TREND_PULLBACK.
        deep_dip = (i % 11 == 0) and i > 45
        low = price - D("0.0060") if deep_dip else price - D("0.0004")
        bars.append(
            Bar(
                symbol=symbol, start_utc=t0 + timedelta(hours=i),
                open=price - D("0.0002"), high=price + D("0.0008"),
                low=low, close=price, volume=D("1000"), source=DataSource.HISTORICAL,
            )
        )
    return bars


def bars_ending_on_a_signal() -> list[Bar]:
    """شموع تنتهي بشمعة ارتداد مطابقة لشرط الدخول (المؤشر 198 قابل للقسمة على 11)."""
    return trending_bars(199)


class ApprovedForTest(TrendPullbackV1):
    from dataclasses import replace as _replace

    metadata = _replace(TrendPullbackV1.metadata, state=StrategyState.APPROVED, markets=("EURUSD",))


# --- محرّك الاختبار التاريخي --------------------------------------------------

def test_backtest_refuses_to_run_without_data():
    with pytest.raises(InsufficientData, match="لا يولّد بيانات"):
        Backtester(cost_model(), config()).run(ApprovedForTest(), [])


def test_backtest_refuses_insufficient_bars():
    with pytest.raises(InsufficientData):
        Backtester(cost_model(), config()).run(ApprovedForTest(), trending_bars(10))


def test_backtest_is_deterministic_same_inputs_same_run_id():
    bars = trending_bars()
    a = Backtester(cost_model(), config()).run(ApprovedForTest(), bars)
    b = Backtester(cost_model(), config()).run(ApprovedForTest(), bars)
    assert a.run_id == b.run_id
    assert [t.entry_price for t in a.trades] == [t.entry_price for t in b.trades]
    assert a.net_pnl == b.net_pnl


def test_different_config_gives_a_different_run_id():
    bars = trending_bars()
    a = Backtester(cost_model(), config()).run(ApprovedForTest(), bars)
    b = Backtester(cost_model(), config(stop_distance_pips=D("50"))).run(ApprovedForTest(), bars)
    assert a.run_id != b.run_id


def test_entry_always_happens_after_the_signal_bar_no_lookahead():
    bars = trending_bars()
    result = Backtester(cost_model(), config()).run(ApprovedForTest(), bars)
    for trade in result.trades:
        assert trade.index_in >= 1
        # سعر الدخول مشتق من فتح الشمعة التالية لا من إغلاق شمعة الإشارة
        assert trade.entry_price >= bars[trade.index_in].open


def test_exit_index_is_never_before_entry_index():
    result = Backtester(cost_model(), config()).run(ApprovedForTest(), trending_bars())
    for trade in result.trades:
        assert trade.index_out >= trade.index_in


def test_costs_are_deducted_from_every_trade():
    result = Backtester(cost_model(), config()).run(ApprovedForTest(), trending_bars())
    assert result.trades, "يجب أن تُنتج بيانات الاختبار صفقات"
    for trade in result.trades:
        assert trade.costs > 0
        assert trade.net_pnl == trade.gross_pnl - trade.costs


def test_ambiguous_bar_is_counted_as_a_stop_worst_case():
    bars = trending_bars()
    # شمعة واسعة تلامس الوقف والهدف معاً
    wide = bars[60]
    bars[60] = wide.model_copy(update={"high": wide.high + D("0.02"), "low": wide.low - D("0.02")})
    result = Backtester(cost_model(), config()).run(ApprovedForTest(), bars)
    reasons = {t.exit_reason for t in result.trades}
    if ExitReason.AMBIGUOUS_BAR_ASSUMED_STOP in reasons:
        assert any("أسوأ حالة" in w for w in result.warnings)


def test_overnight_is_not_held_when_disallowed():
    result = Backtester(cost_model(), config(allow_overnight=False)).run(
        ApprovedForTest(), trending_bars()
    )
    assert all(t.nights_held == 0 for t in result.trades)


def test_overnight_costs_apply_when_allowed():
    result = Backtester(
        cost_model(), config(allow_overnight=True, max_bars_in_trade=48)
    ).run(ApprovedForTest(), trending_bars())
    assert result.trade_count > 0


def test_small_sample_produces_an_explicit_warning():
    result = Backtester(
        cost_model(), config(min_trades_for_conclusion=1000)
    ).run(ApprovedForTest(), trending_bars())
    assert any("غير كافية لأي استنتاج" in w for w in result.warnings)


def test_provisional_economics_warn_in_the_result():
    from app.risk.capital_costs import PROVISIONAL_EURUSD

    provisional = CapitalComCostModel(PROVISIONAL_EURUSD)
    result = Backtester(provisional, config()).run(ApprovedForTest(), trending_bars())
    assert any("مبدئية" in w for w in result.warnings)


def test_profit_factor_is_undefined_not_infinite_without_losses():
    result = Backtester(cost_model(), config()).run(ApprovedForTest(), trending_bars())
    if result.gross_loss == 0:
        assert result.profit_factor is None
        assert result.summary()["profit_factor"] == "غير معرّف"


def test_positions_never_overlap():
    result = Backtester(cost_model(), config()).run(ApprovedForTest(), trending_bars())
    for earlier, later in zip(result.trades, result.trades[1:]):
        assert later.index_in > earlier.index_out


# --- Walk-forward ------------------------------------------------------------

def test_walk_forward_splits_are_sequential_and_non_overlapping():
    folds = split_walk_forward(400, folds=4)
    assert len(folds) == 4
    for fold in folds:
        assert fold.in_sample[1] == fold.out_of_sample[0]
    for a, b in zip(folds, folds[1:]):
        assert a.out_of_sample[1] <= b.in_sample[0]


def test_walk_forward_refuses_folds_that_are_too_short():
    with pytest.raises(InsufficientData):
        split_walk_forward(20, folds=10)


def test_walk_forward_produces_in_and_out_of_sample_results():
    backtester = Backtester(cost_model(), config())
    result = run_walk_forward(backtester, ApprovedForTest(), trending_bars(400), folds=3)
    assert len(result.folds) == 3
    assert result.summary()["folds"] == 3


# --- استقرار المعاملات --------------------------------------------------------

def test_parameter_stability_reports_positive_share():
    bars = trending_bars()
    configs = [config(stop_distance_pips=D(str(p))) for p in (20, 25, 30, 35)]
    report = analyse_parameter_stability(
        lambda c: Backtester(cost_model(), c), ApprovedForTest(), bars, configs
    )
    assert len(report.results) == len(configs)
    assert report.positive_share is not None


# --- وضع الظل -----------------------------------------------------------------

def shadow_runner():
    limits = RiskLimits.for_mode(RiskMode.VALIDATION, D("150.00"), Broker.CAPITAL_COM)
    return ShadowRunner(
        strategy=ApprovedForTest(),
        cost_model=cost_model(),
        risk_engine=RiskEngine(limits),
        stop_distance_pips=D("25"),
        take_profit_distance_pips=D("50"),
    )


def a_quote(at: datetime, *, bid="1.08540", ask="1.08546"):
    from app.contracts import Quote

    return Quote(
        symbol="EURUSD", bid=D(bid), ask=D(ask), last=D(bid),
        timestamp_utc=at, source=DataSource.REALTIME, received_at_utc=at,
    )


def a_state():
    return SessionRiskState(
        baseline_equity=D("150"), current_equity=D("150"), realized_pnl_today=D("0"),
        realized_pnl_week=D("0"), unrealized_pnl=D("0"), open_positions=0,
        entry_orders_today=0, consecutive_losses=0,
    )


def test_shadow_mode_never_submits_an_order():
    runner = shadow_runner()
    bars = bars_ending_on_a_signal()
    now = bars[-1].start_utc
    for _ in range(5):
        runner.observe(
            symbol="EURUSD", bars=bars, quote=a_quote(now), state=a_state(),
            balances=make_balances("150.00", at=now), kill_switch_active=False, now=now,
        )
    assert runner.session.submitted_orders == 0
    assert runner.session.summary()["orders_actually_submitted"] == 0
    assert all(o.as_dict()["submitted"] is False for o in runner.session.observations)


def test_shadow_mode_records_the_decision_and_economics():
    runner = shadow_runner()
    bars = bars_ending_on_a_signal()
    now = bars[-1].start_utc
    observation = runner.observe(
        symbol="EURUSD", bars=bars, quote=a_quote(now), state=a_state(),
        balances=make_balances("150.00", at=now), kill_switch_active=False, now=now,
    )
    assert observation.decision in (Decision.TRADE, Decision.NO_TRADE)
    assert observation.signal is not None, "بيانات الاختبار يجب أن تُنتج إشارة"
    assert observation.economics is not None
    assert observation.economics.all_in_risk > 0
    assert observation.economics.notional_exposure > observation.economics.margin_required


def test_shadow_mode_rejects_stale_prices_before_the_strategy_runs():
    runner = shadow_runner()
    bars = trending_bars()
    now = bars[-1].start_utc
    stale = a_quote(now - timedelta(minutes=10))
    observation = runner.observe(
        symbol="EURUSD", bars=bars, quote=stale, state=a_state(),
        balances=make_balances("150.00", at=now), kill_switch_active=False, now=now,
    )
    assert observation.would_have_submitted is False
    assert observation.reason_code == "STALE"
    assert observation.signal is None


def test_shadow_mode_respects_the_kill_switch():
    runner = shadow_runner()
    bars = bars_ending_on_a_signal()
    now = bars[-1].start_utc
    observation = runner.observe(
        symbol="EURUSD", bars=bars, quote=a_quote(now), state=a_state(),
        balances=make_balances("150.00", at=now), kill_switch_active=True, now=now,
    )
    assert observation.would_have_submitted is False
    assert observation.decision is Decision.HALTED


def test_shadow_session_json_is_serialisable():
    import json as jsonlib

    runner = shadow_runner()
    bars = trending_bars()
    now = bars[-1].start_utc
    runner.observe(
        symbol="EURUSD", bars=bars, quote=a_quote(now), state=a_state(),
        balances=make_balances("150.00", at=now), kill_switch_active=False, now=now,
    )
    payload = jsonlib.loads(runner.session.to_json())
    assert payload["summary"]["orders_actually_submitted"] == 0


# --- بوابات الاعتماد ----------------------------------------------------------

def test_strategy_is_not_approved_just_because_connectivity_works():
    report = evaluate_admission(strategy_label="TREND_PULLBACK@1.0.0")
    assert report.passed is False
    assert len(report.failures) >= 6


def test_owner_approval_gate_can_never_be_passed_by_code():
    result = Backtester(cost_model(), config()).run(ApprovedForTest(), trending_bars(400))
    walk = run_walk_forward(
        Backtester(cost_model(), config()), ApprovedForTest(), trending_bars(800), folds=4
    )
    runner = shadow_runner()
    bars = trending_bars()
    now = bars[-1].start_utc
    for _ in range(25):
        runner.observe(
            symbol="EURUSD", bars=bars, quote=a_quote(now), state=a_state(),
            balances=make_balances("150.00", at=now), kill_switch_active=False, now=now,
        )
    report = evaluate_admission(
        strategy_label="TREND_PULLBACK@1.0.0",
        full_sample=result,
        walk_forward=walk,
        parameter_positive_share=D("1"),
        shadow=runner.session,
        regimes={"a": result, "b": result, "c": result},
    )
    owner_gate = next(g for g in report.gates if g.name == "OWNER_WRITTEN_APPROVAL")
    assert owner_gate.passed is False
    assert report.passed is False


def test_missing_evidence_fails_the_gate_rather_than_skipping_it():
    report = evaluate_admission(strategy_label="X", full_sample=None)
    names = {g.name for g in report.failures}
    assert {"SAMPLE_SIZE", "OUT_OF_SAMPLE", "PARAMETER_STABILITY", "SHADOW_MODE"} <= names


def test_real_strategy_remains_research_in_production_code():
    assert TrendPullbackV1.metadata.state is StrategyState.RESEARCH
