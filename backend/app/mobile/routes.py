"""
مسارات الجوال في FastAPI — الوصلة التي كانت مفقودة.

## ما كان ناقصاً

`MobileApi` و`MobileSecurityService` كُتبتا واختُبرتا في معلم 0.4.0، ثم
**لم تُركَّبا في الخادم**. فلم يكن تحت `/api/mobile/v1/` مسارٌ واحد، وكان
التطبيق يعرض «لا جهاز مسجَّل» بحقّ: لا مسار تسجيل يعمل.

## ثلاث طبقات، وحدودها

    التسجيل      لا يحتاج رمزاً  — يستهلك تحدّياً وُلّد على الخادم
    التجديد      يحتاج رمز تجديد — يُدوَّر إجبارياً عند كل استعمال
    القراءة والتقليل  تحتاج رمز وصول — تمرّ كلها عبر `MobileApi.handle`

**ولا مسار رابع.** كل ما تحت المجال يُوجَّه إلى `MobileApi`، وهي ترفض أي
`POST` خارج الثلاثة المُقلِّلة للمخاطرة. فإضافة مسار تنفيذ هنا تتطلب تعديل
طبقتين وكسر اختبارَي عقد — لا سطراً واحداً في لحظة غفلة.

## الأخطاء تفشل مغلقة

`MobileApiError` تُترجَم إلى رمز الحالة الذي تحمله، ورسالتها عربية بلا
تفاصيل تقنية. وأي استثناء آخر يصير **500 برسالة ثابتة**: لا نصّ استثناء
يُعاد إلى الجوال، لأن نصوص الاستثناءات تسرّب مسارات وأسماء حقول.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .api import API_PREFIX, MobileApi, MobileApiError, describe_api
from .security import MobileSecurityService

router = APIRouter(prefix=API_PREFIX, tags=["mobile"])


def _bearer(authorization: Optional[str]) -> Optional[str]:
    """
    يستخرج الرمز من ترويسة `Authorization`.

    الترويسة تُقرأ **حصراً** — لا يُقبل رمز في مسار الطلب ولا في معاملاته،
    لأن الأول يُسجَّل في سجلّات الوسطاء والثاني يظهر في `Referer`.
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


# ---------------------------------------------------------------------------
# الأشكال الواردة — مُقيَّدة الطول عمداً
# ---------------------------------------------------------------------------

class EnrollRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    public_identity: str = Field(min_length=8, max_length=512)
    device_name: str = Field(min_length=1, max_length=64)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class PushTokenRequest(BaseModel):
    apns_token: str = Field(min_length=1, max_length=512)


class MobileRuntime:
    """
    يجمع الخدمة الأمنية وطبقة التطبيق في كائن واحد يُحقَن في المسارات.

    يُبنى مرة واحدة عند إقلاع الخادم. `state_source` يُحقَن كي تبقى طبقة
    الجوال **جاهلة بالوسيط** — لا تستورده ولا تصل إليه.
    """

    def __init__(
        self, *, security: MobileSecurityService,
        state_source: Callable[[], dict] = dict,
    ) -> None:
        self.security = security
        self.api = MobileApi(security=security, state_source=state_source)


_runtime: Optional[MobileRuntime] = None


def set_runtime(runtime: MobileRuntime) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> MobileRuntime:
    if _runtime is None:
        raise MobileApiError("طبقة الجوال غير مُهيّأة على الخادم.", status=503)
    return _runtime


def _error(exc: MobileApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error_ar": str(exc)})


# ---------------------------------------------------------------------------
# التسجيل
# ---------------------------------------------------------------------------

@router.post("/enroll/complete")
def enroll_complete(body: EnrollRequest) -> Any:
    """
    يستهلك التحدّي ويصدر أول زوج رموز.

    **لا يحتاج مصادقة** — ولا يمكن أن يحتاجها: الجهاز ليس له رمز بعد.
    وحارسه أن التحدّي وُلّد على الخادم بأمر، وعمره دقيقتان، ويُستهلَك مرة.
    """
    try:
        runtime = get_runtime()
        device = runtime.security.complete_enrollment(
            challenge_id=body.challenge_id,
            public_identity=body.public_identity,
            device_name=body.device_name,
        )
        if device is None:
            raise MobileApiError(
                "تحدّي التسجيل غير صالح أو منتهٍ أو مُستهلَك. ولّدي رمزاً جديداً.",
                status=401,
            )
        issued = runtime.security.issue_tokens(device.device_id)
        if issued is None:  # pragma: no cover - الجهاز أُنشئ نشطاً للتوّ
            raise MobileApiError("تعذّر إصدار رموز الجلسة.", status=500)
        access, refresh = issued
        return {
            "device": device.as_dict(),
            "access_token": access.token,
            "access_expires_utc": access.expires_utc.isoformat(),
            "refresh_token": refresh.token,
            "refresh_expires_utc": refresh.expires_utc.isoformat(),
            "authorises_execution": False,
        }
    except MobileApiError as exc:
        return _error(exc)


@router.post("/token/refresh")
def token_refresh(body: RefreshRequest) -> Any:
    """
    تدوير إجباري: الرمز المُقدَّم يُبطَل، ويُصدر زوج جديد.

    فشلُه **لا يفرّق** بين منتهٍ ومسروق في الرد — التفريق يُسجَّل في التدقيق
    ولا يُعاد إلى المتصل، كي لا يصير الردّ أداة استكشاف.
    """
    try:
        runtime = get_runtime()
        rotated = runtime.security.rotate_refresh(body.refresh_token)
        if rotated is None:
            raise MobileApiError("رمز تجديد غير صالح. أعيدي تسجيل الجهاز.", status=401)
        access, refresh = rotated
        return {
            "access_token": access.token,
            "access_expires_utc": access.expires_utc.isoformat(),
            "refresh_token": refresh.token,
            "refresh_expires_utc": refresh.expires_utc.isoformat(),
            "authorises_execution": False,
        }
    except MobileApiError as exc:
        return _error(exc)


@router.post("/push/register")
def push_register(
    body: PushTokenRequest, authorization: Optional[str] = Header(default=None)
) -> Any:
    """يسجّل رمز إشعارات. **لا يُعاد الرمز في الاستجابة ولا يُسجَّل نصّه.**"""
    try:
        runtime = get_runtime()
        device = runtime.security.authenticate(_bearer(authorization) or "")
        if device is None:
            raise MobileApiError("رمز وصول غير صالح.", status=401)
        ok = runtime.security.register_push_token(device.device_id, body.apns_token)
        return {"registered": ok, "has_push_token": ok}
    except MobileApiError as exc:
        return _error(exc)


# ---------------------------------------------------------------------------
# وصف المجال — بلا مصادقة عمداً: لا يحوي بيانات، ويوثّق حدود الإصدار
# ---------------------------------------------------------------------------

@router.get("/describe")
def describe() -> Any:
    return describe_api()


# ---------------------------------------------------------------------------
# كل ما تبقّى يمرّ عبر MobileApi
# ---------------------------------------------------------------------------

@router.get("/{route:path}")
def mobile_read(
    route: str, authorization: Optional[str] = Header(default=None)
) -> Any:
    try:
        runtime = get_runtime()
        result = runtime.api.handle("GET", route, token=_bearer(authorization))
        return result.body
    except MobileApiError as exc:
        return _error(exc)


@router.post("/{route:path}")
async def mobile_mutate(
    route: str, request: Request, authorization: Optional[str] = Header(default=None)
) -> Any:
    try:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        runtime = get_runtime()
        result = runtime.api.handle(
            "POST", route, token=_bearer(authorization), payload=payload
        )
        return result.body
    except MobileApiError as exc:
        return _error(exc)


__all__ = ["router", "MobileRuntime", "set_runtime", "get_runtime"]
