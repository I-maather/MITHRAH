"""
Secret redaction — طبقة واحدة تمنع تسرّب الأسرار إلى أي مخرج.

المبدأ: كل قيمة سرّية تُسجَّل في سجل مركزي فور قراءتها، وكل نص يخرج من النظام
(سجلات، استثناءات، تقارير، Audit Log، واجهة) يمرّ عبر `redact()`.

لا يُخزَّن أي سرّ على القرص من هنا، ولا يُطبع، ولا يدخل رسالة استثناء.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

MASK = "***REDACTED***"

#: أسماء الحقول/الترويسات التي تُحجب دائماً حتى لو لم تُسجَّل قيمتها.
SENSITIVE_KEYS = frozenset(
    {
        "cst",
        "x-security-token",
        "x_security_token",
        "securitytoken",
        "x-cap-api-key",
        "x_cap_api_key",
        "apikey",
        "api_key",
        "capital_api_key",
        "password",
        "capital_api_password",
        "encryptedpassword",
        "encryptionkey",
        "identifier",
        "capital_identifier",
        "email",
        "login",
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "otp",
        "twofa",
        "2fa",
    }
)

#: أنماط تُحجب حتى لو لم نكن نعرف القيمة مسبقاً.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ترويسات بصيغة "CST: value"
    (re.compile(r"(?i)\b(CST|X-SECURITY-TOKEN|X-CAP-API-KEY)\s*[:=]\s*\S+"), r"\1: " + MASK),
    # بريد إلكتروني (المعرّف في Capital.com بريد غالباً)
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), MASK),
)


class SecretRegistry:
    """
    سجل القيم السرّية النشطة في الذاكرة فقط.

    لا يُكتب إلى قرص ولا إلى قاعدة بيانات. يُمسح عند انتهاء العملية.
    """

    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str | None) -> None:
        if not value:
            return
        text = str(value)
        # قيم قصيرة جداً تُنتج حجباً عشوائياً لنصوص عادية — نتجاهلها.
        if len(text) < 6:
            return
        self._values.add(text)

    def register_many(self, values: Iterable[str | None]) -> None:
        for v in values:
            self.register(v)

    def forget(self, value: str | None) -> None:
        if value:
            self._values.discard(str(value))

    def clear(self) -> None:
        self._values.clear()

    def known_values(self) -> frozenset[str]:
        """للاختبارات فقط — يعيد عدد العناصر لا القيم."""
        return frozenset(self._values)

    def scrub(self, text: str) -> str:
        out = text
        # الأطول أولاً حتى لا يفسد استبدال جزئي قيمة أطول تحتويه.
        for value in sorted(self._values, key=len, reverse=True):
            if value in out:
                out = out.replace(value, MASK)
        return out


#: السجل العام. تُسجَّل فيه الأسرار فور قراءتها من SecretProvider.
REGISTRY = SecretRegistry()


def redact(value: Any) -> Any:
    """
    يحجب الأسرار من أي بنية: نص، قاموس، قائمة، استثناء.
    يعيد نفس شكل المدخل مع استبدال القيم الحسّاسة.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, bytes):
        return _redact_text(value.decode("utf-8", errors="replace")).encode()
    if isinstance(value, dict):
        return {k: (MASK if _is_sensitive_key(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        rebuilt = [redact(v) for v in value]
        return type(value)(rebuilt) if isinstance(value, tuple) else rebuilt
    if isinstance(value, BaseException):
        return type(value)(_redact_text(str(value)))
    return value


def _is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and key.strip().lower().replace("-", "_").replace(" ", "_") in {
        k.replace("-", "_") for k in SENSITIVE_KEYS
    }


def _redact_text(text: str) -> str:
    out = REGISTRY.scrub(text)
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """ترويسات HTTP — تُحجب بالاسم دائماً، بلا استثناء."""
    return {k: (MASK if _is_sensitive_key(k) else redact(v)) for k, v in headers.items()}


class RedactingFilter(logging.Filter):
    """فلتر تسجيل يحجب الأسرار من الرسالة والوسائط معاً."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = redact(record.args)
                else:
                    record.args = tuple(redact(a) for a in record.args)
        except Exception:  # noqa: BLE001 — التسجيل يجب ألا يُسقط التطبيق أبداً
            record.msg = MASK
            record.args = ()
        return True


def install_redacting_filter(logger: logging.Logger | None = None) -> None:
    """يُركَّب على الجذر عند الإقلاع، فيغطي كل مسجّلات النظام."""
    target = logger or logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in target.filters):
        target.addFilter(RedactingFilter())
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


class RedactedError(RuntimeError):
    """
    استثناء لا يمكن أن يحمل سرّاً: يُحجب نصه عند الإنشاء.
    كل أخطاء طبقة الوسيط ترث منه.
    """

    def __init__(self, message: str, *, context: dict | None = None) -> None:
        super().__init__(_redact_text(message))
        self.context = redact(context or {})

    def __str__(self) -> str:
        return _redact_text(super().__str__())
