"""
الإشعارات — محلية أو وهمية فقط في هذا الإصدار.

لا ترسل بريداً ولا رسائل دعم ولا أي اتصال خارجي.
كل رسالة تمرّ عبر طبقة الحجب قبل الكتابة.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from ..clock import format_riyadh, now_utc
from ..secretstore.redaction import redact

logger = logging.getLogger(__name__)


class NotificationKind(str, Enum):
    CONNECTION_LOST = "CONNECTION_LOST"
    STALE_PRICES = "STALE_PRICES"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    RECONCILIATION_FAILURE = "RECONCILIATION_FAILURE"
    UNKNOWN_EXECUTION_STATE = "UNKNOWN_EXECUTION_STATE"
    RISK_REJECTION = "RISK_REJECTION"
    DAILY_LIMIT_REACHED = "DAILY_LIMIT_REACHED"
    WEEKLY_LIMIT_REACHED = "WEEKLY_LIMIT_REACHED"
    TWO_LOSS_LOCK = "TWO_LOSS_LOCK"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    BROKER_STOP_MISSING = "BROKER_STOP_MISSING"
    POSITION_MISMATCH = "POSITION_MISMATCH"


KIND_LABELS_AR: dict[NotificationKind, str] = {
    NotificationKind.CONNECTION_LOST: "انقطع الاتصال بالوسيط",
    NotificationKind.STALE_PRICES: "أسعار متأخرة",
    NotificationKind.SESSION_EXPIRED: "انتهت جلسة الوسيط",
    NotificationKind.RECONCILIATION_FAILURE: "فشل المطابقة مع الوسيط",
    NotificationKind.UNKNOWN_EXECUTION_STATE: "حالة تنفيذ غير معلومة",
    NotificationKind.RISK_REJECTION: "رفض من محرك المخاطر",
    NotificationKind.DAILY_LIMIT_REACHED: "بلوغ الحد اليومي",
    NotificationKind.WEEKLY_LIMIT_REACHED: "بلوغ الحد الأسبوعي",
    NotificationKind.TWO_LOSS_LOCK: "خسارتان متتاليتان — قفل مراجعة",
    NotificationKind.KILL_SWITCH_ACTIVATED: "تفعيل Kill Switch",
    NotificationKind.BROKER_STOP_MISSING: "وقف الخسارة غير موجود لدى الوسيط",
    NotificationKind.POSITION_MISMATCH: "اختلاف المركز بيننا وبين الوسيط",
}


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


SEVERITY_BY_KIND: dict[NotificationKind, Severity] = {
    NotificationKind.CONNECTION_LOST: Severity.WARNING,
    NotificationKind.STALE_PRICES: Severity.WARNING,
    NotificationKind.SESSION_EXPIRED: Severity.INFO,
    NotificationKind.RECONCILIATION_FAILURE: Severity.CRITICAL,
    NotificationKind.UNKNOWN_EXECUTION_STATE: Severity.CRITICAL,
    NotificationKind.RISK_REJECTION: Severity.INFO,
    NotificationKind.DAILY_LIMIT_REACHED: Severity.WARNING,
    NotificationKind.WEEKLY_LIMIT_REACHED: Severity.WARNING,
    NotificationKind.TWO_LOSS_LOCK: Severity.CRITICAL,
    NotificationKind.KILL_SWITCH_ACTIVATED: Severity.CRITICAL,
    NotificationKind.BROKER_STOP_MISSING: Severity.CRITICAL,
    NotificationKind.POSITION_MISMATCH: Severity.CRITICAL,
}


@dataclass(frozen=True)
class Notification:
    kind: NotificationKind
    severity: Severity
    title_ar: str
    detail_ar: str
    context: dict
    created_at_utc: datetime

    def as_dict(self) -> dict:
        return redact(
            {
                "kind": self.kind.value,
                "severity": self.severity.value,
                "title_ar": self.title_ar,
                "detail_ar": self.detail_ar,
                "context": self.context,
                "created_at_utc": self.created_at_utc.isoformat(),
                "created_at_riyadh": format_riyadh(self.created_at_utc),
            }
        )


class Notifier(ABC):
    name = "abstract"

    @abstractmethod
    def send(self, notification: Notification) -> bool: ...

    def notify(
        self,
        kind: NotificationKind,
        *,
        detail_ar: str,
        context: Optional[dict] = None,
        at: Optional[datetime] = None,
    ) -> Notification:
        notification = Notification(
            kind=kind,
            severity=SEVERITY_BY_KIND[kind],
            title_ar=KIND_LABELS_AR[kind],
            detail_ar=detail_ar,
            context=redact(context or {}),
            created_at_utc=at or now_utc(),
        )
        self.send(notification)
        return notification


@dataclass
class InMemoryNotifier(Notifier):
    """للاختبارات — لا يخرج شيء من العملية."""

    name: str = "in-memory"
    sent: list[Notification] = field(default_factory=list)

    def send(self, notification: Notification) -> bool:
        self.sent.append(notification)
        return True

    def kinds(self) -> list[NotificationKind]:
        return [n.kind for n in self.sent]


@dataclass
class LocalFileNotifier(Notifier):
    """
    يكتب سطراً JSON لكل إشعار في ملف محلي. لا شبكة، لا بريد.
    """

    path: Path
    name: str = "local-file"

    def send(self, notification: Notification) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(notification.as_dict(), ensure_ascii=False) + "\n")
            return True
        except OSError as exc:
            logger.warning("تعذّر كتابة الإشعار محلياً: %s", type(exc).__name__)
            return False


@dataclass
class NullNotifier(Notifier):
    """يُستعمل في الاختبارات التي يجب ألا ترسل شيئاً على الإطلاق."""

    name: str = "null"

    def send(self, notification: Notification) -> bool:
        return True
