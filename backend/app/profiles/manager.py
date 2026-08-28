"""
مدير ملفات التداول — التبديل، التهدئة، والتوقيع.

قواعد التبديل، حرفياً:

  خفض المخاطرة  → فوري (ما لم يُبطل مركزاً مفتوحاً)، بلا تهدئة، بلا تأكيد إضافي.
  رفع المخاطرة  → يتطلب **كل** ما يلي معاً:
                    · تأكيد صريح من المالكة
                    · لا مركز مفتوح
                    · لا أمر معلّق ولا حالة UNKNOWN
                    · محرك مخاطر سليم
                    · لا قفل خسارة نشط
                    · لا Kill Switch
                    · مرور 24 ساعة تهدئة قبل أن تصبح المخاطرة الأعلى **متاحة**

التبديل **لا يعيد ضبط** أي عدّاد: اليومي، الأسبوعي، الخسائر المتتالية،
التراجع الكلي، المخاطرة المفتوحة، حالة Kill Switch، أو تاريخ التحقق من
الاستراتيجيات. هذا مفروض بالبنية: المدير لا يملك مرجعاً واحداً يستطيع
الكتابة فوق أي من هذه القيم.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

from ..clock import now_utc
from ..money import D
from . import (
    DEFAULT_PROFILE,
    PROFILE_SPECS,
    PROFILE_SYSTEM_VERSION,
    PROFILE_UPGRADE_COOLING_HOURS,
    REFUSAL_TEXT_AR,
    NON_RESETTABLE_ON_PROFILE_CHANGE,
    ProfileChangeRefusal,
    ProfileLimits,
    TradingProfile,
    is_upgrade,
    profile_fingerprint,
)


@dataclass(frozen=True)
class SystemGuardState:
    """
    لقطة الحالة التي يقرأها المدير **ولا يكتب فيها**.

    كل حقل هنا مملوك لوحدة أخرى (محرك المخاطر، Kill Switch، التنفيذ).
    المدير يقرأ فقط — ولذلك لا يستطيع «إعادة ضبط» شيء عند التبديل.
    """

    open_positions: int = 0
    pending_orders: int = 0
    unknown_executions: int = 0
    risk_engine_healthy: bool = True
    loss_lock_active: bool = False
    kill_switch_active: bool = False

    # عدّادات تُعرض للمالكة، ولا تُمَس أبداً عند التبديل
    daily_loss: Decimal = Decimal("0")
    weekly_loss: Decimal = Decimal("0")
    total_drawdown: Decimal = Decimal("0")
    consecutive_losses: int = 0
    open_risk: Decimal = Decimal("0")
    strategy_validation_history_len: int = 0

    def counters_snapshot(self) -> dict:
        """القيم التي يجب أن تبقى كما هي عبر أي تبديل — تُقارَن في الاختبارات."""
        return {
            "daily_loss": str(self.daily_loss),
            "weekly_loss": str(self.weekly_loss),
            "consecutive_losses": self.consecutive_losses,
            "total_drawdown": str(self.total_drawdown),
            "open_risk": str(self.open_risk),
            "kill_switch_state": self.kill_switch_active,
            "strategy_validation_history": self.strategy_validation_history_len,
        }


@dataclass(frozen=True)
class ProfileChangeRecord:
    """قيد موقَّع لتغيير ملف — يدخل سجل التدقيق المقاوم للعبث."""

    sequence: int
    at_utc: datetime
    from_profile: TradingProfile
    to_profile: TradingProfile
    direction: str                     # "UPGRADE" | "DOWNGRADE"
    owner_confirmed: bool
    owner_reference: str
    profile_system_version: str
    from_fingerprint: str
    to_fingerprint: str
    counters_at_change: dict
    effective_at_utc: datetime
    note_ar: str

    def as_audit_payload(self) -> dict:
        return {
            "event": "PROFILE_CHANGE",
            "sequence": self.sequence,
            "at_utc": self.at_utc.isoformat(),
            "from_profile": self.from_profile.value,
            "to_profile": self.to_profile.value,
            "direction": self.direction,
            "owner_confirmed": self.owner_confirmed,
            "owner_reference": self.owner_reference,
            "profile_system_version": self.profile_system_version,
            "from_fingerprint": self.from_fingerprint,
            "to_fingerprint": self.to_fingerprint,
            "counters_at_change": self.counters_at_change,
            "effective_at_utc": self.effective_at_utc.isoformat(),
            "note_ar": self.note_ar,
        }


@dataclass(frozen=True)
class PendingUpgrade:
    """طلب رفع مخاطرة في انتظار انقضاء التهدئة."""

    target: TradingProfile
    requested_at_utc: datetime
    available_at_utc: datetime
    owner_reference: str

    def remaining(self, now: datetime) -> timedelta:
        return max(timedelta(0), self.available_at_utc - now)

    def is_ready(self, now: datetime) -> bool:
        return now >= self.available_at_utc


@dataclass(frozen=True)
class ProfileChangeResult:
    accepted: bool
    effective_profile: TradingProfile
    pending: Optional[PendingUpgrade]
    refusal: Optional[ProfileChangeRefusal]
    message_ar: str
    record: Optional[ProfileChangeRecord] = None


class ProfileManager:
    """
    يحتفظ بالملف الفعّال، والطلب المعلّق، وسجل التغييرات.

    لا يملك مرجعاً إلى محرك المخاطر ولا إلى Kill Switch ولا إلى أي عدّاد —
    يستقبل `SystemGuardState` للقراءة فقط. هذا هو ما يجعل «التبديل لا يعيد
    ضبط شيئاً» خاصية بنيوية لا وعداً نصياً.
    """

    def __init__(
        self,
        initial: TradingProfile = DEFAULT_PROFILE,
        clock: Callable[[], datetime] = None,
        cooling_hours: int = PROFILE_UPGRADE_COOLING_HOURS,
    ) -> None:
        self._effective: TradingProfile = initial
        self._selected: TradingProfile = initial
        self._pending: Optional[PendingUpgrade] = None
        self._clock: Callable[[], datetime] = clock or now_utc
        self._cooling = timedelta(hours=cooling_hours)
        self._history: list[ProfileChangeRecord] = []
        self._sequence = 0

    # -- قراءة -------------------------------------------------------------

    @property
    def effective_profile(self) -> TradingProfile:
        """الملف الذي تُطبَّق حدوده فعلاً الآن."""
        return self._effective

    @property
    def selected_profile(self) -> TradingProfile:
        """ما اختارته المالكة — قد يختلف عن الفعّال أثناء التهدئة."""
        return self._selected

    @property
    def pending_upgrade(self) -> Optional[PendingUpgrade]:
        return self._pending

    @property
    def history(self) -> tuple[ProfileChangeRecord, ...]:
        return tuple(self._history)

    def limits(self, current_equity: Optional[Decimal] = None) -> ProfileLimits:
        return ProfileLimits.for_profile(self._effective, current_equity)

    def cooling_remaining(self) -> Optional[timedelta]:
        if self._pending is None:
            return None
        return self._pending.remaining(self._clock())

    # -- تقييم بلا آثار جانبية ---------------------------------------------

    def evaluate_change(
        self,
        target: TradingProfile,
        guards: SystemGuardState,
        owner_confirmed: bool,
    ) -> Optional[ProfileChangeRefusal]:
        """
        يعيد سبب الرفض إن وُجد، بلا تغيير أي حالة.
        تُستعمل للواجهة كي تعرض «سبب عدم السماح بتغيير الملف» قبل المحاولة.
        """
        if target not in PROFILE_SPECS:
            return ProfileChangeRefusal.UNKNOWN_PROFILE
        if target is self._effective and self._pending is None:
            return ProfileChangeRefusal.SAME_PROFILE

        if not is_upgrade(self._effective, target):
            # خفض المخاطرة: يُسمح فوراً ما لم يُبطل مركزاً مفتوحاً.
            if guards.open_positions > 0:
                return ProfileChangeRefusal.OPEN_POSITION
            return None

        # رفع المخاطرة: كل الشروط معاً.
        if not owner_confirmed:
            return ProfileChangeRefusal.OWNER_CONFIRMATION_MISSING
        if guards.kill_switch_active:
            return ProfileChangeRefusal.KILL_SWITCH_ACTIVE
        if guards.open_positions > 0:
            return ProfileChangeRefusal.OPEN_POSITION
        if guards.pending_orders > 0 or guards.unknown_executions > 0:
            return ProfileChangeRefusal.PENDING_OR_UNKNOWN_ORDER
        if not guards.risk_engine_healthy:
            return ProfileChangeRefusal.RISK_ENGINE_UNHEALTHY
        if guards.loss_lock_active:
            return ProfileChangeRefusal.ACTIVE_LOSS_LOCK
        return None

    # -- تنفيذ -------------------------------------------------------------

    def request_change(
        self,
        target: TradingProfile,
        guards: SystemGuardState,
        owner_confirmed: bool = False,
        owner_reference: str = "",
    ) -> ProfileChangeResult:
        now = self._clock()
        refusal = self.evaluate_change(target, guards, owner_confirmed)
        if refusal is not None:
            return ProfileChangeResult(
                accepted=False,
                effective_profile=self._effective,
                pending=self._pending,
                refusal=refusal,
                message_ar=REFUSAL_TEXT_AR[refusal],
            )

        if not is_upgrade(self._effective, target):
            return self._apply(target, now, guards, owner_confirmed, owner_reference, "DOWNGRADE")

        # رفع: يبدأ التهدئة، ولا يصبح فعّالاً الآن.
        if self._pending is not None and self._pending.target is target:
            if self._pending.is_ready(now):
                return self._apply(
                    target, now, guards, True, owner_reference or self._pending.owner_reference,
                    "UPGRADE",
                )
            remaining = self._pending.remaining(now)
            return ProfileChangeResult(
                accepted=False,
                effective_profile=self._effective,
                pending=self._pending,
                refusal=ProfileChangeRefusal.COOLING_PERIOD_ACTIVE,
                message_ar=(
                    f"{REFUSAL_TEXT_AR[ProfileChangeRefusal.COOLING_PERIOD_ACTIVE]} "
                    f"المتبقي: {_format_remaining_ar(remaining)}."
                ),
            )

        self._pending = PendingUpgrade(
            target=target,
            requested_at_utc=now,
            available_at_utc=now + self._cooling,
            owner_reference=owner_reference,
        )
        self._selected = target
        return ProfileChangeResult(
            accepted=False,
            effective_profile=self._effective,
            pending=self._pending,
            refusal=ProfileChangeRefusal.COOLING_PERIOD_ACTIVE,
            message_ar=(
                f"بدأت فترة التهدئة {PROFILE_UPGRADE_COOLING_HOURS} ساعة. "
                f"المخاطرة الأعلى تصبح متاحة في "
                f"{self._pending.available_at_utc.isoformat()}. "
                "الملف الفعّال لم يتغيّر."
            ),
        )

    def confirm_pending_upgrade(
        self, guards: SystemGuardState, owner_reference: str = ""
    ) -> ProfileChangeResult:
        """تأكيد الرفع بعد انقضاء التهدئة. الشروط تُفحص **من جديد** لحظة التفعيل."""
        if self._pending is None:
            return ProfileChangeResult(
                accepted=False,
                effective_profile=self._effective,
                pending=None,
                refusal=ProfileChangeRefusal.SAME_PROFILE,
                message_ar="لا يوجد طلب رفع معلّق.",
            )
        return self.request_change(
            self._pending.target,
            guards,
            owner_confirmed=True,
            owner_reference=owner_reference or self._pending.owner_reference,
        )

    def cancel_pending(self) -> None:
        self._pending = None
        self._selected = self._effective

    def _apply(
        self,
        target: TradingProfile,
        now: datetime,
        guards: SystemGuardState,
        owner_confirmed: bool,
        owner_reference: str,
        direction: str,
    ) -> ProfileChangeResult:
        previous = self._effective
        self._sequence += 1
        record = ProfileChangeRecord(
            sequence=self._sequence,
            at_utc=now,
            from_profile=previous,
            to_profile=target,
            direction=direction,
            owner_confirmed=owner_confirmed,
            owner_reference=owner_reference,
            profile_system_version=PROFILE_SYSTEM_VERSION,
            from_fingerprint=profile_fingerprint(previous),
            to_fingerprint=profile_fingerprint(target),
            # يُسجَّل ما كانت عليه العدّادات، إثباتاً أنها لم تُمَس.
            counters_at_change=guards.counters_snapshot(),
            effective_at_utc=now,
            note_ar=(
                "خفض مستوى المخاطرة — فوري."
                if direction == "DOWNGRADE"
                else "رفع مستوى المخاطرة بعد انقضاء التهدئة وتأكيد المالكة."
            ),
        )
        self._history.append(record)
        self._effective = target
        self._selected = target
        self._pending = None
        return ProfileChangeResult(
            accepted=True,
            effective_profile=target,
            pending=None,
            refusal=None,
            message_ar=(
                f"الملف الفعّال أصبح «{PROFILE_SPECS[target].name_ar}». "
                "لم يُعَد ضبط أي عدّاد خسارة أو قفل."
            ),
            record=record,
        )

    # -- عرض ---------------------------------------------------------------

    def state_for_display(
        self, guards: SystemGuardState, current_equity: Optional[Decimal] = None
    ) -> dict:
        now = self._clock()
        limits = self.limits(current_equity)
        pending = self._pending
        blocked_reason = self.evaluate_change(
            self._selected, guards, owner_confirmed=True
        ) if self._selected is not self._effective else None
        return {
            "selected_profile": self._selected.value,
            "selected_name_ar": PROFILE_SPECS[self._selected].name_ar,
            "effective_profile": self._effective.value,
            "effective_name_ar": PROFILE_SPECS[self._effective].name_ar,
            "risk_level_ar": PROFILE_SPECS[self._effective].name_ar,
            "pending_profile": pending.target.value if pending else None,
            "pending_available_at_utc": (
                pending.available_at_utc.isoformat() if pending else None
            ),
            "cooling_remaining_seconds": (
                int(pending.remaining(now).total_seconds()) if pending else 0
            ),
            "cooling_remaining_ar": (
                _format_remaining_ar(pending.remaining(now)) if pending else "—"
            ),
            "change_blocked_reason": blocked_reason.value if blocked_reason else None,
            "change_blocked_reason_ar": (
                REFUSAL_TEXT_AR[blocked_reason] if blocked_reason else ""
            ),
            "limits": limits.as_display_dict(),
            "fingerprint": profile_fingerprint(self._effective),
            "non_resettable_counters": sorted(NON_RESETTABLE_ON_PROFILE_CHANGE),
            "counters": guards.counters_snapshot(),
            "history_len": len(self._history),
        }


def _format_remaining_ar(delta: timedelta) -> str:
    total = int(max(0, delta.total_seconds()))
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    if hours == 0 and minutes == 0:
        return "انتهت"
    return f"{hours} ساعة و{minutes} دقيقة"


__all__ = [
    "ProfileManager",
    "SystemGuardState",
    "ProfileChangeRecord",
    "ProfileChangeResult",
    "PendingUpgrade",
]
