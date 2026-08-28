"""
SQLAlchemy-backed audit store. Append-only بحكم الكود:
لا توجد هنا أي عملية update أو delete.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AuditEventRow
from .log import AuditEvent


def _to_row(event: AuditEvent) -> AuditEventRow:
    return AuditEventRow(
        sequence=event.sequence,
        timestamp_utc=event.timestamp_utc,
        actor=event.actor,
        action=event.action,
        decision=event.decision,
        reason_ar=event.reason_ar,
        source=event.source,
        before_json=json.dumps(event.before, ensure_ascii=False) if event.before is not None else None,
        after_json=json.dumps(event.after, ensure_ascii=False) if event.after is not None else None,
        related_id=event.related_id,
        previous_hash=event.previous_hash,
        entry_hash=event.entry_hash,
    )


def _restore_utc(value: datetime) -> datetime:
    """
    SQLite لا يحفظ tzinfo. كل ما نكتبه UTC بحكم clock.ensure_utc،
    فإعادة إلصاق UTC عند القراءة تعيد بناء نفس القيمة بالضبط —
    وهذا شرط لازم لإعادة حساب البصمة بنفس النتيجة.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _from_row(row: AuditEventRow) -> AuditEvent:
    return AuditEvent(
        sequence=row.sequence,
        timestamp_utc=_restore_utc(row.timestamp_utc),
        actor=row.actor,
        action=row.action,
        decision=row.decision,
        reason_ar=row.reason_ar,
        source=row.source,
        before=json.loads(row.before_json) if row.before_json else None,
        after=json.loads(row.after_json) if row.after_json else None,
        related_id=row.related_id,
        previous_hash=row.previous_hash,
        entry_hash=row.entry_hash,
    )


class SqlAuditStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: AuditEvent) -> None:
        self._session.add(_to_row(event))
        self._session.commit()

    def last(self) -> Optional[AuditEvent]:
        row = self._session.execute(
            select(AuditEventRow).order_by(AuditEventRow.sequence.desc()).limit(1)
        ).scalar_one_or_none()
        return _from_row(row) if row else None

    def all(self) -> Iterable[AuditEvent]:
        rows = self._session.execute(
            select(AuditEventRow).order_by(AuditEventRow.sequence.asc())
        ).scalars()
        return [_from_row(r) for r in rows]
