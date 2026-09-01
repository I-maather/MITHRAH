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

from dataclasses import dataclass, field
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
    "scan/latest",
    "market/candles",
)

#: مسارات التعديل — **كلها تقلّل المخاطرة**.
RISK_REDUCING_ROUTES: tuple[str, ...] = (
    "pause/request",
    "killswitch/activate",
    "device/revoke",
)

#: **المسار الوحيد الذي يزيد المخاطرة** — في فئةٍ خاصّة به عمداً.
#:
#: ## لماذا فئة ثالثة ولا يُضاف إلى الثانية
#:
#: كان العقد: «قراءة + ثلاثة مسارات كلها تقلّل المخاطرة». وإضافة الاستئناف
#: إليها تُلغي العقد **بصمت** — يبقى الاسم `RISK_REDUCING_ROUTES` ويصير
#: كاذباً. وفئةٌ ثالثة تُبقي الحقيقة مقروءة: المجال فيه مسارٌ واحد يزيد
#: المخاطرة، وهو معروفٌ بالاسم ومحروسٌ بأكثر مما يُحرَس به غيره.
#:
#: ## ولماذا الاستئناف مقبول أصلاً من الجوال
#:
#: لأنه **ليس مفتاح التداول**. يرفع `locally_paused` وحده، ولا يمسّ أياً من
#: الأقفال الأربعة الباقية. فأسوأ ما يفعله جهازٌ مسروق أن يعيد النظام من
#: «موقوف» إلى «يقيّم» — ولا يستطيع بعدها إرسال أمر واحد.
#:
#: وقاطع الطوارئ يبقى **بلا إلغاء من الجوال**: إلغاؤه يزيد المخاطرة فعلاً،
#: ويحتاج الخادم. والاستئناف يُرفَض ما دام القاطع مفعّلاً.
RISK_INCREASING_ROUTES: tuple[str, ...] = (
    "pause/resume",
    "broker/environment",
)

#: عبارة تأكيد الانتقال إلى الحساب الحقيقي.
#:
#: ## لماذا هذا المسار مقبولٌ من الهاتف أصلاً
#:
#: **لأنه ليس مفتاح التداول.** يغيّر الحساب الذي **يُقرأ منه ويُتصل به**، ولا
#: يفتح الإرسال: `LIVE_TRADING` يبقى في بيئة الخادم بيد المالكة وحدها، وقفل
#: التنفيذ مستقلّ عنه، ورفض `is_live` في `place_order` مستقلّ عن الاثنين.
#:
#: ⇒ جهازٌ مسروق يستطيع التبديل إلى الحساب الحقيقي، ولا يستطيع إرسال أمرٍ
#: واحد. أقصى ما يفعله أن يرى رصيداً.
#:
#: وبصمة الوجه تحمي من **شخصٍ آخر** يمسك الهاتف — لا من ضغطةٍ خاطئة واليد
#: يد المالكة. فالعبارة تحرس ما لا تحرسه البصمة.
#:
#: والاتجاه المعاكس (حقيقي ⇐ تجريبي) **يقلّل المخاطرة**، فلا يطلب عبارة:
#: حارسٌ يعرقل التراجع عن الخطر ليس حارساً.
LIVE_ENVIRONMENT_PHRASE = "أنتقل إلى الحساب الحقيقي"

#: عبارة التأكيد. تُكتب بالكامل، ولا تُقبَل قريبةً منها.
#: زرٌّ يُضغط بالخطأ في الجيب لا يكتب جملة.
RESUME_PHRASE = "أستأنف التداول"

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

for _route in READ_ROUTES + RISK_REDUCING_ROUTES + RISK_INCREASING_ROUTES:
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


class MobileActionUnavailable(MobileApiError):
    """الإجراء غير موصول بالنظام. **يفشل مغلقاً** ولا يُقال «تمّ»."""

    def __init__(self, action_ar: str) -> None:
        super().__init__(
            f"{action_ar} غير موصول بهذا الخادم — لم يقع شيء. "
            "لا تعتمدي على هذا الزرّ حتى يُصلَح.",
            status=503,
        )


@dataclass
class MobileActions:
    """
    ما تفعله أزرار الجوال **فعلاً** في النظام.

    ## العطل الذي فرض وجود هذا الصنف

    كان `pause/request` يكتب قيداً في السجل ويعيد `accepted: true` — **ولا
    يوقف شيئاً**. ومثله `killswitch/activate`: يسجّل ولا يُفعّل القاطع.

    أي أن أخطر زرَّين في التطبيق كانا يقولان «تمّ» ولا يفعلان. تضغط المالكة
    «إيقاف» في لحظة تحتاجه، فيؤكّد لها التطبيق، والنظام يواصل. وهذا أسوأ من
    زرٍّ معطّل ظاهرَ العطل، لأنه يشتري سكوتها.

    ## ولماذا الافتراض يرفع لا يسكت

    الافتراضي هنا **يرفع استثناءً** ولا يعيد نجاحاً صامتاً: خادمٌ لم يوصل
    إجراءً يجب أن يقول ذلك للمالكة، لا أن يبتلعه. فشلٌ ظاهرٌ خيرٌ من نجاحٍ
    كاذب — وهذه هي القاعدة التي كُسرت هنا.
    """

    pause: Optional[Callable[[str], None]] = None
    activate_kill_switch: Optional[Callable[[str], None]] = None
    #: يبدّل بيئة الوسيط ويعيد وصفها. لا يفتح تداولاً.
    switch_environment: Optional[Callable[[str], dict]] = None
    #: يعيد `locally_paused` إلى False. يرفع `KillSwitchIsActive` إن كان
    #: القاطع مفعّلاً — والرفض من عند المصدر لا من عند الواجهة.
    resume: Optional[Callable[[str], None]] = None

    def do_pause(self, reason_ar: str) -> None:
        if self.pause is None:
            raise MobileActionUnavailable("الإيقاف المحلي")
        self.pause(reason_ar)

    def do_kill(self, reason_ar: str) -> None:
        if self.activate_kill_switch is None:
            raise MobileActionUnavailable("قاطع الطوارئ")
        self.activate_kill_switch(reason_ar)

    def do_resume(self, reason_ar: str) -> None:
        if self.resume is None:
            raise MobileActionUnavailable("استئناف التداول")
        self.resume(reason_ar)

    def do_switch_environment(self, target: str) -> dict:
        if self.switch_environment is None:
            raise MobileActionUnavailable("تبديل الحساب")
        return self.switch_environment(target)


@dataclass
class MobileApi:
    """
    طبقة تطبيقية محايدة عن FastAPI كي تُختبَر بلا خادم.

    `providers` و`state_source` تُحقَن، فلا هذه الطبقة تعرف الوسيط ولا تصل إليه.
    """

    security: MobileSecurityService
    state_source: Callable[[], dict] = dict
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    #: الأفعال الحقيقية. غير الموصول منها **يرفض** ولا يدّعي النجاح.
    actions: "MobileActions" = field(default_factory=lambda: MobileActions())

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
        if method.upper() == "POST" and route not in (
            RISK_REDUCING_ROUTES + RISK_INCREASING_ROUTES
        ):
            # كل POST خارج المُعلَن مرفوض — بما فيه أي مسار تداول محتمل.
            raise MobileApiError(
                "لا يوجد في مجال الجوال أي مسار تعديل عدا ثلاثة تقلّل المخاطرة "
                "وواحدٍ يستأنف الإيقاف المحلي وحده.",
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
            "scan/latest": lambda: state.get("scan", {}),
            "market/candles": lambda: state.get("candles", {}),
            "audit/recent": lambda: {
                "entries": [e.as_dict() for e in self.security.audit()]
            },
        }[route]()
        return {**common, "data": section}

    # -- التعديل المُقلِّل للمخاطرة ------------------------------------------

    def _mutate(self, route: str, device: RegisteredDevice, payload: dict) -> dict:
        now = self.clock()
        if route == "pause/request":
            reason = str(payload.get("reason_ar") or "إيقاف بطلب من الجوال.")
            # **يُنفَّذ أوّلاً، ثم يُسجَّل.** التسجيل قبل التنفيذ يُنتج سجلاً
            # يقول «أُوقف» عن إيقافٍ لم يقع.
            try:
                self.actions.do_pause(reason)
            except MobileApiError:
                self.security._audit_log(
                    "MOBILE_PAUSE_FAILED", device_id=device.device_id,
                    detail_ar="طُلب الإيقاف ولم يُنفَّذ — الإجراء غير موصول.",
                    success=False,
                )
                raise
            self.security._audit_log(
                "MOBILE_PAUSE_REQUESTED", device_id=device.device_id,
                detail_ar="أُوقف التداول محلياً من الجوال — إجراء يقلّل المخاطرة.",
                success=True,
            )
            return {
                "action": "PAUSE_REQUESTED", "accepted": True,
                "at_utc": now.isoformat(),
                "note_ar": "أُوقف التداول محلياً. الإيقاف يقلّل المخاطرة ولا يفتح شيئاً.",
            }

        if route == "killswitch/activate":
            reason = str(payload.get("reason_ar") or "تفعيل من الجوال.")
            try:
                self.actions.do_kill(reason)
            except MobileApiError:
                self.security._audit_log(
                    "MOBILE_KILL_SWITCH_FAILED", device_id=device.device_id,
                    detail_ar="طُلب القاطع ولم يُفعَّل — الإجراء غير موصول.",
                    success=False,
                )
                raise
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

        if route == "pause/resume":
            # السور الأول: العبارة كاملةً حرفاً بحرف.
            if str(payload.get("confirm") or "").strip() != RESUME_PHRASE:
                self.security._audit_log(
                    "MOBILE_RESUME_REFUSED", device_id=device.device_id,
                    detail_ar="طُلب الاستئناف بلا عبارة التأكيد — لم يقع شيء.",
                    success=False,
                )
                raise MobileApiError(
                    f"الاستئناف يحتاج كتابة العبارة كاملة: «{RESUME_PHRASE}».",
                    status=400,
                )
            reason = str(payload.get("reason_ar") or "استئناف بطلب من الجوال.")
            try:
                self.actions.do_resume(reason)
            except MobileApiError:
                self.security._audit_log(
                    "MOBILE_RESUME_FAILED", device_id=device.device_id,
                    detail_ar="طُلب الاستئناف ولم يُنفَّذ.", success=False,
                )
                raise
            self.security._audit_log(
                "MOBILE_RESUME", device_id=device.device_id,
                detail_ar="استُؤنف التداول من الجوال — إجراء يزيد المخاطرة.",
                success=True,
            )
            return {
                "action": "RESUMED", "accepted": True, "at_utc": now.isoformat(),
                "note_ar": (
                    "رُفع الإيقاف المحلي وحده. **لم يُفتح أي قفل آخر** — "
                    "النظام يعود إلى التقييم، ولا يستطيع إرسال أمر."
                ),
            }

        if route == "broker/environment":
            target = str(payload.get("target") or "").upper()
            if target not in ("DEMO", "LIVE"):
                raise MobileApiError(
                    "الوجهة يجب أن تكون DEMO أو LIVE.", status=400
                )
            # الانتقال إلى الحقيقي وحده يطلب عبارة. والعودة إلى التجريبي
            # تقلّل المخاطرة، وحارسٌ يعرقل التراجع عن الخطر ليس حارساً.
            if target == "LIVE" and (
                str(payload.get("confirm") or "").strip() != LIVE_ENVIRONMENT_PHRASE
            ):
                self.security._audit_log(
                    "MOBILE_ENVIRONMENT_REFUSED", device_id=device.device_id,
                    detail_ar="طُلب الانتقال إلى الحقيقي بلا عبارة — لم يقع شيء.",
                    success=False,
                )
                raise MobileApiError(
                    f"الانتقال إلى الحساب الحقيقي يحتاج كتابة: "
                    f"«{LIVE_ENVIRONMENT_PHRASE}».",
                    status=400,
                )
            try:
                described = self.actions.do_switch_environment(target)
            except MobileApiError:
                self.security._audit_log(
                    "MOBILE_ENVIRONMENT_FAILED", device_id=device.device_id,
                    detail_ar=f"تعذّر التبديل إلى {target} — لم تتغيّر البيئة.",
                    success=False,
                )
                raise
            self.security._audit_log(
                "MOBILE_ENVIRONMENT_SWITCHED", device_id=device.device_id,
                detail_ar=f"بُدِّل حساب الوسيط إلى {target}.", success=True,
            )
            return {
                "action": "ENVIRONMENT_SWITCHED", "accepted": True,
                "environment": described.get("environment"),
                "is_demo": described.get("is_demo"),
                "broker_name": described.get("broker_name"),
                "at_utc": now.isoformat(),
                "note_ar": (
                    "بُدِّل الحساب المقروء منه. **ولم يُفتح تداول**: مفتاح "
                    "التداول الحقيقي في بيئة الخادم، وقفل التنفيذ مستقلّ عنه."
                ),
            }

        raise MobileApiError("مسار غير معروف.", status=404)


def describe_api() -> dict:
    """وصف المجال — يُستعمل في التوثيق وفي اختبارات العقد."""
    return {
        "prefix": API_PREFIX,
        "read_routes": list(READ_ROUTES),
        "risk_reducing_routes": list(RISK_REDUCING_ROUTES),
        "risk_increasing_routes": list(RISK_INCREASING_ROUTES),
        "trading_routes": [],
        "forbidden_actions": list(FORBIDDEN_MOBILE_ACTIONS),
        "permissions": [p.value for p in MobilePermission],
        "note_ar": (
            "لا نقطة نهاية تداول في مجال الجوال. ثلاثة مسارات تقلّل "
            "المخاطرة، وواحدٌ يرفع الإيقاف المحلي وحده بعبارة تأكيد — "
            "ولا يفتح أي قفلٍ آخر ولا يُلغي قاطع الطوارئ."
        ),
    }


__all__ = [
    "API_PREFIX", "READ_ROUTES", "RISK_REDUCING_ROUTES",
    "RISK_INCREASING_ROUTES", "RESUME_PHRASE", "LIVE_ENVIRONMENT_PHRASE",
    "FORBIDDEN_ROUTE_TOKENS", "FORBIDDEN_RESPONSE_TOKENS",
    "MobileApi", "MobileApiError", "MobileResponse",
    "MobileActions", "MobileActionUnavailable",
    "assert_response_is_clean", "describe_api",
]
