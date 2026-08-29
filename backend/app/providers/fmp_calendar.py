"""
FMP ECONOMIC CALENDAR — تقويم اقتصادي، بعقدٍ **غير مُثبَت بالكامل**.

## إفصاح صريح في رأس الملف

وثائق FMP التفاعلية تُبنى في المتصفح (SPA)، فتعذّر استخراج **أسماء حقول
الاستجابة** و**شكل خطأ الخطة** من مصدر رسمي. أسماء الحقول أدناه هي المتداولة
في أمثلة FMP نفسها، لكنها **لم تُثبَت** من صفحة توثيق رسمية.

ولذلك:

  * `CONTRACT_VERIFIED = False`، ويظهر في كل مخرَج.
  * المُطبِّع يجرّب **أسماء بديلة معروفة** لكل حقل، ولا يخترع قيمة.
  * حقل إلزامي مفقود ⇒ `MALFORMED`، لا سجل ناقص يمرّ.
  * `provider-probe fmp-calendar` هو ما يثبت العقد فعلياً — بمفتاح المالكة،
    على جهازها، لاحقاً.

هذا أصدق من ادعاء عقدٍ لم يُقرأ.

## الخطة

توفّر التقويم على الخطة المجانية **غير مؤكَّد**. الرد المتوقَّع عند عدم
الشمول قد يكون 402 أو 403 أو **200 بجسم خطأ** — والأخيرة هي الخطرة، لأنها
تبدو نجاحاً. لذلك يُفحَص جسم الاستجابة بحثاً عن شكل خطأ حتى مع 200.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from urllib.parse import urlencode

from ..intelligence.providers import EconomicCalendarProvider, ProviderKind
from ..intelligence.snapshot import UNKNOWN, EconomicEvent
from .classification import INITIAL_CURRENCY_ALLOWLIST, classify_event
from .http import ProviderHttpError, ProviderTransport, RateLimiter, get_with_retry
from .provenance import LicenseClass, build_provenance, to_utc
from .results import ProviderResult, ProviderResultState

PROVIDER_NAME = "FmpEconomicCalendarProvider"
CREDENTIAL_NAME = "FMP_API_KEY"

BASE_URL = "https://financialmodelingprep.com"
#: المسار الحديث كما تعلنه صفحة التوثيق، مع الإرث كبديل مُوثَّق.
CALENDAR_PATH = "/stable/economic-calendar"
LEGACY_CALENDAR_PATH = "/api/v3/economic_calendar"

#: **غير مُثبَت**: أسماء حقول الاستجابة لم تُقرأ من توثيق رسمي.
CONTRACT_VERIFIED = False
CONTRACT_NOTE_AR = (
    "عقد الاستجابة غير مُثبَت من توثيق رسمي — صفحة FMP تُبنى في المتصفح. "
    "أثبتيه بـ`provider-probe fmp-calendar` قبل الاعتماد عليه في قرار."
)

#: الحد المُعلَن للخطة المجانية: 250 طلباً يومياً (مؤكَّد من أسئلة FMP الشائعة).
FREE_TIER_DAILY_CALLS = 250
#: أقصى مدى زمني لطلب واحد كما تنص أمثلة FMP.
MAX_WINDOW_DAYS = 90

FRESHNESS_WINDOW_SECONDS = 15 * 60.0

#: أسماء بديلة لكل حقل. تُجرَّب بالترتيب، وأول موجود يفوز.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "dateTime", "datetime", "eventDate"),
    "country": ("country", "countryCode"),
    "event": ("event", "eventName", "name", "title"),
    "currency": ("currency", "currencyCode"),
    "previous": ("previous", "previousValue"),
    "estimate": ("estimate", "consensus", "forecast", "expected"),
    "actual": ("actual", "actualValue"),
    "change": ("change", "revision", "changePercentage"),
    "impact": ("impact", "importance"),
    "unit": ("unit",),
}

#: أشكال جسم الخطأ المحتملة حتى مع HTTP 200.
_ERROR_BODY_KEYS = ("Error Message", "error", "message", "Error")
_PLAN_TOKENS = (
    "exclusive endpoint", "not available under your", "upgrade",
    "premium", "subscription", "plan", "not authorized",
)


def _pick(raw: dict, field: str) -> Any:
    for alias in _FIELD_ALIASES[field]:
        if alias in raw:
            return raw[alias]
    return None


def _parse_moment(value: Any) -> Optional[datetime]:
    """
    FMP يعيد الوقت بصيغ عدة. **الوقت بلا منطقة زمنية يُعامَل UTC هنا وحدها**،
    لأن FMP يوثّق أن تواريخ التقويم بتوقيت UTC — ويُسجَّل ذلك في المصدر.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _looks_like_plan_error(body: Any) -> Optional[str]:
    """يكشف جسم خطأ خطة حتى داخل استجابة 200."""
    if isinstance(body, dict):
        for key in _ERROR_BODY_KEYS:
            if key in body:
                message = str(body[key]).lower()
                if any(token in message for token in _PLAN_TOKENS):
                    return "PLAN"
                return "ERROR_BODY"
    if isinstance(body, str) and body.strip().startswith("{"):
        return "ERROR_BODY"
    return None


@dataclass
class FmpEconomicCalendarProvider(EconomicCalendarProvider):
    """
    مزوّد التقويم. **لا يستورد ولا يستطيع استيراد أي تنفيذ** — مُختبَر بـAST.
    """

    api_key: Optional[str] = None
    transport: ProviderTransport = None            # type: ignore[assignment]
    limiter: RateLimiter = None                    # type: ignore[assignment]
    base_url: str = BASE_URL
    path: str = CALENDAR_PATH
    allowlist: tuple[str, ...] = INITIAL_CURRENCY_ALLOWLIST

    def __post_init__(self) -> None:
        self.kind = ProviderKind.ECONOMIC_CALENDAR
        if self.transport is None:
            self.transport = ProviderTransport()
        if self.limiter is None:
            # 250 طلباً يومياً ⇒ نافذة يوم كامل، بهامش أمان.
            self.limiter = RateLimiter(
                name=PROVIDER_NAME, max_calls=FREE_TIER_DAILY_CALLS, per_seconds=86_400.0
            )

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _url(self, start: datetime, end: datetime) -> str:
        query = urlencode({
            "from": start.date().isoformat(),
            "to": end.date().isoformat(),
            "apikey": self.api_key or "",
        })
        return f"{self.base_url}{self.path}?{query}"

    # -- الاستدعاء ---------------------------------------------------------

    def fetch(
        self,
        *,
        currencies: Sequence[str],
        window_start_utc: datetime,
        window_end_utc: datetime,
        now_utc: Optional[datetime] = None,
    ) -> ProviderResult[EconomicEvent]:
        """يعيد نتيجة **بحالتها**. القائمة الفارغة لا تعني «لا أحداث»."""
        now = now_utc or datetime.now(timezone.utc)
        if not self.configured:
            return ProviderResult(
                provider=PROVIDER_NAME,
                state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now,
                error_code="NOT_CONFIGURED",
                detail_ar=f"المفتاح {CREDENTIAL_NAME} غير مُعدّ. لا يُخترع مفتاح.",
            )
        if (window_end_utc - window_start_utc) > timedelta(days=MAX_WINDOW_DAYS):
            return ProviderResult(
                provider=PROVIDER_NAME,
                state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now,
                error_code="WINDOW_TOO_WIDE",
                detail_ar=f"المدى الأقصى لطلب واحد {MAX_WINDOW_DAYS} يوماً.",
            )

        try:
            response = get_with_retry(
                self.transport,
                self._url(window_start_utc, window_end_utc),
                limiter=self.limiter,
                secrets=(self.api_key,) if self.api_key else (),
            )
        except ProviderHttpError as exc:
            return ProviderResult(
                provider=PROVIDER_NAME, state=exc.state, retrieved_at_utc=now,
                error_code=exc.state.value, detail_ar=str(exc), http_status=exc.status,
            )

        # خطأ خطة قد يصل بحالة 200 — يُفحَص الجسم لا الحالة وحدها.
        flavour = _looks_like_plan_error(response.body)
        if flavour == "PLAN":
            return ProviderResult(
                provider=PROVIDER_NAME,
                state=ProviderResultState.UNAVAILABLE_PLAN,
                retrieved_at_utc=now,
                error_code="UNAVAILABLE_PLAN",
                detail_ar=(
                    "التقويم غير مشمول بالخطة الحالية. **لا يُشترى اشتراك ولا "
                    "يُبدَّل مزوّد تلقائياً** — يُبلَّغ ويُنتظر قرار المالكة."
                ),
                http_status=response.status,
            )
        if flavour == "ERROR_BODY" or not isinstance(response.body, list):
            return ProviderResult(
                provider=PROVIDER_NAME,
                state=ProviderResultState.MALFORMED,
                retrieved_at_utc=now,
                error_code="MALFORMED",
                detail_ar=(
                    "شكل الاستجابة لا يطابق العقد المتوقَّع (قائمة أحداث). "
                    + CONTRACT_NOTE_AR
                ),
                http_status=response.status,
            )

        events: list[EconomicEvent] = []
        skipped = 0
        wanted = {c.upper() for c in currencies}
        for raw in response.body:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            event = self._normalise(raw, now=now, wanted=wanted)
            if event is None:
                skipped += 1
                continue
            if window_start_utc <= event.scheduled_utc <= window_end_utc:
                events.append(event)

        state = ProviderResultState.FRESH
        detail = f"{len(events)} حدثاً ضمن النافذة. " + CONTRACT_NOTE_AR
        if skipped:
            state = ProviderResultState.PARTIAL
            detail = f"{len(events)} حدثاً، و{skipped} سجلاً تعذّر تطبيعه. " + CONTRACT_NOTE_AR

        return ProviderResult(
            provider=PROVIDER_NAME,
            state=state,
            records=tuple(events),
            retrieved_at_utc=now,
            freshness_window_seconds=FRESHNESS_WINDOW_SECONDS,
            detail_ar=detail,
            missing=("normalisation_failures",) if skipped else (),
            http_status=response.status,
        )

    def _normalise(
        self, raw: dict, *, now: datetime, wanted: set[str]
    ) -> Optional[EconomicEvent]:
        name = _pick(raw, "event")
        scheduled = _parse_moment(_pick(raw, "date"))
        if not name or scheduled is None:
            return None                      # حقل إلزامي مفقود ⇒ لا سجل ناقص

        currency = _pick(raw, "currency")
        country = _pick(raw, "country")
        currencies = tuple(
            c for c in ((str(currency).upper(),) if currency else ()) if c
        ) or ((str(country).upper(),) if country else ())
        if wanted and currencies and not (set(currencies) & wanted):
            return None

        classification = classify_event(
            str(name), provider_impact=_pick(raw, "impact"),
            currencies=currencies, allowlist=self.allowlist,
        )
        provenance = build_provenance(
            provider=PROVIDER_NAME,
            raw=raw,
            source_id=f"fmp:{scheduled.isoformat()}:{name}",
            retrieved_at_utc=now,
            event_timestamp_utc=scheduled,
            original_source="Financial Modeling Prep",
            currency=currencies[0] if currencies else None,
            category=classification.category.value,
            impact=classification.impact.value,
            license_class=LicenseClass.METADATA_ONLY,
            freshness_window_seconds=FRESHNESS_WINDOW_SECONDS,
        )

        def value_or_unknown(field: str) -> Any:
            value = _pick(raw, field)
            return UNKNOWN if value in (None, "") else value

        return EconomicEvent(
            event_id=provenance.source_id,
            name=str(name),
            category=classification.category,
            currencies=currencies,
            impact=classification.impact,
            scheduled_utc=scheduled,
            provider=PROVIDER_NAME,
            provider_timestamp_utc=scheduled,
            retrieved_at_utc=now,
            expected_value=value_or_unknown("estimate"),
            previous_value=value_or_unknown("previous"),
            actual_value=value_or_unknown("actual"),
            source_reference=provenance.raw_checksum,
        )

    # -- واجهة `EconomicCalendarProvider` القائمة --------------------------

    def events(
        self, *, currencies: Sequence[str], window_start_utc: datetime, window_end_utc: datetime
    ) -> tuple[EconomicEvent, ...]:
        """
        التوافق مع الواجهة القائمة. **تُفضَّل `fetch()`** لأنها تحمل الحالة؛
        هذه تعيد السجلات وحدها، والقائمة الفارغة هنا غامضة بطبيعتها.
        """
        return self.fetch(
            currencies=currencies,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
        ).records


__all__ = [
    "PROVIDER_NAME",
    "CREDENTIAL_NAME",
    "BASE_URL",
    "CALENDAR_PATH",
    "LEGACY_CALENDAR_PATH",
    "CONTRACT_VERIFIED",
    "CONTRACT_NOTE_AR",
    "MAX_WINDOW_DAYS",
    "FREE_TIER_DAILY_CALLS",
    "FmpEconomicCalendarProvider",
]
