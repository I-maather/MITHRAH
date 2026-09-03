"""
«لا فرصة مطابقة» — جملةٌ واحدة تصلح لكل سببٍ، فلا تصلح لأيٍّ منها.

## ما فرض هذا الملف

بين ٣٠ أغسطس و٣ سبتمبر ٢٠٢٦ كان النظام يولّد الإشارات ويرفضها كلّها عند
بوابةٍ واحدة، والشاشة تقول «لا تداول اليوم — لا فرصة مطابقة». وهي الجملة
نفسها التي تظهر حين يكون السوق مغلقاً، وحين لا تُشير الاستراتيجية، وحين
تُرفض كل إشارة عند حدٍّ محسوبٍ خطأً.

والفرق بين «لا فرصة» و«٤٨٦ فرصة رُفضت كلّها في بوابةٍ واحدة» هو الفرق بين
انتظارٍ وعطل. وأربعة أيام ضاعت في هذا الفرق.

## القاعدة

* القمع يُشتقّ من **سجلّ التدقيق وحده** — لا عدّاد موازٍ يختلف عنه بصمت.
* أوّل مرحلةٍ ينهار عندها العدد هي موضع التشخيص، وتُنسَب إلى جهةٍ مسمّاة.
* اليوم الذي أوقفته المالكة **يُخرَج من المقام** ولا يُحسَب إخفاق مشاركة.
* صفقات التشغيل والاختبار لا تُحسَب صفقاتٍ استراتيجية.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.participation.funnel import DayFunnel, funnel_for_day
from app.participation.metrics import (
    build_day,
    build_report,
    daily_no_trade_report,
)

DAY = "2026-09-03"
BASE = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


def ev(action, decision="", *, source="Pipeline", reason="", minute=0):
    return SimpleNamespace(
        timestamp_utc=BASE + timedelta(minutes=minute),
        action=action, decision=decision, source=source, reason_ar=reason,
    )


def trade(**over):
    base = dict(
        strategy_name="TREND_PULLBACK", strategy_version="2.0.0",
        opened_at_utc=BASE, closed_at_utc=BASE + timedelta(hours=1),
        net_pnl=Decimal("0.40"),
    )
    base.update(over)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# ١ · القمع يعدّ ما وقع
# ---------------------------------------------------------------------------

def test_the_funnel_counts_each_stage():
    events = [
        ev("PIPELINE_RUN", "START"),
        ev("ELIGIBILITY_DECISION", "ELIGIBLE"),
        ev("SIGNAL_GENERATED", "SIGNAL"),
        ev("RISK_DECISION", "TRADE"),
        ev("ORDER_INTENT_CREATED", "CREATED"),
        ev("ORDER_SUBMITTED", "SENT"),
        ev("ORDER_CONFIRMED", "ACK"),
        ev("EXECUTION_RECORDED", "FILLED"),
        ev("RECONCILIATION", "MATCHED"),
    ]
    f = funnel_for_day(events, DAY)
    for stage in ("scans", "eligible", "signals", "risk_approved", "intents",
                  "submitted", "acknowledged", "filled", "reconciled"):
        assert f.counts.get(stage) == 1, stage
    assert f.collapse_stage is None
    assert f.blamed_on == "NONE"


def test_the_collapse_stage_is_the_first_zero_after_a_positive():
    """**الفحص الذي يعضّ.** ٤٨٦ إشارة ثم صفر عند اقتصاديات الأداة."""
    events = [ev("PIPELINE_RUN", "START", minute=i) for i in range(10)]
    events += [ev("ELIGIBILITY_DECISION", "ELIGIBLE", minute=i) for i in range(10)]
    events += [ev("SIGNAL_GENERATED", "SIGNAL", minute=i) for i in range(10)]
    events += [
        ev("NO_TRADE", "BROKER_MIN_STOP_DISTANCE_VIOLATION",
           source="Pipeline.cfd_review", minute=i)
        for i in range(10)
    ]
    f = funnel_for_day(events, DAY)
    assert f.counts["signals"] == 10
    assert f.counts.get("instrument_economics_ok", 0) == 0
    assert f.collapse_stage == "instrument_economics_ok"
    assert f.blamed_on == "DATA"
    assert f.rejections["instrument_economics_ok"]["BROKER_MIN_STOP_DISTANCE_VIOLATION"] == 10


def test_a_risk_gate_collapse_is_blamed_on_risk():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE"),
              ev("SIGNAL_GENERATED", "SIGNAL"), ev("RISK_DECISION", "TRADE"),
              ev("RISK_DECISION", "BROKER_MIN_QUANTITY_RISK_EXCEEDED")]
    f = funnel_for_day(events, DAY)
    assert f.counts["risk_approved"] == 1
    assert f.rejections["risk_approved"]["BROKER_MIN_QUANTITY_RISK_EXCEEDED"] == 1
    # الانهيار بعدها: لا نيّة أمر
    assert f.collapse_stage == "intents"
    assert f.blamed_on == "EXECUTION"


def test_a_strategy_that_never_signals_is_blamed_on_the_strategy():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE"),
              ev("NO_TRADE", "NO_SETUP", source="strategy")]
    f = funnel_for_day(events, DAY)
    assert f.collapse_stage == "signals"
    assert f.blamed_on == "STRATEGY"


# ---------------------------------------------------------------------------
# ٢ · اليوم المؤهَّل
# ---------------------------------------------------------------------------

def test_a_paused_day_is_not_counted_against_participation():
    """قرارُ المالكة ليس إخفاق مشاركة — يُخرَج من المقام ويُقال بالاسم."""
    events = [ev("PIPELINE_RUN", "START"),
              ev("CONFIG_CHANGE", "LOCAL_PAUSE", source="ui"),
              ev("ELIGIBILITY_DECISION", "ELIGIBLE")]
    day = build_day(events, DAY)
    assert day.eligible is False
    assert day.not_eligible_because == "OWNER_PAUSED"


def test_a_closed_market_day_is_not_eligible():
    events = [ev("PIPELINE_RUN", "START"),
              ev("ELIGIBILITY_DECISION", "MARKET_CLOSED")]
    day = build_day(events, DAY)
    assert day.eligible is False
    assert day.not_eligible_because == "MARKET_CLOSED"


def test_a_kill_switch_day_is_not_eligible():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE"),
              ev("KILL_SWITCH_TRIGGERED", "TRIGGERED")]
    day = build_day(events, DAY)
    assert day.eligible is False
    assert day.not_eligible_because == "KILL_SWITCH_ACTIVE"


def test_an_open_healthy_day_is_eligible():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE")]
    day = build_day(events, DAY)
    assert day.eligible is True
    assert day.not_eligible_because == ""


# ---------------------------------------------------------------------------
# ٣ · ما يُحسَب صفقةً استراتيجية
# ---------------------------------------------------------------------------

def test_a_commissioning_trade_does_not_count_towards_the_objective():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE")]
    day = build_day(events, DAY, trades=[trade(strategy_name="COMMISSIONING")])
    assert day.strategy_trades_filled == 0
    assert day.participated is False


def test_a_manual_or_test_trade_does_not_count_either():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE")]
    for name in ("MANUAL", "SMOKE_TEST", "DIAGNOSTIC_ROUND_TRIP"):
        day = build_day(events, DAY, trades=[trade(strategy_name=name)])
        assert day.strategy_trades_filled == 0, name


def test_a_strategy_trade_counts():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE")]
    day = build_day(events, DAY, trades=[trade()])
    assert day.strategy_trades_filled == 1
    assert day.participated is True


# ---------------------------------------------------------------------------
# ٤ · المؤشرات
# ---------------------------------------------------------------------------

def _two_days():
    d1 = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE"),
          ev("SIGNAL_GENERATED", "SIGNAL"), ev("SIGNAL_GENERATED", "SIGNAL")]
    d2 = []
    for e in d1:
        d2.append(SimpleNamespace(
            timestamp_utc=e.timestamp_utc + timedelta(days=1),
            action=e.action, decision=e.decision, source=e.source, reason_ar=e.reason_ar,
        ))
    return d1 + d2


def test_participation_rate_counts_only_eligible_days():
    report = build_report(_two_days(), trades_by_day={DAY: [trade()]})
    assert report.eligible_trading_days == 2
    assert report.days_with_strategy_trades == 1
    assert report.daily_participation_rate == 0.5
    assert report.avg_qualified_signals_per_day == 2.0


def test_expectancy_is_none_without_a_closed_trade():
    """صفرٌ يُقرأ «لا ربح ولا خسارة»، والحقيقة «لا عيّنة»."""
    report = build_report(_two_days(), trades_by_day={})
    assert report.net_expectancy_after_costs is None


def test_expectancy_uses_closed_trades_only():
    report = build_report(_two_days(), trades_by_day={
        DAY: [trade(net_pnl=Decimal("0.60")), trade(closed_at_utc=None, net_pnl=Decimal("9"))],
    })
    assert report.closed_strategy_trades == 1
    assert report.net_expectancy_after_costs == Decimal("0.60")


def test_the_rejection_funnel_aggregates_across_days():
    events = _two_days() + [
        ev("NO_TRADE", "BROKER_MIN_STOP_DISTANCE_VIOLATION",
           source="Pipeline.cfd_review", minute=5),
    ]
    report = build_report(events)
    funnel = report.rejection_funnel()
    assert funnel["instrument_economics_ok"]["BROKER_MIN_STOP_DISTANCE_VIOLATION"] == 1


# ---------------------------------------------------------------------------
# ٥ · التقرير اليومي
# ---------------------------------------------------------------------------

def test_the_daily_report_names_the_stage_and_the_owner():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "ELIGIBLE"),
              ev("SIGNAL_GENERATED", "SIGNAL"),
              ev("NO_TRADE", "BROKER_MIN_STOP_DISTANCE_VIOLATION",
                 source="Pipeline.cfd_review")]
    text = daily_no_trade_report(build_day(events, DAY))
    assert "DAILY-NO-TRADE-REPORT" in text
    assert "اقتصاديات الأداة" in text
    assert "BROKER_MIN_STOP_DISTANCE_VIOLATION" in text
    assert "البيانات أو مواصفات الأداة" in text
    assert "تكرارُ أيامٍ مؤهَّلة بلا صفقة" in text


def test_no_report_is_written_for_an_ineligible_day():
    events = [ev("PIPELINE_RUN", "START"), ev("ELIGIBILITY_DECISION", "MARKET_CLOSED")]
    text = daily_no_trade_report(build_day(events, DAY))
    assert "غير مؤهَّل" in text
    assert "لا يُحسَب في مقام" in text


def test_an_isolated_instrument_is_named_and_does_not_stop_the_rest():
    events = [ev("PIPELINE_RUN", "START"),
              ev("ELIGIBILITY_DECISION", "ELIGIBLE"),
              ev("ELIGIBILITY_DECISION", "CONVERSION_COST_UNMEASURED",
                 source="Eligibility", reason="USDJPY مسعَّر بـJPY لا USD."),
              ev("SIGNAL_GENERATED", "SIGNAL")]
    f = funnel_for_day(events, DAY)
    assert f.isolated_instruments.get("USDJPY") == "CONVERSION_COST_UNMEASURED"
    assert f.counts["eligible"] == 1
