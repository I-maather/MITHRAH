"""
MOBILE SECURITY — تسجيل الأجهزة، والرموز، والصلاحيات.

## الفرضية

الهاتف **عميل مراقبة وتحكّم بالتقليل**، لا طرف موثوق. كل ما يستطيع فعله
مُعرَّف هنا على الخادم، ولا يستطيع التطبيق توسيعه مهما عُدِّل — لأن الفرض
هنا لا هناك.

## Face ID ليست مصادقة خادم

Face ID تفتح التطبيق على الجهاز. لا تُثبت شيئاً للخادم: جهاز مكسور الحماية
يستطيع تجاوزها. لذلك:

    Face ID = بوابة وصول محلية
    رمز الخادم قصير العمر = المصادقة الفعلية

وأي إجراء يرفع المخاطرة يحتاج **تحدّياً من الخادم** فوق الاثنين معاً.

## التسجيل بـQR

    الخادم يولّد تحدّياً لمرة واحدة، قصير العمر، **بلا أي سرّ وسيط فيه**.
    الهاتف يمسحه ويسجّل هويته العامة. التحدّي يُستهلَك فوراً.

رمز QR قد يُصوَّر أو يُشارَك شاشةً، فمحتواه يجب أن يكون عديم القيمة بعد
ثوانٍ ومحدود الاستعمال بمرة.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets as _secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional

#: عمر تحدّي التسجيل. قصير عمداً — رمز QR يُصوَّر بسهولة.
ENROLLMENT_CHALLENGE_TTL = timedelta(minutes=2)
#: عمر رمز الوصول. قصير كي يقلّ أثر تسريبه.
ACCESS_TOKEN_TTL = timedelta(minutes=15)
#: عمر رمز التجديد، ويُدوَّر عند كل استعمال.
REFRESH_TOKEN_TTL = timedelta(days=30)
#: مدّة التبريد قبل تفعيل رفع المخاطرة — **مفروضة على الخادم**.
PROFILE_UPGRADE_COOLING = timedelta(hours=24)


class MobilePermission(str, Enum):
    """صلاحيات إصدار الجوال الأول."""

    VIEW_STATUS = "VIEW_STATUS"
    VIEW_INTELLIGENCE = "VIEW_INTELLIGENCE"
    VIEW_RISK = "VIEW_RISK"
    VIEW_POSITIONS = "VIEW_POSITIONS"
    VIEW_HISTORY = "VIEW_HISTORY"
    VIEW_PERFORMANCE = "VIEW_PERFORMANCE"
    VIEW_PROVIDERS = "VIEW_PROVIDERS"
    VIEW_AUDIT = "VIEW_AUDIT"
    RECEIVE_NOTIFICATIONS = "RECEIVE_NOTIFICATIONS"
    REQUEST_PAUSE = "REQUEST_PAUSE"
    ACTIVATE_KILL_SWITCH = "ACTIVATE_KILL_SWITCH"
    REVOKE_DEVICE = "REVOKE_DEVICE"


#: ما يُمنَح للجهاز المسجَّل. **كله قراءة أو تقليل مخاطرة.**
GRANTED_PERMISSIONS: frozenset[MobilePermission] = frozenset(MobilePermission)

#: ما **لا يُمنَح أبداً** في هذا الإصدار. قائمة صريحة كي تُختبَر لا لتُقرأ.
FORBIDDEN_MOBILE_ACTIONS: tuple[str, ...] = (
    "CONSTRUCT_ORDER", "CHANGE_QUANTITY", "CHANGE_STOP_LOSS", "CHANGE_TAKE_PROFIT",
    "PLACE_TRADE", "CLOSE_POSITION", "CHANGE_LEVERAGE", "CHANGE_BROKER_PREFERENCES",
    "REACTIVATE_BROKER_KEY", "APPROVE_CONTINUOUS_LIVE", "FUND_ACCOUNT",
    "WITHDRAW", "MODIFY_POSITION", "CREATE_WORKING_ORDER",
)

assert not (
    {p.value for p in MobilePermission} & set(FORBIDDEN_MOBILE_ACTIONS)
), "لا صلاحية ممنوحة تتقاطع مع قائمة الممنوع."

#: أسرار **لا يجوز أن تصل إلى التطبيق** بأي حال.
NEVER_ON_DEVICE: tuple[str, ...] = (
    "CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_API_PASSWORD",
    "FMP_API_KEY", "FINNHUB_API_KEY", "FRED_API_KEY",
    "APNS_PRIVATE_KEY", "CST", "X-SECURITY-TOKEN",
    "DATABASE_URL", "ORDER_SIGNING_SECRET",
)


class DeviceState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass
class EnrollmentChallenge:
    """
    تحدّي تسجيل لمرة واحدة. **لا يحمل سرّ وسيط ولا مفتاح مزوّد** — يحمل
    معرّفاً عشوائياً وعمراً قصيراً فقط.
    """

    challenge_id: str
    nonce: str
    created_utc: datetime
    expires_utc: datetime
    consumed: bool = False
    consumed_by: Optional[str] = None

    def is_valid(self, now: datetime) -> bool:
        return not self.consumed and now < self.expires_utc

    def qr_payload(self, *, backend_url: str) -> dict:
        """
        محتوى رمز QR. يُفحَص في الاختبارات أنه **لا يحتوي أي اسم من
        `NEVER_ON_DEVICE`** ولا أي قيمة تشبه مفتاحاً.
        """
        return {
            "v": 1,
            "backend": backend_url,
            "challenge_id": self.challenge_id,
            "nonce": self.nonce,
            "expires_utc": self.expires_utc.isoformat(),
            "contains_secret": False,
        }


@dataclass
class RegisteredDevice:
    device_id: str
    public_identity: str          # بصمة مفتاح الجهاز العام — لا مفتاح خاص
    name: str
    state: DeviceState
    enrolled_utc: datetime
    last_seen_utc: Optional[datetime] = None
    apns_token: Optional[str] = None
    revoked_utc: Optional[datetime] = None
    revocation_reason: str = ""

    @property
    def active(self) -> bool:
        return self.state is DeviceState.ACTIVE

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "state": self.state.value,
            "enrolled_utc": self.enrolled_utc.isoformat(),
            "last_seen_utc": self.last_seen_utc.isoformat() if self.last_seen_utc else None,
            "revoked_utc": self.revoked_utc.isoformat() if self.revoked_utc else None,
            "revocation_reason": self.revocation_reason,
            "has_push_token": self.apns_token is not None,
            # البصمة تُعرض مقنَّعة — لا تُعرض كاملة ولا يُعرض الرمز أبداً.
            "public_identity_masked": (
                self.public_identity[:8] + "…" if self.public_identity else ""
            ),
        }


@dataclass
class IssuedToken:
    token: str
    device_id: str
    issued_utc: datetime
    expires_utc: datetime
    kind: str                     # "access" | "refresh"
    rotated_from: Optional[str] = None
    revoked: bool = False

    def is_valid(self, now: datetime) -> bool:
        return not self.revoked and now < self.expires_utc


@dataclass
class AuditEntry:
    at_utc: datetime
    action: str
    device_id: Optional[str]
    detail_ar: str
    success: bool

    def as_dict(self) -> dict:
        return {
            "at_utc": self.at_utc.isoformat(),
            "action": self.action,
            "device_id": self.device_id,
            "detail_ar": self.detail_ar,
            "success": self.success,
        }


class MobileSecurityService:
    """
    كل قرار أمني للجوال يمرّ من هنا. **التخزين في الذاكرة** في هذه المرحلة:
    التسجيل غير مُفعَّل بعد، والاستمرارية تُضاف مع تفعيله.
    """

    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    ) -> None:
        self.clock = clock
        self._challenges: dict[str, EnrollmentChallenge] = {}
        self._devices: dict[str, RegisteredDevice] = {}
        self._tokens: dict[str, IssuedToken] = {}
        self._audit: list[AuditEntry] = []
        #: يمنع التفعيل قبل انقضاء التبريد — **على الخادم**.
        self._upgrade_requests: dict[str, datetime] = {}

    # -- التدقيق ----------------------------------------------------------

    def _audit_log(
        self, action: str, *, device_id: Optional[str], detail_ar: str, success: bool
    ) -> AuditEntry:
        entry = AuditEntry(self.clock(), action, device_id, detail_ar, success)
        self._audit.append(entry)
        return entry

    def audit(self, limit: int = 50) -> tuple[AuditEntry, ...]:
        return tuple(self._audit[-limit:])

    # -- التسجيل ----------------------------------------------------------

    def create_enrollment_challenge(self) -> EnrollmentChallenge:
        now = self.clock()
        challenge = EnrollmentChallenge(
            challenge_id=_secrets.token_urlsafe(12),
            nonce=_secrets.token_urlsafe(24),
            created_utc=now,
            expires_utc=now + ENROLLMENT_CHALLENGE_TTL,
        )
        self._challenges[challenge.challenge_id] = challenge
        self._audit_log(
            "ENROLLMENT_CHALLENGE_CREATED", device_id=None,
            detail_ar=f"تحدّي تسجيل صالح {int(ENROLLMENT_CHALLENGE_TTL.total_seconds())} ثانية.",
            success=True,
        )
        return challenge

    def complete_enrollment(
        self, *, challenge_id: str, public_identity: str, device_name: str
    ) -> Optional[RegisteredDevice]:
        """
        يستهلك التحدّي **مرة واحدة**. الاستعمال الثاني يفشل حتى لو كان قبل
        انتهاء المهلة — وهذا هو الفرق بين «قصير العمر» و«لمرة واحدة».
        """
        now = self.clock()
        challenge = self._challenges.get(challenge_id)
        if challenge is None or not challenge.is_valid(now):
            self._audit_log(
                "ENROLLMENT_REJECTED", device_id=None,
                detail_ar="تحدّي غير موجود أو منتهٍ أو مُستهلَك.", success=False,
            )
            return None

        device = RegisteredDevice(
            device_id=_secrets.token_urlsafe(12),
            public_identity=hashlib.sha256(public_identity.encode()).hexdigest(),
            name=device_name[:64],
            state=DeviceState.ACTIVE,
            enrolled_utc=now,
        )
        challenge.consumed = True
        challenge.consumed_by = device.device_id
        self._devices[device.device_id] = device
        self._audit_log(
            "DEVICE_ENROLLED", device_id=device.device_id,
            detail_ar=f"جهاز «{device.name}» سُجِّل.", success=True,
        )
        return device

    def revoke_device(self, device_id: str, *, reason: str = "") -> bool:
        device = self._devices.get(device_id)
        if device is None:
            return False
        device.state = DeviceState.REVOKED
        device.revoked_utc = self.clock()
        device.revocation_reason = reason
        device.apns_token = None
        # كل رموز الجهاز تسقط فوراً — الإلغاء لا ينتظر انتهاء المهلة.
        for token in self._tokens.values():
            if token.device_id == device_id:
                token.revoked = True
        self._audit_log(
            "DEVICE_REVOKED", device_id=device_id,
            detail_ar=f"أُلغي الجهاز. السبب: {reason or '—'}. كل رموزه أُبطلت.",
            success=True,
        )
        return True

    def devices(self) -> tuple[RegisteredDevice, ...]:
        return tuple(self._devices.values())

    # -- الرموز -----------------------------------------------------------

    def issue_tokens(self, device_id: str) -> Optional[tuple[IssuedToken, IssuedToken]]:
        device = self._devices.get(device_id)
        if device is None or not device.active:
            return None
        now = self.clock()
        access = IssuedToken(
            _secrets.token_urlsafe(32), device_id, now, now + ACCESS_TOKEN_TTL, "access"
        )
        refresh = IssuedToken(
            _secrets.token_urlsafe(32), device_id, now, now + REFRESH_TOKEN_TTL, "refresh"
        )
        self._tokens[access.token] = access
        self._tokens[refresh.token] = refresh
        return access, refresh

    def rotate_refresh(self, refresh_token: str) -> Optional[tuple[IssuedToken, IssuedToken]]:
        """
        تدوير إجباري: الرمز القديم **يُبطَل** عند الاستعمال. إعادة استعماله
        بعد ذلك مؤشّر سرقة، ويُسجَّل.
        """
        now = self.clock()
        existing = self._tokens.get(refresh_token)
        if existing is None or existing.kind != "refresh":
            return None
        if not existing.is_valid(now):
            self._audit_log(
                "REFRESH_REUSE_DETECTED", device_id=existing.device_id,
                detail_ar="محاولة استعمال رمز تجديد مُبطَل — يُعامَل مؤشّر سرقة.",
                success=False,
            )
            return None
        existing.revoked = True
        issued = self.issue_tokens(existing.device_id)
        if issued is None:
            return None
        access, refresh = issued
        return access, IssuedToken(
            refresh.token, refresh.device_id, refresh.issued_utc,
            refresh.expires_utc, "refresh", rotated_from=refresh_token,
        )

    def authenticate(self, token: str) -> Optional[RegisteredDevice]:
        """
        **يفشل مغلقاً**: رمز غير معروف أو منتهٍ أو لجهاز مُلغى ⇒ لا هوية.
        """
        issued = self._tokens.get(token)
        if issued is None or issued.kind != "access" or not issued.is_valid(self.clock()):
            return None
        device = self._devices.get(issued.device_id)
        if device is None or not device.active:
            return None
        device.last_seen_utc = self.clock()
        return device

    def register_push_token(self, device_id: str, apns_token: str) -> bool:
        device = self._devices.get(device_id)
        if device is None or not device.active:
            return False
        device.apns_token = apns_token
        self._audit_log(
            "PUSH_TOKEN_REGISTERED", device_id=device_id,
            detail_ar="سُجِّل رمز إشعارات جديد (لا يُعرض ولا يُسجَّل نصّه).",
            success=True,
        )
        return True

    # -- رفع المخاطرة ------------------------------------------------------

    def request_profile_upgrade(
        self, device_id: str, *, target_profile: str
    ) -> tuple[bool, str]:
        """
        يبدأ التبريد فقط. **لا يفعّل شيئاً** — التفعيل قرار منفصل بعد 24 ساعة
        وبعد إعادة فحص كل الشروط، والهاتف لا يستطيع تقصير المدّة.
        """
        device = self._devices.get(device_id)
        if device is None or not device.active:
            return False, "جهاز غير مُفعَّل."
        self._upgrade_requests[device_id] = self.clock()
        self._audit_log(
            "PROFILE_UPGRADE_REQUESTED", device_id=device_id,
            detail_ar=(
                f"طُلب الترقية إلى {target_profile}. "
                f"تبريد {int(PROFILE_UPGRADE_COOLING.total_seconds() // 3600)} ساعة "
                "مفروض على الخادم."
            ),
            success=True,
        )
        return True, "بدأ التبريد. لا تفعيل قبل انقضائه وإعادة فحص الشروط."

    def upgrade_cooling_remaining(self, device_id: str) -> Optional[timedelta]:
        started = self._upgrade_requests.get(device_id)
        if started is None:
            return None
        elapsed = self.clock() - started
        remaining = PROFILE_UPGRADE_COOLING - elapsed
        return remaining if remaining.total_seconds() > 0 else timedelta(0)


def constant_time_equals(a: str, b: str) -> bool:
    """مقارنة بزمن ثابت — مقارنة نصية عادية تسرّب طول البادئة المطابقة."""
    return hmac.compare_digest(a.encode(), b.encode())


__all__ = [
    "ENROLLMENT_CHALLENGE_TTL", "ACCESS_TOKEN_TTL", "REFRESH_TOKEN_TTL",
    "PROFILE_UPGRADE_COOLING", "MobilePermission", "GRANTED_PERMISSIONS",
    "FORBIDDEN_MOBILE_ACTIONS", "NEVER_ON_DEVICE", "DeviceState",
    "EnrollmentChallenge", "RegisteredDevice", "IssuedToken", "AuditEntry",
    "MobileSecurityService", "constant_time_equals",
]
