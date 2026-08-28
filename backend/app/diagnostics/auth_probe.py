"""
DEMO AUTH PROBE — تشخيص مصادقة واحد، آمن، ومحدود.

يقارن **وضعَي المصادقة الرسميين** لدى Capital.com على `POST /session`:

    1. encryptedPassword=true   — كلمة مرور المفتاح مشفّرة بـRSA/PKCS1
    2. encryptedPassword=false  — كلمة مرور المفتاح كما هي عبر HTTPS

الغرض: تحديد **أي الوضعين يقبله حسابك**، لا أكثر.

## الحدود المفروضة بالكود

  * بيئة **Demo** حصراً — عنوان Live مرفوض قبل أي إرسال، ولا تراجع إليه أبداً.
  * **محاولة واحدة كحد أقصى لكل وضع** — لا حلقة، لا إعادة محاولة، لا تصعيد.
  * **`POST /session` فقط** (مع `GET /session/encryptionKey` اللازم للوضع الأول).
    أي مسار آخر يُرفض بقائمة بيضاء صريحة ويُفشل التشخيص كله.
  * **لا مركز ولا أمر ولا تفضيل ولا شحن رصيد** — لا يستورد هذا الملف المحوّل أصلاً.
  * **لا يُسجَّل ولا يُطبع**: المعرّف · كلمة المرور · مفتاح API · الحمولة المشفّرة ·
    `CST` · `X-SECURITY-TOKEN`.
  * التقرير يحمل **رمز الحالة HTTP ورمز خطأ Capital المُنقَّى فقط**.
  * **تُنسى رموز الجلسة فوراً** إن وردت — لا تُخزَّن ولا تُعاد ولا تُكتب.

## لماذا لا يُعاد استعمال `CapitalSession.ensure_session()`

لأنها مصمَّمة للتشغيل: تجدّد الجلسة، وتعيد المحاولة، وتُقفل ذاتياً بعد ثلاث
محاولات. ذلك سلوك صحيح للتشغيل و**خاطئ للتشخيص**، إذ قد يُنتج أكثر من محاولة
لكل وضع. هذا الملف يبني الطلب بنفسه، مرة واحدة لكل وضع، وينتهي.
"""
from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from ..clock import format_riyadh, now_utc
from ..secretstore.provider import (
    CAPITAL_API_KEY,
    CAPITAL_API_PASSWORD,
    CAPITAL_IDENTIFIER,
    SecretProvider,
)
from ..secretstore.redaction import REGISTRY, redact
from ..brokers.capital.endpoints import (
    DEMO_BASE_URL,
    PATH_ENCRYPTION_KEY,
    PATH_SESSION,
    CapitalEnvironment,
)
from ..brokers.capital.errors import CapitalAuthError
from ..brokers.capital.safety import LIVE_API_ENABLED, assert_environment_allowed
from ..brokers.capital.transport import ApiResponse, Transport

#: المسارات الوحيدة المسموح بها في هذا التشخيص. أي غيرها ⇒ انتهاك.
ALLOWED_OPERATIONS: frozenset[tuple[str, str]] = frozenset({
    ("GET", PATH_ENCRYPTION_KEY),
    ("POST", PATH_SESSION),
})

#: حد صارم: محاولة مصادقة واحدة لكل وضع، ولا أكثر في عمر التشغيلة.
MAX_ATTEMPTS_PER_MODE = 1

#: رمز خطأ Capital مقبول للعرض فقط إن طابق هذا النمط الضيق.
#: أي نص حر من الخادم لا يُعرض إطلاقاً — قد يحمل ما لا نتوقعه.
_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class ProbeViolation(RuntimeError):
    """رُفعت لأن التشخيص لمس ما لا يجوز — يُفشل التقرير كله."""


class AuthMode(str, Enum):
    ENCRYPTED = "encryptedPassword=true"
    PLAINTEXT = "encryptedPassword=false"


MODE_NAME_AR: dict[AuthMode, str] = {
    AuthMode.ENCRYPTED: "كلمة مرور مشفّرة (RSA/PKCS1)",
    AuthMode.PLAINTEXT: "كلمة مرور المفتاح كما هي عبر HTTPS",
}


#: تفسيرات حتمية لرموز خطأ Capital المعروفة. لا تخمين ولا اختراع:
#: أي رمز غير مذكور هنا يُعرض كما ورد بلا تفسير.
ERROR_HINTS_AR: dict[str, str] = {
    "error.invalid.details": (
        "الوسيط يرفض تركيبة (المعرّف + كلمة المرور). في حسابات Google Sign-In "
        "هذا شائع حين تكون كلمة المرور المستعملة ليست كلمة المرور المخصّصة "
        "للمفتاح، أو حين يكون المفتاح من بيئة أخرى."
    ),
    "error.invalid.api.key": "المفتاح غير صالح لهذه البيئة أو غير مفعّل.",
    "error.null.api.key": "لم تصل ترويسة X-CAP-API-KEY.",
    "error.invalid.api.key.expired": "المفتاح منتهي الصلاحية.",
    "error.too-many.requests": "تجاوز حد الطلبات — انتظري ثم أعيدي مرة واحدة.",
    "error.invalid.api.key.disabled": "المفتاح موقوف من صفحة API.",
}


@dataclass(frozen=True)
class ProbeAttempt:
    """
    نتيجة محاولة واحدة. **لا تحمل أي قيمة سرّية بالتصميم**:
    لا حقل للمعرّف ولا لكلمة المرور ولا للحمولة ولا للرموز.
    """

    mode: AuthMode
    attempted: bool
    http_status: Optional[int]
    error_code: Optional[str]          # مُنقّى، أو None
    succeeded: bool
    note_ar: str

    def as_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "mode_ar": MODE_NAME_AR[self.mode],
            "attempted": self.attempted,
            "http_status": self.http_status,
            "error_code": self.error_code,
            "succeeded": self.succeeded,
            "note_ar": self.note_ar,
        }


@dataclass(frozen=True)
class ProbeReport:
    environment: str
    base_url: str
    generated_at_utc: datetime
    generated_at_riyadh: str
    encryption_key_available: bool
    attempts: tuple[ProbeAttempt, ...]
    guidance_ar: tuple[str, ...]
    operations_sent: tuple[tuple[str, str], ...]
    tokens_retained: bool               # يجب أن تبقى False دائماً

    @property
    def working_mode(self) -> Optional[AuthMode]:
        for a in self.attempts:
            if a.succeeded:
                return a.mode
        return None

    def as_dict(self) -> dict:
        return {
            "environment": self.environment,
            "base_url": self.base_url,
            "generated_at_utc": self.generated_at_utc.isoformat(),
            "generated_at_riyadh": self.generated_at_riyadh,
            "encryption_key_available": self.encryption_key_available,
            "attempts": [a.as_dict() for a in self.attempts],
            "working_mode": self.working_mode.value if self.working_mode else None,
            "guidance_ar": list(self.guidance_ar),
            "operations_sent": [list(op) for op in self.operations_sent],
            "tokens_retained": self.tokens_retained,
        }


# ---------------------------------------------------------------------------
# أدوات داخلية
# ---------------------------------------------------------------------------

def _sanitize_error_code(body: Any) -> Optional[str]:
    """
    يستخرج رمز خطأ Capital **فقط** إن كان نمطاً ضيقاً معروف الشكل.
    أي نص حر من الخادم يُهمَل تماماً — لا يُعرض ولا يُسجَّل.
    """
    if not isinstance(body, dict):
        return None
    raw = body.get("errorCode")
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not _SAFE_ERROR_CODE.match(candidate):
        return None
    # حزام إضافي: لو تسلّل سرّ إلى الرمز لأي سبب، يُحجب.
    cleaned = redact(candidate)
    return cleaned if _SAFE_ERROR_CODE.match(cleaned) else None


def _forget_tokens(response: ApiResponse) -> bool:
    """
    ينسى أي رموز جلسة وردت، فوراً وبلا تخزين.
    يعيد True إن كانت الاستجابة تحمل رموزاً (للتقرير فقط، لا للقيمة).
    """
    headers = response.headers or {}
    lowered = {k.lower(): v for k, v in headers.items()}
    cst = lowered.get("cst")
    token = lowered.get("x-security-token")
    had_tokens = bool(cst or token)
    # تُسجَّل في سجل الحجب لحظةً ثم تُنسى، كي لا تظهر في أي أثر لاحق.
    for value in (cst, token):
        if value:
            REGISTRY.register(value)
            REGISTRY.forget(value)
    return had_tokens


def _encrypt(password: str, key_b64: str, timestamp: int) -> str:
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    staged = base64.b64encode(f"{password}|{timestamp}".encode()).decode()
    public_key = load_der_public_key(base64.b64decode(key_b64))
    encrypted = public_key.encrypt(staged.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


# ---------------------------------------------------------------------------
# التشخيص
# ---------------------------------------------------------------------------

def run_auth_probe(
    *,
    transport: Transport,
    secrets: SecretProvider,
    environment: CapitalEnvironment = CapitalEnvironment.DEMO,
    timeout: float = 20.0,
) -> ProbeReport:
    """
    محاولة واحدة كحد أقصى لكل وضع. يتوقف عند أول نجاح — فلا داعي لإرسال
    الاعتمادات مرة أخرى بعد معرفة الجواب.
    """
    if environment is not CapitalEnvironment.DEMO:
        raise ProbeViolation("التشخيص مسموح على Demo فقط. لا تراجع إلى Live إطلاقاً.")
    if LIVE_API_ENABLED:
        raise ProbeViolation("قفل Live مفتوح في الكود — توقّف.")

    base_url = environment.base_url
    if base_url != DEMO_BASE_URL:
        raise ProbeViolation("عنوان غير عنوان Demo — رُفض قبل أي إرسال.")
    assert_environment_allowed(base_url)

    api_key = secrets.get(CAPITAL_API_KEY)
    identifier = secrets.get(CAPITAL_IDENTIFIER)
    password = secrets.get(CAPITAL_API_PASSWORD)
    # تُسجَّل في سجل الحجب كي لا تظهر في أي سجل أو أثر استثناء.
    REGISTRY.register_many([api_key, identifier, password])

    sent: list[tuple[str, str]] = []
    attempts: list[ProbeAttempt] = []
    tokens_seen = False

    def post_session(payload: dict[str, Any]) -> ApiResponse:
        sent.append(("POST", PATH_SESSION))
        return transport.send(
            "POST",
            f"{base_url}{PATH_SESSION}",
            headers={"X-CAP-API-KEY": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )

    # --- الوضع 1: كلمة مرور مشفّرة ---------------------------------------
    encryption_key_available = False
    key_b64: Optional[str] = None
    key_timestamp: Optional[int] = None

    sent.append(("GET", PATH_ENCRYPTION_KEY))
    try:
        key_response = transport.send(
            "GET",
            f"{base_url}{PATH_ENCRYPTION_KEY}",
            headers={"X-CAP-API-KEY": api_key},
            timeout=timeout,
        )
        if key_response.ok and isinstance(key_response.body, dict):
            candidate = key_response.body.get("encryptionKey")
            stamp = key_response.body.get("timeStamp")
            if isinstance(candidate, str) and candidate:
                key_b64 = candidate
                key_timestamp = int(stamp) if stamp is not None else int(time.time() * 1000)
                encryption_key_available = True
    except Exception:  # noqa: BLE001
        # لا تفاصيل: قد تحمل رسالة الاستثناء ما لا نريد عرضه.
        encryption_key_available = False

    if not encryption_key_available:
        attempts.append(ProbeAttempt(
            mode=AuthMode.ENCRYPTED,
            attempted=False,
            http_status=None,
            error_code=None,
            succeeded=False,
            note_ar="تعذّر الحصول على مفتاح التشفير — لم تُرسل محاولة في هذا الوضع.",
        ))
    else:
        try:
            encrypted = _encrypt(password, key_b64 or "", key_timestamp or 0)
        except Exception:  # noqa: BLE001
            encrypted = None
        if encrypted is None:
            attempts.append(ProbeAttempt(
                mode=AuthMode.ENCRYPTED,
                attempted=False,
                http_status=None,
                error_code=None,
                succeeded=False,
                note_ar="تعذّر التشفير محلياً (حزمة cryptography؟) — لم تُرسل محاولة.",
            ))
        else:
            # ⚠️ `encrypted` لا يُسجَّل ولا يُعرض في أي مكان.
            response = post_session({
                "identifier": identifier,
                "password": encrypted,
                "encryptedPassword": True,
            })
            tokens_seen = _forget_tokens(response) or tokens_seen
            code = _sanitize_error_code(response.body)
            attempts.append(ProbeAttempt(
                mode=AuthMode.ENCRYPTED,
                attempted=True,
                http_status=response.status,
                error_code=code,
                succeeded=response.ok,
                note_ar=("قُبلت المصادقة." if response.ok else "رُفضت المصادقة."),
            ))

    # --- الوضع 2: كلمة المرور كما هي (فقط إن لم ينجح الأول) ----------------
    already_succeeded = any(a.succeeded for a in attempts)
    if already_succeeded:
        attempts.append(ProbeAttempt(
            mode=AuthMode.PLAINTEXT,
            attempted=False,
            http_status=None,
            error_code=None,
            succeeded=False,
            note_ar="لم تُجرَّب: الوضع الأول نجح، فلا داعي لإرسال الاعتمادات ثانيةً.",
        ))
    else:
        response = post_session({
            "identifier": identifier,
            "password": password,
            "encryptedPassword": False,
        })
        tokens_seen = _forget_tokens(response) or tokens_seen
        code = _sanitize_error_code(response.body)
        attempts.append(ProbeAttempt(
            mode=AuthMode.PLAINTEXT,
            attempted=True,
            http_status=response.status,
            error_code=code,
            succeeded=response.ok,
            note_ar=("قُبلت المصادقة." if response.ok else "رُفضت المصادقة."),
        ))

    _assert_only_allowed_operations(sent)
    _assert_attempt_budget(sent)

    return ProbeReport(
        environment=environment.value,
        base_url=base_url,
        generated_at_utc=now_utc(),
        generated_at_riyadh=format_riyadh(now_utc()),
        encryption_key_available=encryption_key_available,
        attempts=tuple(attempts),
        guidance_ar=_build_guidance(attempts, encryption_key_available),
        operations_sent=tuple(sent),
        tokens_retained=False,   # ثابت: لا تُخزَّن رموز في أي مسار
    )


def _assert_only_allowed_operations(sent: list[tuple[str, str]]) -> None:
    """قائمة بيضاء صارمة: لا شيء خارج مفتاح التشفير وإنشاء الجلسة."""
    forbidden = [op for op in sent if op not in ALLOWED_OPERATIONS]
    if forbidden:
        raise ProbeViolation(
            "التشخيص لمس مساراً غير مسموح: "
            + "، ".join(f"{m} {p}" for m, p in forbidden)
        )


def _assert_attempt_budget(sent: list[tuple[str, str]]) -> None:
    """محاولة واحدة لكل وضع ⇒ حدّان اثنان على الأكثر لـ`POST /session`."""
    posts = sum(1 for op in sent if op == ("POST", PATH_SESSION))
    if posts > 2 * MAX_ATTEMPTS_PER_MODE:
        raise ProbeViolation(f"عدد محاولات المصادقة {posts} يتجاوز الحد المسموح.")


def _build_guidance(
    attempts: list[ProbeAttempt], encryption_key_available: bool
) -> tuple[str, ...]:
    """
    إرشاد حتمي مبني على ما وردت به الاستجابة فعلاً — لا تخمين.
    """
    out: list[str] = []
    working = next((a for a in attempts if a.succeeded), None)

    if working is not None:
        out.append(
            f"✅ الوضع العامل: {MODE_NAME_AR[working.mode]}. "
            "اضبطي هذا الوضع في الإعداد ثم أعيدي أمر الاكتشاف."
        )
        return tuple(out)

    codes = {a.error_code for a in attempts if a.error_code}
    statuses = {a.http_status for a in attempts if a.http_status is not None}

    for code in sorted(c for c in codes if c):
        hint = ERROR_HINTS_AR.get(code)
        out.append(f"رمز الخطأ `{code}`" + (f": {hint}" if hint else "."))

    if statuses == {401} or (401 in statuses and len(statuses) == 1):
        out.append(
            "**فشل الوضعان بـ401.** الاعتمادات نفسها تصل إلى الخادم في الحالتين، "
            "فالمشكلة ليست في صيغة كلمة المرور بل في **أي اعتماد** يُقبل."
        )
        out.append(
            "**الاحتمال الأول — بيئة المفتاح.** مفاتيح Capital.com مرتبطة ببيئة "
            "بعينها: المفتاح المُنشأ داخل الحساب الحقيقي **لا يعمل** على عنوان "
            "Demo. تحقّقي أن المفتاح أُنشئ وأنتِ **داخل الحساب التجريبي**."
        )
        out.append(
            "**الاحتمال الثاني — المعرّف مع Google Sign-In.** بعض الحسابات "
            "المنشأة بتسجيل دخول Google تحتاج ضبط كلمة مرور للحساب مرة واحدة "
            "من إعدادات الحساب قبل أن تعمل واجهة API، حتى مع كلمة مرور مخصّصة "
            "للمفتاح."
        )
        out.append(
            "**الاحتمال الثالث — حالة المفتاح.** تأكّدي أن المفتاح مفعّل وغير "
            "منتهٍ، وأن أي تقييد بعنوان IP لا يمنع جهازك."
        )
        out.append(
            "لا تعيدي التشغيل أكثر من مرة أو مرتين: تكرار الفشل قد يُقفل المفتاح "
            "مؤقتاً لدى الوسيط."
        )
    elif 403 in statuses:
        out.append("**403:** المفتاح صالح لكن الصلاحية مرفوضة — راجعي حالة المفتاح وقيود IP.")
    elif 429 in statuses:
        out.append("**429:** تجاوز حد الطلبات. انتظري ثم أعيدي **مرة واحدة**.")

    if not encryption_key_available:
        out.append(
            "لم يُجلب مفتاح التشفير، فلم يُجرَّب الوضع المشفّر. هذا وحده مؤشر على "
            "أن المفتاح غير مقبول في هذه البيئة."
        )

    out.append(
        "لم تُخزَّن أي رموز جلسة، ولم يُلمس أي مسار غير `POST /session` "
        "و`GET /session/encryptionKey`، ولم يُستعمل عنوان Live."
    )
    return tuple(out)


def render_report(report: ProbeReport) -> str:
    """نص عربي للعرض. **يمر عبر `redact()` قبل الإرجاع** حزاماً أخيراً."""
    lines: list[str] = [
        "تشخيص مصادقة Capital.com — Demo",
        "─" * 46,
        f"البيئة       : {report.environment}",
        f"العنوان      : {report.base_url}",
        f"التوقيت      : {report.generated_at_riyadh} (الرياض)",
        f"مفتاح التشفير: {'متاح' if report.encryption_key_available else 'غير متاح'}",
        "",
        "النتائج:",
    ]
    for a in report.attempts:
        if not a.attempted:
            lines.append(f"  ◦ {MODE_NAME_AR[a.mode]}: لم تُجرَّب — {a.note_ar}")
            continue
        mark = "✅" if a.succeeded else "❌"
        code = f" · رمز الخطأ: {a.error_code}" if a.error_code else ""
        lines.append(
            f"  {mark} {MODE_NAME_AR[a.mode]}: HTTP {a.http_status}{code}"
        )

    lines += ["", "العمليات المرسَلة فعلاً:"]
    for method, path in report.operations_sent:
        lines.append(f"  · {method} {path}")

    lines += ["", "الإرشاد:"]
    for g in report.guidance_ar:
        lines.append(f"  • {g}")

    lines += [
        "",
        f"رموز جلسة مُخزَّنة: {'نعم ⚠️' if report.tokens_retained else 'لا'}",
        "لم يُعرض في هذا التقرير: معرّف · كلمة مرور · مفتاح API · حمولة مشفّرة · CST · رمز أمان.",
    ]
    return redact("\n".join(lines))


__all__ = [
    "AuthMode",
    "MODE_NAME_AR",
    "ERROR_HINTS_AR",
    "ALLOWED_OPERATIONS",
    "MAX_ATTEMPTS_PER_MODE",
    "ProbeAttempt",
    "ProbeReport",
    "ProbeViolation",
    "run_auth_probe",
    "render_report",
]
