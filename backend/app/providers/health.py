"""
PROVIDER HEALTH — لوحة صحة المزوّدين وسجل تدقيقها.

مزوّدٌ يفشل بصمت هو أخطر من مزوّد غائب: الغائب يُسقط الأهلية صراحةً، والفاشل
بصمت يُنتج «صفر أحداث» فيبدو كل شيء هادئاً في اللحظة التي يجب فيها التوقّف.

هذه اللوحة تجعل الفشل **مرئياً ومؤرَّخاً**، وتغذّي شاشة «صحة المزوّدين» في
تطبيق الجوال.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Deque, Optional

from .results import FAILURE_STATES, ProviderResult, ProviderResultState

#: عدد الأحداث المحفوظة لكل مزوّد. سجل بلا حد يستهلك الذاكرة بلا فائدة.
AUDIT_RING_SIZE = 200

#: عدد الإخفاقات المتتالية التي تُعلن المزوّد «ساقطاً».
CONSECUTIVE_FAILURES_FOR_DOWN = 3


@dataclass(frozen=True)
class ProviderAuditEvent:
    at_utc: datetime
    provider: str
    operation: str
    state: ProviderResultState
    detail_ar: str
    error_code: Optional[str] = None
    http_status: Optional[int] = None
    duration_ms: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "at_utc": self.at_utc.isoformat(),
            "provider": self.provider,
            "operation": self.operation,
            "state": self.state.value,
            "detail_ar": self.detail_ar,
            "error_code": self.error_code,
            "http_status": self.http_status,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ProviderHealth:
    provider: str
    total_calls: int = 0
    successful_calls: int = 0
    consecutive_failures: int = 0
    last_state: Optional[ProviderResultState] = None
    last_success_utc: Optional[datetime] = None
    last_failure_utc: Optional[datetime] = None
    last_error_code: Optional[str] = None

    @property
    def is_down(self) -> bool:
        return self.consecutive_failures >= CONSECUTIVE_FAILURES_FOR_DOWN

    @property
    def success_rate(self) -> Optional[float]:
        if self.total_calls == 0:
            return None
        return self.successful_calls / self.total_calls

    def status_ar(self) -> str:
        if self.total_calls == 0:
            return "لم يُستدعَ بعد."
        if self.is_down:
            return f"ساقط — {self.consecutive_failures} إخفاقات متتالية."
        if self.consecutive_failures:
            return f"متذبذب — آخر استدعاء فشل ({self.consecutive_failures})."
        return "سليم."

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "consecutive_failures": self.consecutive_failures,
            "is_down": self.is_down,
            "success_rate": self.success_rate,
            "last_state": self.last_state.value if self.last_state else None,
            "last_success_utc": (
                self.last_success_utc.isoformat() if self.last_success_utc else None
            ),
            "last_failure_utc": (
                self.last_failure_utc.isoformat() if self.last_failure_utc else None
            ),
            "last_error_code": self.last_error_code,
            "status_ar": self.status_ar(),
        }


class ProviderHealthRegistry:
    """يجمع صحة كل المزوّدين وسجل أحداثهم في مكان واحد."""

    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    ) -> None:
        self.clock = clock
        self._health: dict[str, ProviderHealth] = {}
        self._events: Deque[ProviderAuditEvent] = deque(maxlen=AUDIT_RING_SIZE)

    def record(
        self, result: ProviderResult, *, operation: str, duration_ms: Optional[float] = None
    ) -> ProviderAuditEvent:
        health = self._health.setdefault(
            result.provider, ProviderHealth(provider=result.provider)
        )
        now = self.clock()
        health.total_calls += 1
        health.last_state = result.state

        if result.state in FAILURE_STATES:
            health.consecutive_failures += 1
            health.last_failure_utc = now
            health.last_error_code = result.error_code
        else:
            health.successful_calls += 1
            health.consecutive_failures = 0
            health.last_success_utc = now

        event = ProviderAuditEvent(
            at_utc=now,
            provider=result.provider,
            operation=operation,
            state=result.state,
            detail_ar=result.detail_ar,
            error_code=result.error_code,
            http_status=result.http_status,
            duration_ms=duration_ms,
        )
        self._events.append(event)
        return event

    def health(self, provider: str) -> Optional[ProviderHealth]:
        return self._health.get(provider)

    def all_health(self) -> tuple[ProviderHealth, ...]:
        return tuple(self._health.values())

    def recent_events(self, limit: int = 50) -> tuple[ProviderAuditEvent, ...]:
        return tuple(list(self._events)[-limit:])

    def dashboard(self) -> dict:
        providers = [h.as_dict() for h in self._health.values()]
        down = [p["provider"] for p in providers if p["is_down"]]
        return {
            "providers": providers,
            "down": down,
            "any_down": bool(down),
            "recent_events": [e.as_dict() for e in self.recent_events()],
            "note_ar": (
                "مزوّد ساقط ⇒ لا أهلية للتداول الحقيقي. الغياب يُعلَن ولا يُفسَّر "
                "بأنه «لا توجد بيانات»."
            ),
        }


__all__ = [
    "AUDIT_RING_SIZE",
    "CONSECUTIVE_FAILURES_FOR_DOWN",
    "ProviderAuditEvent",
    "ProviderHealth",
    "ProviderHealthRegistry",
]
