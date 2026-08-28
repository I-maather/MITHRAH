"""
LIVE READ-ONLY ALLOWLIST — الحارس الأدنى، على مستوى HTTP نفسه.

هذا الملف هو **الحد الحقيقي**. لا يعتمد على قفل محوّل عالي المستوى ولا على
انضباط المستدعي: كل طلب يمر من هنا يُطبَّع ثم يُقارَن بقائمة بيضاء دقيقة
(الميثود + المسار)، ثم بقائمة سوداء صريحة، وإلا يُرفض قبل مغادرته العملية.

## الطريقة قبل المسار

    GET     → مسموح فقط لما في القائمة البيضاء
    POST    → مسموح **فقط** لـ/api/v1/session (المصادقة)، وبعدد محدود
    PUT     → مرفوض دائماً وبلا استثناء
    PATCH   → مرفوض دائماً وبلا استثناء
    DELETE  → مرفوض دائماً وبلا استثناء
    غير ذلك → مرفوض

## لماذا التطبيع قبل المقارنة

المقارنة النصية الساذجة تُخدَع بسهولة:

    /api/v1/positions                    ← يُرفض
    /api/v1/%70ositions                  ← ترميز مئوي
    /api/v1/%2570ositions                ← ترميز مزدوج
    /api/v1/markets/../positions         ← مقاطع نسبية
    /api/v1//positions                   ← شرطات مكرّرة
    /api/v1/positions/                   ← شرطة ذيلية
    /api/v1/positions?x=1                ← سلسلة استعلام
    /api/v1/POSITIONS                    ← حالة الأحرف
    /api/v1\\positions                   ← شرطة خلفية

كلها تُطبَّع إلى الشكل نفسه هنا قبل أي قرار.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlsplit

#: مضيف الحساب الحقيقي — الوحيد المسموح به لهذا الأمر.
LIVE_HOST = "api-capital.backend-capital.com"
LIVE_BASE_URL = f"https://{LIVE_HOST}"

API_PREFIX = "/api/v1"

# ---------------------------------------------------------------------------
# القائمة البيضاء
# ---------------------------------------------------------------------------

#: مسارات GET ثابتة.
ALLOWED_GET_EXACT: frozenset[str] = frozenset({
    f"{API_PREFIX}/session/encryptionKey",
    f"{API_PREFIX}/session",
    f"{API_PREFIX}/accounts",
    f"{API_PREFIX}/accounts/preferences",
    f"{API_PREFIX}/marketnavigation",
    f"{API_PREFIX}/markets",
})

#: مسارات GET ذات جزء متغيّر. النمط ضيق عمداً: حروف وأرقام وشرطات فقط،
#: فلا يمكن تمرير مقطع مثل `..` أو اسم مسار آخر عبر «الرمز».
ALLOWED_GET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"^{re.escape(API_PREFIX)}/markets/[A-Za-z0-9._-]{{1,64}}$"),
    re.compile(rf"^{re.escape(API_PREFIX)}/prices/[A-Za-z0-9._-]{{1,64}}$"),
    re.compile(rf"^{re.escape(API_PREFIX)}/marketnavigation/[A-Za-z0-9._-]{{1,64}}$"),
)

#: `POST` المسموح الوحيد — المصادقة، ولا شيء غيرها.
ALLOWED_POST_EXACT: frozenset[str] = frozenset({f"{API_PREFIX}/session"})

#: طرق مرفوضة دائماً، بلا استثناء ولا حالة خاصة.
UNCONDITIONALLY_BLOCKED_METHODS: frozenset[str] = frozenset({
    "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT",
})

#: أسماء معاملات الاستعلام المسموح بها. أي معامل آخر يُرفض،
#: كي لا يُهرَّب فعل عبر الاستعلام بدل المسار.
ALLOWED_QUERY_PARAMS: frozenset[str] = frozenset({
    "searchTerm", "epics", "epic", "resolution", "max", "from", "to",
    "nodeId", "limit", "pageSize", "pageNumber",
})

# ---------------------------------------------------------------------------
# القائمة السوداء
# ---------------------------------------------------------------------------

#: مقاطع محظورة صراحةً. تُفحص على المسار **المُطبَّع** وعلى الهدف الخام معاً،
#: بلا حساسية لحالة الأحرف. لا مسار مسموح يحتوي أياً منها — مُختبَر.
BLOCKED_SUBSTRINGS: tuple[str, ...] = (
    "position",       # يغطي positions وposition
    "workingorder",   # يغطي workingorders
    "order",          # أي إنشاء أمر
    "topup",
    "top-up",
    "confirm",        # confirms
    "deposit",
    "withdraw",
    "transfer",
    "leverage",
    "hedg",           # hedging / hedge
    "switch",         # تبديل الحساب
    "close",
    "cancel",
    "amend",
    "update",
    "create",
    "delete",
    "payment",
    "funding",
    "otc",
)


class AllowlistViolation(RuntimeError):
    """رُفض الطلب قبل مغادرته العملية. لا يحمل نص الاستثناء أي سرّ."""


@dataclass(frozen=True)
class NormalizedTarget:
    method: str
    host: str
    path: str                 # مُطبَّع بالكامل
    query_params: tuple[str, ...]
    raw_target: str           # للفحص الإضافي، لا للمقارنة

    @property
    def operation(self) -> tuple[str, str]:
        return (self.method, self.path)


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _decode_fully(text: str, *, rounds: int = 5) -> str:
    """
    يفكّ الترميز المئوي **تكراراً** حتى يستقر، فلا ينجو الترميز المزدوج
    (`%252e` ← `%2e` ← `.`).
    """
    seen = text
    for _ in range(rounds):
        decoded = unquote(seen)
        if decoded == seen:
            return decoded
        seen = decoded
    # لم يستقر بعد عدة جولات ⇒ مدخل عدائي.
    raise AllowlistViolation("مسار مُرمَّز ترميزاً متداخلاً بعمق غير مقبول.")


def _collapse_and_resolve(path: str) -> str:
    """يوحّد الشرطات ويحلّ `.` و`..` بلا الوصول إلى نظام الملفات."""
    path = path.replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")

    out: list[str] = []
    for segment in path.split("/"):
        if segment == "" or segment == ".":
            continue
        if segment == "..":
            if out:
                out.pop()
            continue
        out.append(segment)
    normalized = "/" + "/".join(out)
    return normalized


def normalize(method: str, url: str) -> NormalizedTarget:
    """
    يطبّع الطلب تطبيعاً كاملاً قبل أي مقارنة.
    يرفع `AllowlistViolation` عند أي شكل مشبوه بنيوياً.
    """
    if not isinstance(method, str) or not isinstance(url, str):
        raise AllowlistViolation("طلب بصيغة غير متوقعة.")

    upper = method.strip().upper()
    if not upper or not upper.isalpha():
        raise AllowlistViolation("ميثود غير صالحة.")

    if _CONTROL_CHARS.search(url):
        raise AllowlistViolation("العنوان يحتوي محارف تحكّم.")

    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise AllowlistViolation("لا يُسمح إلا بـHTTPS.")

    host = (parts.hostname or "").lower()
    if parts.port not in (None, 443):
        raise AllowlistViolation("منفذ غير قياسي.")

    decoded_path = _decode_fully(parts.path or "/")
    if _CONTROL_CHARS.search(decoded_path):
        raise AllowlistViolation("المسار يحتوي محارف تحكّم بعد فك الترميز.")

    normalized_path = _collapse_and_resolve(decoded_path)
    if len(normalized_path) > 512:
        raise AllowlistViolation("مسار أطول من الحد المعقول.")

    # الشرطة الذيلية تُزال (عدا الجذر) كي لا يُنشئ `/x/` و`/x` حالتين.
    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path[:-1]

    decoded_query = _decode_fully(parts.query or "")
    params: list[str] = []
    for chunk in decoded_query.split("&"):
        if not chunk:
            continue
        name = chunk.split("=", 1)[0].strip()
        if name:
            params.append(name)

    return NormalizedTarget(
        method=upper,
        host=host,
        path=normalized_path,
        query_params=tuple(params),
        raw_target=f"{parts.path}?{parts.query}" if parts.query else parts.path,
    )


def _assert_no_blocked_substring(target: NormalizedTarget) -> None:
    """
    يُفحص المسار المُطبَّع **والهدف الخام** معاً: الأول يمنع الالتفاف بالترميز،
    والثاني يمنع تمرير فعل محظور في سلسلة الاستعلام.
    """
    haystacks = (
        target.path.lower(),
        _decode_fully(target.raw_target).lower(),
    )
    for needle in BLOCKED_SUBSTRINGS:
        for hay in haystacks:
            if needle in hay:
                raise AllowlistViolation(
                    f"المسار يحتوي مقطعاً محظوراً صراحةً: «{needle}»."
                )


def assert_allowed(method: str, url: str) -> NormalizedTarget:
    """
    البوابة الوحيدة. تعيد الهدف المُطبَّع عند السماح، وترفع عند المنع.

    الترتيب مقصود: الطرق المرفوضة دائماً تُرفض **قبل** أي نظر في المسار،
    فلا يمكن لمسار مسموح أن يُمرّر `DELETE`.
    """
    target = normalize(method, url)

    if target.host != LIVE_HOST:
        raise AllowlistViolation(
            "مضيف غير مضيف الحساب الحقيقي المصرَّح به لهذا الأمر."
        )

    if target.method in UNCONDITIONALLY_BLOCKED_METHODS:
        raise AllowlistViolation(
            f"الطريقة {target.method} مرفوضة دائماً في وضع القراءة فقط."
        )

    _assert_no_blocked_substring(target)

    for name in target.query_params:
        if name not in ALLOWED_QUERY_PARAMS:
            raise AllowlistViolation(f"معامل استعلام غير مسموح: «{name}».")

    if target.method == "GET":
        if target.path in ALLOWED_GET_EXACT:
            return target
        for pattern in ALLOWED_GET_PATTERNS:
            if pattern.match(target.path):
                return target
        raise AllowlistViolation(f"مسار GET خارج القائمة البيضاء: {target.path}")

    if target.method == "POST":
        if target.path in ALLOWED_POST_EXACT:
            return target
        raise AllowlistViolation(
            "الـPOST الوحيد المسموح هو المصادقة على /api/v1/session."
        )

    raise AllowlistViolation(f"الطريقة {target.method} غير مسموح بها.")


def describe_allowlist() -> dict:
    """وصف قابل للطباعة والاختبار — يُعرض في التقرير."""
    return {
        "host": LIVE_HOST,
        "get_exact": sorted(ALLOWED_GET_EXACT),
        "get_patterns": [p.pattern for p in ALLOWED_GET_PATTERNS],
        "post_exact": sorted(ALLOWED_POST_EXACT),
        "blocked_methods": sorted(UNCONDITIONALLY_BLOCKED_METHODS),
        "blocked_substrings": list(BLOCKED_SUBSTRINGS),
        "allowed_query_params": sorted(ALLOWED_QUERY_PARAMS),
    }


__all__ = [
    "LIVE_HOST",
    "LIVE_BASE_URL",
    "ALLOWED_GET_EXACT",
    "ALLOWED_GET_PATTERNS",
    "ALLOWED_POST_EXACT",
    "UNCONDITIONALLY_BLOCKED_METHODS",
    "ALLOWED_QUERY_PARAMS",
    "BLOCKED_SUBSTRINGS",
    "AllowlistViolation",
    "NormalizedTarget",
    "normalize",
    "assert_allowed",
    "describe_allowlist",
]
