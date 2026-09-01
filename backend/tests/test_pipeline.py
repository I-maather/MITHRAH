"""
اختبارات الخط الكامل: Data → Signal → Risk → Preview → Mock Execution → Audit.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from app.audit.log import verify_chain
from app.brokers.mock import MockBehaviour, MockBrokerAdapter, make_quote
from app.contracts import DataSource, Decision, StrategyState
from app.execution.orders import ExecutionService, IdempotencyGuard
from app.killswitch.engine import KillSwitch, KillSwitchTrigger
from app.money import D
from app.pipeline.runner import BlackoutCalendar, MacroAssessment, NewsBlackout, Pipeline
from app.contracts import Broker
from app.risk.constitution import RiskLimits
from app.risk.costs import IBKR_PRO_TIERED_US_STOCK, CostAssumptions
from app.risk.engine import RiskEngine, SessionRiskState
from app.strategies.trend_pullback_v1 import TrendPullbackV1
from tests.conftest import MID_SESSION, make_balances, make_permissions, uptrend_bars

UTC = timezone.utc
NO_MACRO_BLOCK = MacroAssessment(blocks_trading=False, reason_ar="لا مانع كلي.")


class ApprovedForTest(TrendPullbackV1):
    """
    نسخة معتمدة *للاختبار فقط*، حتى نتمكن من اختبار الخط كاملاً
    دون تزييف حالة الاستراتيجية الحقيقية في كود الإنتاج.
    """

    metadata = replace(TrendPullbackV1.metadata, state=StrategyState.APPROVED)


def confirmed_calendar(day: date, entries=None) -> BlackoutCalendar:
    return BlackoutCalendar(entries=entries or [], confirmed_for={day})


def build(
    *,
    equity="5000.00",
    now=MID_SESSION,
    strategies=None,
    behaviour=None,
    calendar=None,
    state=None,
):
    from app.audit.log import AuditLog, InMemoryAuditStore

    broker = MockBrokerAdapter(
        behaviour=behaviour or MockBehaviour(stop_on_fractional_supported=True)
    )
    broker.connect()
    broker.balances = make_balances(equity, at=now)
    broker.permissions = make_permissions(at=now)
    broker.set_quote(make_quote("SPY", "639.99", "640.00", at=now, source=DataSource.REALTIME))

    audit = AuditLog(InMemoryAuditStore())
    ks = KillSwitch()
    engine = RiskEngine(RiskLimits.from_baseline(D(equity), Broker.IBKR))
    execution = ExecutionService(broker=broker, audit=audit, guard=IdempotencyGuard())

    pipeline = Pipeline(
        broker=broker, risk_engine=engine, kill_switch=ks, audit=audit, execution=execution,
        strategies=strategies if strategies is not None else [ApprovedForTest()],
        schedule=IBKR_PRO_TIERED_US_STOCK,
        assumptions=CostAssumptions(D("0.01"), D("0.0005"), D("0")),
        blackouts=calendar or confirmed_calendar(now.date()),
    )
    default_state = SessionRiskState(
        baseline_equity=D(equity), current_equity=D(equity),
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )
    return pipeline, broker, audit, ks, (state or default_state)


def run(pipeline, state, now=MID_SESSION, macro=NO_MACRO_BLOCK, bars=None):
    return pipeline.run(
        symbol="SPY", bars=bars if bars is not None else uptrend_bars(),
        state=state, macro=macro, now=now,
    )


# --- happy path -------------------------------------------------------------

def test_end_to_end_execution_on_adequate_capital():
    pipeline, broker, audit, ks, state = build()
    result = run(pipeline, state)
    assert result.decision is Decision.TRADE, result.reason_ar
    assert result.submission.outcome.value in ("FILLED", "PARTIALLY_FILLED")
    assert result.reconciliation_ok
    assert verify_chain(audit.events()).ok


def test_audit_records_the_whole_journey():
    pipeline, broker, audit, ks, state = build()
    run(pipeline, state)
    actions = [e.action for e in audit.events()]
    for expected in (
        "PIPELINE_RUN", "ELIGIBILITY_DECISION", "SIGNAL_GENERATED", "RISK_DECISION",
        "ORDER_INTENT_CREATED", "ORDER_PREVIEWED", "ORDER_SUBMITTED", "ORDER_CONFIRMED",
        "RECONCILIATION",
    ):
        assert expected in actions, f"حدث ناقص في السجل: {expected}"


def test_one_line_verdict_is_arabic():
    pipeline, broker, audit, ks, state = build()
    assert "تنفيذ" in run(pipeline, state).one_line_ar


# --- the $100 reality -------------------------------------------------------

def test_real_capital_produces_no_trade_and_logs_the_reason():
    pipeline, broker, audit, ks, state = build(equity="150.00")
    result = run(pipeline, state)
    assert result.decision is Decision.NO_TRADE
    assert result.stage == "risk"
    assert result.reason_code in (
        "COST_DOMINATED", "ACCOUNT_SIZE_INSUFFICIENT",
        "BELOW_BROKER_MIN_ORDER", "BREAKEVEN_MOVE_TOO_FAR",
    )
    assert any(e.action == "NO_TRADE" or e.decision == result.reason_code for e in audit.events())


# --- gates in order ---------------------------------------------------------

def test_kill_switch_blocks_before_anything_else():
    pipeline, broker, audit, ks, state = build()
    ks.trigger(KillSwitchTrigger.MANUAL, reason_ar="اختبار")
    result = run(pipeline, state)
    assert result.decision is Decision.HALTED
    assert result.stage == "kill_switch"


def test_macro_can_veto_but_not_force():
    pipeline, broker, audit, ks, state = build()
    result = run(pipeline, state, macro=MacroAssessment(True, "يوم بيانات تضخم عالية الأثر."))
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == "MACRO_VETO"


def test_unconfirmed_news_calendar_forces_no_trade():
    """لا نخترع أخباراً: تقويم غير مؤكد => NO_TRADE."""
    pipeline, broker, audit, ks, state = build(calendar=BlackoutCalendar())
    result = run(pipeline, state)
    assert result.reason_code == "NEWS_CALENDAR_UNCONFIRMED"


def test_active_news_blackout_blocks():
    blackout = NewsBlackout(
        symbol=None, starts_utc=MID_SESSION - timedelta(minutes=10),
        ends_utc=MID_SESSION + timedelta(minutes=10),
        title_ar="محضر الفيدرالي", source="تقويم يدوي معتمد",
    )
    pipeline, broker, audit, ks, state = build(
        calendar=confirmed_calendar(MID_SESSION.date(), [blackout])
    )
    assert run(pipeline, state).reason_code == "NEWS_BLACKOUT"


def test_no_approved_strategy_means_no_trade():
    pipeline, broker, audit, ks, state = build(strategies=[TrendPullbackV1()])
    result = run(pipeline, state)
    assert result.reason_code == "NO_APPROVED_STRATEGY"


def test_closed_market_blocks_at_eligibility():
    saturday = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)
    pipeline, broker, audit, ks, state = build(now=saturday, calendar=confirmed_calendar(saturday.date()))
    result = run(pipeline, state, now=saturday)
    assert result.stage == "eligibility"
    assert result.reason_code == "MARKET_CLOSED"


def test_stale_data_blocks_at_eligibility():
    pipeline, broker, audit, ks, state = build()
    broker.set_quote(make_quote(
        "SPY", "639.99", "640.00",
        at=MID_SESSION - timedelta(minutes=30), source=DataSource.REALTIME,
    ))
    result = run(pipeline, state)
    assert result.reason_code == "DATA_NOT_TRADABLE"


def test_broker_disconnect_triggers_kill_switch():
    pipeline, broker, audit, ks, state = build()
    broker.behaviour.connected = False
    result = run(pipeline, state)
    assert result.decision is Decision.HALTED
    assert ks.is_active
    assert ks.state.current_event.trigger is KillSwitchTrigger.BROKER_DISCONNECTED


def test_no_setup_when_strategy_conditions_absent():
    pipeline, broker, audit, ks, state = build()
    flat = uptrend_bars()
    flat = [b.model_copy(update={"close": D("600"), "high": D("601"), "low": D("599")}) for b in flat]
    result = run(pipeline, state, bars=flat)
    assert result.reason_code == "NO_SETUP"


# --- risk gates through the pipeline ---------------------------------------

def test_the_position_limit_blocks_the_next_entry_whatever_the_limit_is():
    """
    العدد يُقرأ من الحدود لا يُكتب رقماً.

    كان الاختبار يثبّت «مركزٌ واحد يمنع الثاني» — وهي **قيمة الوضع** لا
    **قاعدة المحرّك**. ولما اتّسع وضع التحقّق إلى ثلاثة مراكز يوم 2026-09-01
    سقط الاختبار، والمحرّك لم يتغيّر. فصار يسأل: عند الحدّ أياً كان، أيمنع؟
    """
    pipeline, broker, audit, ks, state = build()
    limit = pipeline.risk.limits.max_open_positions
    busy = SessionRiskState(
        baseline_equity=D("5000"), current_equity=D("5000"), realized_pnl_today=D("0"),
        realized_pnl_week=D("0"), unrealized_pnl=D("0"), open_positions=limit,
        entry_orders_today=0, consecutive_losses=0,
    )
    assert run(pipeline, busy).reason_code == "MAX_OPEN_POSITIONS_REACHED"

    below = SessionRiskState(
        baseline_equity=D("5000"), current_equity=D("5000"), realized_pnl_today=D("0"),
        realized_pnl_week=D("0"), unrealized_pnl=D("0"), open_positions=limit - 1,
        entry_orders_today=0, consecutive_losses=0,
    )
    assert run(pipeline, below).reason_code != "MAX_OPEN_POSITIONS_REACHED", (
        "يمنع تحت الحدّ — بوابةٌ تمنع دائماً معطوبة بقدر بوابةٍ لا تمنع أبداً"
    )


def test_duplicate_run_same_day_is_blocked_and_halts():
    pipeline, broker, audit, ks, state = build()
    first = run(pipeline, state)
    assert first.decision is Decision.TRADE
    second = run(pipeline, state)
    assert second.decision is Decision.HALTED
    assert ks.state.current_event.trigger is KillSwitchTrigger.DUPLICATE_ORDER


def test_reconciliation_mismatch_halts():
    pipeline, broker, audit, ks, state = build()
    from app.contracts import Position

    broker._positions["AAPL"] = Position(
        account_id="DU0000000", symbol="AAPL", quantity=D("3"),
        average_cost=D("200"), as_of_utc=MID_SESSION,
    )
    result = run(pipeline, state)
    assert result.decision is Decision.HALTED
    assert result.reason_code == "RECONCILIATION_MISMATCH"
    assert ks.is_active


def test_restart_with_open_position_does_not_double_enter():
    """محاكاة إعادة تشغيل: نفس المدخلات، حارس idempotency جديد، لكن مركز مفتوح."""
    pipeline, broker, audit, ks, state = build()
    run(pipeline, state)
    # **المركز المفتوح يُسمّى الآن، لا يُعدّ فقط.** وهذا ما يمنع الدخول ثانيةً
    # على SPY نفسها بعد إعادة التشغيل: بوابة مصدر التعرّض تراه بالاسم، بينما
    # عدّادٌ وحده كان يمرّره ما دام تحت السقف الجديد (ثلاثة).
    after_restart = SessionRiskState(
        baseline_equity=D("5000"), current_equity=D("5000"), realized_pnl_today=D("0"),
        realized_pnl_week=D("0"), unrealized_pnl=D("0"), open_positions=1,
        entry_orders_today=1, consecutive_losses=0, open_symbols=("SPY",),
    )
    result = run(pipeline, after_restart)
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == "EXPOSURE_BUCKET_ALREADY_OCCUPIED"


def test_audit_chain_stays_valid_across_many_runs():
    pipeline, broker, audit, ks, state = build(equity="150.00")
    for _ in range(5):
        run(pipeline, state)
    assert verify_chain(audit.events()).ok
