"""
إدارة جلسة Capital.com.

الحقائق الرسمية المعتمدة (تُحقق 2026-08-28 من https://open-api.capital.com/):
  * POST /api/v1/session بترويسة X-CAP-API-KEY وجسم {identifier, password, encryptedPassword}
  * الاستجابة تعيد في الترويسات: CST و X-SECURITY-TOKEN
  * كلاهما صالح **10 دقائق من آخر استخدام**
  * GET /api/v1/ping يبقي الجلسة حيّة
  * POST /session محدود بطلب واحد في الثانية لكل مفتاح

قواعد هذا الملف:
  * CST و X-SECURITY-TOKEN يعيشان في الذاكرة فقط. لا قاعدة بيانات، لا ملف، لا سجل.
  * كل قيمة سرّية تُسجَّل في سجل الحجب فور استلامها.
  * بعد فشل مصادقة متكرر، النظام يقفل نفسه ولا يستمر في المحاولة.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from ...clock import now_utc
from ...secretstore.provider import (
    CAPITAL_API_KEY,
    CAPITAL_API_PASSWORD,
    CAPITAL_IDENTIFIER,
    SecretProvider,
)
from ...secretstore.redaction import REGISTRY, redact_headers
from .endpoints import (
    PATH_ENCRYPTION_KEY,
    PATH_PING,
    PATH_SESSION,
    CapitalEnvironment,
)
from .errors import (
    CapitalAuthError,
    CapitalAuthLockout,
    CapitalMalformedResponse,
    CapitalSessionExpired,
)
from .safety import assert_environment_allowed
from .transport import ApiResponse, Transport

logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(minutes=10)
#: هامش أمان: نجدّد قبل انتهاء المهلة الرسمية بدقيقتين.
SESSION_RENEW_MARGIN = timedelta(minutes=2)
MAX_AUTH_FAILURES = 3

HEADER_API_KEY = "X-CAP-API-KEY"
HEADER_CST = "CST"
HEADER_SECURITY_TOKEN = "X-SECURITY-TOKEN"


@dataclass
class SessionTokens:
    """
    رموز الجلسة — في الذاكرة فقط.

    `__repr__` مُعاد تعريفه حتى لا تظهر القيم في أي تتبّع أو تسجيل.
    """

    cst: str
    security_token: str
    issued_at_utc: datetime
    last_used_utc: datetime

    def __repr__(self) -> str:  # pragma: no cover - سلوك عرض فقط
        return "SessionTokens(cst=***REDACTED***, security_token=***REDACTED***)"

    __str__ = __repr__

    def is_expired(self, at: datetime, ttl: timedelta = SESSION_TTL) -> bool:
        return (at - self.last_used_utc) >= ttl

    def needs_renewal(self, at: datetime) -> bool:
        return (at - self.last_used_utc) >= (SESSION_TTL - SESSION_RENEW_MARGIN)

    def touch(self, at: datetime) -> None:
        self.last_used_utc = at


def encrypt_password(password: str, encryption_key_b64: str, timestamp: int) -> str:
    """
    التشفير الرسمي: RSA/ECB/PKCS1Padding على base64(password|timestamp)،
    ثم base64 للناتج.

    يُستعمل عندما يوفّر الوسيط مفتاح تشفير. إن تعذّر (مكتبة غير متاحة)،
    ترتفع استثناء ولا نتراجع بصمت إلى إرسال كلمة مرور خام دون قرار صريح.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_der_public_key
    except ImportError as exc:  # pragma: no cover - بيئة بلا cryptography
        raise CapitalAuthError(
            "التشفير غير متاح: مكتبة cryptography غير مثبّتة."
        ) from None

    payload = f"{password}|{timestamp}".encode()
    staged = base64.b64encode(payload)
    public_key = load_der_public_key(base64.b64decode(encryption_key_b64))
    encrypted = public_key.encrypt(staged, padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


@dataclass
class CapitalSession:
    """
    دورة حياة الجلسة: إنشاء، إبقاء حيّة، تجديد، إغلاق.
    """

    transport: Transport
    secrets: SecretProvider
    environment: CapitalEnvironment = CapitalEnvironment.DEMO
    use_encrypted_password: bool = True
    # default_factory حتى تكون سمة نسخة لا سمة صنف، فلا تُربط كميثود.
    clock: Callable[[], datetime] = field(default_factory=lambda: now_utc)

    tokens: Optional[SessionTokens] = field(default=None, init=False)
    account_id: Optional[str] = field(default=None, init=False)
    _auth_failures: int = field(default=0, init=False)
    _locked_out: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        assert_environment_allowed(self.environment)

    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        return self.environment.base_url

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _api_key(self) -> str:
        return self.secrets.get(CAPITAL_API_KEY)

    def _key_headers(self) -> dict[str, str]:
        return {HEADER_API_KEY: self._api_key(), "Content-Type": "application/json"}

    def auth_headers(self) -> dict[str, str]:
        """ترويسات مصادقة كاملة. تُستدعى بعد ضمان جلسة صالحة."""
        if self.tokens is None:
            raise CapitalSessionExpired("لا توجد جلسة نشطة.")
        return {
            HEADER_API_KEY: self._api_key(),
            HEADER_CST: self.tokens.cst,
            HEADER_SECURITY_TOKEN: self.tokens.security_token,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    def _fetch_encryption_key(self) -> Optional[tuple[str, int]]:
        response = self.transport.send(
            "GET", self._url(PATH_ENCRYPTION_KEY), headers=self._key_headers()
        )
        if not response.ok:
            return None
        body = response.json()
        key = body.get("encryptionKey")
        timestamp = body.get("timeStamp")
        if not key or timestamp is None:
            return None
        return str(key), int(timestamp)

    def login(self) -> SessionTokens:
        if self._locked_out:
            raise CapitalAuthLockout(
                f"أُقفلت المصادقة بعد {MAX_AUTH_FAILURES} محاولات فاشلة. "
                "لن يحاول النظام مجدداً تلقائياً — راجعي الاعتمادات ثم أعيدي التشغيل."
            )
        assert_environment_allowed(self.environment)

        identifier = self.secrets.get(CAPITAL_IDENTIFIER)
        password = self.secrets.get(CAPITAL_API_PASSWORD)
        REGISTRY.register_many([identifier, password])

        payload: dict[str, object] = {"identifier": identifier}
        if self.use_encrypted_password:
            key_pair = self._fetch_encryption_key()
            if key_pair is not None:
                encryption_key, timestamp = key_pair
                payload["password"] = encrypt_password(password, encryption_key, timestamp)
                payload["encryptedPassword"] = True
            else:
                payload["password"] = password
                payload["encryptedPassword"] = False
        else:
            payload["password"] = password
            payload["encryptedPassword"] = False

        response = self.transport.send(
            "POST", self._url(PATH_SESSION), headers=self._key_headers(), json=payload
        )
        return self._consume_login_response(response)

    def _consume_login_response(self, response: ApiResponse) -> SessionTokens:
        if response.status in (401, 403):
            self._register_auth_failure()
            raise CapitalAuthError(
                "رفض Capital.com المصادقة (مفتاح أو معرّف أو كلمة مرور API غير صحيحة). "
                "لن تُعرض أي قيمة اعتماد هنا."
            )
        if not response.ok:
            self._register_auth_failure()
            raise CapitalAuthError(
                f"فشل إنشاء الجلسة برمز الحالة {response.status}."
            )

        headers = {k.upper(): v for k, v in response.headers.items()}
        cst = headers.get(HEADER_CST.upper())
        security_token = headers.get(HEADER_SECURITY_TOKEN.upper())
        if not cst or not security_token:
            self._register_auth_failure()
            raise CapitalMalformedResponse(
                "استجابة الجلسة لا تحتوي CST أو X-SECURITY-TOKEN."
            )

        REGISTRY.register_many([cst, security_token])
        at = self.clock()
        self.tokens = SessionTokens(
            cst=cst, security_token=security_token, issued_at_utc=at, last_used_utc=at
        )
        self._auth_failures = 0

        body = response.body if isinstance(response.body, dict) else {}
        self.account_id = body.get("currentAccountId") or self.account_id
        logger.info(
            "capital session established env=%s headers=%s",
            self.environment.value,
            redact_headers(response.headers),
        )
        return self.tokens

    def _register_auth_failure(self) -> None:
        self._auth_failures += 1
        if self._auth_failures >= MAX_AUTH_FAILURES:
            self._locked_out = True

    # ------------------------------------------------------------------
    def ensure_session(self) -> SessionTokens:
        """يضمن جلسة صالحة، ويجدّدها قبل انتهائها بهامش أمان."""
        at = self.clock()
        if self.tokens is None or self.tokens.is_expired(at) or self.tokens.needs_renewal(at):
            return self.login()
        return self.tokens

    def ping(self) -> bool:
        """إبقاء الجلسة حيّة. يعيد False إن انتهت بدل أن يرمي."""
        if self.tokens is None:
            return False
        response = self.transport.send("GET", self._url(PATH_PING), headers=self.auth_headers())
        if response.status in (401, 403):
            self.tokens = None
            return False
        if response.ok:
            self.tokens.touch(self.clock())
            return True
        return False

    def logout(self) -> None:
        """يُنهي الجلسة وينسى الرموز من الذاكرة ومن سجل الحجب."""
        tokens = self.tokens
        self.tokens = None
        if tokens is not None:
            REGISTRY.forget(tokens.cst)
            REGISTRY.forget(tokens.security_token)

    @property
    def is_locked_out(self) -> bool:
        return self._locked_out

    @property
    def auth_failure_count(self) -> int:
        return self._auth_failures

    def state_for_report(self) -> dict:
        """حالة الجلسة كما تُعرض — بلا أي رمز."""
        return {
            "environment": self.environment.value,
            "authenticated": self.tokens is not None,
            "locked_out": self._locked_out,
            "auth_failures": self._auth_failures,
            "tokens_persisted": False,
        }
