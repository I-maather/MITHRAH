"""
MOBILE API — `/api/mobile/v1/` — قراءة، وثلاثة إجراءات تُقلّل المخاطرة.

## ما ليس هنا

**لا نقطة نهاية تداول.** لا إنشاء أمر ولا تعديل كمية ولا وقف ولا هدف ولا
إغلاق مركز ولا تغيير رافعة ولا إعادة تفعيل مفتاح الوسيط. هذا ليس سهواً
يُستدرَك لاحقاً — هو حدّ الإصدار، ويُختبَر أن المسارات المُعلَنة لا تحتوي أي
فعل تنفيذي.

## ثلاثة إجراءات فقط

    pause/request         إيقاف مؤقت — يقلّل المخاطرة
    killswitch/activate   قاطع الطوارئ — يقلّل المخاطرة
    device/revoke         إلغاء جهاز — يقلّل سطح الهجوم

الثلاثة **لا تفتح شيئاً**. لا يوجد في هذا الملف مسار يزيد المخاطرة، ولذلك لا
حاجة لتحدٍّ إضافي على أيٍّ منها: أسوأ ما يفعله مهاجم بها هو إيقاف التداول.

## التقارير الخاصة

`data/private/` **لا يُقدَّم عبر هذا المجال** بحال. لا مسار ملفات، ولا نقطة
تنزيل، ولا حقل يحمل مساراً خاصاً.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .security import (
    FORBIDDEN_MOBILE_ACTIONS,
    MobilePermission,
    MobileSecurityService,
    RegisteredDevice,
)

API_PREFIX = "/api/mobile/v1"

#: مسارات القراءة المُعلَنة. القائمة تُختبَر كما هي.
READ_ROUTES: tuple[str, ...] = (
    "status",
    "intelligence/latest",
    "decision/latest",
    "risk",
    "profiles",
    "positions/current",
    "trades",
    "performance",
    "providers/health",
    "notifications",
    "audit/recent",
)

#: مسارات التعديل — **كلها تقلّل المخاطرة**.
RISK_REDUCING_ROUTES: tuple[str, ...] = (
    "pause/request",
    "killswitch/activate",
    "device/revoke",
)

#: كلمات لا يجوز أن تظهر في أي مسار من هذا المجال.
FORBIDDEN_ROUTE_TOKENS: tuple[str, ...] = (
    "order", "trade/submit", "position/open", "position/close", "leverage",
    "preferences", "deposit", "withdraw", "quantity", "stop", "takeprofit",
    "activate-key", "commissioning",
)

#: مفاتيح ممنوعة في أي استجابة — بيانات خاصة أو مسارات خاصة.
FORBIDDEN_RESPONSE_TOKENS: tuple[str, ...] = (
    "data/private", "capital_live_discovery", "CAPITAL_API_KEY",
    "FMP_API_KEY", "FINNHUB_API_KEY", "FRED_API_KEY",
    "X-SECURITY-TOKEN", "CST",
)

for _route in READ_ROUTES + RISK_REDUCING_ROUTES:
    for _token in FORBIDDEN_ROUTE_TOKENS:
        assert _token not in _route, f"مسار محظور تسلّل: {_route}"


class MobileApiError(RuntimeError):
    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class MobileResponse:
    status: int
    body: dict

    def as_dict(self) -> dict:
        return {"status": self.status, "body": self.body}


def assert_response_is_clean(body: Any) -> None:
    """
    فحص أخير قبل إعادة أي استجابة: لا مسار خاص ولا اسم مفتاح.

    الفحص هنا لا في المستدعي، لأن المستدعي هو من يُنسى.
    """
    blob = repr(body)
    for token in FORBIDDEN_RESPONSE_TOKENS:
        if token in blob:
            raise MobileApiError(
                f"استجابة الجوال كانت ستحمل «{token}» — مُنعت.", status=500
            )


@dataclass
class MobileApi:
    """
    طبقة تطبيقية محايدة عن FastAPI كي تُختبَر بلا خادم.

    `providers` و`state_source` تُحقَن، فلا هذه الطبقة تعرف الوسيط ولا تصل إليه.
    """

    security: MobileSecurityService
    state_source: Callable[[], dict] = dict
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    # -- المصادقة ----------------------------------------------------------

    def _authenticate(self, token: Optional[str]) -> RegisteredDevice:
        device = self.security.authenticate(token or "")
        if device is None:
            raise MobileApiError("رمز غير صالح أو منتهٍ أو لجهاز مُلغى.", status=401)
        return device

    # -- التوجيه ------------------------------------------------------------

    def handle(
        self, method: str, route: str, *, token: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> MobileResponse:
        route = route.strip("/")
        payload = payload or {}

        if method.upper() not in ("GET", "POST"):
            raise MobileApiError("طريقة غير مسموحة في مجال الجوال.", status=405)
        if method.upper() == "GET" and route not in READ_ROUTES:
            raise MobileApiError("مسار قراءة غير معروف.", status=404)
        if method.upper() == "POST" and route not in RISK_REDUCING_ROUTES:
            # كل POST خارج الثلاثة مرفوض — بما فيه أي مسار تداول محتمل.
            raise MobileApiError(
                "لا يوجد في مجال الجوال أي مسار تعديل عدا ثلاثة تقلّل المخاطرة.",
                status=403,
            )

        device = self._authenticate(token)
        body = (
            self._read(route, device) if method.upper() == "GET"
            else self._mutate(route, device, payload)
        )
        assert_response_is_clean(body)
        return MobileResponse(200, body)

    # -- القراءة ------------------------------------------------------------

    def _read(self, route: str, device: RegisteredDevice) -> dict:
        state = self.state_source() or {}
        now = self.clock()
        common = {
            "route": route,
            "server_time_utc": now.isoformat(),
            "device_id": device.device_id,
            "authorises_execution": False,
        }
        section = {
            "status": lambda: state.get("status", {}),
            "intelligence/latest": lambda: state.get("intelligence", {}),
            "decision/latest": lambda: state.get("decision", {}),
            "risk": lambda: state.get("risk", {}),
            "profiles": lambda: state.get("profiles", {}),
            "positions/current": lambda: state.get("position", {}),
            "trades": lambda: {"trades": state.get("trades", [])},
            "performance": lambda: state.get("performance", {}),
            "providers/health": lambda: state.get("providers", {}),
            "notifications": lambda: {"notifications": state.get("notifications", [])},
            "audit/recent": lambda: {
                "entries": [e.as_dict() for e in self.security.audit()]
            },
        }[route]()
        return {**common, "data": section}

    # -- التعديل المُقلِّل للمخاطرة ------------------------------------------

    def _mutate(self, route: str, device: RegisteredDevice, payload: dict) -> dict:
        now = self.clock()
        if route == "pause/request":
            self.security._audit_log(
                "MOBILE_PAUSE_REQUESTED", device_id=device.device_id,
                detail_ar="طُلب إيقاف مؤقت من الجوال — إجراء يقلّل المخاطرة.",
                success=True,
            )
            return {
                "action": "PAUSE_REQUESTED", "accepted": True,
                "at_utc": now.isoformat(),
                "note_ar": "الإيقاف يقلّل المخاطرة ولا يفتح شيئاً.",
            }

        if route == "killswitch/activate":
            self.security._audit_log(
                "MOBILE_KILL_SWITCH", device_id=device.device_id,
                detail_ar="فُعِّل قاطع الطوارئ من الجوال.", success=True,
            )
            return {
                "action": "KILL_SWITCH_ACTIVATED", "accepted": True,
                "at_utc": now.isoformat(),
                "note_ar": (
                    "القاطع مُفعَّل. **لا يُلغى من الجوال** — الإلغاء إجراء "
                    "يزيد المخاطرة ويحتاج الخادم."
                ),
            }

        if route == "device/revoke":
            target = str(payload.get("device_id") or device.device_id)
            ok = self.security.revoke_device(
                target, reason=str(payload.get("reason", "بطلب من الجوال"))
            )
            return {
                "action": "DEVICE_REVOKED", "accepted": ok,
                "device_id": target, "at_utc": now.isoformat(),
            }

        raise MobileApiError("مسار غير معروف.", status=404)


def describe_api() -> dict:
    """وصف المجال — يُستعمل في التوثيق وفي اختبارات العقد."""
    return {
        "prefix": API_PREFIX,
        "read_routes": list(READ_ROUTES),
        "risk_reducing_routes": list(RISK_REDUCING_ROUTES),
        "trading_routes": [],
        "forbidden_actions": list(FORBIDDEN_MOBILE_ACTIONS),
        "permissions": [p.value for p in MobilePermission],
        "note_ar": (
            "لا نقطة نهاية تداول في إصدار الجوال الأول. الثلاثة المتاحة "
            "للتعديل **تقلّل المخاطرة** ولا تزيدها."
        ),
    }


__all__ = [
    "API_PREFIX", "READ_ROUTES", "RISK_REDUCING_ROUTES",
    "FORBIDDEN_ROUTE_TOKENS", "FORBIDDEN_RESPONSE_TOKENS",
    "MobileApi", "MobileApiError", "MobileResponse",
    "assert_response_is_clean", "describe_api",
]
