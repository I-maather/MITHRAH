"""
أوضاع المخاطرة — دستور المخاطر الإصدار 0.2.0 على رأس مال 150 دولاراً.

تغييرات 0.2.0 المُختبَرة هنا:
  * وضع LOCKED_REVIEW الجديد لا يسمح بأي دخول.
  * خسارتان متتاليتان ⇒ LOCKED_REVIEW بلا استئناف تلقائي غداً.
  * CONSERVATIVE_LIVE: الحد = الأصغر بين 1.50 و1% من حقوق الملكية الحالية.
  * حد تشغيلي 6.50 مع احتياطي فجوة 1.00 دون الحاجز المطلق 7.50.
  * قيود الكمية وقوائم الأدوات صارت حسب الوسيط.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import Settings
from app.contracts import Broker, Side, Signal
from app.money import D
from app.risk.constitution import (
    CONSTITUTION_VERSION,
    INITIAL_CAPITAL_USD,
    MODE_SPECS,
    REAL_MONEY_MODES,
    PauseScope,
    RiskLimits,
    RiskMode,
    constitution_fingerprint,
)
from app.risk.engine import (
    CONSECUTIVE_LOSS_PAUSE,
    INSTRUMENT_NOT_ALLOWED_IN_MODE,
    LIFETIME_ENTRY_LIMIT_REACHED,
    MODE_FORBIDS_ENTRIES,
    OPERATIONAL_DRAWDOWN_STOP,
    PER_ORDER_APPROVAL_REQUIRED,
    RiskEngine,
    SessionRiskState,
)
from tests.conftest import MID_SESSION, make_balances


def signal(symbol="SPY", entry="640", stop="620.80", target="678.40"):
    return Signal(
        strategy_name="TREND_PULLBACK", strategy_version="1.0.0", symbol=symbol, side=Side.BUY,
        entry_price=D(entry), stop_price=D(stop), take_profit_price=D(target),
        generated_at_utc=MID_SESSION, rationale_ar="اختبار", invalidation_ar="اختبار",
        inputs_digest="mode-test",
    )


def state(**kw):
    base = dict(
        baseline_equity=D("150"), current_equity=D("150"),
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )
    base.update(kw)
    return SessionRiskState(**base)


# --- الأرقام النهائية --------------------------------------------------------

def test_constitution_is_version_0_2_0():
    assert CONSTITUTION_VERSION == "0.2.0"


def test_capital_is_exactly_150():
    assert INITIAL_CAPITAL_USD == D("150.00")


def test_validation_mode_dollar_limits():
    L = RiskLimits.for_mode(RiskMode.VALIDATION, broker=Broker.CAPITAL_COM)
    assert L.hard_total_loss == D("7.50")
    assert L.daily_loss == D("1.50")
    assert L.weekly_loss == D("4.50")
    assert L.max_risk_per_trade == D("0.75")
    assert f"{L.target_risk_per_trade:.2f}" == "0.38"
    assert L.max_open_positions == 1
    assert L.max_entry_orders_per_day == 1
    assert L.consecutive_losses_pause == 2
    assert L.pause_scope is PauseScope.LOCKED_REVIEW
    assert L.consecutive_losses_kill == 3
    assert L.allowed_instruments == frozenset({"EURUSD"})


def test_conservative_live_mode_dollar_limits():
    L = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, broker=Broker.CAPITAL_COM)
    assert L.max_risk_per_trade == D("1.50")          # 1% all-in
    assert L.daily_loss == D("1.50")                  # 1%
    assert L.weekly_loss == D("3.00")                 # 2%
    assert L.hard_total_loss == D("7.50")             # حاجز مطلق
    assert L.effective_drawdown_stop() == D("6.50")   # حد تشغيلي
    assert L.gap_slippage_reserve == D("1.00")        # احتياطي الفجوة
    assert L.min_reward_risk_ratio == D("1.5")
    assert L.max_open_positions == 1
    assert L.max_entry_orders_per_day == 1
    assert L.pause_scope is PauseScope.LOCKED_REVIEW


def test_operational_stop_plus_reserve_equals_absolute_boundary():
    L = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, broker=Broker.CAPITAL_COM)
    assert L.effective_drawdown_stop() + L.gap_slippage_reserve == L.hard_total_loss


def test_conservative_live_risk_is_lower_of_dollar_cap_and_one_percent_of_equity():
    L = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, broker=Broker.CAPITAL_COM)
    assert L.effective_max_risk(D("150")) == D("1.50")
    assert L.effective_max_risk(D("100")) == D("1.00")   # الحساب تراجع ⇒ المخاطرة تتراجع
    assert L.effective_max_risk(D("500")) == D("1.50")   # الحساب ارتفع ⇒ لا ترتفع المخاطرة


def test_commissioning_mode_constraints():
    L = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING, broker=Broker.CAPITAL_COM)
    assert L.max_lifetime_entry_orders == 1
    assert L.requires_per_order_approval is True
    assert L.enforce_economic_viability is False
    assert L.max_risk_per_trade == D("0.75")
    assert f"{L.target_risk_per_trade:.2f}" == "0.50"   # المفضّل
    assert L.require_take_profit is True
    assert L.prefer_guaranteed_stop is True
    assert L.allow_overnight is False
    assert L.allow_weekend_hold is False
    assert L.allowed_instruments == frozenset({"EURUSD"})
    assert L.use_broker_minimum_quantity is True


def test_locked_review_forbids_every_entry():
    L = RiskLimits.for_mode(RiskMode.LOCKED_REVIEW, broker=Broker.CAPITAL_COM)
    assert L.allows_entries is False
    assert L.max_entry_orders_per_day == 0
    assert L.max_lifetime_entry_orders == 0
    assert L.target_risk_per_trade == D("0")
    assert L.max_risk_per_trade == D("0")


def test_real_money_modes_are_exactly_the_two_live_modes():
    assert REAL_MONEY_MODES == frozenset(
        {RiskMode.LIVE_COMMISSIONING, RiskMode.CONSERVATIVE_LIVE}
    )
    assert RiskMode.VALIDATION not in REAL_MONEY_MODES
    assert RiskMode.LOCKED_REVIEW not in REAL_MONEY_MODES


def test_no_mode_ever_exceeds_the_hard_total_loss():
    for mode, spec in MODE_SPECS.items():
        assert spec.hard_total_loss_pct == D("0.05"), mode
        assert spec.max_risk_pct <= spec.daily_loss_pct or spec.max_risk_pct == 0, mode
        assert spec.daily_loss_pct <= spec.weekly_loss_pct, mode
        assert spec.weekly_loss_pct <= spec.hard_total_loss_pct, mode
        assert spec.max_open_positions == 1, mode
        assert spec.max_entry_orders_per_day <= 1, mode
        assert spec.require_take_profit is True, mode
        assert spec.allow_overnight is False, mode
        assert spec.allow_weekend_hold is False, mode


def test_each_mode_and_broker_pair_has_a_distinct_fingerprint():
    prints = {
        (m, b): constitution_fingerprint(m, b)
        for m in RiskMode
        for b in (Broker.CAPITAL_COM, Broker.IBKR)
    }
    assert len(set(prints.values())) == len(prints)


def test_fingerprint_changes_when_broker_changes():
    a = constitution_fingerprint(RiskMode.CONSERVATIVE_LIVE, Broker.CAPITAL_COM)
    b = constitution_fingerprint(RiskMode.CONSERVATIVE_LIVE, Broker.IBKR)
    assert a != b


# --- سلوك المحرك لكل وضع ----------------------------------------------------

def evaluate(mode, st, *, schedule, assumptions, broker=Broker.IBKR, symbol="SPY"):
    engine = RiskEngine(RiskLimits.for_mode(mode, D("150.00"), broker))
    return engine.evaluate(
        signal=signal(symbol=symbol), state=st, balances=make_balances("150.00", at=MID_SESSION),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=False, now=MID_SESSION,
    )


def test_locked_review_rejects_before_anything_else(schedule, assumptions):
    d = evaluate(RiskMode.LOCKED_REVIEW, state(), schedule=schedule, assumptions=assumptions)
    assert not d.approved
    assert d.reason_code == MODE_FORBIDS_ENTRIES


def test_capital_com_modes_reject_non_eurusd_instruments(schedule, assumptions):
    d = evaluate(
        RiskMode.CONSERVATIVE_LIVE, state(), schedule=schedule, assumptions=assumptions,
        broker=Broker.CAPITAL_COM, symbol="SPY",
    )
    assert not d.approved
    assert d.reason_code == INSTRUMENT_NOT_ALLOWED_IN_MODE


def test_commissioning_requires_owner_approval_for_this_very_order(schedule, assumptions):
    d = evaluate(RiskMode.LIVE_COMMISSIONING, state(), schedule=schedule, assumptions=assumptions)
    assert not d.approved
    assert d.reason_code == PER_ORDER_APPROVAL_REQUIRED


def test_commissioning_approves_one_small_trade_when_approved(schedule, assumptions):
    d = evaluate(
        RiskMode.LIVE_COMMISSIONING, state(owner_approved_this_order=True),
        schedule=schedule, assumptions=assumptions,
    )
    assert d.approved, d.reason_ar
    assert D("5.00") <= d.notional <= D("10.00")   # سياسة IBKR للكمية
    assert d.expected_risk_usd <= D("0.75")


def test_commissioning_allows_exactly_one_trade_in_its_lifetime(schedule, assumptions):
    d = evaluate(
        RiskMode.LIVE_COMMISSIONING,
        state(owner_approved_this_order=True, lifetime_entry_orders=1),
        schedule=schedule, assumptions=assumptions,
    )
    assert not d.approved
    assert d.reason_code == LIFETIME_ENTRY_LIMIT_REACHED


def test_conservative_live_still_says_no_trade_on_ibkr_equities_at_150(schedule, assumptions):
    """
    مسار IBKR (أسهم) يبقى غير مجدٍ عند 150 دولاراً — استنتاج 0.1.0 ما زال صحيحاً
    **لـIBKR وحده**. لا علاقة له بـCapital.com.
    """
    d = evaluate(RiskMode.CONSERVATIVE_LIVE, state(), schedule=schedule, assumptions=assumptions)
    assert not d.approved
    assert d.reason_code in (
        "COST_DOMINATED", "ACCOUNT_SIZE_INSUFFICIENT",
        "BREAKEVEN_MOVE_TOO_FAR", "BELOW_BROKER_MIN_ORDER",
    )


def test_two_consecutive_losses_move_to_locked_review_not_tomorrow(schedule, assumptions):
    for mode in (RiskMode.VALIDATION, RiskMode.CONSERVATIVE_LIVE):
        d = evaluate(mode, state(consecutive_losses=2), schedule=schedule, assumptions=assumptions)
        assert not d.approved, mode
        assert d.reason_code == CONSECUTIVE_LOSS_PAUSE, mode
        assert "LOCKED_REVIEW" in d.reason_ar, mode
        assert "لا استئناف تلقائي" in d.reason_ar, mode


def test_one_loss_ends_commissioning_mode(schedule, assumptions):
    d = evaluate(
        RiskMode.LIVE_COMMISSIONING, state(consecutive_losses=1, owner_approved_this_order=True),
        schedule=schedule, assumptions=assumptions,
    )
    assert not d.approved
    assert d.reason_code == CONSECUTIVE_LOSS_PAUSE


def test_operational_drawdown_stop_fires_before_the_absolute_boundary(schedule, assumptions):
    d = evaluate(
        RiskMode.CONSERVATIVE_LIVE,
        state(current_equity=D("143.50")),  # خسارة 6.50 = الحد التشغيلي
        schedule=schedule, assumptions=assumptions,
    )
    assert not d.approved
    assert d.reason_code == OPERATIONAL_DRAWDOWN_STOP
    assert "احتياطي الفجوة" in d.reason_ar


def test_risk_never_rises_after_profit(schedule, assumptions):
    engine = RiskEngine(RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("150.00"), Broker.CAPITAL_COM))
    after_profit = engine.risk_budget_for_next_trade(
        state(current_equity=D("200"), realized_pnl_today=D("50"))
    )
    assert after_profit == D("1.50")


def test_risk_never_rises_after_loss(schedule, assumptions):
    engine = RiskEngine(RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("150.00"), Broker.CAPITAL_COM))
    fresh = engine.risk_budget_for_next_trade(state())
    after_loss = engine.risk_budget_for_next_trade(state(realized_pnl_today=D("-0.90")))
    assert fresh == D("1.50")
    assert after_loss == D("0.60")
    assert after_loss < fresh


# --- القفل الرابع: وضع حقيقي يتطلب أقفال Live -------------------------------

def _settings(**kw) -> Settings:
    base = dict(LIVE_TRADING=False, BROKER_MODE="MOCK",
                LIVE_APPROVAL_FILE="/nonexistent/approval.json", RISK_MODE="VALIDATION")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_validation_mode_needs_no_approval():
    _settings().assert_mode_allowed()


def test_locked_review_needs_no_approval():
    _settings(RISK_MODE="LOCKED_REVIEW").assert_mode_allowed()


@pytest.mark.parametrize("mode", ["LIVE_COMMISSIONING", "CONSERVATIVE_LIVE"])
def test_real_modes_require_live_flag(mode):
    with pytest.raises(RuntimeError, match="LIVE_TRADING=true"):
        _settings(RISK_MODE=mode).assert_mode_allowed()


@pytest.mark.parametrize("mode", ["LIVE_COMMISSIONING", "CONSERVATIVE_LIVE"])
def test_real_modes_require_approval_file(mode):
    with pytest.raises(RuntimeError, match="ملف موافقة"):
        _settings(RISK_MODE=mode, LIVE_TRADING=True).assert_mode_allowed()


def test_real_mode_passes_with_both_locks(tmp_path):
    approval = tmp_path / "live_approval.json"
    approval.write_text('{"approved_by":"Maather"}', encoding="utf-8")
    _settings(
        RISK_MODE="CONSERVATIVE_LIVE", LIVE_TRADING=True, LIVE_APPROVAL_FILE=str(approval)
    ).assert_mode_allowed()
