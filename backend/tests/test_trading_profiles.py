"""
اختبارات نظام ملفات التداول.

كل اختبار هنا مكتوب ليفشل عند **تخفيف** قيد، لا عند تشديده.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.money import D
from app.profiles import (
    DEFAULT_PROFILE,
    GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD,
    GLOBAL_GAP_SLIPPAGE_RESERVE_USD,
    GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD,
    NON_RESETTABLE_ON_PROFILE_CHANGE,
    PROFILE_RISK_ORDER,
    PROFILE_SPECS,
    PROFILE_UPGRADE_COOLING_HOURS,
    UNIVERSALLY_FORBIDDEN,
    ProfileChangeRefusal,
    ProfileLimits,
    TradingProfile,
    is_upgrade,
    profile_fingerprint,
)
from app.profiles.manager import ProfileManager, SystemGuardState

CAPITAL = D("150.00")
T0 = datetime(2026, 8, 28, 9, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now = self.now + timedelta(**kw)


# ---------------------------------------------------------------------------
# 1. حدود كل ملف بالأرقام الدقيقة
# ---------------------------------------------------------------------------

def test_capital_preservation_exact_limits():
    l = ProfileLimits.for_profile(TradingProfile.CAPITAL_PRESERVATION, CAPITAL)
    # الأصغر بين 0.50 دولار و0.35% من 150 = 0.525 ⇒ 0.50
    assert l.max_risk_per_trade == D("0.50")
    assert l.max_daily_loss == D("0.75")
    assert l.max_weekly_loss == D("1.50")
    assert l.min_net_reward_risk == D("1.75")
    assert l.min_quality_score == 90
    assert l.max_open_positions == 1
    assert l.max_entry_orders_per_day == 1
    assert l.allowed_instruments == frozenset({"EURUSD"})


def test_balanced_exact_limits():
    l = ProfileLimits.for_profile(TradingProfile.BALANCED, CAPITAL)
    # الأصغر بين 0.75 و0.50% من 150 = 0.75 ⇒ 0.75
    assert l.max_risk_per_trade == D("0.75")
    assert l.max_daily_loss == D("1.50")
    assert l.max_weekly_loss == D("3.00")
    assert l.min_net_reward_risk == D("1.5")
    assert l.min_quality_score == 85


def test_active_controlled_exact_limits():
    l = ProfileLimits.for_profile(TradingProfile.ACTIVE_CONTROLLED, CAPITAL)
    # الأصغر بين 1.50 و1% من 150 = 1.50 ⇒ 1.50
    assert l.max_risk_per_trade == D("1.50")
    assert l.max_daily_loss == D("1.50")
    assert l.max_weekly_loss == D("3.00")
    assert l.min_net_reward_risk == D("1.5")
    assert l.min_quality_score == 85
    assert l.full_risk_loss_ends_day is True


def test_percentage_cap_binds_when_equity_falls():
    """الحساب المتراجع يقلّص المخاطرة تلقائياً — النسبة تصبح هي القيد."""
    l = ProfileLimits.for_profile(TradingProfile.ACTIVE_CONTROLLED, D("100.00"))
    assert l.max_risk_per_trade == D("1.00")       # 1% من 100 أصغر من 1.50


def test_dollar_cap_binds_when_equity_rises():
    """الرصيد المرتفع لا يرفع المخاطرة فوق السقف الدولاري أبداً."""
    l = ProfileLimits.for_profile(TradingProfile.ACTIVE_CONTROLLED, D("1000.00"))
    assert l.max_risk_per_trade == D("1.50")


def test_no_unrestricted_high_risk_profile_exists():
    assert set(TradingProfile) == {
        TradingProfile.CAPITAL_PRESERVATION,
        TradingProfile.BALANCED,
        TradingProfile.ACTIVE_CONTROLLED,
    }
    assert not any("HIGH_RISK" in p.value for p in TradingProfile)


def test_global_loss_constitution_is_identical_in_every_profile():
    for p in TradingProfile:
        l = ProfileLimits.for_profile(p, CAPITAL)
        assert l.operational_drawdown_stop == GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD == D("6.50")
        assert l.gap_slippage_reserve == GLOBAL_GAP_SLIPPAGE_RESERVE_USD == D("1.00")
        assert l.absolute_loss_boundary == GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD == D("7.50")


def test_operational_stop_plus_reserve_equals_boundary_exactly():
    assert (
        GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD + GLOBAL_GAP_SLIPPAGE_RESERVE_USD
        == GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD
    )


def test_no_profile_allows_overnight_or_weekend_holding():
    for p in TradingProfile:
        l = ProfileLimits.for_profile(p, CAPITAL)
        assert l.allow_overnight is False
        assert l.allow_weekend_hold is False


def test_active_profile_does_not_lower_any_analysis_requirement():
    """
    الملف الأكثر نشاطاً يرفع الحجم فقط. عتبة الجودة و R:R لا تنخفضان دونه
    عن المتوازن، ولا يوجد حقل واحد في المواصفة يخفّف بوابة تحليلية.
    """
    balanced = PROFILE_SPECS[TradingProfile.BALANCED]
    active = PROFILE_SPECS[TradingProfile.ACTIVE_CONTROLLED]
    assert active.min_quality_score >= balanced.min_quality_score
    assert active.min_net_reward_risk >= balanced.min_net_reward_risk
    assert active.max_entry_orders_per_day == balanced.max_entry_orders_per_day
    assert active.max_open_positions == balanced.max_open_positions
    assert active.max_daily_loss_usd == balanced.max_daily_loss_usd
    assert active.max_weekly_loss_usd == balanced.max_weekly_loss_usd
    # الفارق الوحيد المسموح: حجم المخاطرة لكل صفقة
    assert active.max_risk_per_trade_usd > balanced.max_risk_per_trade_usd


def test_conservative_profile_is_strictly_stricter_than_balanced():
    cp = PROFILE_SPECS[TradingProfile.CAPITAL_PRESERVATION]
    b = PROFILE_SPECS[TradingProfile.BALANCED]
    assert cp.max_risk_per_trade_usd < b.max_risk_per_trade_usd
    assert cp.max_daily_loss_usd < b.max_daily_loss_usd
    assert cp.max_weekly_loss_usd < b.max_weekly_loss_usd
    assert cp.min_quality_score > b.min_quality_score
    assert cp.min_net_reward_risk > b.min_net_reward_risk


def test_active_controlled_forbidden_behaviours_are_declared():
    for phrase in ("مارتينجيل", "التهرّم (pyramiding)", "تداول الانتقام"):
        assert phrase in UNIVERSALLY_FORBIDDEN
    assert "إعادة الفتح تلقائياً بعد خسارة" in UNIVERSALLY_FORBIDDEN


def test_each_profile_has_a_distinct_fingerprint():
    prints = {p: profile_fingerprint(p) for p in TradingProfile}
    assert len(set(prints.values())) == len(TradingProfile)


# ---------------------------------------------------------------------------
# 2. تبديل الملفات
# ---------------------------------------------------------------------------

def test_downgrade_is_immediate_when_no_open_position():
    clock = FakeClock(T0)
    m = ProfileManager(TradingProfile.ACTIVE_CONTROLLED, clock=clock)
    r = m.request_change(TradingProfile.CAPITAL_PRESERVATION, SystemGuardState())
    assert r.accepted is True
    assert m.effective_profile is TradingProfile.CAPITAL_PRESERVATION
    assert r.record is not None and r.record.direction == "DOWNGRADE"


def test_downgrade_is_refused_while_a_position_is_open():
    m = ProfileManager(TradingProfile.ACTIVE_CONTROLLED, clock=FakeClock(T0))
    r = m.request_change(
        TradingProfile.CAPITAL_PRESERVATION, SystemGuardState(open_positions=1)
    )
    assert r.accepted is False
    assert r.refusal is ProfileChangeRefusal.OPEN_POSITION


def test_upgrade_requires_owner_confirmation():
    m = ProfileManager(TradingProfile.BALANCED, clock=FakeClock(T0))
    r = m.request_change(
        TradingProfile.ACTIVE_CONTROLLED, SystemGuardState(), owner_confirmed=False
    )
    assert r.refusal is ProfileChangeRefusal.OWNER_CONFIRMATION_MISSING
    assert m.effective_profile is TradingProfile.BALANCED


def test_upgrade_is_refused_with_an_open_position():
    m = ProfileManager(TradingProfile.BALANCED, clock=FakeClock(T0))
    r = m.request_change(
        TradingProfile.ACTIVE_CONTROLLED,
        SystemGuardState(open_positions=1),
        owner_confirmed=True,
    )
    assert r.refusal is ProfileChangeRefusal.OPEN_POSITION


def test_upgrade_is_refused_with_a_pending_or_unknown_order():
    m = ProfileManager(TradingProfile.BALANCED, clock=FakeClock(T0))
    for guards in (
        SystemGuardState(pending_orders=1),
        SystemGuardState(unknown_executions=1),
    ):
        r = m.request_change(
            TradingProfile.ACTIVE_CONTROLLED, guards, owner_confirmed=True
        )
        assert r.refusal is ProfileChangeRefusal.PENDING_OR_UNKNOWN_ORDER


def test_upgrade_is_refused_when_risk_engine_unhealthy_or_loss_locked():
    m = ProfileManager(TradingProfile.BALANCED, clock=FakeClock(T0))
    r1 = m.request_change(
        TradingProfile.ACTIVE_CONTROLLED,
        SystemGuardState(risk_engine_healthy=False),
        owner_confirmed=True,
    )
    assert r1.refusal is ProfileChangeRefusal.RISK_ENGINE_UNHEALTHY
    r2 = m.request_change(
        TradingProfile.ACTIVE_CONTROLLED,
        SystemGuardState(loss_lock_active=True),
        owner_confirmed=True,
    )
    assert r2.refusal is ProfileChangeRefusal.ACTIVE_LOSS_LOCK


def test_upgrade_is_refused_while_kill_switch_is_active():
    m = ProfileManager(TradingProfile.BALANCED, clock=FakeClock(T0))
    r = m.request_change(
        TradingProfile.ACTIVE_CONTROLLED,
        SystemGuardState(kill_switch_active=True),
        owner_confirmed=True,
    )
    assert r.refusal is ProfileChangeRefusal.KILL_SWITCH_ACTIVE


def test_upgrade_requires_the_full_cooling_period():
    clock = FakeClock(T0)
    m = ProfileManager(TradingProfile.BALANCED, clock=clock)
    guards = SystemGuardState()

    first = m.request_change(
        TradingProfile.ACTIVE_CONTROLLED, guards, owner_confirmed=True, owner_reference="OWNER-1"
    )
    assert first.accepted is False
    assert first.pending is not None
    assert m.effective_profile is TradingProfile.BALANCED

    clock.advance(hours=PROFILE_UPGRADE_COOLING_HOURS - 1)
    mid = m.confirm_pending_upgrade(guards)
    assert mid.accepted is False
    assert mid.refusal is ProfileChangeRefusal.COOLING_PERIOD_ACTIVE
    assert m.effective_profile is TradingProfile.BALANCED

    clock.advance(hours=1)
    done = m.confirm_pending_upgrade(guards)
    assert done.accepted is True
    assert m.effective_profile is TradingProfile.ACTIVE_CONTROLLED


def test_conditions_are_rechecked_at_activation_not_only_at_request():
    """التهدئة ليست تصريحاً مؤجّلاً: الشروط تُفحص من جديد لحظة التفعيل."""
    clock = FakeClock(T0)
    m = ProfileManager(TradingProfile.BALANCED, clock=clock)
    m.request_change(TradingProfile.ACTIVE_CONTROLLED, SystemGuardState(), owner_confirmed=True)
    clock.advance(hours=PROFILE_UPGRADE_COOLING_HOURS + 1)
    r = m.confirm_pending_upgrade(SystemGuardState(kill_switch_active=True))
    assert r.accepted is False
    assert r.refusal is ProfileChangeRefusal.KILL_SWITCH_ACTIVE
    assert m.effective_profile is TradingProfile.BALANCED


def test_profile_change_never_resets_any_counter():
    clock = FakeClock(T0)
    m = ProfileManager(TradingProfile.ACTIVE_CONTROLLED, clock=clock)
    guards = SystemGuardState(
        daily_loss=D("1.20"),
        weekly_loss=D("2.40"),
        total_drawdown=D("4.00"),
        consecutive_losses=1,
        open_risk=D("0"),
        strategy_validation_history_len=7,
    )
    before = guards.counters_snapshot()
    r = m.request_change(TradingProfile.CAPITAL_PRESERVATION, guards)
    assert r.accepted is True
    assert guards.counters_snapshot() == before
    assert r.record is not None
    assert r.record.counters_at_change == before


def test_kill_switch_state_survives_a_profile_change():
    clock = FakeClock(T0)
    m = ProfileManager(TradingProfile.ACTIVE_CONTROLLED, clock=clock)
    guards = SystemGuardState(kill_switch_active=True)
    # الخفض مسموح، لكنه لا يمسّ حالة Kill Switch
    r = m.request_change(TradingProfile.CAPITAL_PRESERVATION, guards)
    assert r.accepted is True
    assert guards.kill_switch_active is True
    assert r.record.counters_at_change["kill_switch_state"] is True


def test_switching_to_a_higher_risk_profile_cannot_clear_a_loss_lock():
    m = ProfileManager(TradingProfile.CAPITAL_PRESERVATION, clock=FakeClock(T0))
    guards = SystemGuardState(loss_lock_active=True, daily_loss=D("0.75"))
    r = m.request_change(TradingProfile.BALANCED, guards, owner_confirmed=True)
    assert r.accepted is False
    assert guards.loss_lock_active is True


def test_every_change_is_versioned_signed_and_auditable():
    m = ProfileManager(TradingProfile.ACTIVE_CONTROLLED, clock=FakeClock(T0))
    r = m.request_change(
        TradingProfile.BALANCED, SystemGuardState(), owner_reference="OWNER-REF-9"
    )
    rec = r.record
    assert rec is not None
    payload = rec.as_audit_payload()
    assert payload["event"] == "PROFILE_CHANGE"
    assert payload["from_profile"] == "ACTIVE_CONTROLLED"
    assert payload["to_profile"] == "BALANCED"
    assert payload["from_fingerprint"] != payload["to_fingerprint"]
    assert payload["profile_system_version"]
    assert payload["counters_at_change"]


def test_manager_exposes_selected_effective_pending_and_remaining():
    clock = FakeClock(T0)
    m = ProfileManager(TradingProfile.BALANCED, clock=clock)
    guards = SystemGuardState()
    m.request_change(TradingProfile.ACTIVE_CONTROLLED, guards, owner_confirmed=True)
    state = m.state_for_display(guards, CAPITAL)
    assert state["selected_profile"] == "ACTIVE_CONTROLLED"
    assert state["effective_profile"] == "BALANCED"
    assert state["pending_profile"] == "ACTIVE_CONTROLLED"
    assert state["cooling_remaining_seconds"] > 0
    assert "ساعة" in state["cooling_remaining_ar"]


def test_non_resettable_counter_list_is_complete():
    for key in (
        "daily_loss", "weekly_loss", "consecutive_losses", "total_drawdown",
        "open_risk", "kill_switch_state", "strategy_validation_history",
    ):
        assert key in NON_RESETTABLE_ON_PROFILE_CHANGE


def test_risk_order_is_strict_and_upgrade_detection_is_correct():
    assert (
        PROFILE_RISK_ORDER[TradingProfile.CAPITAL_PRESERVATION]
        < PROFILE_RISK_ORDER[TradingProfile.BALANCED]
        < PROFILE_RISK_ORDER[TradingProfile.ACTIVE_CONTROLLED]
    )
    assert is_upgrade(TradingProfile.BALANCED, TradingProfile.ACTIVE_CONTROLLED)
    assert not is_upgrade(TradingProfile.ACTIVE_CONTROLLED, TradingProfile.BALANCED)


def test_default_profile_is_the_most_conservative():
    assert DEFAULT_PROFILE is TradingProfile.CAPITAL_PRESERVATION
