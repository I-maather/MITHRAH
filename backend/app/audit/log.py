"""
Append-only, hash-chained audit log.

ما تضمنه هذه الطبقة فعلياً:
  * كل حدث يحمل hash يشمل hash الحدث السابق => أي تعديل أو حذف لصف
    في المنتصف يكسر السلسلة ويُكتشف بأداة التحقق.
  * التطبيق نفسه لا يحتوي أي مسار UPDATE أو DELETE على هذا الجدول.

ما لا تضمنه (بصراحة — انظر docs/KNOWN_LIMITATIONS.md):
  * ليست immutable بالمعنى المطلق. قاعدة البيانات محلية على جهاز المالكة،
    ومن يملك الجهاز يستطيع إعادة بناء السلسلة كاملة بأداة خارجية.
  * الحماية الحقيقية هنا هي *الكشف*، لا *المنع*.
  * ترسيخ خارجي (نشر hash يومي خارج الجهاز) هو ما يرفع الضمانة، وهو غير مفعّل في V1.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Optional, Protocol

from ..clock import now_utc

GENESIS_HASH = "0" * 64


class AuditAction(str, Enum):
    SYSTEM_START = "SYSTEM_START"
    PIPELINE_RUN = "PIPELINE_RUN"
    MARKET_DATA_REJECTED = "MARKET_DATA_REJECTED"
    ELIGIBILITY_DECISION = "ELIGIBILITY_DECISION"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    RISK_DECISION = "RISK_DECISION"
    NO_TRADE = "NO_TRADE"
    ORDER_INTENT_CREATED = "ORDER_INTENT_CREATED"
    ORDER_PREVIEWED = "ORDER_PREVIEWED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_TIMEOUT = "ORDER_TIMEOUT"
    EXECUTION_RECORDED = "EXECUTION_RECORDED"
    RECONCILIATION = "RECONCILIATION"
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    KILL_SWITCH_RESET = "KILL_SWITCH_RESET"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    HEALTH_CHECK = "HEALTH_CHECK"


class Actor(str, Enum):
    SYSTEM = "system"
    PIPELINE = "pipeline"
    RISK_ENGINE = "risk_engine"
    KILL_SWITCH = "kill_switch"
    BROKER = "broker"
    OWNER = "owner"
    AI_NARRATOR = "ai_narrator"


def _json_default(obj: Any):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return str(obj)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default, ensure_ascii=False)


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    timestamp_utc: datetime
    actor: str
    action: str
    decision: str
    reason_ar: str
    source: str
    before: Optional[dict]
    after: Optional[dict]
    related_id: Optional[str]
    previous_hash: str
    entry_hash: str

    def payload_for_hash(self) -> str:
        return canonical_json(
            {
                "sequence": self.sequence,
                "timestamp_utc": self.timestamp_utc,
                "actor": self.actor,
                "action": self.action,
                "decision": self.decision,
                "reason_ar": self.reason_ar,
                "source": self.source,
                "before": self.before,
                "after": self.after,
                "related_id": self.related_id,
                "previous_hash": self.previous_hash,
            }
        )

    def compute_hash(self) -> str:
        return hashlib.sha256(self.payload_for_hash().encode("utf-8")).hexdigest()


class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def last(self) -> Optional[AuditEvent]: ...
    def all(self) -> Iterable[AuditEvent]: ...


class InMemoryAuditStore:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def last(self) -> Optional[AuditEvent]:
        return self._events[-1] if self._events else None

    def all(self) -> Iterable[AuditEvent]:
        return list(self._events)


class AuditLog:
    """الواجهة الوحيدة المسموح بها للكتابة في السجل."""

    def __init__(self, store: AuditStore) -> None:
        self._store = store

    def record(
        self,
        *,
        actor: Actor | str,
        action: AuditAction | str,
        decision: str,
        reason_ar: str,
        source: str,
        before: dict | None = None,
        after: dict | None = None,
        related_id: str | None = None,
        at: datetime | None = None,
    ) -> AuditEvent:
        last = self._store.last()
        sequence = (last.sequence + 1) if last else 1
        previous_hash = last.entry_hash if last else GENESIS_HASH

        draft = AuditEvent(
            sequence=sequence,
            timestamp_utc=at or now_utc(),
            actor=actor.value if isinstance(actor, Actor) else actor,
            action=action.value if isinstance(action, AuditAction) else action,
            decision=decision,
            reason_ar=reason_ar,
            source=source,
            before=before,
            after=after,
            related_id=related_id,
            previous_hash=previous_hash,
            entry_hash="",
        )
        event = AuditEvent(**{**draft.__dict__, "entry_hash": draft.compute_hash()})
        self._store.append(event)
        return event

    def events(self) -> list[AuditEvent]:
        return list(self._store.all())


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    checked: int
    first_bad_sequence: Optional[int]
    problem_ar: Optional[str]


def verify_chain(events: Iterable[AuditEvent]) -> ChainVerification:
    """يتحقق من الترابط والتسلسل. يُستدعى من CLI ومن صفحة صحة النظام."""
    previous_hash = GENESIS_HASH
    expected_sequence = 1
    count = 0

    for event in events:
        count += 1
        if event.sequence != expected_sequence:
            return ChainVerification(
                False, count, event.sequence,
                f"انقطاع في التسلسل: متوقع {expected_sequence} ووجد {event.sequence} (حذف صف؟)",
            )
        if event.previous_hash != previous_hash:
            return ChainVerification(
                False, count, event.sequence,
                f"سلسلة مكسورة عند الصف {event.sequence}: previous_hash لا يطابق الصف السابق",
            )
        if event.compute_hash() != event.entry_hash:
            return ChainVerification(
                False, count, event.sequence,
                f"محتوى الصف {event.sequence} عُدّل بعد كتابته: البصمة لا تطابق المحتوى",
            )
        previous_hash = event.entry_hash
        expected_sequence += 1

    return ChainVerification(True, count, None, None)
