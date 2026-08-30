"""
بقاء قاطع الطوارئ عبر إعادة التشغيل — إصلاح C2.

قبل هذا الملف كانت حالة القاطع **في الذاكرة وحدها**. وsystemd يعمل بـ
`Restart=always`. فانهيارٌ متكرّر — أو إعادة نشر — كان **يُطفئ القاطع بصمت**
ويصفّر العدّادات. أي أن الإعداد الذي يُبقي الخدمة حيّة كان يمحو الإعداد الذي
يوقفها عند الخطر.

القاعدة هنا: **القاطع يُطفَأ بموافقة إنسان مكتوبة فقط.** أي طريق آخر لإطفائه
— بما فيه إعادة الإقلاع — عيب.

جدول `kill_switch_events` موجود في المخطط منذ البداية ولم يكن يُكتَب فيه.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import KillSwitchEventRow
from .engine import (
    DEFAULT_EMERGENCY_POLICY,
    KillSwitchEvent,
    KillSwitchState,
    KillSwitchTrigger,
    ResetApproval,
)


def _latest_row(session: Session) -> Optional[KillSwitchEventRow]:
    return session.execute(
        select(KillSwitchEventRow).order_by(KillSwitchEventRow.id.desc()).limit(1)
    ).scalars().first()


def load_kill_switch_state(session: Session) -> KillSwitchState:
    """
    يعيد بناء الحالة من السجل.

    القاطع يُعتبر **مفعّلاً** إذا كان آخر حدث بلا `reset_at_utc`. لا يُستنتَج
    الإطفاء من غياب البيانات: سجلٌّ فارغ يعني «لم يُفعَّل قطّ»، وهذه حالة
    مختلفة عن «فُعِّل ثم أُطفئ».
    """
    row = _latest_row(session)
    if row is None:
        return KillSwitchState()

    try:
        trigger = KillSwitchTrigger(row.trigger)
    except ValueError:
        # محفِّز غير معروف في هذا الإصدار: نُبقي القاطع مفعّلاً ولا نتجاهله.
        trigger = KillSwitchTrigger.MANUAL

    try:
        context = json.loads(row.context_json or "{}")
    except (ValueError, TypeError):
        context = {}

    event = KillSwitchEvent(
        trigger=trigger,
        reason_ar=row.reason_ar,
        policy=DEFAULT_EMERGENCY_POLICY[trigger],
        context=context,
        triggered_at_utc=row.triggered_at_utc,
    )
    state = KillSwitchState(active=row.reset_at_utc is None, events=[event])
    if row.reset_at_utc is not None:
        state.resets.append(
            ResetApproval(
                approved_by=row.reset_approved_by,
                reason_ar=row.reset_reason_ar,
                approved_at_utc=row.reset_at_utc,
                reviewed_trigger=trigger,
            )
        )
    return state


def record_trigger(session: Session, event: KillSwitchEvent) -> None:
    """يُكتَب فور التفعيل. يُستدعى من `notifier` فلا يحتاج تعديل المحرّك."""
    session.add(
        KillSwitchEventRow(
            trigger=event.trigger.value,
            reason_ar=event.reason_ar,
            policy=str(getattr(event.policy, "value", event.policy)),
            context_json=json.dumps(event.context, ensure_ascii=False, default=str),
            triggered_at_utc=event.triggered_at_utc,
        )
    )
    session.commit()


def record_reset(session: Session, approval: ResetApproval) -> None:
    """يُغلق آخر حدث مفتوح. لا يُنشئ صفاً جديداً — الإطفاء ليس حدثاً مستقلاً."""
    row = _latest_row(session)
    if row is None or row.reset_at_utc is not None:
        return
    row.reset_approved_by = approval.approved_by
    row.reset_reason_ar = approval.reason_ar
    row.reset_at_utc = approval.approved_at_utc
    session.commit()


__all__ = ["load_kill_switch_state", "record_trigger", "record_reset"]
