"""
ECB MACRO — بيانات منطقة اليورو من بوابة ECB، بلا مفتاح.

## العقد — مُثبَت من `data.ecb.europa.eu/help/api/data`

    GET https://data-api.ecb.europa.eu/service/data/{flowRef}/{key}?format=jsondata

`flowRef` = `AGENCY,FLOW,VERSION` (الافتراضي: كل الوكالات، آخر إصدار).
معاملات: `startPeriod` · `endPeriod` · `lastNObservations` ·
`firstNObservations` · `format` · `detail` · `updatedAfter`.

**لا مفتاح مطلوب.** المضيف القديم `sdw-wsrest.ecb.europa.eu` مهجور منذ 2021.

## «لا تُخترَع مفاتيح SDMX»

مفتاح SDMX سلسلةُ أبعادٍ مرتّبة، وتغيير بُعد واحد يعطي سلسلة **مختلفة تماماً**
لا خطأً: `ICP.M.U2.N.000000.4.ANR` هو التضخم السنوي العام، و`.4.INX` هو
الرقم القياسي نفسه. كلاهما يعمل، وأحدهما إجابة على سؤال آخر.

لذلك: مفتاح خارج السجل ⇒ **فشل مغلق**، ولا محاولة تخمين.

## بنية `jsondata`

الملاحظات متداخلة: `dataSets[0].series["0:0:0:..."].observations["0"] = [value, ...]`
والمعاني في `structure.dimensions`. الفهرسة بالمواضع لا بالأسماء، فقراءتها
بالحدس تُنتج قيمة من بُعد آخر.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import InvalidOperation
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

PROVIDER_NAME = "EcbMacroDataProvider"
#: **لا مفتاح**. الثابت موجود ليُختبَر أنه `None`.
CREDENTIAL_NAME: Optional[str] = None

BASE_URL = "https://data-api.ecb.europa.eu"
DATA_PATH = "/service/data"
LEGACY_HOST = "sdw-wsrest.ecb.europa.eu"

ECB_REGISTRY_VERSION = "1.0.0"
CONSERVATIVE_CALLS_PER_MINUTE = 30


class EcbCategory(str, Enum):
    DEPOSIT_FACILITY_RATE = "DEPOSIT_FACILITY_RATE"
    HICP = "HICP"
    HICP_CORE = "HICP_CORE"
    UNEMPLOYMENT = "UNEMPLOYMENT"
    GDP = "GDP"
    EUR_USD_REFERENCE = "EUR_USD_REFERENCE"


@dataclass(frozen=True)
class EcbSeriesSpec:
    dataflow: str
    key: str
    category: EcbCategory
    official_title: str
    frequency: str
    units: str
    seasonal_adjustment: str
    release_source: str
    expected_cadence: str
    transformation: str
    revision_policy: str
    validated: bool = False
    validation_note_ar: str = "لم يُتحقَّق حيّاً بعد — لا يدخل قراراً."

    @property
    def series_key(self) -> str:
        return f"{self.dataflow}.{self.key}"

    def as_dict(self) -> dict:
        return {
            "dataflow": self.dataflow, "key": self.key,
            "series_key": self.series_key, "category": self.category.value,
            "official_title": self.official_title, "frequency": self.frequency,
            "units": self.units, "seasonal_adjustment": self.seasonal_adjustment,
            "release_source": self.release_source,
            "expected_cadence": self.expected_cadence,
            "transformation": self.transformation,
            "revision_policy": self.revision_policy,
            "validated": self.validated,
            "validation_note_ar": self.validation_note_ar,
        }


#: المفاتيح مُتحقَّق من وجودها في بوابة ECB. الأوصاف كما تنشرها البوابة.
ECB_REGISTRY: dict[EcbCategory, EcbSeriesSpec] = {
    EcbCategory.DEPOSIT_FACILITY_RATE: EcbSeriesSpec(
        "FM", "D.U2.EUR.4F.KR.DFR.LEV", EcbCategory.DEPOSIT_FACILITY_RATE,
        "Deposit facility - date of changes (raw data) - Level",
        "Daily", "Percent per annum", "Not applicable",
        "European Central Bank",
        "عند كل تغيير في سعر الفائدة", "المستوى كما هو", "لا تُراجَع",
    ),
    EcbCategory.HICP: EcbSeriesSpec(
        "ICP", "M.U2.N.000000.4.ANR", EcbCategory.HICP,
        "HICP - Overall index, Euro area, Annual rate of change, "
        "neither seasonally nor working day adjusted",
        "Monthly", "Annual percentage change", "Neither seasonally nor "
        "working day adjusted", "Eurostat / European Central Bank",
        "شهرياً — تقدير سريع ثم نهائي", "المستوى كما هو (معدّل سنوي)",
        "يُراجَع بين التقدير السريع والنهائي",
    ),
    EcbCategory.HICP_CORE: EcbSeriesSpec(
        "ICP", "M.U2.N.XEF000.4.ANR", EcbCategory.HICP_CORE,
        "HICP - Overall index excluding energy and food, Euro area, "
        "Annual rate of change",
        "Monthly", "Annual percentage change",
        "Neither seasonally nor working day adjusted",
        "Eurostat / European Central Bank",
        "شهرياً مع الرقم العام", "المستوى كما هو",
        "يُراجَع بين التقدير السريع والنهائي",
    ),
    EcbCategory.UNEMPLOYMENT: EcbSeriesSpec(
        "LFSI", "M.I9.S.UNEHRT.TOTAL0.15_74.T", EcbCategory.UNEMPLOYMENT,
        "Unemployment rate, Total, Age 15 to 74, Total, Seasonally adjusted",
        "Monthly", "Percent of labour force", "Seasonally adjusted",
        "Eurostat / European Central Bank",
        "شهرياً بتأخّر نحو شهر", "المستوى كما هو", "يُراجَع بأثر رجعي",
    ),
    EcbCategory.GDP: EcbSeriesSpec(
        "MNA", "Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY", EcbCategory.GDP,
        "Real GDP at market prices, euro area, chain linked volume, "
        "annual growth rate",
        "Quarterly", "Annual percentage change", "Calendar and seasonally adjusted",
        "Eurostat / European Central Bank",
        "ربع سنوي — تقدير سريع ثم مراجعات", "المستوى كما هو (نمو سنوي)",
        "يُراجَع عدة مرات",
    ),
    EcbCategory.EUR_USD_REFERENCE: EcbSeriesSpec(
        "EXR", "D.USD.EUR.SP00.A", EcbCategory.EUR_USD_REFERENCE,
        "US dollar/Euro, ECB reference exchange rate, "
        "Average of observations through period",
        "Daily", "USD per EUR", "Not applicable",
        "European Central Bank",
        "يومياً نحو 16:00 بتوقيت وسط أوروبا", "المستوى كما هو",
        "لا تُراجَع",
    ),
}

SERIES_BY_KEY: dict[str, EcbSeriesSpec] = {
    spec.series_key: spec for spec in ECB_REGISTRY.values()
}


@dataclass
class EcbMacroDataProvider(MacroDataProvider):
    """بيانات منطقة اليورو الرسمية. **سياق فقط — لا تأذن بصفقة.**"""

    transport: ProviderTransport = None      # type: ignore[assignment]
    limiter: RateLimiter = None              # type: ignore[assignment]
    base_url: str = BASE_URL
    registry: dict[EcbCategory, EcbSeriesSpec] = field(
        default_factory=lambda: dict(ECB_REGISTRY)
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
        """**بلا مفتاح** — الوصول مفتوح، فالمزوّد مُعدّ دائماً بنيوياً."""
        return True

    def _url(self, spec: EcbSeriesSpec, *, last_n: int) -> str:
        params = urlencode({
            "format": "jsondata", "lastNObservations": last_n, "detail": "full",
        })
        return f"{self.base_url}{DATA_PATH}/{spec.dataflow}/{spec.key}?{params}"

    def observations(
        self,
        series_key: str,
        *,
        last_n: int = 24,
        now_utc: Optional[datetime] = None,
        require_validation: bool = True,
    ) -> ProviderResult[dict]:
        now = now_utc or datetime.now(timezone.utc)
        spec = SERIES_BY_KEY.get(series_key)
        if spec is None:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="UNKNOWN_SERIES_KEY",
                detail_ar=(
                    f"المفتاح {series_key} ليس في السجل. مفاتيح SDMX لا تُخمَّن — "
                    "تغيير بُعد واحد يعطي سلسلة أخرى تعمل وتجيب سؤالاً مختلفاً."
                ),
            )
        if require_validation and series_key not in self._validated:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="SERIES_NOT_VALIDATED",
                detail_ar=f"المفتاح {series_key} لم يُتحقَّق منه حيّاً بعد.",
            )

        try:
            response = get_with_retry(
                self.transport, self._url(spec, last_n=last_n), limiter=self.limiter,
            )
        except ProviderHttpError as exc:
            return ProviderResult(
                provider=PROVIDER_NAME, state=exc.state, retrieved_at_utc=now,
                error_code=exc.state.value, detail_ar=str(exc), http_status=exc.status,
            )

        parsed = parse_sdmx_json(response.body)
        if parsed is None:
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.MALFORMED,
                retrieved_at_utc=now, error_code="MALFORMED",
                detail_ar="بنية SDMX-JSON غير متوقَّعة — لا تُقرأ بالحدس.",
                http_status=response.status,
            )

        records: list[dict] = []
        for period, value in parsed:
            provenance = build_provenance(
                provider=PROVIDER_NAME,
                raw={"series": series_key, "period": period, "value": str(value)},
                source_id=f"ecb:{series_key}:{period}",
                retrieved_at_utc=now,
                event_timestamp_utc=_parse_period(period),
                original_source=spec.release_source,
                original_url=f"https://data.ecb.europa.eu/data/datasets/{spec.dataflow}",
                currency="EUR", category=spec.category.value, impact=None,
                license_class=LicenseClass.PUBLIC_OFFICIAL,
            )
            records.append({
                "series_key": series_key, "period": period,
                "value": str(value), "units": spec.units,
                "provenance": provenance.as_dict(),
            })

        return ProviderResult(
            provider=PROVIDER_NAME,
            state=ProviderResultState.FRESH if records else ProviderResultState.PARTIAL,
            records=tuple(reversed(records)),   # الأحدث أولاً
            retrieved_at_utc=now,
            detail_ar=f"{len(records)} ملاحظة للسلسلة {series_key}.",
            http_status=response.status,
        )

    def validate_series(
        self, series_key: str, *, now_utc: Optional[datetime] = None
    ) -> ProviderResult[dict]:
        """
        التحقّق هنا **وجودي**: هل يعيد المفتاح ملاحظات فعلاً؟ ECB لا تُعيد
        بيانات وصفية بنفس ثراء FRED، فالإثبات العملي هو أن السلسلة حيّة.
        """
        now = now_utc or datetime.now(timezone.utc)
        result = self.observations(
            series_key, last_n=1, now_utc=now, require_validation=False
        )
        if result.state is ProviderResultState.FRESH and result.records:
            self._validated.add(series_key)
            return ProviderResult(
                provider=PROVIDER_NAME, state=ProviderResultState.FRESH,
                records=result.records, retrieved_at_utc=now,
                detail_ar=f"المفتاح {series_key} حيّ ويعيد ملاحظات.",
            )
        return ProviderResult(
            provider=PROVIDER_NAME,
            state=result.state if result.is_failure else ProviderResultState.MALFORMED,
            retrieved_at_utc=now, error_code=result.error_code or "NO_OBSERVATIONS",
            detail_ar=result.detail_ar or "لم تُعِد السلسلة أي ملاحظة.",
        )

    def is_validated(self, series_key: str) -> bool:
        return series_key in self._validated

    @property
    def known_series_keys(self) -> tuple[str, ...]:
        return tuple(SERIES_BY_KEY)

    def series(
        self, *, keys: Sequence[str], as_of_utc: datetime
    ) -> dict[str, Sourced[Any]]:
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
                    # لا قيمة ⇒ لا لحظة رصد. `None` لا `as_of_utc`.
                    source_timestamp_utc=None,
                    retrieved_at_utc=as_of_utc,
                    note_ar=result.detail_ar or "غير متاح.",
                )
                continue
            latest = result.records[0]
            out[key] = Sourced(
                value=D(latest["value"]), source=PROVIDER_NAME,
                reliability=SourceReliability.OFFICIAL_PROVIDER,
                # لحظة الرصد من **فترة السلسلة** لا من وقت الجلب: سعرُ فائدة
                # نُشر قبل ثلاثة أشهر عمرُه ثلاثة أشهر، ووضعُ وقت الجلب هنا
                # يجعل حارس الطزاجة يمرّ على بيانٍ بائت وهو يظنّه طازجاً.
                source_timestamp_utc=period_to_utc(latest.get("period")),
                retrieved_at_utc=as_of_utc,
                note_ar=f"{SERIES_BY_KEY[key].official_title} — {latest['period']}",
            )
        return out


def parse_sdmx_json(body: Any) -> Optional[list[tuple[str, Any]]]:
    """
    يقرأ `[(الفترة، القيمة)]` من SDMX-JSON.

    الفهرسة بالمواضع: مفتاح الملاحظة رقمٌ يشير إلى `structure.dimensions
    .observation[0].values[i].id`. قراءتها بترتيب القاموس بدل هذا الجدول
    تُنتج تواريخ مبعثرة تبدو صحيحة.
    """
    if not isinstance(body, dict):
        return None
    datasets = body.get("dataSets")
    structure = body.get("structure")
    if not isinstance(datasets, list) or not datasets or not isinstance(structure, dict):
        return None

    dims = (structure.get("dimensions") or {}).get("observation")
    if not isinstance(dims, list) or not dims:
        return None
    periods = [str(v.get("id")) for v in (dims[0].get("values") or []) if isinstance(v, dict)]
    if not periods:
        return None

    series = (datasets[0] or {}).get("series")
    if not isinstance(series, dict) or not series:
        return None
    first = next(iter(series.values()))
    observations = (first or {}).get("observations")
    if not isinstance(observations, dict):
        return None

    out: list[tuple[str, Any]] = []
    for index_text, payload in observations.items():
        try:
            index = int(index_text)
        except (TypeError, ValueError):
            continue
        if not (0 <= index < len(periods)) or not isinstance(payload, list) or not payload:
            continue
        raw = payload[0]
        if raw is None:
            continue
        try:
            value = D(str(raw))
        except (InvalidOperation, ValueError):
            continue
        out.append((periods[index], value))
    out.sort(key=lambda pair: pair[0])
    return out


def _parse_period(period: str) -> Optional[datetime]:
    """`2026-08` أو `2026-Q2` أو `2026-08-28`."""
    text = str(period)
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    if "-Q" in text:
        try:
            year, quarter = text.split("-Q")
            month = (int(quarter) - 1) * 3 + 1
            return datetime(int(year), month, 1, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            return None
    return None


def registry_summary() -> dict:
    return {
        "version": ECB_REGISTRY_VERSION,
        "requires_key": False,
        "series": [spec.as_dict() for spec in ECB_REGISTRY.values()],
    }


__all__ = [
    "PROVIDER_NAME", "CREDENTIAL_NAME", "BASE_URL", "DATA_PATH", "LEGACY_HOST",
    "ECB_REGISTRY_VERSION", "EcbCategory", "EcbSeriesSpec", "ECB_REGISTRY",
    "SERIES_BY_KEY", "EcbMacroDataProvider", "parse_sdmx_json", "registry_summary",
]
