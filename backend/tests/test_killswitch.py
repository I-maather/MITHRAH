from __future__ import annotations

import pytest

from app.killswitch.engine import (
    DEFAULT_EMERGENCY_POLICY,
    TRIGGER_LABELS_AR,
    EmergencyPolicy,
    KillSwitch,
    KillSwitchTrigger,
    LossPicture,
    evaluate_loss_triggers,
)
from app.money import D
from app.risk.constitution import RiskLimits


@pytest.fixture
def limits150():
    return RiskLimits.from_baseline(D("150.00"))


def picture(**kw):
    base = dict(
        baseline_equity=D("150"), current_equity=D("150"),
        realized_today=D("0"), unrealized=D("0"), realized_this_week=D("0"),
        consecutive_losses=0,
    )
    base.update(kw)
    return LossPicture(**base)


# --- كل مُطلِق له اختبار ----------------------------------------------------

def test_every_trigger_has_arabic_label_and_policy():
    for trigger in KillSwitchTrigger:
        assert trigger in TRIGGER_LABELS_AR, f"{trigger} بلا وصف عربي"
        assert trigger in DEFAULT_EMERGENCY_POLICY, f"{trigger} بلا سياسة طوارئ محددة مسبقاً"


@pytest.mark.parametrize("trigger", list(KillSwitchTrigger))
def test_each_trigger_halts_new_entries(trigger):
    ks = KillSwitch()
    assert ks.allows_new_entries()
    ks.trigger(trigger)
    assert ks.is_active
    assert not ks.allows_new_entries()


def test_hard_total_loss_trigger(limits150):
    result = evaluate_loss_triggers(picture(current_equity=D("142.50")), limits150)
    assert result is not None and result[0] is KillSwitchTrigger.HARD_TOTAL_LOSS


def test_daily_loss_trigger(limits150):
    result = evaluate_loss_triggers(picture(realized_today=D("-1.50")), limits150)
    assert result is not None and result[0] is KillSwitchTrigger.DAILY_LOSS_LIMIT


def test_weekly_loss_trigger(limits150):
    result = evaluate_loss_triggers(picture(realized_this_week=D("-4.50")), limits150)
    assert result is not None and result[0] is KillSwitchTrigger.WEEKLY_LOSS_LIMIT


def test_three_consecutive_losses_trigger(limits150):
    result = evaluate_loss_triggers(picture(consecutive_losses=3), limits150)
    assert result is not None and result[0] is KillSwitchTrigger.CONSECUTIVE_LOSSES


def test_two_consecutive_losses_do_not_kill(limits150):
    assert evaluate_loss_triggers(picture(consecutive_losses=2), limits150) is None


def test_unrealized_loss_counts_toward_daily_limit(limits150):
    result = evaluate_loss_triggers(picture(unrealized=D("-1.50")), limits150)
    assert result is not None and result[0] is KillSwitchTrigger.DAILY_LOSS_LIMIT


def test_hard_loss_takes_priority_over_daily(limits150):
    result = evaluate_loss_triggers(
        picture(current_equity=D("141.00"), realized_today=D("-9.00"), consecutive_losses=5),
        limits150,
    )
    assert result[0] is KillSwitchTrigger.HARD_TOTAL_LOSS


def test_no_trigger_when_clean(limits150):
    assert evaluate_loss_triggers(picture(), limits150) is None


# --- إعادة التفعيل ----------------------------------------------------------

def test_never_resets_automatically():
    ks = KillSwitch()
    ks.trigger(KillSwitchTrigger.DAILY_LOSS_LIMIT)
    for _ in range(10):
        assert not ks.allows_new_entries()


def test_reset_requires_approver_and_reason():
    ks = KillSwitch()
    ks.trigger(KillSwitchTrigger.MANUAL)
    with pytest.raises(ValueError):
        ks.reset(approved_by="", reason_ar="سبب كافٍ جداً للمراجعة")
    with pytest.raises(ValueError):
        ks.reset(approved_by="Maather", reason_ar="قصير")
    approval = ks.reset(approved_by="Maather", reason_ar="راجعت السجل وسبب التفعيل مفهوم ومعالج.")
    assert ks.allows_new_entries()
    assert approval.reviewed_trigger is KillSwitchTrigger.MANUAL


def test_reset_when_inactive_is_an_error():
    with pytest.raises(RuntimeError):
        KillSwitch().reset(approved_by="Maather", reason_ar="لا يوجد ما يُعاد تفعيله هنا")


def test_emergency_policy_is_not_always_close():
    """التصميم يرفض افتراض أن الإغلاق الفوري دائماً أفضل."""
    assert DEFAULT_EMERGENCY_POLICY[KillSwitchTrigger.STALE_MARKET_DATA] is EmergencyPolicy.KEEP_PROTECTIVE_STOP
    assert DEFAULT_EMERGENCY_POLICY[KillSwitchTrigger.STOP_LOSS_REJECTED] is EmergencyPolicy.CLOSE_AT_MARKET


def test_trigger_records_context_and_notifies():
    seen = []
    ks = KillSwitch(notifier=seen.append)
    ev = ks.trigger(KillSwitchTrigger.ABNORMAL_SPREAD, context={"spread_pct": "0.9"})
    assert seen and seen[0] is ev
    assert ev.context["spread_pct"] == "0.9"
    assert ev.cancel_pending_orders is True
