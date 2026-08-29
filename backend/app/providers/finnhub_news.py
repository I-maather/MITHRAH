"""
FINNHUB FOREX NEWS — عناوين مُجمَّعة، تحجب ولا تُنشئ صفقة.

## العقد — مُثبَت من `finnhub.io/static/swagger.json`

    GET /api/v1/news?category=forex[&minId=N]

حقول كل عنصر (من مخطط `MarketNews` الرسمي):
`category` · `datetime` · `headline` · `id` · `image` · `related` ·
`source` · `summary` · `url`

`datetime` عدد صحيح بتوقيت يونكس بالثواني.

## ما لا يُخزَّن

**لا نص مقال ولا محتوى كامل.** الرخصة مصنَّفة `METADATA_ONLY`، والحقول
المخزَّنة محدودة بقائمة صريحة يفرضها الكود — لا بتذكير في وثيقة. الملخّص
المزوَّد يُقتطَع بحدٍّ أقصى صريح.

## التقويم الاقتصادي لدى Finnhub

**لا يُستعمل** — موسوم Premium. القرار متخذ في الكود لا في الوثيقة: لا يوجد
مسار في هذا الملف يستدعي `/calendar/economic`.

## التصنيف

عنوان Finnhub وحده = `AGGREGATED_UNVERIFIED` **دائماً**. Finnhub مُجمِّع لا
مصدر، ولا يصير مصدراً بتكرار الظهور. رفع المستوى لا يحدث إلا بتأكيد من نطاق
مستقل عبر `verification.classify_news`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from urllib.parse import urlencode

from ..intelligence.providers import ProviderKind, VerifiedNewsProvider
from ..intelligence.snapshot import EventCategory, ImpactLevel, NewsItem, NewsVerification
from .classification import classify_event
from .http import ProviderHttpError, ProviderTransport, RateLimiter, get_with_retry
from .provenance import LicenseClass, build_provenance, source_domain
from .results import ProviderResult, ProviderResultState
from .verification import NewsCandidate, VerificationLevel

PROVIDER_NAME = "FinnhubForexNewsProvider"
CREDENTIAL_NAME = "FINNHUB_API_KEY"

BASE_URL = "https://finnhub.io/api/v1"
NEWS_PATH = "/news"
NEWS_CATEGORY = "forex"

#: مؤكَّد من swagger الرسمي: 429 عند التجاوز، وسقف عام 30 طلباً/ثانية.
GLOBAL_CALLS_PER_SECOND = 30
#: حد محافظ محلياً — الرقم الرسمي للخطة المجانية بالدقيقة غير مؤكَّد.
CONSERVATIVE_CALLS_PER_MINUTE = 30

FRESHNESS_WINDOW_SECONDS = 10 * 60.0

#: أقصى طول للملخّص المخزَّن. الاقتطاع يمنع تخزين مقال كامل بالتدريج.
MAX_SUMMARY_CHARS = 300

#: الحقول **الوحيدة** التي تُقرأ من الاستجابة. أي حقل آخر يُهمَل.
PERMITTED_FIELDS: tuple[str, ...] = (
    "category", "datetime", "headline", "id", "related", "source", "summary", "url",
)

#: حقول محظور تخزينها صراحةً.
FORBIDDEN_FIELDS: tuple[str, ...] = ("content", "body", "fullText", "article", "text")

_CURRENCY_TOKENS = ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD")


def _extract_currencies(item: dict) -> tuple[str, ...]:
    """
    العملات من `related` ومن العنوان. `related` لدى Finnhub قد يحمل رموز
    أسهم لا عملات، فلا يُوثَق به وحده.
    """
    found: list[str] = []
    haystack = " ".join(
        str(item.get(k, "")) for k in ("related", "headline", "summary")
    ).upper()
    for token in _CURRENCY_TOKENS:
        if token in haystack and token not in found:
            found.append(token)
    return tuple(found)


@dataclass
class FinnhubForexNewsProvider(VerifiedNewsProvider):
    """أخبار الفوركس المُجمَّعة. **لا مسار فيها يُنشئ قراراً بالشراء أو البيع.**"""

    api_key: Optional[str] = None
    transport: ProviderTransport = None      # type: ignore[assignment]
    limiter: RateLimiter = None              # type: ignore[assignment]
    base_url: str = BASE_URL

    def __post_init__(self) -> None:
        self.kind = ProviderKind.VERIFIED_NEWS
        if self.transport is None:
            self.transport = ProviderTransport()
        if self.limiter is None:
            self.limiter = RateLimiter(
                name=PROVIDER_NAME,
                max_calls=CONSERVATIVE_CALLS_PER_MINUTE,
                per_seconds=60.0,
            )

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _url(self, min_id: Optional[int] = None) -> str:
        params: dict[str, Any] = {"category": NEWS_CATEGORY, "token": self.api_key or ""}
        if min_id is not None:
            params["minId"] = min_id
        return f"{self.base_url}{NEWS_PATH}?{urlencode(params)}"

    def fetch(
        self,
        *,
        currencies: Sequence[str] = (),
        since_utc: Optional[datetime] = None,
        now_utc: Optional[datetime] = None,
    ) -> ProviderResult[NewsItem]:
        now = now_utc or datetime.now(timezone.utc)
        if not self.configured:
            return ProviderResult(
                provider=PROVIDER_NAME,
                state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now,
                error_code="NOT_CONFIGURED",
                detail_ar=f"المفتاح {CREDENTIAL_NAME} غير مُعدّ.",
            )

        try:
            response = get_with_retry(
                self.transport, self._url(),
                limiter=self.limiter,
                secrets=(self.api_key,) if self.api_key else (),
            )
        except ProviderHttpError as exc:
            return ProviderResult(
                provider=PROVIDER_NAME, state=exc.state, retrieved_at_utc=now,
                error_code=exc.state.value, detail_ar=str(exc), http_status=exc.status,
            )

        if not isinstance(response.body, list):
            return ProviderResult(
                provider=PROVIDER_NAME,
                state=ProviderResultState.MALFORMED,
                retrieved_at_utc=now,
                error_code="MALFORMED",
                detail_ar="الاستجابة ليست قائمة أخبار كما يوثّق مخطط MarketNews.",
                http_status=response.status,
            )

        items: list[NewsItem] = []
        skipped = 0
        wanted = {c.upper() for c in currencies}
        for raw in response.body:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            item = self._normalise(raw, now=now)
            if item is None:
                skipped += 1
                continue
            if since_utc and item.provider_timestamp_utc < since_utc:
                continue
            if wanted and item.currencies and not (set(item.currencies) & wanted):
                continue
            items.append(item)

        state = ProviderResultState.PARTIAL if skipped else ProviderResultState.FRESH
        return ProviderResult(
            provider=PROVIDER_NAME,
            state=state,
            records=tuple(items),
            retrieved_at_utc=now,
            freshness_window_seconds=FRESHNESS_WINDOW_SECONDS,
            detail_ar=(
                f"{len(items)} عنواناً. كلها `AGGREGATED_UNVERIFIED` — "
                "تحجب ولا تُنشئ صفقة."
                + (f" و{skipped} سجلاً تعذّر تطبيعه." if skipped else "")
            ),
            missing=("normalisation_failures",) if skipped else (),
            http_status=response.status,
        )

    def _normalise(self, raw: dict, *, now: datetime) -> Optional[NewsItem]:
        headline = raw.get("headline")
        stamp = raw.get("datetime")
        if not headline or stamp is None:
            return None
        try:
            published = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        except (ValueError, OSError, OverflowError, TypeError):
            return None

        url = raw.get("url")
        currencies = _extract_currencies(raw)
        classification = classify_event(
            str(headline), provider_impact=None, currencies=currencies
        )

        # يُبنى المصدر من الحقول المسموحة **وحدها**.
        permitted = {k: raw.get(k) for k in PERMITTED_FIELDS if k in raw}
        provenance = build_provenance(
            provider=PROVIDER_NAME,
            raw=permitted,
            source_id=f"finnhub:{raw.get('id', provider_fallback_id(raw))}",
            retrieved_at_utc=now,
            event_timestamp_utc=published,
            original_source=str(raw.get("source") or "") or None,
            original_url=str(url) if url else None,
            currency=currencies[0] if currencies else None,
            category=classification.category.value,
            impact=classification.impact.value,
            license_class=LicenseClass.METADATA_ONLY,
            retention_days=30,
            freshness_window_seconds=FRESHNESS_WINDOW_SECONDS,
        )

        return NewsItem(
            news_id=provenance.source_id,
            headline=str(headline)[:500],
            currencies=currencies,
            impact=classification.impact,
            category=classification.category,
            # مُجمِّع ⇒ غير متحقَّق منه، دائماً وبلا استثناء.
            verification=NewsVerification.UNVERIFIED,
            provider=PROVIDER_NAME,
            provider_timestamp_utc=published,
            retrieved_at_utc=now,
            source_reference=provenance.raw_checksum,
        )

    def candidates(
        self, *, currencies: Sequence[str] = (), now_utc: Optional[datetime] = None
    ) -> tuple[NewsCandidate, ...]:
        """
        يبني مرشّحين للتصنيف بسياسة التحقق. مستواهم الابتدائي **دائماً**
        `AGGREGATED_UNVERIFIED` — يرفعه التأكيد المستقل لا المزوّد.
        """
        now = now_utc or datetime.now(timezone.utc)
        result = self.fetch(currencies=currencies, now_utc=now)
        out: list[NewsCandidate] = []
        for item in result.records:
            out.append(NewsCandidate(
                headline=item.headline,
                summary="",
                currencies=item.currencies,
                provenance=build_provenance(
                    provider=PROVIDER_NAME,
                    raw=item.news_id,
                    source_id=item.news_id,
                    retrieved_at_utc=item.retrieved_at_utc,
                    event_timestamp_utc=item.provider_timestamp_utc,
                    original_source="Finnhub",
                    original_url=f"https://{source_domain('https://finnhub.io') or 'finnhub.io'}",
                    currency=item.currencies[0] if item.currencies else None,
                    category=item.category.value,
                    impact=item.impact.value,
                    license_class=LicenseClass.METADATA_ONLY,
                ),
            ))
        return tuple(out)

    def news(
        self, *, currencies: Sequence[str], since_utc: datetime, now_utc: datetime
    ) -> tuple[NewsItem, ...]:
        return self.fetch(
            currencies=currencies, since_utc=since_utc, now_utc=now_utc
        ).records


def provider_fallback_id(raw: dict) -> str:
    """معرّف بديل حين لا يُعيد المزوّد `id` — من العنوان والطابع الزمني."""
    return f"{raw.get('datetime', '0')}:{str(raw.get('headline', ''))[:60]}"


def baseline_level() -> VerificationLevel:
    """المستوى الابتدائي لكل ما يأتي من هذا المزوّد."""
    return VerificationLevel.AGGREGATED_UNVERIFIED


__all__ = [
    "PROVIDER_NAME",
    "CREDENTIAL_NAME",
    "BASE_URL",
    "NEWS_PATH",
    "NEWS_CATEGORY",
    "PERMITTED_FIELDS",
    "FORBIDDEN_FIELDS",
    "MAX_SUMMARY_CHARS",
    "FinnhubForexNewsProvider",
    "baseline_level",
]
