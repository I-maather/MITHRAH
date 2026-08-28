"""
استرداد الحالة عند الإقلاع.

القاعدة: **الإقلاع لا يفتح شيئاً أبداً.**
النظام يبدأ مقفلاً، ثم يحاول إثبات أنه يستحق الفتح — لا العكس.

ترتيب الفحص:
  1. تحميل الحالة الدائمة (Kill Switch يبقى مفعّلاً عبر إعادة التشغيل).
  2. البحث عن محاولات تنفيذ غير محسومة.
  3. مطابقة المراكز المحلية مع الوسيط.
  4. لا يُسمح بأي دخول جديد حتى تنجح 2 و3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now_utc
from ..contracts import ExecutionUncertainty, Position
from ..risk.constitution import CONSTITUTION_VERSION, RiskMode
from .models import ExecutionAttempt, SystemStateRow


class StartupVerdict(str, Enum):
    LOCKED_PENDING_RECONCILIATION = "LOCKED_PENDING_RECONCILIATION"
    LOCKED_UNKNOWN_EXECUTION = "LOCKED_UNKNOWN_EXECUTION"
    LOCKED_KILL_SWITCH = "LOCKED_KILL_SWITCH"
    LOCKED_BY_DEFAULT = "LOCKED_BY_DEFAULT"
    READY_TRADING_STILL_LOCKED = "READY_TRADING_STILL_LOCKED"


@dataclass
class StartupReport:
    verdict: StartupVerdict
    trading_locked: bool
    kill_switch_active: bool
    risk_mode: str
    unresolved_attempts: list[str] = field(default_factory=list)
    reconciliation_problems: list[str] = field(default_factory=list)
    notes_ar: list[str] = field(default_factory=list)
    checked_at_utc: datetime = field(default_factory=now_utc)

    @property
    def allows_new_entries(self) -> bool:
        """
        لا يعيد True أبداً من الإقلاع وحده. فتح التداول قرار منفصل موثّق.
        """
        return False

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "trading_locked": self.trading_locked,
            "kill_switch_active": self.kill_switch_active,
            "risk_mode": self.risk_mode,
            "unresolved_attempts": list(self.unresolved_attempts),
            "reconciliation_problems": list(self.reconciliation_problems),
            "notes_ar": list(self.notes_ar),
            "allows_new_entries": self.allows_new_entries,
            "checked_at_utc": self.checked_at_utc.isoformat(),
        }


def load_or_create_state(session: Session) -> SystemStateRow:
    row = session.execute(select(SystemStateRow).limit(1)).scalar_one_or_none()
    if row is None:
        row = SystemStateRow(
            trading_locked=True,
            kill_switch_active=False,
            risk_mode=RiskMode.VALIDATION.value,
            risk_constitution_version=CONSTITUTION_VERSION,
            updated_at_utc=now_utc(),
        )
        session.add(row)
        session.commit()
    return row


def unresolved_attempts(session: Session) -> list[ExecutionAttempt]:
    return list(
        session.execute(
            select(ExecutionAttempt).where(ExecutionAttempt.resolved.is_(False))
        ).scalars()
    )


def record_attempt(
    session: Session,
    *,
    idempotency_key: str,
    broker: str,
    broker_environment: str,
    epic: str,
    deal_reference: Optional[str] = None,
    uncertainty: ExecutionUncertainty = ExecutionUncertainty.PENDING_CONFIRMATION,
    at: Optional[datetime] = None,
) -> ExecutionAttempt:
    """
    يُكتب **قبل** الإرسال. هذا هو ما يجعل إعادة الإرسال الأعمى مستحيلة:
    حتى لو انقطعت العملية بعد الإرسال مباشرة، المحاولة مسجّلة.
    """
    attempt = ExecutionAttempt(
        idempotency_key=idempotency_key,
        broker=broker,
        broker_environment=broker_environment,
        epic=epic,
        deal_reference=deal_reference,
        uncertainty=uncertainty.value,
        resolved=False,
        attempted_at_utc=at or now_utc(),
    )
    session.add(attempt)
    session.commit()
    return attempt


def resolve_attempt(
    session: Session,
    attempt: ExecutionAttempt,
    *,
    uncertainty: ExecutionUncertainty,
    note_ar: str,
    broker_deal_id: Optional[str] = None,
    at: Optional[datetime] = None,
) -> ExecutionAttempt:
    attempt.uncertainty = uncertainty.value
    attempt.resolution_note_ar = note_ar
    attempt.broker_deal_id = broker_deal_id
    attempt.resolved = uncertainty in (
        ExecutionUncertainty.RESOLVED_FILLED,
        ExecutionUncertainty.RESOLVED_REJECTED,
        ExecutionUncertainty.RESOLVED_ABSENT,
    )
    attempt.resolved_at_utc = at or now_utc()
    session.commit()
    return attempt


def run_startup_recovery(
    session: Session,
    *,
    fetch_broker_positions: Optional[Callable[[], Sequence[Position]]] = None,
    local_positions: Optional[Sequence[Position]] = None,
) -> StartupReport:
    """
    يفحص ولا يصلح. الإصلاح قرار بشري.
    """
    state = load_or_create_state(session)
    notes: list[str] = []

    if state.risk_constitution_version != CONSTITUTION_VERSION:
        notes.append(
            f"إصدار دستور المخاطر تغيّر من {state.risk_constitution_version or '—'} "
            f"إلى {CONSTITUTION_VERSION}. راجعي docs/RISK_CONSTITUTION_V0.2.md."
        )

    if state.kill_switch_active:
        return StartupReport(
            verdict=StartupVerdict.LOCKED_KILL_SWITCH,
            trading_locked=True,
            kill_switch_active=True,
            risk_mode=state.risk_mode,
            notes_ar=notes
            + [
                f"Kill Switch ما زال مفعّلاً بعد إعادة التشغيل: {state.kill_switch_reason_ar}",
                "إعادة التشغيل لا تُلغي Kill Switch — يلزم إعادة تفعيل موثّقة.",
            ],
        )

    pending = unresolved_attempts(session)
    if pending:
        return StartupReport(
            verdict=StartupVerdict.LOCKED_UNKNOWN_EXECUTION,
            trading_locked=True,
            kill_switch_active=False,
            risk_mode=state.risk_mode,
            unresolved_attempts=[a.idempotency_key for a in pending],
            notes_ar=notes
            + [
                f"توجد {len(pending)} محاولة تنفيذ غير محسومة. "
                "ممنوع أي إرسال جديد قبل حسمها بالقراءة من الوسيط — لا بإعادة الإرسال.",
            ],
        )

    problems: list[str] = []
    if fetch_broker_positions is not None:
        from ..execution.orders import reconcile

        try:
            broker_positions = list(fetch_broker_positions())
        except Exception as exc:  # noqa: BLE001
            return StartupReport(
                verdict=StartupVerdict.LOCKED_PENDING_RECONCILIATION,
                trading_locked=True,
                kill_switch_active=False,
                risk_mode=state.risk_mode,
                reconciliation_problems=[f"تعذّر جلب مراكز الوسيط: {exc}"],
                notes_ar=notes,
            )
        result = reconcile(
            local_positions=list(local_positions or []),
            broker_positions=broker_positions,
            now=now_utc(),
        )
        problems = list(result.discrepancies_ar)
        if problems:
            return StartupReport(
                verdict=StartupVerdict.LOCKED_PENDING_RECONCILIATION,
                trading_locked=True,
                kill_switch_active=False,
                risk_mode=state.risk_mode,
                reconciliation_problems=problems,
                notes_ar=notes,
            )
        notes.append("المطابقة مع الوسيط ناجحة عند الإقلاع.")
    else:
        notes.append("لم تُطلب مطابقة مع الوسيط عند هذا الإقلاع (وضع غير متصل).")

    return StartupReport(
        verdict=StartupVerdict.READY_TRADING_STILL_LOCKED,
        trading_locked=True,
        kill_switch_active=False,
        risk_mode=state.risk_mode,
        notes_ar=notes
        + ["الفحوص نجحت، لكن التداول يبقى مقفلاً: الفتح قرار بشري موثّق لا نتيجة إقلاع."],
    )
