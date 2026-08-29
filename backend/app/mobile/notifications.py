"""
NOTIFICATIONS — APNs، بواجهة إنتاج ومُقلِّد، ونصّ قفل شاشة خاص.

## قاعدة السلامة

    الإشعار **استشاري**. لا شيء في سلامة النظام يعتمد على وصوله.

وقف الخسارة وجني الأرباح **لدى الوسيط** لا في التطبيق. لو صمت الهاتف أسبوعاً،
أو أُلغي الجهاز، أو سقطت APNs، تبقى الحماية قائمة. الإشعار يُعلِم، ولا يحمي.

## نصّ شاشة القفل

    «لدى Maather Trader تحديث. افتحي التطبيق للتفاصيل.»

شاشة القفل تُقرأ فوق الكتف وتظهر في لقطات الشاشة والساعة. ولذلك **لا يظهر
فيها**: رصيد · ربح/خسارة · حجم مركز · سعر دخول · معرّف حساب · اتجاه
الاستراتيجية. التفاصيل خلف مصادقة التطبيق.

## APNs مباشرةً لا عبر وسيط

التسليم المباشر من الخادم إلى Apple يعني أن حمولة الإشعار لا تمرّ بطرف ثالث.
`expo-notifications` تُستعمل للحصول على **رمز الجهاز الأصلي** فقط.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional

#: النص الوحيد الذي يظهر على شاشة القفل افتراضياً.
PRIVATE_LOCK_SCREEN_TITLE = "Maather Trader"
PRIVATE_LOCK_SCREEN_BODY = "لدى Maather Trader تحديث. افتحي التطبيق للتفاصيل."

#: قيم **ممنوعة** في أي حمولة إشعار. تُفحَص قبل الإرسال لا بعده.
FORBIDDEN_PAYLOAD_KEYS: tuple[str, ...] = (
    "balance", "available", "profit_loss", "pnl", "position_size", "quantity",
    "entry_price", "stop_price", "take_profit", "account_id", "accountId",
    "direction", "side", "buy", "sell", "equity",
)

#: اعتمادات APNs التي ستُضبَط لاحقاً. **لا تُطلب الآن ولا تُنشأ.**
APNS_CREDENTIAL_NAMES: tuple[str, ...] = (
    "APNS_KEY_ID", "APPLE_TEAM_ID", "IOS_BUNDLE_ID", "APNS_PRIVATE_KEY_P8_PATH",
)

#: نافذة إزالة التكرار: إشعاران بالمعنى نفسه خلالها يُدمجان.
DEDUPLICATION_WINDOW = timedelta(minutes=5)
MAX_DELIVERY_ATTEMPTS = 3


class NotificationType(str, Enum):
    ELIGIBLE_SETUP_DETECTED = "ELIGIBLE_SETUP_DETECTED"
    NO_TRADE_EVENT_RISK = "NO_TRADE_EVENT_RISK"
    TRADE_SUBMITTED = "TRADE_SUBMITTED"
    BROKER_CONFIRMATION = "BROKER_CONFIRMATION"
    STOP_LOSS_EVENT = "STOP_LOSS_EVENT"
    TAKE_PROFIT_EVENT = "TAKE_PROFIT_EVENT"
    SPREAD_ANOMALY = "SPREAD_ANOMALY"
    STALE_DATA = "STALE_DATA"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    BROKER_DISCONNECT = "BROKER_DISCONNECT"
    DAILY_LIMIT_REACHED = "DAILY_LIMIT_REACHED"
    WEEKLY_LIMIT_REACHED = "WEEKLY_LIMIT_REACHED"
    TWO_LOSS_LOCK = "TWO_LOSS_LOCK"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    DAILY_SUMMARY = "DAILY_SUMMARY"


#: أنواع لا تُرسَل في هذا الإصدار — التداول غير مأذون به بعد.
NOT_YET_AUTHORISED: frozenset[NotificationType] = frozenset({
    NotificationType.TRADE_SUBMITTED,
})


class DeliveryState(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    INVALID_TOKEN = "INVALID_TOKEN"
    SUPPRESSED_DUPLICATE = "SUPPRESSED_DUPLICATE"
    BLOCKED_PRIVACY = "BLOCKED_PRIVACY"


class PrivacyViolation(RuntimeError):
    """حمولة كانت ستحمل قيمة حساب — **لا تُرسَل**."""


@dataclass(frozen=True)
class Notification:
    type: NotificationType
    created_utc: datetime
    #: تفاصيل تُعرَض **داخل التطبيق بعد المصادقة** فقط.
    in_app_detail_ar: str = ""
    deep_link: Optional[str] = None
    #: مفتاح إزالة التكرار — إشعاران بالمفتاح نفسه يُدمجان.
    dedup_key: str = ""

    def lock_screen_payload(self) -> dict:
        """
        حمولة شاشة القفل. **ثابتة النص** — لا تعتمد على محتوى الإشعار إطلاقاً،
        فلا يمكن أن يتسرّب رقم عبرها ولو بالخطأ.
        """
        return {
            "aps": {
                "alert": {
                    "title": PRIVATE_LOCK_SCREEN_TITLE,
                    "body": PRIVATE_LOCK_SCREEN_BODY,
                },
                "sound": "default",
                "mutable-content": 0,
            },
            "type": self.type.value,
            "requires_authentication": True,
        }

    def as_dict(self) -> dict:
        return {
            "type": self.type.value,
            "created_utc": self.created_utc.isoformat(),
            "in_app_detail_ar": self.in_app_detail_ar,
            "deep_link": self.deep_link,
            "dedup_key": self.dedup_key,
        }


def assert_payload_is_private(payload: dict) -> None:
    """
    يرفض أي حمولة تحمل مفتاحاً محظوراً — بالبحث في **المفاتيح والقيم** معاً.

    الفحص على القيم مقصود: رقمٌ يُدسّ في نص العنوان يتجاوز فحص المفاتيح وحده.
    """
    blob = repr(payload).lower()
    for key in FORBIDDEN_PAYLOAD_KEYS:
        if key.lower() in blob:
            raise PrivacyViolation(
                f"حمولة الإشعار تحتوي «{key}» — لا تُرسَل. "
                "شاشة القفل تُقرأ فوق الكتف."
            )


@dataclass
class DeliveryReceipt:
    notification: Notification
    device_id: str
    state: DeliveryState
    attempts: int = 0
    at_utc: Optional[datetime] = None
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "type": self.notification.type.value,
            "device_id": self.device_id,
            "state": self.state.value,
            "attempts": self.attempts,
            "at_utc": self.at_utc.isoformat() if self.at_utc else None,
            "reason": self.reason,
        }


class ApnsProvider(ABC):
    """واجهة الإنتاج. التنفيذ الحقيقي يُضاف حين تُنشئ المالكة مفتاح APNs."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def send(self, *, apns_token: str, payload: dict) -> tuple[bool, str]: ...


class MockApnsProvider(ApnsProvider):
    """
    مُقلِّد. **لا يفتح اتصالاً ولا يحمل مفتاحاً.** كل الاختبارات تستعمله،
    ولا مسار في المستودع يُنشئ مزوّداً حقيقياً بعد.
    """

    def __init__(self, *, fail_tokens: frozenset[str] = frozenset()) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.fail_tokens = fail_tokens

    @property
    def name(self) -> str:
        return "MockApnsProvider"

    @property
    def configured(self) -> bool:
        return True

    def send(self, *, apns_token: str, payload: dict) -> tuple[bool, str]:
        if apns_token in self.fail_tokens:
            return False, "BadDeviceToken"
        self.sent.append((apns_token, payload))
        return True, "OK"


class NotificationService:
    """يبني الإشعار، يفحص خصوصيته، يزيل تكراره، ثم يسلّمه ويسجّل الإيصال."""

    def __init__(
        self,
        *,
        apns: Optional[ApnsProvider] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.apns = apns or MockApnsProvider()
        self.clock = clock
        self._recent: dict[str, datetime] = {}
        self._receipts: list[DeliveryReceipt] = []
        self._invalid_tokens: set[str] = set()

    def _is_duplicate(self, key: str) -> bool:
        if not key:
            return False
        last = self._recent.get(key)
        now = self.clock()
        if last is not None and (now - last) < DEDUPLICATION_WINDOW:
            return True
        self._recent[key] = now
        return False

    def send(
        self, notification: Notification, *, device_id: str, apns_token: Optional[str]
    ) -> DeliveryReceipt:
        now = self.clock()

        if notification.type in NOT_YET_AUTHORISED:
            return self._record(DeliveryReceipt(
                notification, device_id, DeliveryState.FAILED, 0, now,
                "نوع غير مأذون به في هذا الإصدار — لا تداول بعد.",
            ))

        payload = notification.lock_screen_payload()
        try:
            assert_payload_is_private(payload)
        except PrivacyViolation as exc:
            return self._record(DeliveryReceipt(
                notification, device_id, DeliveryState.BLOCKED_PRIVACY, 0, now, str(exc),
            ))

        if self._is_duplicate(notification.dedup_key):
            # التكرار يُبتلَع بلا تنبيه ثانٍ — التنبيه المكرر يُدرِّب على التجاهل.
            return self._record(DeliveryReceipt(
                notification, device_id, DeliveryState.SUPPRESSED_DUPLICATE, 0, now,
                "مكرر ضمن نافذة الدمج — لا تنبيه ثانٍ للمستخدمة.",
            ))

        if not apns_token or apns_token in self._invalid_tokens:
            return self._record(DeliveryReceipt(
                notification, device_id, DeliveryState.INVALID_TOKEN, 0, now,
                "لا رمز إشعارات صالح لهذا الجهاز.",
            ))

        attempts = 0
        last_reason = ""
        while attempts < MAX_DELIVERY_ATTEMPTS:
            attempts += 1
            ok, reason = self.apns.send(apns_token=apns_token, payload=payload)
            last_reason = reason
            if ok:
                return self._record(DeliveryReceipt(
                    notification, device_id, DeliveryState.DELIVERED, attempts, now, reason,
                ))
            if reason in ("BadDeviceToken", "Unregistered"):
                # رمز باطل: يُسجَّل ولا يُعاد المحاولة — الإلحاح لا يصلحه.
                self._invalid_tokens.add(apns_token)
                return self._record(DeliveryReceipt(
                    notification, device_id, DeliveryState.INVALID_TOKEN,
                    attempts, now, reason,
                ))

        return self._record(DeliveryReceipt(
            notification, device_id, DeliveryState.FAILED, attempts, now, last_reason,
        ))

    def _record(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        self._receipts.append(receipt)
        return receipt

    def receipts(self, limit: int = 50) -> tuple[DeliveryReceipt, ...]:
        return tuple(self._receipts[-limit:])

    def invalidate_token(self, apns_token: str) -> None:
        self._invalid_tokens.add(apns_token)

    def rotate_token(self, old_token: str, new_token: str) -> None:
        """تدوير الرمز: القديم يسقط، ولا يُحتفَظ به «احتياطاً»."""
        self._invalid_tokens.discard(new_token)
        self._invalid_tokens.add(old_token)


__all__ = [
    "PRIVATE_LOCK_SCREEN_TITLE", "PRIVATE_LOCK_SCREEN_BODY",
    "FORBIDDEN_PAYLOAD_KEYS", "APNS_CREDENTIAL_NAMES", "DEDUPLICATION_WINDOW",
    "MAX_DELIVERY_ATTEMPTS", "NotificationType", "NOT_YET_AUTHORISED",
    "DeliveryState", "PrivacyViolation", "Notification", "DeliveryReceipt",
    "ApnsProvider", "MockApnsProvider", "NotificationService",
    "assert_payload_is_private",
]
