"""
Kill Switch — أعلى صلاحية برمجية في النظام.

مستقل تماماً عن Strategy Engine و Risk Engine:
  * لا يستورد أياً منهما.
  * حالته تُفحص *قبل* أي شيء آخر في الـpipeline.
  * لا يُعاد تفعيله تلقائياً أبداً — يتطلب موافقة بشرية موثقة.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..clock import now_utc
from ..money import D


class KillSwitchTrigger(str, Enum):
    HARD_TOTAL_LOSS = "HARD_TOTAL_LOSS"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    MISSING_MARKET_DATA = "MISSING_MARKET_DATA"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    UNKNOWN_POSITION = "UNKNOWN_POSITION"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    EXECUTION_CONFIRMATION_FAILED = "EXECUTION_CONFIRMATION_FAILED"
    STOP_LOSS_REJECTED = "STOP_LOSS_REJECTED"
    SIZE_EXCEEDS_EXPECTED = "SIZE_EXCEEDS_EXPECTED"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    CLOCK_ERROR = "CLOCK_ERROR"
    PERMISSIONS_CHANGED = "PERMISSIONS_CHANGED"
    ACCOUNT_BECAME_MARGIN = "ACCOUNT_BECAME_MARGIN"
    BASELINE_CHANGED_WITHOUT_APPROVAL = "BASELINE_CHANGED_WITHOUT_APPROVAL"
    STRATEGY_ANOMALY = "STRATEGY_ANOMALY"
    AUDIT_LOG_UNAVAILABLE = "AUDIT_LOG_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    MANUAL = "MANUAL"


TRIGGER_LABELS_AR: dict[KillSwitchTrigger, str] = {
    KillSwitchTrigger.HARD_TOTAL_LOSS: "بلوغ حد الخسارة الإجمالي الصارم",
    KillSwitchTrigger.DAILY_LOSS_LIMIT: "بلوغ حد الخسارة اليومي",
    KillSwitchTrigger.WEEKLY_LOSS_LIMIT: "بلوغ حد الخسارة الأسبوعي",
    KillSwitchTrigger.CONSECUTIVE_LOSSES: "ثلاث خسائر متتالية",
    KillSwitchTrigger.STALE_MARKET_DATA: "بيانات سوق متأخرة",
    KillSwitchTrigger.MISSING_MARKET_DATA: "بيانات سوق مفقودة",
    KillSwitchTrigger.BROKER_DISCONNECTED: "انقطاع الاتصال بالوسيط",
    KillSwitchTrigger.RECONCILIATION_MISMATCH: "اختلاف سجلاتنا عن حساب الوسيط",
    KillSwitchTrigger.UNKNOWN_POSITION: "مركز غير معروف في الحساب",
    KillSwitchTrigger.DUPLICATE_ORDER: "أمر مكرر",
    KillSwitchTrigger.EXECUTION_CONFIRMATION_FAILED: "فشل تأكيد التنفيذ",
    KillSwitchTrigger.STOP_LOSS_REJECTED: "رفض أمر وقف الخسارة",
    KillSwitchTrigger.SIZE_EXCEEDS_EXPECTED: "الحجم المنفذ يتجاوز المتوقع",
    KillSwitchTrigger.ABNORMAL_SPREAD: "اتساع غير طبيعي في السبريد",
    KillSwitchTrigger.CLOCK_ERROR: "خطأ في الساعة أو الجلسة",
    KillSwitchTrigger.PERMISSIONS_CHANGED: "تغيّر صلاحيات التداول في الحساب",
    KillSwitchTrigger.ACCOUNT_BECAME_MARGIN: "تحوّل الحساب إلى Margin",
    KillSwitchTrigger.BASELINE_CHANGED_WITHOUT_APPROVAL: "تغيّر رأس المال المرجعي دون اعتماد",
    KillSwitchTrigger.STRATEGY_ANOMALY: "سلوك غير متوقع من الاستراتيجية",
    KillSwitchTrigger.AUDIT_LOG_UNAVAILABLE: "تعذّر الوصول إلى سجل التدقيق",
    KillSwitchTrigger.DATABASE_UNAVAILABLE: "تعذّر الوصول إلى قاعدة البيانات",
    KillSwitchTrigger.MANUAL: "تفعيل يدوي من المالكة",
}


class EmergencyPolicy(str, Enum):
    """
    ماذا نفعل بالمركز المفتوح عند التفعيل.
    الافتراض *ليس* الإغلاق الفوري: الإغلاق بأمر سوق أثناء عطل بيانات
    أو اتساع سبريد قد يكون أسوأ من الانتظار.
    """

    KEEP_PROTECTIVE_STOP = "KEEP_PROTECTIVE_STOP"
    CLOSE_AT_MARKET = "CLOSE_AT_MARKET"
    NOTIFY_OWNER_ONLY = "NOTIFY_OWNER_ONLY"


#: السياسة الافتراضية لكل مُطلِق — موثقة مسبقاً وليست قراراً لحظياً.
DEFAULT_EMERGENCY_POLICY: dict[KillSwitchTrigger, EmergencyPolicy] = {
    KillSwitchTrigger.HARD_TOTAL_LOSS: EmergencyPolicy.CLOSE_AT_MARKET,
    KillSwitchTrigger.DAILY_LOSS_LIMIT: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.WEEKLY_LOSS_LIMIT: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.CONSECUTIVE_LOSSES: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.STALE_MARKET_DATA: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.MISSING_MARKET_DATA: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.BROKER_DISCONNECTED: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.RECONCILIATION_MISMATCH: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.UNKNOWN_POSITION: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.DUPLICATE_ORDER: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.EXECUTION_CONFIRMATION_FAILED: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.STOP_LOSS_REJECTED: EmergencyPolicy.CLOSE_AT_MARKET,
    KillSwitchTrigger.SIZE_EXCEEDS_EXPECTED: EmergencyPolicy.CLOSE_AT_MARKET,
    KillSwitchTrigger.ABNORMAL_SPREAD: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.CLOCK_ERROR: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.PERMISSIONS_CHANGED: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.ACCOUNT_BECAME_MARGIN: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.BASELINE_CHANGED_WITHOUT_APPROVAL: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.STRATEGY_ANOMALY: EmergencyPolicy.KEEP_PROTECTIVE_STOP,
    KillSwitchTrigger.AUDIT_LOG_UNAVAILABLE: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.DATABASE_UNAVAILABLE: EmergencyPolicy.NOTIFY_OWNER_ONLY,
    KillSwitchTrigger.MANUAL: EmergencyPolicy.NOTIFY_OWNER_ONLY,
}


@dataclass(frozen=True)
class KillSwitchEvent:
    trigger: KillSwitchTrigger
    reason_ar: str
    policy: EmergencyPolicy
    context: dict
    triggered_at_utc: datetime
    cancel_pending_orders: bool = True


@dataclass(frozen=True)
class ResetApproval:
    approved_by: str
    reason_ar: str
    approved_at_utc: datetime
    reviewed_trigger: KillSwitchTrigger


@dataclass
class KillSwitchState:
    active: bool = False
    events: list[KillSwitchEvent] = field(default_factory=list)
    resets: list[ResetApproval] = field(default_factory=list)

    @property
    def current_event(self) -> Optional[KillSwitchEvent]:
        return self.events[-1] if self.active and self.events else None


class KillSwitch:
    """
    الحالة الافتراضية: غير مفعّل. بمجرد التفعيل، `allows_new_entries()` تعود False
    إلى الأبد حتى يستدعي إنسان `reset()` بموافقة موثقة.
    """

    def __init__(self, state: KillSwitchState | None = None, notifier=None) -> None:
        self.state = state or KillSwitchState()
        self._notifier = notifier

    # --- state -------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self.state.active

    def allows_new_entries(self) -> bool:
        return not self.state.active

    def trigger(
        self,
        trigger: KillSwitchTrigger,
        *,
        reason_ar: str | None = None,
        context: dict | None = None,
        at: datetime | None = None,
    ) -> KillSwitchEvent:
        policy = DEFAULT_EMERGENCY_POLICY[trigger]
        event = KillSwitchEvent(
            trigger=trigger,
            reason_ar=reason_ar or TRIGGER_LABELS_AR[trigger],
            policy=policy,
            context=context or {},
            triggered_at_utc=at or now_utc(),
        )
        self.state.active = True
        self.state.events.append(event)
        if self._notifier is not None:
            self._notifier(event)
        return event

    def reset(self, *, approved_by: str, reason_ar: str, at: datetime | None = None) -> ResetApproval:
        if not self.state.active:
            raise RuntimeError("Kill Switch غير مفعّل — لا شيء لإعادة تفعيله")
        if not approved_by.strip():
            raise ValueError("إعادة التفعيل تتطلب اسم الموافِق")
        if len(reason_ar.strip()) < 10:
            raise ValueError("إعادة التفعيل تتطلب سبباً مكتوباً لا يقل عن 10 أحرف")
        current = self.state.events[-1]
        approval = ResetApproval(
            approved_by=approved_by,
            reason_ar=reason_ar,
            approved_at_utc=at or now_utc(),
            reviewed_trigger=current.trigger,
        )
        self.state.active = False
        self.state.resets.append(approval)
        return approval


# ---------------------------------------------------------------------------
# Evaluators — دوال نقية تُقرر هل يجب التفعيل
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LossPicture:
    baseline_equity: Decimal
    current_equity: Decimal
    realized_today: Decimal
    unrealized: Decimal
    realized_this_week: Decimal
    consecutive_losses: int

    @property
    def total_loss(self) -> Decimal:
        return max(Decimal("0"), self.baseline_equity - self.current_equity)

    @property
    def day_loss(self) -> Decimal:
        return max(Decimal("0"), -(self.realized_today + self.unrealized))

    @property
    def week_loss(self) -> Decimal:
        return max(Decimal("0"), -(self.realized_this_week + self.unrealized))


def evaluate_loss_triggers(picture: LossPicture, limits) -> Optional[tuple[KillSwitchTrigger, str]]:
    """الترتيب مقصود: الأشد أولاً."""
    if picture.total_loss >= D(limits.hard_total_loss):
        return (
            KillSwitchTrigger.HARD_TOTAL_LOSS,
            f"الخسارة الإجمالية {picture.total_loss:.2f} بلغت الحد الصارم {D(limits.hard_total_loss):.2f} دولار.",
        )
    if picture.consecutive_losses >= limits.consecutive_losses_kill:
        return (
            KillSwitchTrigger.CONSECUTIVE_LOSSES,
            f"{picture.consecutive_losses} خسائر متتالية — الحد {limits.consecutive_losses_kill}.",
        )
    if picture.week_loss >= D(limits.weekly_loss):
        return (
            KillSwitchTrigger.WEEKLY_LOSS_LIMIT,
            f"خسارة الأسبوع {picture.week_loss:.2f} بلغت الحد {D(limits.weekly_loss):.2f} دولار.",
        )
    if picture.day_loss >= D(limits.daily_loss):
        return (
            KillSwitchTrigger.DAILY_LOSS_LIMIT,
            f"خسارة اليوم {picture.day_loss:.2f} بلغت الحد {D(limits.daily_loss):.2f} دولار.",
        )
    return None
