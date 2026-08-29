"""
PROVIDER HTTP — طلبات GET آمنة، بمعدّل محدود، وبأسرار مُنقّاة من كل أثر.

## المشكلة الخاصة بهذه الطبقة

مفاتيح هذه المزوّدات تُمرَّر في **سلسلة الاستعلام** لا في ترويسة:

    https://api.stlouisfed.org/fred/series?series_id=UNRATE&api_key=SECRET

أي أن المفتاح يدخل: نص الاستثناء · سجل الوصول · رسالة المهلة ·
`repr` الكائن · تقرير الخطأ · لوحة الصحة. ترويسةٌ سرّية تُنسى مرة؛ سلسلة
استعلام سرّية تُسرَّب **تلقائياً** في كل مسار خطأ إن لم تُنقَّ عمداً.

لذلك: **لا يظهر عنوان خام واحد** خارج هذه الوحدة. كل ما يخرج منها يمرّ عبر
`redact_url()`، والاستثناءات تُلتقط وتُعاد بعنوان منقّى.

## قراءة فقط

`get()` هي الميثود الوحيدة. لا `post` ولا `put` ولا `delete` — مزوّد بيانات
لا يحتاج أن يكتب شيئاً، ومنحه القدرة على ذلك يفتح باباً لا مبرّر له.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .results import ProviderResultState

#: أسماء معاملات تُعامَل أسراراً أينما ظهرت.
SECRET_QUERY_KEYS: frozenset[str] = frozenset({
    "api_key", "apikey", "apiKey", "key", "token", "access_token",
    "auth", "secret", "password", "x-api-key",
})

REDACTED = "***REDACTED***"

#: مهلة افتراضية. الطلب الذي لا ينتهي يجمّد دورة التحليل كلها.
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 8.0


class ProviderHttpError(RuntimeError):
    """
    خطأ نقل مُنقّى. **لا يحمل عنواناً خاماً ولا مفتاحاً** — بالبناء لا بالانضباط.
    """

    def __init__(self, message: str, *, state: ProviderResultState, status: Optional[int] = None):
        super().__init__(message)
        self.state = state
        self.status = status


def redact_url(url: str) -> str:
    """
    يستبدل قيمة كل معامل سرّي بـ`***REDACTED***` مع إبقاء بنية العنوان.

    البنية تبقى لأنها مفيدة في التشخيص (أي نقطة نهاية؟ أي نطاق تواريخ؟)،
    والقيمة السرّية تختفي.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return REDACTED
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    cleaned = [
        (k, REDACTED if k.lower() in {s.lower() for s in SECRET_QUERY_KEYS} else v)
        for k, v in pairs
    ]
    # `safe="*"` كي لا يُرمَّز `***REDACTED***` إلى `%2A%2A%2A` فيصعب تمييزه.
    return urlunsplit((
        parts.scheme, parts.netloc, parts.path,
        urlencode(cleaned, safe="*"), parts.fragment,
    ))


def redact_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    """
    ينقّي نصاً حراً (رسالة استثناء مثلاً) من قيم سرّية معروفة ومن أي عنوان.

    القيم القصيرة جداً تُتجاهَل عمداً: استبدال سلسلة من محرفين يفسد النص كله
    بلا فائدة أمنية.
    """
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 8:
            cleaned = cleaned.replace(secret, REDACTED)
    out: list[str] = []
    for token in cleaned.split():
        out.append(redact_url(token) if "://" in token else token)
    return " ".join(out)


@dataclass
class RateLimiter:
    """
    محدّد معدل بسيط لكل مزوّد: عدد أقصى من الطلبات في نافذة منزلقة.

    حساب **محلي** لا يعتمد على ردّ الوسيط: الاعتماد على 429 وحدها يعني أننا
    نكتشف التجاوز **بعد** وقوعه، وبعض المزوّدين يعاقب التجاوز المتكرر بحظر
    أطول من الحد نفسه.
    """

    name: str
    max_calls: int
    per_seconds: float
    _timestamps: list[float] = field(default_factory=list)
    clock: Callable[[], float] = time.monotonic

    def _prune(self, now: float) -> None:
        cutoff = now - self.per_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def allowance(self) -> int:
        now = self.clock()
        self._prune(now)
        return max(0, self.max_calls - len(self._timestamps))

    def seconds_until_free(self) -> float:
        now = self.clock()
        self._prune(now)
        if len(self._timestamps) < self.max_calls:
            return 0.0
        return max(0.0, self._timestamps[0] + self.per_seconds - now)

    def try_acquire(self) -> bool:
        now = self.clock()
        self._prune(now)
        if len(self._timestamps) >= self.max_calls:
            return False
        self._timestamps.append(now)
        return True


def backoff_delay(attempt: int, *, jitter: Callable[[], float] = random.random) -> float:
    """
    تراجع أسّي مع تشويش. التشويش ليس زينة: بلا،ه تتزامن كل إعادات المحاولة
    بعد انقطاع فتصنع موجة ثانية تُسقط الخدمة من جديد.
    """
    raw = BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1))
    return min(BACKOFF_CAP_SECONDS, raw) * (0.5 + 0.5 * jitter())


@dataclass
class HttpResponse:
    status: int
    body: Any
    headers: Mapping[str, str] = field(default_factory=dict)


class ProviderTransport:
    """
    ناقل GET فقط. يُحقَن في الاختبارات بمُقلِّد، فلا اختبار يلمس الشبكة.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        sender: Optional[Callable[[str, Mapping[str, str], float], HttpResponse]] = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._sender = sender
        #: العمليات المُرسَلة، **بعناوين منقّاة** — للتدقيق والاختبار.
        self.sent: list[str] = []

    def _default_sender(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        import httpx

        response = httpx.get(url, headers=dict(headers), timeout=timeout)
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            body = response.text
        return HttpResponse(response.status_code, body, dict(response.headers))

    def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        secrets: tuple[str, ...] = (),
    ) -> HttpResponse:
        """
        طلب واحد. الاستثناءات تُلتقط وتُعاد **منقّاة** — الاستثناء الخام من
        `httpx` يحمل العنوان كاملاً بمفتاحه.
        """
        safe = redact_url(url)
        self.sent.append(safe)
        sender = self._sender or self._default_sender
        try:
            return sender(url, headers or {}, self.timeout_seconds)
        except ProviderHttpError:
            raise
        except Exception as exc:                       # noqa: BLE001
            raise ProviderHttpError(
                f"{type(exc).__name__}: "
                f"{redact_text(str(exc), secrets)} ({safe})",
                state=ProviderResultState.UNAVAILABLE,
            ) from None


def get_with_retry(
    transport: ProviderTransport,
    url: str,
    *,
    limiter: Optional[RateLimiter] = None,
    headers: Optional[Mapping[str, str]] = None,
    secrets: tuple[str, ...] = (),
    max_attempts: int = MAX_ATTEMPTS,
    sleeper: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> HttpResponse:
    """
    GET مع تراجع أسّي. **لا يُعاد المحاولة على 401 ولا 403 ولا 402**: مفتاح
    مرفوض أو خطة غير كافية لن تتغيّر بالإلحاح، وإعادة المحاولة عليها تستهلك
    الحد وتزيد احتمال الحظر.
    """
    if limiter is not None and not limiter.try_acquire():
        raise ProviderHttpError(
            f"حد المعدّل المحلي لـ{limiter.name}: "
            f"يلزم انتظار {limiter.seconds_until_free():.1f} ثانية.",
            state=ProviderResultState.RATE_LIMITED,
        )

    last: Optional[ProviderHttpError] = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = transport.get(url, headers=headers, secrets=secrets)
        except ProviderHttpError as exc:
            last = exc
            if attempt >= max_attempts:
                raise
            sleeper(backoff_delay(attempt, jitter=jitter))
            continue

        if response.status in (401, 403):
            raise ProviderHttpError(
                "المصادقة مرفوضة لدى المزوّد.",
                state=ProviderResultState.AUTH_FAILED, status=response.status,
            )
        if response.status == 402:
            raise ProviderHttpError(
                "نقطة النهاية غير مشمولة بالخطة الحالية.",
                state=ProviderResultState.UNAVAILABLE_PLAN, status=response.status,
            )
        if response.status == 429:
            if attempt >= max_attempts:
                raise ProviderHttpError(
                    "تجاوز حد المعدّل لدى المزوّد.",
                    state=ProviderResultState.RATE_LIMITED, status=429,
                )
            sleeper(backoff_delay(attempt, jitter=jitter))
            continue
        if 500 <= response.status < 600:
            if attempt >= max_attempts:
                raise ProviderHttpError(
                    f"خطأ خادم لدى المزوّد ({response.status}).",
                    state=ProviderResultState.UNAVAILABLE, status=response.status,
                )
            sleeper(backoff_delay(attempt, jitter=jitter))
            continue
        return response

    raise last or ProviderHttpError(
        "تعذّر الوصول إلى المزوّد.", state=ProviderResultState.UNAVAILABLE
    )


__all__ = [
    "SECRET_QUERY_KEYS",
    "REDACTED",
    "ProviderHttpError",
    "redact_url",
    "redact_text",
    "RateLimiter",
    "backoff_delay",
    "HttpResponse",
    "ProviderTransport",
    "get_with_retry",
]
