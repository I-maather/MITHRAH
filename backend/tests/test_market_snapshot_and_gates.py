"""
اختبارات اللقطة غير القابلة للتعديل، والمزوّدين، والبوابات الإلزامية.

**لا اختبار هنا يلمس الشبكة.** كل شيء من `intelligence_fixtures`.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.intelligence.fundamentals import (
    MIN_COMPLETENESS_FOR_CONFIDENCE,
    Bias,
    assess_fundamentals,
)
from app.intelligence.gates import (
    DEFAULT_BLACKOUTS,
    ExecutionHealth,
    HealthVerdict,
    run_calendar_gate,
    run_data_health_gate,
    run_market_status_gate,
    run_news_gate,
)
from app.intelligence.providers import (
    MANDATORY_FOR_LIVE,
    ProviderKind,
    ProviderRegistry,
    StaticCalendarProvider,
    StaticNewsProvider,
)
from app.intelligence.snapshot import (
    UNKNOWN,
    EventCategory,
    ImpactLevel,
    MarketStatus,
    NewsVerification,
    SnapshotMismatch,
    Sourced,
    Timeframe,
    assert_same_snapshot,
    is_unknown,
)
from app.money import D

from .intelligence_fixtures import (
    NOW,
    full_registry,
    healthy_execution,
    high_impact_event,
    low_impact_event,
    macro_values,
    make_snapshot,
    news_item,
)


# ---------------------------------------------------------------------------
# اللقطة
# ---------------------------------------------------------------------------

def test_snapshot_is_immutable():
    snap = make_snapshot()
    with pytest.raises(Exception):
        snap.instrument = "GBPUSD"       # type: ignore[misc]


def test_snapshot_id_is_content_addressed():
    a = make_snapshot()
    b = make_snapshot()
    assert a.snapshot_id == b.snapshot_id

    c = make_snapshot(bid=D("1.08000"), ask=D("1.08006"))
    assert c.snapshot_id != a.snapshot_id


def test_mixing_two_snapshots_in_one_cycle_is_rejected():
    a = make_snapshot()
    b = make_snapshot(bid=D("1.09000"), ask=D("1.09006"))
    assert assert_same_snapshot(a, a) == a.snapshot_id
    with pytest.raises(SnapshotMismatch):
        assert_same_snapshot(a, b)


def test_missing_critical_value_is_unknown_and_never_substituted():
    snap = make_snapshot(bid=None)
    assert not snap.bid.known
    assert is_unknown(snap.bid.value)
    assert is_unknown(snap.mid)
    assert "bid" in snap.unknown_critical_fields()


def test_every_field_carries_full_source_lineage():
    snap = make_snapshot()
    for field in (snap.bid, snap.ask, snap.spread, snap.market_status):
        d = field.as_dict()
        assert d["source"]
        assert d["source_timestamp_utc"]
        assert d["retrieved_at_utc"]
        assert d["reliability"]


def test_snapshot_exposes_checksums_for_every_timeframe():
    snap = make_snapshot()
    sums = snap.checksums()
    assert sums["snapshot_id"] == snap.snapshot_id
    assert set(sums["series"]) == {tf.value for tf in Timeframe}


def test_riyadh_time_is_derived_not_stored_separately():
    snap = make_snapshot()
    assert snap.captured_at_riyadh.utcoffset() == timedelta(hours=3)


# ---------------------------------------------------------------------------
# المزوّدون
# ---------------------------------------------------------------------------

def test_unconfigured_registry_reports_every_missing_provider_by_exact_name():
    reg = ProviderRegistry()
    names = reg.missing_names()
    assert "EconomicCalendarProvider" in names
    assert "VerifiedNewsProvider" in names
    assert "MacroDataProvider" in names
    assert "MarketDataProvider" in names
    assert "FundamentalContextProvider" in names


def test_missing_mandatory_provider_removes_live_eligibility():
    reg = ProviderRegistry()
    assert reg.live_eligible() is False
    assert set(reg.missing_mandatory()) == set(MANDATORY_FOR_LIVE)


def test_fully_configured_registry_is_live_eligible_by_providers():
    reg = full_registry()
    assert reg.live_eligible() is True
    assert reg.missing_mandatory() == ()


def test_unconfigured_calendar_returning_empty_does_not_mean_no_events():
    """قائمة فارغة من مزوّد غير مُعدّ تعني «لا نعرف»، والبوابة تسقط."""
    snap = make_snapshot()
    reg = ProviderRegistry()          # لا مزوّدين
    result = run_calendar_gate(snap, reg, now=NOW)
    assert result.passed is False
    assert result.provider_configured is False
    assert "لا نعرف" in result.reason_ar


# ---------------------------------------------------------------------------
# بوابة سلامة البيانات
# ---------------------------------------------------------------------------

def test_healthy_snapshot_passes_the_data_health_gate():
    result = run_data_health_gate(
        make_snapshot(), full_registry(), healthy_execution(), now=NOW
    )
    assert result.verdict is HealthVerdict.PASS
    assert result.live_eligible is True


def test_stale_quote_fails_the_gate():
    snap = make_snapshot(quote_age_seconds=600)
    result = run_data_health_gate(snap, full_registry(), healthy_execution(), now=NOW)
    assert result.live_eligible is False
    assert any(c.key == "QUOTE_FRESH" and not c.passed for c in result.checks)


def test_bid_above_ask_is_impossible_data_and_fails_hard():
    snap = make_snapshot(bid=D("1.08600"), ask=D("1.08500"))
    result = run_data_health_gate(snap, full_registry(), healthy_execution(), now=NOW)
    assert result.verdict is HealthVerdict.FAIL_NO_TRADE
    assert any(c.key == "BID_BELOW_ASK" and not c.passed for c in result.checks)


def test_impossible_ohlc_fails_hard():
    snap = make_snapshot(bad_ohlc=True)
    result = run_data_health_gate(snap, full_registry(), healthy_execution(), now=NOW)
    assert result.verdict is HealthVerdict.FAIL_NO_TRADE


def test_duplicate_bars_fail_hard():
    snap = make_snapshot(duplicate_bars=True)
    result = run_data_health_gate(snap, full_registry(), healthy_execution(), now=NOW)
    assert result.verdict is HealthVerdict.FAIL_NO_TRADE


def test_incomplete_timeframe_degrades_to_research_only():
    snap = make_snapshot(incomplete_timeframe=Timeframe.H4)
    result = run_data_health_gate(snap, full_registry(), healthy_execution(), now=NOW)
    assert result.verdict is HealthVerdict.DEGRADED_RESEARCH_ONLY
    assert result.live_eligible is False
    assert result.allows_research is True


def test_unknown_execution_blocks_everything():
    result = run_data_health_gate(
        make_snapshot(), full_registry(),
        ExecutionHealth(unknown_executions=1), now=NOW,
    )
    assert result.verdict is HealthVerdict.FAIL_NO_TRADE


def test_kill_switch_blocks_the_health_gate():
    result = run_data_health_gate(
        make_snapshot(), full_registry(),
        ExecutionHealth(kill_switch_active=True), now=NOW,
    )
    assert result.verdict is HealthVerdict.FAIL_NO_TRADE


# ---------------------------------------------------------------------------
# حالة السوق
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status",
    [MarketStatus.CLOSED, MarketStatus.WEEKEND, MarketStatus.HALTED, MarketStatus.PRE_OPEN],
)
def test_non_open_market_fails_the_status_gate(status):
    snap = make_snapshot(market_status=status)
    assert run_market_status_gate(snap).passed is False


def test_open_market_passes():
    assert run_market_status_gate(make_snapshot()).passed is True


# ---------------------------------------------------------------------------
# التقويم الاقتصادي
# ---------------------------------------------------------------------------

def test_high_impact_event_inside_the_window_blocks_trading():
    event = high_impact_event(minutes_from_now=30)
    snap = make_snapshot(events=[event])
    reg = full_registry(events=[event])
    result = run_calendar_gate(snap, reg, now=NOW)
    assert result.passed is False
    assert result.in_blackout is True
    assert result.blocking_events


def test_high_impact_event_after_release_still_blocks():
    event = high_impact_event(minutes_from_now=-20)      # صدر قبل 20 دقيقة
    snap = make_snapshot(events=[event])
    reg = full_registry(events=[event])
    assert run_calendar_gate(snap, reg, now=NOW).passed is False


def test_distant_high_impact_event_does_not_block_but_is_listed():
    event = high_impact_event(minutes_from_now=600)
    snap = make_snapshot(events=[event])
    reg = full_registry(events=[event])
    result = run_calendar_gate(snap, reg, now=NOW)
    assert result.passed is True
    assert result.upcoming


def test_low_impact_event_never_blocks():
    event = low_impact_event(minutes_from_now=5)
    snap = make_snapshot(events=[event])
    reg = full_registry(events=[event])
    assert run_calendar_gate(snap, reg, now=NOW).passed is True


def test_central_bank_decision_uses_a_longer_window_than_other_events():
    rate = DEFAULT_BLACKOUTS[EventCategory.CENTRAL_BANK_RATE]
    pmi = DEFAULT_BLACKOUTS[EventCategory.PMI]
    assert rate.minutes_before > pmi.minutes_before
    assert rate.minutes_after > pmi.minutes_after


def test_blackout_extends_while_conditions_remain_abnormal():
    # نافذة NFP بعد الإصدار 45 دقيقة؛ الحدث صدر قبل 50 دقيقة ⇒ خارجها عادةً،
    # وداخلها عند التمديد (45 + 30 = 75).
    event = high_impact_event(minutes_from_now=-50)
    snap = make_snapshot(events=[event])
    reg = full_registry(events=[event])
    normal = run_calendar_gate(snap, reg, now=NOW, conditions_abnormal=False)
    extended = run_calendar_gate(snap, reg, now=NOW, conditions_abnormal=True)
    assert normal.passed is True
    assert extended.passed is False
    assert extended.extended_for_abnormal is True


def test_no_profile_argument_exists_on_the_blackout_gate():
    """لا يمكن لأي ملف تجاوز الحجب — الدالة لا تستقبل الملف أصلاً."""
    import inspect

    params = set(inspect.signature(run_calendar_gate).parameters)
    assert "profile" not in params
    assert "limits" not in params


# ---------------------------------------------------------------------------
# الأخبار
# ---------------------------------------------------------------------------

def test_unverified_breaking_news_blocks_but_never_creates_a_trade():
    item = news_item(verification=NewsVerification.UNVERIFIED, minutes_ago=3)
    snap = make_snapshot(news=[item])
    reg = full_registry(news=[item])
    result = run_news_gate(snap, reg, now=NOW)
    assert result.passed is False
    assert item in result.blocking_items
    assert item in result.unverified_items
    # لا يوجد في نتيجة البوابة أي حقل يمكن أن يُنشئ إشارة
    assert not hasattr(result, "signal")
    assert not hasattr(result, "side")


def test_expired_news_stops_blocking():
    item = news_item(verification=NewsVerification.EXPIRED, minutes_ago=5)
    snap = make_snapshot(news=[item])
    reg = full_registry(news=[item])
    assert run_news_gate(snap, reg, now=NOW).passed is True


def test_old_unverified_news_stops_blocking_after_its_window():
    item = news_item(verification=NewsVerification.UNVERIFIED, minutes_ago=120)
    snap = make_snapshot(news=[item])
    reg = full_registry(news=[item])
    assert run_news_gate(snap, reg, now=NOW).passed is True


def test_missing_news_provider_blocks_trading():
    snap = make_snapshot()
    reg = ProviderRegistry(calendar=StaticCalendarProvider([]))
    result = run_news_gate(snap, reg, now=NOW)
    assert result.passed is False
    assert result.provider_configured is False


def test_low_impact_news_does_not_block():
    item = news_item(
        verification=NewsVerification.VERIFIED, impact=ImpactLevel.LOW, minutes_ago=2
    )
    snap = make_snapshot(news=[item])
    reg = full_registry(news=[item])
    assert run_news_gate(snap, reg, now=NOW).passed is True


# ---------------------------------------------------------------------------
# الأساسيات
# ---------------------------------------------------------------------------

def test_missing_macro_provider_yields_unknown_bias_not_neutral():
    result = assess_fundamentals({}, provider_configured=False)
    assert result.relative_bias is Bias.UNKNOWN
    assert result.usable is False
    assert result.confidence == D("0")


def test_partial_macro_data_lowers_confidence_and_blocks_usability():
    values = macro_values(complete=False)
    result = assess_fundamentals(values, provider_configured=True)
    assert result.completeness < MIN_COMPLETENESS_FOR_CONFIDENCE
    assert result.usable is False


def test_complete_bullish_macro_produces_a_bullish_relative_bias():
    result = assess_fundamentals(macro_values(bullish_eur=True), provider_configured=True)
    assert result.relative_bias in (Bias.BULLISH, Bias.STRONGLY_BULLISH)
    assert result.usable is True
    assert result.supporting_ar


def test_complete_bearish_macro_produces_a_bearish_relative_bias():
    result = assess_fundamentals(macro_values(bullish_eur=False), provider_configured=True)
    assert result.relative_bias in (Bias.BEARISH, Bias.STRONGLY_BEARISH)


def test_unknown_macro_fields_are_listed_not_guessed():
    values = macro_values(complete=False)
    result = assess_fundamentals(values, provider_configured=True)
    assert result.unknown_fields
    assert "risk_sentiment" in result.unknown_fields


def test_fundamental_module_cannot_approve_a_trade():
    """لا يوجد في نتيجة التقييم أي حقل موافقة أو اتجاه تنفيذي."""
    result = assess_fundamentals(macro_values(), provider_configured=True)
    for forbidden in ("approved", "decision", "side", "quantity", "entry", "stop"):
        assert not hasattr(result, forbidden)
