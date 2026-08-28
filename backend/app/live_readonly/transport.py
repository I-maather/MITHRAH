"""
LIVE READ-ONLY TRANSPORT — الناقل المخصّص، يفرض القائمة البيضاء بنفسه.

لا يعتمد هذا الناقل على `GuardedTransport` العام ولا على قفل المحوّل: يستدعي
`assert_allowed()` بنفسه على **كل** طلب قبل أي إرسال. لو استُعمل من كود آخر
لاحقاً بلا انتباه، تبقى الحماية سارية.

ترويسات المصادقة **تُحجب دائماً** في أي تسجيل أو تمثيل نصي.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..secretstore.redaction import redact, redact_headers
from .allowlist import (
    ALLOWED_POST_EXACT,
    AllowlistViolation,
    NormalizedTarget,
    assert_allowed,
)

DEFAULT_TIMEOUT_SECONDS = 20.0

#: أسماء ترويسات لا تظهر في أي سجل أو تمثيل — بأي حال.
SENSITIVE_HEADERS: frozenset[str] = frozenset({
    "x-cap-api-key", "cst", "x-security-token", "authorization", "cookie",
})


@dataclass(frozen=True)
class LiveResponse:
    status: int
    headers: dict[str, str]
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def safe_repr(self) -> str:
        return f"<LiveResponse status={self.status}>"

    def __repr__(self) -> str:  # noqa: D105
        return self.safe_repr()


class LiveTransportError(RuntimeError):
    """عطل نقل. لا يحمل نصه أي سرّ — يُنقّى قبل الرفع."""

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


class LiveTimeout(LiveTransportError):
    """مهلة. في وضع القراءة فقط لا خطر منها: لم يُرسل أي أمر."""


@dataclass
class LiveReadOnlyTransport:
    """
    ناقل HTTPS مقيَّد. كل طلب يمر عبر `assert_allowed()` أولاً.

    `sent` تسجّل **العمليات المُطبَّعة فقط** — لا عناوين كاملة ولا ترويسات
    ولا أجسام — كي يستطيع التقرير إثبات ما أُرسل بلا تسريب.
    """

    timeout: float = DEFAULT_TIMEOUT_SECONDS
    sent: list[tuple[str, str]] = field(default_factory=list)
    #: حد صارم على عدد طلبات المصادقة في عمر هذا الناقل.
    max_session_posts: int = 1
    _session_posts: int = 0

    @property
    def name(self) -> str:
        return "live-read-only"

    @property
    def session_posts(self) -> int:
        return self._session_posts

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> LiveResponse:
        # 1) الحارس أولاً — قبل بناء أي اتصال.
        target: NormalizedTarget = assert_allowed(method, url)

        # 2) ميزانية المصادقة: محاولة واحدة في عمر الناقل.
        if target.method == "POST" and target.path in ALLOWED_POST_EXACT:
            if self._session_posts >= self.max_session_posts:
                raise AllowlistViolation(
                    "استُهلكت محاولة المصادقة الوحيدة. لا إعادة محاولة."
                )
            self._session_posts += 1
        elif json is not None:
            # جسم مع طلب غير مصادقة = محاولة تمرير حمولة. يُرفض.
            raise AllowlistViolation("جسم طلب غير مسموح مع عملية قراءة.")

        self.sent.append(target.operation)

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise LiveTransportError("حزمة httpx غير مثبّتة.") from exc

        try:
            with httpx.Client(timeout=timeout or self.timeout, follow_redirects=False) as client:
                response = client.request(
                    target.method,
                    url,
                    headers=headers or {},
                    params=params,
                    json=json,
                )
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if "Timeout" in name:
                raise LiveTimeout(f"مهلة اتصال ({name}).") from None
            # لا تُمرَّر رسالة الاستثناء الأصلية: قد تحمل العنوان بترويساته.
            raise LiveTransportError(f"تعذّر إتمام الطلب ({name}).") from None

        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = None

        return LiveResponse(
            status=response.status_code,
            headers={k: v for k, v in response.headers.items()},
            body=body,
        )

    def safe_log_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """تمثيل آمن للترويسات — يُستعمل في أي تسجيل."""
        masked = {
            k: ("***REDACTED***" if k.lower() in SENSITIVE_HEADERS else v)
            for k, v in (headers or {}).items()
        }
        return redact_headers(masked)


__all__ = [
    "LiveReadOnlyTransport",
    "LiveResponse",
    "LiveTransportError",
    "LiveTimeout",
    "SENSITIVE_HEADERS",
    "DEFAULT_TIMEOUT_SECONDS",
]
