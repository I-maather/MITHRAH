"""
أوضاع المخاطرة الثلاثة — الحدود النهائية على رأس مال 150 دولاراً.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import Settings
from app.contracts import Side, Signal
from app.money import D
from app.risk.constitution import (
    INITIAL_CAPITAL_USD,
    MODE_SPECS,
    PauseScope,
    RiskLimits,
    RiskMode,
    constitution_fingerprint,
)
from app.risk.engine import (
    CONSECUTIVE_LOSS_PAUSE,
    LIFETIME_ENTRY_LIMIT_REACHED,
    PER_ORDER_APPROVAL_REQUIRED,
    RiskEngine,
    SessionRiskState,
)
from tests.conftest import MID_SESSION, make_balances


def signal(entry="640", stop="620.80", target="678.40"):
    return Signal(
        strategy_name="TREND_PULLBACK", strategy_version="1.0.0", symbol="SPY", side=Side.BUY,
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

def test_capital_is_exactly_150():
    assert INITIAL_CAPITAL_USD == D("150.00")


def test_validation_mode_dollar_limits():
    L = RiskLimits.for_mode(RiskMode.VALIDATION)
    assert L.hard_total_loss == D("7.50")
    assert L.daily_loss == D("1.50")
    assert L.weekly_loss == D("4.50")
    assert L.target_risk_per_trade == D("0.375")
    assert f"{L.target_risk_per_trade:.2f}" == "0.38"   # كما تُعرض
    assert L.max_risk_per_trade == D("0.75")
    assert L.max_open_positions == 1
    assert L.max_entry_orders_per_day == 1
    assert L.consecutive_losses_pause == 2
    assert L.pause_scope is PauseScope.NEXT_SESSION
    assert L.consecutive_losses_kill == 3


def test_conservative_live_mode_dollar_limits():
    L = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE)
    assert L.max_risk_per_trade == D("1.50")     # 1% all-in
    assert L.daily_loss == D("1.50")             # 1%
    assert L.weekly_loss == D("3.00")            # 2%
    assert L.hard_total_loss == D("7.50")        # 5%
    assert L.max_open_positions == 1
    assert L.max_entry_orders_per_day == 1
    assert L.consecutive_losses_pause == 2
    assert L.pause_scope is PauseScope.REST_OF_WEEK


def test_commissioning_mode_constraints():
    L = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING)
    assert L.max_lifetime_entry_orders == 1
    assert L.min_notional_usd == D("5.00")
    assert L.max_notional_usd == D("10.00")
    assert L.requires_per_order_approval is True
    assert L.enforce_economic_viability is False
    assert L.max_risk_per_trade == D("0.75")     # السقف المطلق يبقى سارياً


def test_no_mode_ever_exceeds_the_hard_total_loss():
    for mode, spec in MODE_SPECS.items():
        assert spec.hard_total_loss_pct == D("0.05"), mode
        assert spec.max_risk_pct <= spec.daily_loss_pct, mode
        assert spec.daily_loss_pct <= spec.weekly_loss_pct, mode
        assert spec.weekly_loss_pct <= spec.hard_total_loss_pct, mode
        assert spec.max_open_positions == 1, mode
        assert spec.max_entry_orders_per_day == 1, mode


def test_each_mode_has_a_distinct_fingerprint():
    prints = {m: constitution_fingerprint(m) for m in RiskMode}
    assert len(set(prints.values())) == len(RiskMode)


# --- سلوك المحرك لكل وضع ----------------------------------------------------

def evaluate(mode, st, *, schedule, assumptions, cash="150.00"):
    engine = RiskEngine(RiskLimits.for_mode(mode, D("150.00")))
    return engine.evaluate(
        signal=signal(), state=st, balances=make_balances(cash, at=MID_SESSION),
        schedule=schedule, assumptions=assumptions, fractional_allowed=True,
        kill_switch_active=False, now=MID_SESSION,
    )


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
    assert D("5.00") <= d.notional <= D("10.00")
    assert d.expected_risk_usd <= D("0.75")


def test_commissioning_allows_exactly_one_trade_in_its_lifetime(schedule, assumptions):
    d = evaluate(
        RiskMode.LIVE_COMMISSIONING,
        state(owner_approved_this_order=True, lifetime_entry_orders=1),
        schedule=schedule, assumptions=assumptions,
    )
    assert not d.approved
    assert d.reason_code == LIFETIME_ENTRY_LIMIT_REACHED


def test_conservative_live_still_says_no_trade_at_150(schedule, assumptions):
    """
    رأس مال 150 دولاراً لا يكفي لصفقة حقيقية ضمن 1.50 دولار all-in
    مع إبقاء الحواجز الاقتصادية. القرار الصحيح NO_TRADE — لا رفع للمخاطرة.
    """
    d = evaluate(RiskMode.CONSERVATIVE_LIVE, state(), schedule=schedule, assumptions=assumptions)
    assert not d.approved
    assert d.reason_code in (
        "COST_DOMINATED", "ACCOUNT_SIZE_INSUFFICIENT",
        "BREAKEVEN_MOVE_TOO_FAR", "BELOW_BROKER_MIN_ORDER",
    )


def test_conservative_live_two_losses_stop_for_the_week(schedule, assumptions):
    d = evaluate(
        RiskMode.CONSERVATIVE_LIVE, state(consecutive_losses=2),
        schedule=schedule, assumptions=assumptions,
    )
    assert not d.approved
    assert d.reason_code == CONSECUTIVE_LOSS_PAUSE
    assert "لبقية الأسبوع" in d.reason_ar


def test_validation_two_losses_stop_until_next_session(schedule, assumptions):
    d = evaluate(
        RiskMode.VALIDATION, state(consecutive_losses=2),
        schedule=schedule, assumptions=assumptions,
    )
    assert not d.approved
    assert d.reason_code == CONSECUTIVE_LOSS_PAUSE
    assert "حتى الجلسة التالية" in d.reason_ar


def test_conservative_live_never_exceeds_one_percent_after_losses(schedule, assumptions):
    """المخاطرة لا تُرفع بعد الخسائر — بل تُقلَّص بما تبقى من اليوم."""
    engine = RiskEngine(RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("150.00")))
    fresh = engine.risk_budget_for_next_trade(state())
    after_loss = engine.risk_budget_for_next_trade(state(realized_pnl_today=D("-0.90")))
    assert fresh == D("1.50")
    assert after_loss == D("0.60")
    assert after_loss < fresh


def test_conservative_live_never_exceeds_one_percent_after_profit(schedule, assumptions):
    engine = RiskEngine(RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("150.00")))
    after_profit = engine.risk_budget_for_next_trade(
        state(current_equity=D("200"), realized_pnl_today=D("50"))
    )
    assert after_profit == D("1.50")   # مشتقة من Baseline لا من الرصيد المرتفع


# --- القفل الرابع: وضع حقيقي يتطلب أقفال Live -------------------------------

def _settings(**kw) -> Settings:
    base = dict(LIVE_TRADING=False, BROKER_MODE="MOCK",
                LIVE_APPROVAL_FILE="/nonexistent/approval.json", RISK_MODE="VALIDATION")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_validation_mode_needs_no_approval():
    _settings().assert_mode_allowed()


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
