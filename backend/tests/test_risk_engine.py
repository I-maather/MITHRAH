from __future__ import annotations

from decimal import Decimal

from app.contracts import Decision, Side, Signal
from app.money import D
from app.risk.constitution import RiskLimits, constitution_fingerprint
from app.risk.engine import (
    CONSECUTIVE_LOSS_PAUSE,
    DAILY_ENTRY_LIMIT_REACHED,
    DAILY_LOSS_EXHAUSTED,
    KILL_SWITCH_ACTIVE,
    MAX_OPEN_POSITIONS_REACHED,
    NEWS_BLACKOUT,
    REWARD_RISK_TOO_LOW,
    TOTAL_LOSS_EXHAUSTED,
    WEEKLY_LOSS_EXHAUSTED,
    RiskEngine,
)
from tests.conftest import make_balances, make_state


def signal(entry="640", stop="630.40", target="659.20", now=None):
    from tests.conftest import MID_SESSION

    return Signal(
        strategy_name="TREND_PULLBACK", strategy_version="1.0.0", symbol="SPY", side=Side.BUY,
        entry_price=D(entry), stop_price=D(stop), take_profit_price=D(target),
        generated_at_utc=now or MID_SESSION, rationale_ar="اختبار", invalidation_ar="اختبار",
        inputs_digest="abc123",
    )


def big_engine():
    return RiskEngine(RiskLimits.from_baseline(D("5000.00")))


def big_state(**kw):
    base = dict(
        baseline_equity=D("5000"), current_equity=D("5000"),
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )
    base.update(kw)
    from app.risk.engine import SessionRiskState

    return SessionRiskState(**base)


def test_kill_switch_beats_everything(risk_engine, assumptions, schedule, now):
    d = risk_engine.evaluate(
        signal=signal(now=now), state=make_state(), balances=make_balances("150.00", at=now),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=True, now=now,
    )
    assert not d.approved
    assert d.reason_code == KILL_SWITCH_ACTIVE
    assert d.decision is Decision.HALTED


def test_small_account_always_no_trade(risk_engine, assumptions, schedule, now):
    d = risk_engine.evaluate(
        signal=signal(now=now), state=make_state(), balances=make_balances("150.00", at=now),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=False, now=now,
    )
    assert not d.approved
    assert d.decision is Decision.NO_TRADE


def test_viable_trade_on_adequate_capital(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now), state=big_state(), balances=make_balances("5000.00", at=now),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=False, now=now,
    )
    assert d.approved, d.reason_ar
    assert d.quantity > 0
    assert d.expected_risk_usd <= D("5000") * D("0.005")
    assert d.constitution_fingerprint == constitution_fingerprint()


def test_daily_loss_limit_blocks(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(realized_pnl_today=D("-50.00")),  # الحد اليومي 50.00
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == DAILY_LOSS_EXHAUSTED


def test_weekly_loss_limit_blocks(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(realized_pnl_week=D("-150.00")),  # 3% من 5000
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == WEEKLY_LOSS_EXHAUSTED


def test_total_loss_limit_blocks(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(current_equity=D("4750")),  # خسارة 250 = 5%
        balances=make_balances("4750.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == TOTAL_LOSS_EXHAUSTED


def test_two_consecutive_losses_pause(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now), state=big_state(consecutive_losses=2),
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == CONSECUTIVE_LOSS_PAUSE


def test_one_open_position_max(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now), state=big_state(open_positions=1),
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == MAX_OPEN_POSITIONS_REACHED


def test_one_entry_order_per_day(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now), state=big_state(entry_orders_today=1),
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == DAILY_ENTRY_LIMIT_REACHED


def test_reward_risk_below_minimum(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(entry="640", stop="630", target="645", now=now),  # R:R = 0.5
        state=big_state(), balances=make_balances("5000.00", at=now),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == REWARD_RISK_TOO_LOW


def test_news_blackout_blocks(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(in_news_blackout=True, news_blackout_reason_ar="تقرير التضخم"),
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == NEWS_BLACKOUT


def test_risk_budget_shrinks_with_remaining_daily_budget(now):
    engine = big_engine()
    fresh = engine.risk_budget_for_next_trade(big_state())
    used = engine.risk_budget_for_next_trade(big_state(realized_pnl_today=D("-45.00")))
    assert used < fresh
    assert used == D("5.00")  # 50 - 45


def test_risk_budget_never_negative():
    engine = big_engine()
    b = engine.risk_budget_for_next_trade(big_state(realized_pnl_today=D("-999")))
    assert b == 0


def test_every_decision_is_explainable(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now), state=big_state(), balances=make_balances("5000.00", at=now),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=False, now=now,
    )
    assert d.checks, "كل قرار يجب أن يحمل قائمة فحوص"
    for name, _passed, explanation in d.checks:
        assert name and explanation, "كل فحص يجب أن يحمل اسماً وشرحاً عربياً"
