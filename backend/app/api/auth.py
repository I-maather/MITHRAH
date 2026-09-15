"""
بوابةُ مجال `/api` — **حارسٌ على الطبقة لا على كل مسار**.

## العيب الذي أُغلق

طبقةُ الجوال بُنيت بحرصٍ نادر: رمزٌ قصير العمر، وتسجيلٌ بعاملين، وقائمةٌ
مغلقة من ثلاثة مسارات **كلّها تُقلّل المخاطرة**، واختباران يمنعان إضافة
رابعٍ بلا كسرِ عقدٍ في طرفين. وأسوأ ما يفعله من يسرق الجهاز — كما يقول
الدليل — «أن يوقف التداول».

وفي الوقت نفسه كان المجال `/api` مفتوحاً بلا أيّ مصادقة، ومنشوراً على
الشبكة الخاصة عبر `tailscale serve`، وفيه:

    POST /api/trading/resume             ← يستأنف التداول
    POST /api/risk/kill-switch/reset     ← يُطفئ قاطع الطوارئ
    POST /api/profiles/confirm-upgrade   ← يرفع ملف المخاطرة

ثلاثةٌ **تزيد المخاطرة**، بلا رمزٍ ولا جهازٍ مسجَّل. فمن يملك جهازاً على
الشبكة الخاصة — أو هاتفاً مسروقاً عليها — يستدعيها بسطر `curl` واحد ويُبطل
كلَّ ما حرسته طبقةُ الجوال. بابٌ محصَّن وإلى جانبه نافذةٌ مفتوحة.

## ولماذا حارسٌ على الطبقة

لأنّ الحارس على كل مسارٍ يُنسى عند إضافة المسار الحادي والعشرين. والوسيط
يحرس ما لم يُكتَب بعد، ويحرسه افتراضاً: المسارُ الجديد **محميٌّ حتى يُستثنى
صراحةً**، لا العكس.

## ولماذا لا يُستثنى «المحلي»

الفحصُ بأنّ الطلب جاء من `127.0.0.1` حارسٌ **زائف** هنا، والمشروع تعلّمه
مرّةً من قبل (انظر `docs/MOBILE_PAIRING_RUNBOOK.md` §٣): الوسيط يعيد
التوجيه إلى الحلقة المحلية، فيبدو كلُّ طلبٍ قادماً منها — بما فيه طلبُ
جهازٍ آخر. فلا استثناءَ للمصدر إطلاقاً؛ حتى سكربتاتنا تحمل الرمز.

## والفشل مغلق

لا رمزَ مضبوطاً ⇒ لا يُفتَح المجال «تسهيلاً»، بل يُغلَق بـ503 ورسالةٍ
تقول ما ينقص. مجالٌ مفتوحٌ لأنّ الإعداد ناقص هو أسوأ الحالتين: يعمل، فلا
يلاحظه أحد.
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

_LOG = logging.getLogger(__name__)

#: اسمُ السرّ في مخزن الأسرار (Keychain أو ملف `secrets/*.env` بصلاحيات 600).
API_TOKEN_NAME = "MATHRAH_API_TOKEN"

#: المسارات المعفاة — **قائمةٌ مغلقة ومبرَّرة، لا راحة**.
#:
#: · `/api/mobile/` لها مصادقتها الخاصة (رمزٌ قصير العمر لجهازٍ مسجَّل)،
#:   ووضعُ حارسين متتاليين يعني رمزين على الجوال بلا فائدة.
#: · `/api/health/live` نبضُ حياةٍ لا بيانات فيه: `{"ok": true}` وحدها.
#:   يحتاجه فحصُ الخدمة بعد النشر قبل أن يُقرأ أي سرّ.
#:
#: و`/api/health` الكامل **ليس** منها: فيه حالةُ الوسيط وقاطع الطوارئ
#: والمجدول، وتلك معلوماتٌ عن الحساب.
EXEMPT_PREFIXES: tuple[str, ...] = ("/api/mobile/",)
#: و`/api/health/ops` معه: حياةُ الآلة (كوميت، مدّةُ تشغيل، عمرُ آخر
#: دورةِ قرار) بلا أيّ معلومةٍ عن الحساب — لا وسيط ولا رصيد ولا مركز.
EXEMPT_EXACT: frozenset[str] = frozenset(
    {"/api/health/live", "/api/health/ops"}
)

#: ما ليس تحت `/api` أصلاً لا يعني هذا الحارس (`/docs` مثلاً معطّلة إنتاجاً).
GUARDED_PREFIX = "/api"


def _configured_token(state) -> Optional[str]:
    """
    يقرأ الرمز من مخزن الأسرار. `None` تعني «غير مضبوط» لا «فارغ».

    ولا يُقرأ من متغيّرات البيئة افتراضاً — القاعدة نفسها التي تحكم بقية
    الأسرار في هذا المشروع.
    """
    provider = getattr(state, "secrets", None)
    if provider is None:
        return None
    try:
        value = provider.get(API_TOKEN_NAME)
    except Exception:  # noqa: BLE001 — الغياب حالةٌ عادية، لا عطل
        return None
    value = (value or "").strip()
    return value or None


def _presented(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def is_exempt(path: str) -> bool:
    if path in EXEMPT_EXACT:
        return True
    return any(path.startswith(p) for p in EXEMPT_PREFIXES)


def install(app, *, state_getter) -> None:
    """
    يركّب الحارس. `state_getter` يعيد حالة النظام (للوصول إلى مخزن الأسرار).
    """

    @app.middleware("http")
    async def _guard(request: Request, call_next):  # noqa: ANN202
        path = request.url.path
        if not path.startswith(GUARDED_PREFIX) or is_exempt(path):
            return await call_next(request)

        try:
            token = _configured_token(state_getter())
        except Exception:  # noqa: BLE001
            token = None

        if token is None:
            # **فشلٌ مغلق.** لا يُفتَح المجال لأنّ الإعداد ناقص.
            _LOG.warning("طلبٌ على %s ولا رمزَ مضبوط — رُفض.", path)
            return JSONResponse(
                status_code=503,
                content={
                    "error": "API_TOKEN_NOT_CONFIGURED",
                    "reason_ar": (
                        "رمزُ مجال الواجهة غير مضبوط، فالمجال مغلق. "
                        "اضبطيه بـ scripts/configure_api_token.sh — "
                        "ولا يُفتَح المجال بلا رمز."
                    ),
                },
            )

        presented = _presented(request)
        if presented is None or not hmac.compare_digest(presented, token):
            # المقارنة ثابتةُ الزمن: مقارنةٌ عادية تُسرّب طولَ الرمز وبادئته
            # لمن يقيس زمن الردّ.
            return JSONResponse(
                status_code=401,
                content={
                    "error": "UNAUTHORIZED",
                    "reason_ar": "رمزٌ غائب أو غير صحيح — لا قراءة ولا تغيير.",
                },
            )

        return await call_next(request)
