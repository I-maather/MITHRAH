"""
FRED MACRO — سلاسل أمريكية رسمية، بسجل مُرقَّم ورموز **مُتحقَّق منها**.

## العقد — مُثبَت من `fred.stlouisfed.org/docs/api/fred/`

    GET https://api.stlouisfed.org/fred/series?series_id=X&api_key=K&file_type=json
    GET https://api.stlouisfed.org/fred/series/observations?series_id=X&api_key=K&file_type=json

شكل الخطأ (JSON) موثَّق حرفياً:

    {"error_code": 400, "error_message": "Bad Request. ..."}

## «لا تُخترَع رموز سلاسل»

كل رمز في السجل أدناه تُحقِّق منه من صفحة السلسلة الرسمية، وسُجِّل عنوانه
وتواتره ووحدته وتعديله الموسمي **كما تنشرها FRED**. ورغم ذلك، الرمز يبقى
`validated=False` حتى تُقارَن بياناته الوصفية **حيّاً** عبر `/fred/series`
بمفتاح المالكة. التحقّق من مستند ليس تحقّقاً من الواجهة: قد يُعاد تعريف
سلسلة أو تُوقَف.

    رمز غير مُتحقَّق منه حيّاً ⇒ لا يدخل قراراً.

## المراجعات

السلاسل الاقتصادية تُراجَع بأثر رجعي. `revision_policy` يقول لكل سلسلة كيف
تُعامَل المراجعة — وتجاهل ذلك يجعل Backtest يرى أرقاماً **لم تكن معروفة**
في وقتها، وهو تسريب مستقبل صريح.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional, Sequence
from urllib.parse import urlencode

from ..intelligence.providers import MacroDataProvider, ProviderKind
from ..intelligence.snapshot import UNKNOWN, Sourced, SourceReliability
from ..money import D
from .http import ProviderHttpError, ProviderTransport, RateLimiter, get_with_retry
from .period import period_to_utc
from .provenance import LicenseClass, build_provenance
from .results import ProviderResult, ProviderResultState

PROVIDER_NAME = "FredMacroDataProvider"
CREDENTIAL_NAME = "FRED_API_KEY"

BASE_URL = "https://api.stlouisfed.org"
SERIES_PATH = "/fred/series"
OBSERVATIONS_PATH = "/fred/series/observations"

#: إصدار سجل السلاسل. تغيير أي رمز أو سياسة يرفع الرقم.
FRED_REGISTRY_VERSION = "1.0.0"

#: حد محافظ — الرقم الرسمي غير منشور، و429 موثَّق.
CONSERVATIVE_CALLS_PER_MINUTE = 60


class MacroCategory(str, Enum):
    POLICY_RATE = "POLICY_RATE"
    INFLATION = "INFLATION"
    CORE_INFLATION = "CORE_INFLATION"
    UNEMPLOYMENT = "UNEMPLOYMENT"
    PAYROLLS = "PAYROLLS"
    GDP = "GDP"
    PCE_INFLATION = "PCE_INFLATION"
    YIELD_2Y = "YIELD_2Y"
    YIELD_10Y = "YIELD_10Y"


class RevisionPolicy(str, Enum):
    #: تُستعمل آخر قيمة منشورة (مناسب للسلاسل التي لا تُراجَع فعلياً).
    LATEST = "LATEST"
    #: يجب استعمال القيمة **كما كانت معروفة** في التاريخ المطلوب (vintage).
    AS_OF_VINTAGE = "AS_OF_VINTAGE"


@dataclass(frozen=True)
class FredSeriesSpec:
    series_id: str
    category: MacroCategory
    official_title: str
    frequency: str
    units: str
    seasonal_adjustment: str
    release_source: str
    expected_cadence: str
    transformation: str
    revision_policy: RevisionPolicy
    #: يُقلَب إلى True فقط بعد مطابقة البيانات الوصفية **حيّاً**.
    validated: bool = False
    validation_note_ar: str = "لم يُتحقَّق حيّاً بعد — لا يدخل قراراً."

    def as_dict(self) -> dict:
        return {
            "series_id": self.series_id,
            "category": self.category.value,
            "official_title": self.official_title,
            "frequency": self.frequency,
            "units": self.units,
            "seasonal_adjustment": self.seasonal_adjustment,
            "release_source": self.release_source,
            "expected_cadence": self.expected_cadence,
            "transformation": self.transformation,
            "revision_policy": self.revision_policy.value,
            "validated": self.validated,
            "validation_note_ar": self.validation_note_ar,
        }


#: العناوين والوحدات والتواتر والتعديل الموسمي **منقولة من صفحات FRED الرسمية**.
FRED_REGISTRY: dict[MacroCategory, FredSeriesSpec] = {
    MacroCategory.POLICY_RATE: FredSeriesSpec(
        "DFEDTARU", MacroCategory.POLICY_RATE,
        "Federal Funds Target Range – Upper Limit",
        "Daily, 7-Day", "Percent", "Not Seasonally Adjusted",
        "Board of Governors of the Federal Reserve System",
        "عند كل اجتماع FOMC وعند أي تغيير", "المستوى كما هو",
        RevisionPolicy.LATEST,
    ),
    MacroCategory.INFLATION: FredSeriesSpec(
        "CPIAUCSL", MacroCategory.INFLATION,
        "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
        "Monthly", "Index 1982-1984=100", "Seasonally Adjusted",
        "U.S. Bureau of Labor Statistics",
        "شهرياً، منتصف الشهر التالي", "تغيّر سنوي (pc1) للمقارنة",
        RevisionPolicy.AS_OF_VINTAGE,
    ),
    MacroCategory.CORE_INFLATION: FredSeriesSpec(
        "CPILFESL", MacroCategory.CORE_INFLATION,
        "Consumer Price Index for All Urban Consumers: "
        "All Items Less Food and Energy in U.S. City Average",
        "Monthly", "Index 1982-1984=100", "Seasonally Adjusted",
        "U.S. Bureau of Labor Statistics",
        "شهرياً مع الرقم العام", "تغيّر سنوي (pc1)",
        RevisionPolicy.AS_OF_VINTAGE,
    ),
    MacroCategory.UNEMPLOYMENT: FredSeriesSpec(
        "UNRATE", MacroCategory.UNEMPLOYMENT,
        "Unemployment Rate", "Monthly", "Percent", "Seasonally Adjusted",
        "U.S. Bureau of Labor Statistics",
        "شهرياً، أول جمعة", "المستوى كما هو",
        RevisionPolicy.AS_OF_VINTAGE,
    ),
    MacroCategory.PAYROLLS: FredSeriesSpec(
        "PAYEMS", MacroCategory.PAYROLLS,
        "All Employees, Total Nonfarm", "Monthly", "Thousands of Persons",
        "Seasonally Adjusted", "U.S. Bureau of Labor Statistics",
        "شهرياً، أول جمعة مع NFP", "التغيّر الشهري بالآلاف",
        RevisionPolicy.AS_OF_VINTAGE,
    ),
    MacroCategory.GDP: FredSeriesSpec(
        "GDPC1", MacroCategory.GDP,
        "Real Gross Domestic Product", "Quarterly",
        "Billions of Chained 2017 Dollars", "Seasonally Adjusted Annual Rate",
        "U.S. Bureau of Economic Analysis",
        "ربع سنوي، ثلاث تقديرات لكل ربع", "نمو سنوي (pc1)",
        RevisionPolicy.AS_OF_VINTAGE,
    ),
    MacroCategory.PCE_INFLATION: FredSeriesSpec(
        "PCEPILFE", MacroCategory.PCE_INFLATION,
        "Personal Consumption Expenditures Excluding Food and Energy "
        "(Chain-Type Price Index)",
        "Monthly", "Index 2017=100", "Seasonally Adjusted",
        "U.S. Bureau of Economic Analysis",
        "شهرياً — مقياس التضخم المفضّل لدى الفيدرالي", "تغيّر سنوي (pc1)",
        RevisionPolicy.AS_OF_VINTAGE,
    ),
    MacroCategory.YIELD_2Y: FredSeriesSpec(
        "DGS2", MacroCategory.YIELD_2Y,
        "Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity, "
        "Quoted on an Investment Basis",
        "Daily", "Percent", "Not Seasonally Adjusted",
        "Board of Governors of the Federal Reserve System",
        "يومياً في أيام العمل", "المستوى كما هو",
        RevisionPolicy.LATEST,
    ),
    MacroCategory.YIELD_10Y: FredSeriesSpec(
        "DGS10", MacroCategory.YIELD_10Y,
        "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, "
        "Quoted on an Investment Basis",
        "Daily", "Percent", "Not Seasonally Adjusted",
        "Board of Governors of the Federal Reserve System",
        "يومياً في أيام العمل", "المستوى كما هو",
        RevisionPolicy.LATEST,
    ),
}

SERIES_BY_ID: dict[str, FredSeriesSpec] = {
    spec.series_id: spec for spec in FRED_REGISTRY.values()
}


@dataclass
class FredMacroDataProvider(MacroDataProvider):
    """بيانات كلية أمريكية. **سياق فقط — لا تأذن بصفقة.**"""

    api_key: Optional[str] = None
    transport: ProviderTransport = None       # type: ignore[assignment]
    limiter: RateLimiter = None               # type: ignore[assignment]
    base_url: str = BASE_URL
    registry: dict[MacroCategory, FredSeriesSpec] = field(
        default_factory=lambda: dict(FRED_REGISTRY)
    )
    _validated: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.kind = ProviderKind.MACRO_DATA
        if self.transport is None:
            self.transport = ProviderTransport()
        if self.limiter is None:
            self.limiter = RateLimiter(
                name=PROVIDER_NAME,
                max_calls=CONSERVATIVE_CALLS_PER_MINUTE, per_seconds=60.0,
            )

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _url(self, path: str, params: dict[str, Any]) -> str:
        merged = {"api_key": self.api_key or "", "file_type": "json", **params}
        return f"{self.base_url}{path}?{urlencode(merged)}"

    # -- التحقق من الرموز --------------------------------------------------

    def validate_series(
        self, series_id: str, *, now_utc: Optional[datetime] = None
    ) -> ProviderResult[dict]:
        """
        يطابق البيانات الوصفية الحيّة مع السجل المحلي.

        الاختلاف **لا يُصحَّح تلقائياً**: سلسلة تغيّر عنوانها أو وحدتها قد
        تكون سلسلة أخرى تماماً، وقبول التغيير صامتاً يعني حساب تضخم على
        مؤشر مختلف.
        """
        now = now_utc or datetime.now(timezone.utc)
        spec = SERIES_BY_ID.get(series_id)
        if spec is None:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="UNKNOWN_SERIES",
                detail_ar=f"الرمز {series_id} ليس في السجل. لا يُخترع رمز.",
            )
        if not self.configured:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="NOT_CONFIGURED",
                detail_ar=f"المفتاح {CREDENTIAL_NAME} غير مُعدّ.",
            )

        try:
            response = get_with_retry(
                self.transport, self._url(SERIES_PATH, {"series_id": series_id}),
                limiter=self.limiter, secrets=(self.api_key,) if self.api_key else (),
            )
        except ProviderHttpError as exc:
            return ProviderResult(
                provider=PROVIDER_NAME, state=exc.state, retrieved_at_utc=now,
                error_code=exc.state.value, detail_ar=str(exc), http_status=exc.status,
            )

        body = response.body
        if isinstance(body, dict) and "error_code" in body:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.MALFORMED,
                retrieved_at_utc=now, error_code=str(body.get("error_code")),
                detail_ar=f"FRED ردّ بخطأ موثَّق: {body.get('error_message', '')}",
                http_status=response.status,
            )
        seriess = (body or {}).get("seriess") if isinstance(body, dict) else None
        if not isinstance(seriess, list) or not seriess:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.MALFORMED,
                retrieved_at_utc=now, error_code="MALFORMED",
                detail_ar="استجابة البيانات الوصفية لا تحتوي `seriess`.",
                http_status=response.status,
            )

        meta = seriess[0]
        mismatches = [
            f"{label}: السجل «{expected}» والواجهة «{meta.get(key)}»"
            for label, key, expected in (
                ("العنوان", "title", spec.official_title),
                ("التواتر", "frequency", spec.frequency),
                ("الوحدة", "units", spec.units),
                ("التعديل الموسمي", "seasonal_adjustment", spec.seasonal_adjustment),
            )
            if str(meta.get(key, "")).strip() != expected
        ]
        if mismatches:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.MALFORMED,
                records=({"series_id": series_id, "mismatches": mismatches},),
                retrieved_at_utc=now, error_code="METADATA_MISMATCH",
                detail_ar=(
                    "البيانات الوصفية لا تطابق السجل — **لا يُصحَّح تلقائياً**: "
                    + " · ".join(mismatches)
                ),
            )

        self._validated.add(series_id)
        return ProviderResult(
            provider=PROVIDER_NAME, state=ProviderResultState.FRESH,
            records=({"series_id": series_id, "metadata": meta},),
            retrieved_at_utc=now,
            detail_ar=f"الرمز {series_id} مُتحقَّق منه حيّاً ومطابق للسجل.",
        )

    def is_validated(self, series_id: str) -> bool:
        return series_id in self._validated

    # -- الملاحظات ---------------------------------------------------------

    def observations(
        self,
        series_id: str,
        *,
        limit: int = 24,
        now_utc: Optional[datetime] = None,
        require_validation: bool = True,
    ) -> ProviderResult[dict]:
        now = now_utc or datetime.now(timezone.utc)
        if not self.configured:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="NOT_CONFIGURED",
                detail_ar=f"المفتاح {CREDENTIAL_NAME} غير مُعدّ.",
            )
        if series_id not in SERIES_BY_ID:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="UNKNOWN_SERIES",
                detail_ar=f"الرمز {series_id} ليس في السجل.",
            )
        if require_validation and not self.is_validated(series_id):
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="SERIES_NOT_VALIDATED",
                detail_ar=(
                    f"الرمز {series_id} لم يُتحقَّق منه حيّاً بعد. "
                    "التحقّق من مستند ليس تحقّقاً من الواجهة."
                ),
            )

        try:
            response = get_with_retry(
                self.transport,
                self._url(OBSERVATIONS_PATH, {
                    "series_id": series_id, "sort_order": "desc", "limit": limit,
                }),
                limiter=self.limiter, secrets=(self.api_key,) if self.api_key else (),
            )
        except ProviderHttpError as exc:
            return ProviderResult(
                provider=PROVIDER_NAME, state=exc.state, retrieved_at_utc=now,
                error_code=exc.state.value, detail_ar=str(exc), http_status=exc.status,
            )

        body = response.body
        if isinstance(body, dict) and "error_code" in body:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.MALFORMED,
                retrieved_at_utc=now, error_code=str(body.get("error_code")),
                detail_ar=str(body.get("error_message", "")), http_status=response.status,
            )
        rows = (body or {}).get("observations") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.MALFORMED,
                retrieved_at_utc=now, error_code="MALFORMED",
                detail_ar="الاستجابة لا تحتوي `observations`.",
            )

        spec = SERIES_BY_ID[series_id]
        records: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_value = row.get("value")
            # FRED يستعمل "." للقيمة الغائبة — **لا تُقرأ صفراً**.
            if raw_value in (None, "", "."):
                continue
            try:
                value = D(str(raw_value))
            except (InvalidOperation, ValueError):
                continue
            provenance = build_provenance(
                provider=PROVIDER_NAME, raw=row,
                source_id=f"fred:{series_id}:{row.get('date')}",
                retrieved_at_utc=now,
                event_timestamp_utc=_parse_date(row.get("date")),
                original_source=spec.release_source,
                original_url=f"https://fred.stlouisfed.org/series/{series_id}",
                currency="USD", category=spec.category.value, impact=None,
                license_class=LicenseClass.PUBLIC_OFFICIAL,
            )
            records.append({
                "series_id": series_id, "date": row.get("date"),
                "value": str(value), "units": spec.units,
                "provenance": provenance.as_dict(),
            })

        return ProviderResult(
            provider=PROVIDER_NAME,
            state=ProviderResultState.FRESH if records else ProviderResultState.PARTIAL,
            records=tuple(records), retrieved_at_utc=now,
            detail_ar=f"{len(records)} ملاحظة صالحة للسلسلة {series_id}.",
            http_status=response.status,
        )

    @property
    def known_series_keys(self) -> tuple[str, ...]:
        return tuple(SERIES_BY_ID)

    def series(
        self, *, keys: Sequence[str], as_of_utc: datetime
    ) -> dict[str, Sourced[Any]]:
        """الواجهة القائمة. المفقود يعود `UNKNOWN` — لا صفراً ولا تقديراً."""
        out: dict[str, Sourced[Any]] = {}
        for key in keys:
            # **تحقّقٌ كسول.** التحقّق شرطٌ لقراءة أي ملاحظة، ولم يكن في
            # النظام كلّه سطرٌ واحد يستدعيه — فكان كل مفتاح يعود `UNKNOWN`
            # إلى الأبد، وحارسُ الكلّيات ميّتاً بلا أن يشكو أحد.
            #
            # ويبقى التحقّق شرطاً: لا يُقرأ مفتاحٌ لم يُثبَت أنه حيّ. غاية
            # التغيير أن يقع الإثبات عند أوّل حاجة بدل ألّا يقع أبداً.
            if not self.is_validated(key):
                self.validate_series(key, now_utc=as_of_utc)

            result = self.observations(key, now_utc=as_of_utc)
            if not result.usable_for_decision or not result.records:
                out[key] = Sourced(
                    value=UNKNOWN, source=PROVIDER_NAME,
                    reliability=SourceReliability.UNVERIFIED,
                    source_timestamp_utc=None,
                    retrieved_at_utc=as_of_utc,
                    note_ar=result.detail_ar or "غير متاح.",
                )
                continue
            latest = result.records[0]
            out[key] = Sourced(
                value=D(latest["value"]), source=PROVIDER_NAME,
                reliability=SourceReliability.OFFICIAL_PROVIDER,
                source_timestamp_utc=period_to_utc(latest.get("date")),
                retrieved_at_utc=as_of_utc,
                note_ar=f"{SERIES_BY_ID[key].official_title} — {latest['date']}",
            )
        return out


def _parse_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def registry_summary() -> dict:
    return {
        "version": FRED_REGISTRY_VERSION,
        "series": [spec.as_dict() for spec in FRED_REGISTRY.values()],
    }


__all__ = [
    "PROVIDER_NAME", "CREDENTIAL_NAME", "BASE_URL", "SERIES_PATH",
    "OBSERVATIONS_PATH", "FRED_REGISTRY_VERSION", "MacroCategory",
    "RevisionPolicy", "FredSeriesSpec", "FRED_REGISTRY", "SERIES_BY_ID",
    "FredMacroDataProvider", "registry_summary",
]
