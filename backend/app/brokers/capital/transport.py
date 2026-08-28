"""
الناقل — النقطة الوحيدة التي يمكن أن تغادر منها حزمة إلى Capital.com.

كل طلب يمر بأربعة فحوص قبل المغادرة:
  1. العنوان ينتمي إلى بيئة Demo (Live مقفل مصدرياً).
  2. العملية ليست مُعدِّلة، إلا إذا كان قفل التنفيذ مفتوحاً (وهو مغلق دائماً هنا).
  3. حد الطلبات.
  4. تنقية الترويسات والجسم قبل أي تسجيل.

الاختبارات تستعمل `FixtureTransport` الذي لا يفتح أي اتصال شبكي إطلاقاً.
"""
from __future__ import annotations

import json as jsonlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ...secretstore.redaction import redact, redact_headers
from .endpoints import is_mutating
from .errors import CapitalMalformedResponse, CapitalTimeout, CapitalTransportError
from .ratelimit import RateLimiter
from .safety import ExecutionLock, assert_url_allowed

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class ApiResponse:
    status: int
    headers: dict[str, str]
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        if isinstance(self.body, (dict, list)):
            return self.body
        raise CapitalMalformedResponse("استجابة الوسيط ليست JSON صالحاً.")

    def safe_repr(self) -> str:
        return f"ApiResponse(status={self.status}, headers={redact_headers(self.headers)})"


class Transport(ABC):
    """عقد الناقل. لا يعرف شيئاً عن الجلسة ولا عن الأسرار."""

    name: str = "abstract"

    @abstractmethod
    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> ApiResponse: ...


@dataclass
class GuardedTransport(Transport):
    """
    غلاف يفرض الأقفال حول أي ناقل. كل ناقل يُستعمل في النظام يمرّ من هنا.
    """

    inner: Transport
    execution_lock: ExecutionLock
    rate_limiter: RateLimiter = field(default_factory=RateLimiter)
    name: str = "guarded"

    def __post_init__(self) -> None:
        self.name = f"guarded({self.inner.name})"
        self.sent_operations: list[tuple[str, str]] = []

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> ApiResponse:
        path = _path_of(url)

        # 1) العنوان
        assert_url_allowed(url)

        # 2) العملية
        mutating = is_mutating(method, path)
        if mutating:
            self.execution_lock.assert_can_execute(f"{method.upper()} {path}")

        # 3) حد الطلبات
        kind = "session" if path.endswith("/session") and method.upper() == "POST" else (
            "orders" if mutating else "general"
        )
        self.rate_limiter.acquire(kind)

        self.sent_operations.append((method.upper(), path))
        logger.debug(
            "capital request %s %s headers=%s params=%s",
            method.upper(),
            path,
            redact_headers(headers),
            redact(params or {}),
        )
        return self.inner.send(
            method, url, headers=headers, params=params, json=json, timeout=timeout
        )


def _path_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path or url


class HttpxTransport(Transport):
    """
    الناقل الحقيقي. يُستعمل فقط بعد تأكيد المالكة على ضبط الاعتمادات،
    وفقط ضد بيئة Demo. لا يُستدعى إطلاقاً من الاختبارات.
    """

    name = "httpx"

    def __init__(self, *, verify: bool = True) -> None:
        self._verify = verify
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx  # استيراد كسول حتى لا تُحمَّل الشبكة في الاختبارات

            self._client = httpx.Client(verify=self._verify, follow_redirects=False)
        return self._client

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> ApiResponse:
        import httpx

        try:
            response = self._get_client().request(
                method.upper(), url, headers=headers, params=params, json=json, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise CapitalTimeout(
                f"انتهت مهلة الطلب {method.upper()} {_path_of(url)} — الحالة غير معلومة."
            ) from None
        except httpx.HTTPError as exc:
            raise CapitalTransportError(
                f"خطأ شبكة في {method.upper()} {_path_of(url)}: {type(exc).__name__}"
            ) from None

        try:
            body: Any = response.json() if response.content else {}
        except ValueError:
            body = {"_raw_text_omitted": True}

        return ApiResponse(
            status=response.status_code,
            headers={k: v for k, v in response.headers.items()},
            body=body,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


@dataclass
class FixtureTransport(Transport):
    """
    ناقل الاختبارات. **لا يفتح أي اتصال شبكي.**

    `routes` تربط (METHOD, path) بدالة تُرجع ApiResponse، فيمكن محاكاة
    النجاح والفشل والمهلة وانتهاء الجلسة بشكل صريح.
    """

    routes: dict[tuple[str, str], Callable[[dict], ApiResponse]] = field(default_factory=dict)
    name: str = "fixture"
    calls: list[dict] = field(default_factory=list)

    def register(
        self, method: str, path: str, handler: Callable[[dict], ApiResponse]
    ) -> "FixtureTransport":
        self.routes[(method.upper(), path)] = handler
        return self

    def register_json(
        self, method: str, path: str, body: Any, *, status: int = 200, headers: dict | None = None
    ) -> "FixtureTransport":
        response = ApiResponse(status=status, headers=headers or {}, body=body)
        return self.register(method, path, lambda _ctx, r=response: r)

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> ApiResponse:
        path = _path_of(url)
        context = {
            "method": method.upper(),
            "path": path,
            "url": url,
            "headers": dict(headers),
            "params": dict(params or {}),
            "json": dict(json or {}),
        }
        self.calls.append(
            {
                "method": method.upper(),
                "path": path,
                "headers": redact_headers(headers),
                "params": redact(params or {}),
                "json": redact(json or {}),
            }
        )
        handler = self.routes.get((method.upper(), path))
        if handler is None:
            # مسار غير مسجَّل ⇒ 404 صريح بدل استجابة مخترعة
            return ApiResponse(status=404, headers={}, body={"errorCode": "route.not.registered"})
        return handler(context)


def dumps_safe(payload: Any) -> str:
    """تسلسل آمن للتسجيل والتقارير — يمر عبر الحجب أولاً."""
    return jsonlib.dumps(redact(payload), ensure_ascii=False, sort_keys=True, default=str)
