"""
اختبارات عزل النموذج اللغوي، والمعايرة، والمراجعة بعد الصفقة.

الفرضية التي تُختبَر هنا: **النموذج اللغوي لا يستطيع تغيير قرار، ولا إرسال أمر،
ولا إدخال رقم لم يُحسب حتمياً.** والمعايرة تقترح ولا تطبّق.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.contracts import Decision
from app.llm import (
    GuardResult,
    LlmIncident,
    LlmOutputGuard,
    LlmUnavailable,
    NullSummaryProvider,
    StaticSummaryProvider,
    extract_numbers,
    verified_numbers,
)
from app.llm.explain import morning_brief, why_no_trade, why_trade
from app.money import D
from app.profiles import ProfileLimits, TradingProfile
from app.review import (
    MIN_SAMPLE_FOR_INFERENCE,
    REQUIRED_STEPS_FOR_ANY_CHANGE,
    Calibrator,
    OutcomeClass,
    PostTradeRecord,
    ScoredOutcome,
    TradeMode,
    classify_outcome,
)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
FACTS = {
    "decision": "NO_TRADE",
    "all_in_risk": "0.52",
    "quality_score": 92,
    "profile_max_risk": "0.75",
    "net_reward_risk": "1.90",
}


# ---------------------------------------------------------------------------
# استخراج الأرقام
# ---------------------------------------------------------------------------

def test_numbers_are_extracted_from_free_text():
    assert D("0.52") in extract_numbers("الخسارة 0.52 دولار")
    assert D("92") in extract_numbers("الدرجة 92 من 100")


def test_timeframe_tokens_are_not_treated_as_numbers():
    numbers = extract_numbers("الإطار H4 و M15 و D1")
    assert D("4") not in numbers
    assert D("15") not in numbers


def test_verified_numbers_accepts_equivalent_decimal_forms():
    allowed = verified_numbers({"risk": "0.50"})
    assert D("0.5") in allowed or D("0.5").normalize() in allowed
    assert D("0.50") in allowed


# ---------------------------------------------------------------------------
# اختلاق الأرقام
# ---------------------------------------------------------------------------

def test_invented_number_is_flagged_and_the_summary_is_discarded():
    guard = LlmOutputGuard()
    result = guard.check(
        "الخسارة المتوقعة 3.75 دولار وهو رقم ممتاز.",
        facts=FACTS,
        deterministic_decision="NO_TRADE",
        fallback_text="النص القالبي الحتمي",
        now=NOW,
    )
    assert LlmIncident.HALLUCINATION_DETECTED in result.incidents
    assert result.used_llm is False
    assert result.text == "النص القالبي الحتمي"
    assert "3.75" in result.invented_numbers


def test_a_summary_using_only_verified_numbers_is_accepted():
    guard = LlmOutputGuard()
    result = guard.check(
        "لا صفقة. الخسارة المحسوبة 0.52 دولار والدرجة 92.",
        facts=FACTS,
        deterministic_decision="NO_TRADE",
        fallback_text="fallback",
        now=NOW,
    )
    assert result.used_llm is True
    assert result.incidents == ()


def test_hallucination_incident_is_recorded_without_sensitive_data():
    log: list[dict] = []
    guard = LlmOutputGuard(incident_sink=log)
    guard.check(
        "الخسارة 9.99 دولار",
        facts=FACTS,
        deterministic_decision="NO_TRADE",
        fallback_text="fallback",
        now=NOW,
    )
    assert log
    entry = log[0]
    assert entry["incident"] == "HALLUCINATION_DETECTED"
    for forbidden in ("api_key", "password", "token", "identifier", "account_id"):
        assert forbidden not in entry


def test_hallucination_never_changes_the_underlying_decision():
    guard = LlmOutputGuard()
    result = guard.check(
        "الخسارة 8.88 دولار",
        facts=FACTS,
        deterministic_decision="NO_TRADE",
        fallback_text="fallback",
        now=NOW,
    )
    assert result.decision_changed is False


# ---------------------------------------------------------------------------
# مناقضة القرار الحتمي
# ---------------------------------------------------------------------------

def test_llm_contradicting_a_no_trade_decision_is_discarded():
    guard = LlmOutputGuard()
    result = guard.check(
        "الفرصة ممتازة، ندخل الآن.",
        facts=FACTS,
        deterministic_decision="NO_TRADE",
        fallback_text="القرار الحتمي: لا صفقة",
        now=NOW,
    )
    assert LlmIncident.LLM_CONTRADICTION in result.incidents
    assert result.text == "القرار الحتمي: لا صفقة"
    assert result.decision_changed is False


def test_llm_contradicting_a_halted_decision_is_discarded():
    guard = LlmOutputGuard()
    result = guard.check(
        "افتحي صفقة الآن.",
        facts={},
        deterministic_decision="HALTED",
        fallback_text="متوقف",
        now=NOW,
    )
    assert LlmIncident.LLM_CONTRADICTION in result.incidents


def test_contradiction_is_recorded_with_the_deterministic_decision():
    log: list[dict] = []
    guard = LlmOutputGuard(incident_sink=log)
    guard.check(
        "نشتري الآن", facts={}, deterministic_decision="NO_TRADE",
        fallback_text="x", now=NOW,
    )
    assert log[0]["deterministic_decision"] == "NO_TRADE"


# ---------------------------------------------------------------------------
# غياب النموذج
# ---------------------------------------------------------------------------

def test_missing_llm_produces_the_deterministic_template_and_continues():
    guard = LlmOutputGuard()
    result = guard.explain(
        NullSummaryProvider(),
        prompt="اشرحي",
        facts=FACTS,
        deterministic_decision="NO_TRADE",
        fallback_text="القالب الحتمي",
        now=NOW,
    )
    assert LlmIncident.LLM_UNAVAILABLE in result.incidents
    assert result.text == "القالب الحتمي"
    assert result.used_llm is False


def test_a_crashing_provider_is_treated_as_unavailable_not_as_an_error():
    guard = LlmOutputGuard()
    result = guard.explain(
        StaticSummaryProvider(RuntimeError("عطل غير متوقع")),
        prompt="اشرحي",
        facts=FACTS,
        deterministic_decision="NO_TRADE",
        fallback_text="القالب",
        now=NOW,
    )
    assert result.text == "القالب"
    assert LlmIncident.LLM_UNAVAILABLE in result.incidents


def test_empty_summary_falls_back():
    guard = LlmOutputGuard()
    result = guard.check(
        "   ", facts=FACTS, deterministic_decision="NO_TRADE",
        fallback_text="القالب", now=NOW,
    )
    assert LlmIncident.LLM_EMPTY in result.incidents


# ---------------------------------------------------------------------------
# القيود البنيوية
# ---------------------------------------------------------------------------

def test_the_llm_package_imports_nothing_that_can_trade():
    import app.llm as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)

    for name in imported:
        assert "broker" not in name.lower()
        assert "execution" not in name.lower()
        assert "killswitch" not in name.lower()
        assert "risk" not in name.lower()


def test_no_llm_component_can_return_a_decision():
    """
    عقد المزوّد يعيد `str` وحده. لا يوجد شكل إرجاع يسمح بقرار أو رقم مُهيكل.
    """
    from app.llm import SummaryProvider

    sig = inspect.signature(SummaryProvider.summarize)
    # `from __future__ import annotations` يجعل التوصيف نصاً — نقارن بالاسم.
    assert sig.return_annotation in (str, "str")


def test_guard_result_never_reports_a_changed_decision():
    for text, decision in (
        ("ندخل", "NO_TRADE"),
        ("الخسارة 9.99", "NO_TRADE"),
        ("لا صفقة والخسارة 0.52", "NO_TRADE"),
    ):
        r = LlmOutputGuard().check(
            text, facts=FACTS, deterministic_decision=decision,
            fallback_text="x", now=NOW,
        )
        assert r.decision_changed is False


def test_deterministic_templates_contain_only_supplied_numbers():
    text = why_no_trade(
        decision_code="QUALITY_BELOW_PROFILE_THRESHOLD",
        primary_reason_ar="الدرجة دون العتبة.",
        score=84,
        threshold=85,
    )
    guard = LlmOutputGuard()
    result = guard.check(
        text,
        facts={"score": 84, "threshold": 85, "max": 100},
        deterministic_decision="NO_TRADE",
        fallback_text="x",
        now=NOW,
    )
    assert result.incidents == ()


def test_why_no_trade_explains_rather_than_looking_broken():
    text = why_no_trade(
        decision_code="MISSING_CRITICAL_DATA",
        primary_reason_ar="حقل حرج غير معلوم.",
        missing_data=["bid"],
        missing_providers=["EconomicCalendarProvider"],
    )
    assert "سلوك سليم وليس عطلاً" in text
    assert "EconomicCalendarProvider" in text
    assert "bid" in text


def test_why_trade_always_separates_notional_margin_and_risk():
    text = why_trade(
        strategy_key="TREND_PULLBACK@1.0.0",
        regime_ar="اتجاه",
        direction_ar="شراء",
        entry="1.08546",
        stop="1.08046",
        take_profit="1.09546",
        notional="108.55",
        margin="1.09",
        all_in_risk="0.52",
        reward_risk="1.90",
        score=92,
        threshold=85,
        profile_name_ar="متوازن",
        profile_max_risk="0.75",
    )
    assert "قيمة التعرّض: 108.55" in text
    assert "الهامش المحجوز (ليس خسارة): 1.09" in text
    assert "الخسارة النقدية عند الوقف: 0.52" in text


def test_morning_brief_lists_missing_providers():
    text = morning_brief(
        date_riyadh="٢٠٢٦-٠٨-٢٨",
        profile_name_ar="متحفّظ",
        market_status_ar="مفتوح",
        regime_ar="اتجاه",
        missing_providers=["MacroDataProvider"],
    )
    assert "MacroDataProvider" in text


# ---------------------------------------------------------------------------
# المراجعة بعد الصفقة
# ---------------------------------------------------------------------------

def _record(**overrides) -> PostTradeRecord:
    base = dict(
        trade_id="T-1",
        mode=TradeMode.SHADOW,
        opened_at_utc=NOW,
        closed_at_utc=NOW,
        snapshot_id="abc123",
        strategy_key="TREND_PULLBACK@1.0.0",
        profile=TradingProfile.BALANCED,
        entry_reason_ar="ارتداد داخل اتجاه صاعد.",
        contradictions_considered_ar=("لا تناقض مادي",),
        expected_costs=D("0.016"),
        actual_costs=D("0.018"),
        expected_slippage=D("0.010"),
        actual_slippage=D("0.014"),
        max_favorable_excursion=D("0.31"),
        max_adverse_excursion=D("0.22"),
        exit_reason_ar="بلوغ الوقف.",
        outcome_money=D("-0.52"),
        outcome_r=D("-1.00"),
        followed_strategy_rules=True,
        broker_matched_local_expectation=True,
        llm_explanation_accurate=True,
        outcome_class=OutcomeClass.VALID_LOSS,
    )
    base.update(overrides)
    return PostTradeRecord(**base)


def test_post_trade_record_captures_every_required_field():
    d = _record().as_dict()
    for key in (
        "snapshot_id", "strategy_key", "profile", "entry_reason_ar",
        "contradictions_considered_ar", "expected_costs", "actual_costs",
        "expected_slippage", "actual_slippage", "max_favorable_excursion",
        "max_adverse_excursion", "exit_reason_ar", "outcome_money", "outcome_r",
        "followed_strategy_rules", "broker_matched_local_expectation",
        "llm_explanation_accurate", "outcome_class", "lessons_research_only_ar",
    ):
        assert key in d


def test_cost_and_slippage_variance_are_computed():
    r = _record()
    assert r.cost_variance == D("0.002")
    assert r.slippage_variance == D("0.004")


def test_not_every_loss_is_a_strategy_failure():
    cls = classify_outcome(
        followed_rules=True, broker_matched=True, data_was_valid=True,
        regime_was_compatible=True, abnormal_event=False, outcome_money=D("-0.52"),
    )
    assert cls is OutcomeClass.VALID_LOSS
    assert cls is not OutcomeClass.STRATEGY_MISMATCH


def test_execution_failure_takes_priority_over_a_profitable_outcome():
    cls = classify_outcome(
        followed_rules=True, broker_matched=False, data_was_valid=True,
        regime_was_compatible=True, abnormal_event=False, outcome_money=D("2.00"),
    )
    assert cls is OutcomeClass.EXECUTION_FAILURE


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(data_was_valid=False), OutcomeClass.DATA_FAILURE),
        (dict(followed_rules=False), OutcomeClass.RULE_VIOLATION),
        (dict(regime_was_compatible=False), OutcomeClass.STRATEGY_MISMATCH),
        (dict(abnormal_event=True), OutcomeClass.ABNORMAL_MARKET_EVENT),
    ],
)
def test_outcome_classification_covers_every_declared_class(kwargs, expected):
    base = dict(
        followed_rules=True, broker_matched=True, data_was_valid=True,
        regime_was_compatible=True, abnormal_event=False, outcome_money=D("-1.00"),
    )
    base.update(kwargs)
    assert classify_outcome(**base) is expected


# ---------------------------------------------------------------------------
# المعايرة
# ---------------------------------------------------------------------------

def test_small_sample_produces_no_inference():
    outcomes = [
        ScoredOutcome(90, "TREND_PULLBACK@1.0.0", OutcomeClass.VALID_LOSS, D("-1"))
        for _ in range(5)
    ]
    report = Calibrator().report(outcomes)
    band = next(b for b in report.bands if b.band == (90, 94))
    assert band.sufficient_sample is False
    assert any("لا استنتاج" in r for r in report.research_recommendations_ar)


def test_sufficient_sample_produces_a_research_only_recommendation():
    outcomes = [
        ScoredOutcome(90, "TREND_PULLBACK@1.0.0", OutcomeClass.VALID_LOSS, D("-1"))
        for _ in range(MIN_SAMPLE_FOR_INFERENCE)
    ]
    report = Calibrator().report(outcomes)
    assert report.applied_automatically is False
    assert any("بحث فقط" in r for r in report.research_recommendations_ar)
    assert any("لا يُغيَّر معامل حي" in r for r in report.research_recommendations_ar)


def test_calibration_never_applies_anything_automatically():
    report = Calibrator().report([])
    d = report.as_dict()
    assert d["applied_automatically"] is False
    assert "موافقة المالكة" in d["note_ar"]


def test_calibrator_cannot_change_risk_parameters_or_thresholds():
    """
    المعاير لا يملك ميثوداً واحداً يعدّل شيئاً، ولا يستورد الدستور ولا الملفات.
    """
    forbidden = (
        "increase_risk", "set_risk", "change_parameter", "set_threshold",
        "enable_strategy", "disable_kill_switch", "widen_stop", "add_indicator",
        "select_profile", "apply",
    )
    for name in forbidden:
        assert not hasattr(Calibrator, name)

    import app.review as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)
    assert not any("constitution" in n for n in imported)
    assert not any("killswitch" in n for n in imported)
    assert not any("registry" in n for n in imported)


def test_any_change_requires_the_full_validation_path():
    for step in (
        "Backtest جديد",
        "Walk-forward جديد",
        "اختبار خارج العينة جديد",
        "فترة Shadow Mode جديدة",
        "موافقة صريحة من المالكة",
    ):
        assert step in REQUIRED_STEPS_FOR_ANY_CHANGE


def test_calibration_reports_rule_violations_as_engineering_faults():
    outcomes = [
        ScoredOutcome(90, "TREND_PULLBACK@1.0.0", OutcomeClass.RULE_VIOLATION, D("-1"))
        for _ in range(3)
    ]
    report = Calibrator().report(outcomes)
    assert any("خلل تنفيذي يُصلَح بالكود" in r for r in report.research_recommendations_ar)
