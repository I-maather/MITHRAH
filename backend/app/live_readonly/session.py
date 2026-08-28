"""
LIVE SESSION — جلسة واحدة، مصادقة مشفّرة، بلا إعادة محاولة.

القواعد، حرفياً:

  * محاولة مصادقة **واحدة** على الأكثر في عمر الكائن.
  * **المصادقة المشفّرة الرسمية وحدها**. تعذّر التشفير ⇒ توقّف.
  * **لا تراجع** إلى كلمة مرور غير مشفّرة.
  * **لا إعادة محاولة** بعد 401 ولا بعد أي فشل آخر.
  * **لا تراجع إلى Demo** — هذا الملف لا يعرف عنوان Demo أصلاً.
  * الرموز في الذاكرة فقط، **ولا تُحفظ ولا تُطبع**، وتُنسى صراحةً عند الانتهاء.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Optional

from ..secretstore.provider import (
    CAPITAL_API_KEY,
    CAPITAL_API_PASSWORD,
    CAPITAL_IDENTIFIER,
    SecretProvider,
)
from ..secretstore.redaction import REGISTRY
from .allowlist import LIVE_BASE_URL
from .transport import LiveReadOnlyTransport, LiveResponse, LiveTransportError

PATH_ENCRYPTION_KEY = "/api/v1/session/encryptionKey"
PATH_SESSION = "/api/v1/session"


class LiveAuthError(RuntimeError):
    """فشل مصادقة. لا يحمل النص أي سرّ ولا رمز جلسة."""


class LiveAuthAlreadyAttempted(RuntimeError):
    """محاولة ثانية — مرفوضة بالتصميم."""


@dataclass
class LiveSession:
    """
    جلسة حقيقية واحدة. الرموز **لا تُخزَّن في أي حقل دائم**: تُحفظ في حقلين
    خاصّين طوال الاكتشاف ثم تُمسح بـ`discard()`.
    """

    transport: LiveReadOnlyTransport
    secrets: SecretProvider

    _cst: Optional[str] = field(default=None, repr=False)
    _security_token: Optional[str] = field(default=None, repr=False)
    _attempted: bool = field(default=False, repr=False)
    _authenticated: bool = field(default=False, repr=False)

    def __repr__(self) -> str:  # noqa: D105
        return f"<LiveSession authenticated={self._authenticated} tokens=***REDACTED***>"

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    @property
    def attempted(self) -> bool:
        return self._attempted

    # -- المصادقة ---------------------------------------------------------

    def authenticate(self) -> None:
        """محاولة واحدة. أي فشل ⇒ استثناء، بلا إعادة وبلا تراجع."""
        if self._attempted:
            raise LiveAuthAlreadyAttempted(
                "محاولة المصادقة الوحيدة استُهلكت. لا إعادة محاولة على الحساب الحقيقي."
            )
        self._attempted = True

        api_key = self.secrets.get(CAPITAL_API_KEY)
        identifier = self.secrets.get(CAPITAL_IDENTIFIER)
        password = self.secrets.get(CAPITAL_API_PASSWORD)
        REGISTRY.register_many([api_key, identifier, password])

        # 1) مفتاح التشفير — إلزامي. لا مسار بديل.
        try:
            key_response = self.transport.send(
                "GET",
                f"{LIVE_BASE_URL}{PATH_ENCRYPTION_KEY}",
                headers={"X-CAP-API-KEY": api_key},
            )
        except LiveTransportError as exc:
            raise LiveAuthError(f"تعذّر جلب مفتاح التشفير: {exc}") from None

        if not key_response.ok or not isinstance(key_response.body, dict):
            raise LiveAuthError(
                f"جلب مفتاح التشفير فشل (HTTP {key_response.status}). توقّف."
            )
        encryption_key = key_response.body.get("encryptionKey")
        timestamp = key_response.body.get("timeStamp")
        if not isinstance(encryption_key, str) or not encryption_key:
            raise LiveAuthError("استجابة مفتاح التشفير بلا مفتاح صالح. توقّف.")

        # 2) التشفير — إلزامي. لا تراجع إلى نص صريح.
        try:
            encrypted = _encrypt_password(
                password, encryption_key, int(timestamp or time.time() * 1000)
            )
        except Exception as exc:  # noqa: BLE001
            raise LiveAuthError(
                f"تعذّر التشفير محلياً ({type(exc).__name__}). "
                "لا تراجع إلى كلمة مرور غير مشفّرة — توقّف."
            ) from None

        # 3) محاولة واحدة. الناقل نفسه يفرض الحد أيضاً.
        try:
            response = self.transport.send(
                "POST",
                f"{LIVE_BASE_URL}{PATH_SESSION}",
                headers={"X-CAP-API-KEY": api_key, "Content-Type": "application/json"},
                json={
                    "identifier": identifier,
                    "password": encrypted,
                    "encryptedPassword": True,
                },
            )
        except LiveTransportError as exc:
            raise LiveAuthError(f"تعذّر إتمام المصادقة: {exc}") from None

        if response.status == 401:
            raise LiveAuthError(
                "رُفضت المصادقة (401). **لا إعادة محاولة** ولا تراجع إلى Demo. "
                "راجعي حالة المفتاح وصلاحيته."
            )
        if not response.ok:
            raise LiveAuthError(f"فشلت المصادقة (HTTP {response.status}). توقّف.")

        lowered = {k.lower(): v for k, v in (response.headers or {}).items()}
        cst = lowered.get("cst")
        token = lowered.get("x-security-token")
        if not cst or not token:
            raise LiveAuthError("استجابة مصادقة بلا رموز جلسة. توقّف.")

        REGISTRY.register_many([cst, token])
        self._cst = cst
        self._security_token = token
        self._authenticated = True

    # -- القراءة ----------------------------------------------------------

    def get(self, path: str, *, params: Optional[dict] = None) -> LiveResponse:
        """قراءة مُصادَقة. الحارس في الناقل يفحص المسار قبل الإرسال."""
        if not self._authenticated:
            raise LiveAuthError("لا جلسة — لم تكتمل المصادقة.")
        return self.transport.send(
            "GET",
            f"{LIVE_BASE_URL}{path}",
            headers={
                "X-CAP-API-KEY": self.secrets.get(CAPITAL_API_KEY),
                "CST": self._cst or "",
                "X-SECURITY-TOKEN": self._security_token or "",
            },
            params=params,
        )

    # -- الإنهاء ----------------------------------------------------------

    def discard(self) -> None:
        """
        يمحو الرموز من الذاكرة ومن سجل الحجب.

        ⚠️ لا يُستدعى `DELETE /session`: الطريقة `DELETE` **مرفوضة دائماً** في
        هذا الوضع بأمر المالكة، وهو قيد أشد وليس أضعف. الجلسة تنتهي لدى الوسيط
        بانقضاء مهلة الخمول (عشر دقائق).
        """
        for value in (self._cst, self._security_token):
            if value:
                REGISTRY.forget(value)
        self._cst = None
        self._security_token = None
        self._authenticated = False

    @property
    def tokens_retained(self) -> bool:
        return self._cst is not None or self._security_token is not None


def _encrypt_password(password: str, encryption_key_b64: str, timestamp: int) -> str:
    """التشفير الرسمي: RSA/PKCS1 على `base64(password|timestamp)`."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    staged = base64.b64encode(f"{password}|{timestamp}".encode()).decode()
    public_key = load_der_public_key(base64.b64decode(encryption_key_b64))
    encrypted = public_key.encrypt(staged.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


__all__ = [
    "LiveSession",
    "LiveAuthError",
    "LiveAuthAlreadyAttempted",
    "PATH_ENCRYPTION_KEY",
    "PATH_SESSION",
]
