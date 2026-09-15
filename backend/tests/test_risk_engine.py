from __future__ import annotations

from decimal import Decimal

from app.contracts import Decision, Side, Signal
from app.contracts import Broker
from app.money import D
from app.risk.constitution import RiskLimits, RiskMode, constitution_fingerprint
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


#: الحدود تُقرأ مرّة وتُستعمل في كل اختبار بدل أن تُكتب أرقاماً.
#:
#: كانت الأرقام مثبَّتة (50.00 · 150.00 · 4750 · مركز واحد · أمر واحد)، فكانت
#: تثبّت **قيم وضع التحقّق** لا **قواعد المحرّك**. ولما اتّسع الوضع يوم
#: 2026-09-01 سقطت ستّة اختبارات والمحرّك لم يتغيّر سطراً.
#:
#: ⚠️ وهذا تشديد لا تخفيف: اختبارٌ برقمٍ مثبَّت يمرّ لو غُيّر الحدّ في الدستور
#: وفي الاختبار معاً — وتلك هي الطريقة التي يُلغى بها حدٌّ بصمت.
LIMITS = RiskLimits.from_baseline(D("5000.00"), Broker.IBKR)


def big_engine():
    return RiskEngine(LIMITS)


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
    # ⚠️ **تغيّر المعنى برفع ١٥ سبتمبر (التجريبي وحده).**
    #
    # كان هذا الاختبار يثبّت أنّ ١٥٠ دولاراً تُرفض دائماً. وبعد أن صارت
    # ميزانيةُ `VALIDATION` ٦٫٠٠ بدل ٣٫٠٠، صار القبولُ ممكناً — فادّعاءُ
    # «دائماً لا» صار كذباً، وحذفُ الاختبار يترك فجوة.
    #
    # فبقي يحرس ما **لم** يتغيّر: مهما اتّسع المقبول، لا تتجاوز المخاطرةُ
    # السقفَ الصلب، ولا يُقبل قرارٌ بلا كمية. والضمانُ على المال الحقيقي
    # مكانُه `test_150_dollar_account_cannot_produce_a_viable_trade`.
    if d.approved:
        assert d.quantity > 0
        assert d.expected_risk_usd <= risk_engine.limits.max_risk_per_trade
    else:
        assert d.decision is Decision.NO_TRADE


def test_viable_trade_on_adequate_capital(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now), state=big_state(), balances=make_balances("5000.00", at=now),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=False, now=now,
    )
    assert d.approved, d.reason_ar
    assert d.quantity > 0
    # يُقرأ من الحدود: رقمٌ مثبَّتٌ هنا يمرّ لو غُيّر الحدُّ في الدستور وفي
    # الاختبار معاً — وتلك طريقةُ إلغاء حدٍّ بصمت.
    assert d.expected_risk_usd <= big_engine().limits.max_risk_per_trade
    assert d.constitution_fingerprint == constitution_fingerprint(
        RiskMode.VALIDATION, Broker.IBKR
    )


def test_daily_loss_limit_blocks(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(realized_pnl_today=-LIMITS.daily_loss),
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == DAILY_LOSS_EXHAUSTED


def test_weekly_loss_limit_blocks(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(realized_pnl_week=-LIMITS.weekly_loss),
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == WEEKLY_LOSS_EXHAUSTED


def test_total_loss_limit_blocks(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(current_equity=D("5000") - LIMITS.hard_total_loss),
        balances=make_balances(str(D("5000") - LIMITS.hard_total_loss), at=now), schedule=schedule, assumptions=assumptions,
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
        signal=signal(now=now), state=big_state(open_positions=LIMITS.max_open_positions),
        balances=make_balances("5000.00", at=now), schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, kill_switch_active=False, now=now,
    )
    assert not d.approved and d.reason_code == MAX_OPEN_POSITIONS_REACHED


def test_one_entry_order_per_day(assumptions, schedule, now):
    d = big_engine().evaluate(
        signal=signal(now=now),
        state=big_state(entry_orders_today=LIMITS.max_entry_orders_per_day),
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
    spent = LIMITS.daily_loss - D("5.00")
    used = engine.risk_budget_for_next_trade(big_state(realized_pnl_today=-spent))
    assert used < fresh
    assert used == D("5.00"), "الميزانية المتبقية = الحد اليومي ناقص ما أُنفق"


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
