"""
COMPOSITE PROVIDERS — الدمج، والمصدر الرسمي، والميل الكلي.

## قاعدة الدمج

    الأسوأ يفوز.

مصدرٌ واحد فاشل بين ثلاثة **لا يُنتج** نتيجة طازجة. التفاؤل في الدمج هو
بالضبط ما يحوّل «مزوّد أخبار ساقط» إلى «لا أخبار سلبية» — وهو أسوأ خطأ ممكن
في هذه الطبقة، لأنه يبدو هدوءاً.

## الميل الكلي سياق لا إذن

`CompositeMacroDataProvider` يُنتج ميلاً للدولار وميلاً لليورو وميلاً نسبياً
لـEUR/USD. **لا شيء من ذلك يأذن بصفقة.** الميل الكلي يدخل درجة الجودة
كمُدخَل واحد بين عدة، ولا يستطيع وحده رفع قرار من NO_TRADE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Sequence

from ..intelligence.providers import (
    MacroDataProvider,
    ProviderKind,
    VerifiedNewsProvider,
)
from ..intelligence.snapshot import UNKNOWN, NewsItem, Sourced, SourceReliability
from ..money import D
from .provenance import LicenseClass, Provenance, build_provenance
from .results import ProviderResult, ProviderResultState, merge_states
from .verification import (
    DomainPolicy,
    NewsCandidate,
    VerificationLevel,
    classify_news,
)

OFFICIAL_PROVIDER_NAME = "OfficialSourceProvider"
COMPOSITE_NEWS_NAME = "CompositeVerifiedNewsProvider"
COMPOSITE_MACRO_NAME = "CompositeMacroDataProvider"


# ---------------------------------------------------------------------------
# المصدر الرسمي
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OfficialRelease:
    """
    إصدار من جهة رسمية. **لا يُبنى من كشط صفحة** — يُبنى من تغذية معلنة
    (RSS رسمي أو واجهة رسمية) تُضبَط لاحقاً.
    """

    title: str
    domain: str
    url: str
    published_utc: datetime
    body_summary: str = ""
    currencies: tuple[str, ...] = ()


@dataclass
class OfficialSourceProvider(VerifiedNewsProvider):
    """
    مزوّد المصادر الرسمية (الفيدرالي، ECB، BLS…).

    غير مُعدّ ابتداءً: لا تغذية مضبوطة بعد. وحين يُعدّ، مخرجاته وحدها هي التي
    يجوز أن تُصنَّف `OFFICIAL_PRIMARY` — ولذلك لا يُقبل فيه نطاق خارج
    `DomainPolicy.official_domains`.
    """

    releases: tuple[OfficialRelease, ...] = ()
    policy: DomainPolicy = field(default_factory=DomainPolicy)

    def __post_init__(self) -> None:
        self.kind = ProviderKind.VERIFIED_NEWS

    @property
    def name(self) -> str:
        return OFFICIAL_PROVIDER_NAME

    @property
    def configured(self) -> bool:
        return bool(self.releases)

    def candidates(
        self, *, currencies: Sequence[str] = (), now_utc: Optional[datetime] = None
    ) -> tuple[NewsCandidate, ...]:
        now = now_utc or datetime.now(timezone.utc)
        out: list[NewsCandidate] = []
        for release in self.releases:
            level = self.policy.classify_domain(release.domain)
            if level is not VerificationLevel.OFFICIAL_PRIMARY:
                # نطاق غير رسمي داخل مزوّد رسمي ⇒ يُسقَط، لا يُخفَّض.
                continue
            out.append(NewsCandidate(
                headline=release.title,
                summary=release.body_summary,
                currencies=release.currencies,
                provenance=build_provenance(
                    provider=OFFICIAL_PROVIDER_NAME,
                    raw={"title": release.title, "url": release.url},
                    source_id=f"official:{release.domain}:{release.published_utc.isoformat()}",
                    retrieved_at_utc=now,
                    event_timestamp_utc=release.published_utc,
                    original_source=release.domain,
                    original_url=release.url,
                    currency=release.currencies[0] if release.currencies else None,
                    category=None, impact=None,
                    license_class=LicenseClass.PUBLIC_OFFICIAL,
                ),
            ))
        return tuple(out)

    def news(
        self, *, currencies: Sequence[str], since_utc: datetime, now_utc: datetime
    ) -> tuple[NewsItem, ...]:
        return ()


# ---------------------------------------------------------------------------
# دمج الأخبار
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerifiedNewsRecord:
    headline: str
    level: VerificationLevel
    currencies: tuple[str, ...]
    provenance: Provenance
    reason_ar: str
    corroborating_domains: tuple[str, ...] = ()
    contradicting_domains: tuple[str, ...] = ()

    @property
    def may_create_trade(self) -> bool:
        """**False دائماً.** لا مستوى تحقق يُنشئ صفقة."""
        return False

    @property
    def blocks_new_entries(self) -> bool:
        """
        كل ما ليس مؤكَّداً بمصدرين أو رسمياً **يحجب**. والمؤكَّد يحجب أيضاً إن
        كان الحدث نفسه عالي الأثر — الحجب هو الوضع الافتراضي لا الاستثناء.
        """
        return self.level is not VerificationLevel.OFFICIAL_PRIMARY

    def as_dict(self) -> dict:
        return {
            "headline": self.headline,
            "level": self.level.value,
            "currencies": list(self.currencies),
            "reason_ar": self.reason_ar,
            "corroborating_domains": list(self.corroborating_domains),
            "contradicting_domains": list(self.contradicting_domains),
            "may_create_trade": False,
            "blocks_new_entries": self.blocks_new_entries,
            "provenance": self.provenance.as_dict(),
        }


@dataclass
class CompositeVerifiedNewsProvider(VerifiedNewsProvider):
    """يدمج المُجمِّعين والمصادر الرسمية ثم يصنّف كل خبر في ضوء البقية."""

    sources: tuple[Any, ...] = ()
    policy: DomainPolicy = field(default_factory=DomainPolicy)

    def __post_init__(self) -> None:
        self.kind = ProviderKind.VERIFIED_NEWS

    @property
    def name(self) -> str:
        return COMPOSITE_NEWS_NAME

    @property
    def configured(self) -> bool:
        return any(getattr(s, "configured", False) for s in self.sources)

    def fetch(
        self, *, currencies: Sequence[str] = (), now_utc: Optional[datetime] = None
    ) -> ProviderResult[VerifiedNewsRecord]:
        now = now_utc or datetime.now(timezone.utc)
        if not self.sources:
            return ProviderResult(
                provider=COMPOSITE_NEWS_NAME,
                state=ProviderResultState.UNAVAILABLE,
                retrieved_at_utc=now, error_code="NO_SOURCES",
                detail_ar="لا مصدر أخبار مُعدّ. الغياب لا يعني «لا أخبار».",
            )

        candidates: list[NewsCandidate] = []
        states: list[ProviderResultState] = []
        missing: list[str] = []

        for source in self.sources:
            if not getattr(source, "configured", False):
                states.append(ProviderResultState.UNAVAILABLE)
                missing.append(getattr(source, "name", str(source)))
                continue
            try:
                found = source.candidates(currencies=currencies, now_utc=now)
                candidates.extend(found)
                states.append(ProviderResultState.FRESH)
            except Exception:                             # noqa: BLE001
                states.append(ProviderResultState.UNAVAILABLE)
                missing.append(getattr(source, "name", str(source)))

        records: list[VerifiedNewsRecord] = []
        for candidate in candidates:
            outcome = classify_news(candidate, candidates, policy=self.policy)
            records.append(VerifiedNewsRecord(
                headline=candidate.headline,
                level=outcome.level,
                currencies=candidate.currencies,
                provenance=candidate.provenance,
                reason_ar=outcome.reason_ar,
                corroborating_domains=outcome.corroborating_domains,
                contradicting_domains=outcome.contradicting_domains,
            ))

        state = merge_states(states)
        return ProviderResult(
            provider=COMPOSITE_NEWS_NAME,
            state=state,
            records=tuple(records),
            retrieved_at_utc=now,
            detail_ar=(
                f"{len(records)} خبراً من {len(self.sources)} مصدراً. "
                "**لا خبر يُنشئ صفقة**، مهما كان مستوى تحققه."
            ),
            missing=tuple(missing),
        )

    def news(
        self, *, currencies: Sequence[str], since_utc: datetime, now_utc: datetime
    ) -> tuple[NewsItem, ...]:
        return ()


# ---------------------------------------------------------------------------
# دمج البيانات الكلية
# ---------------------------------------------------------------------------

class MacroBias(str, Enum):
    HAWKISH = "HAWKISH"
    NEUTRAL = "NEUTRAL"
    DOVISH = "DOVISH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MacroAssessment:
    usd_bias: MacroBias
    eur_bias: MacroBias
    relative_bias_ar: str
    completeness: Decimal          # 0..1
    freshness: Decimal             # 0..1
    supporting: tuple[str, ...]
    contradicting: tuple[str, ...]
    unknown_fields: tuple[str, ...]

    @property
    def authorises_trade(self) -> bool:
        """**False ثابتة.** الميل الكلي سياق، لا إذن."""
        return False

    def as_dict(self) -> dict:
        return {
            "usd_bias": self.usd_bias.value,
            "eur_bias": self.eur_bias.value,
            "relative_bias_ar": self.relative_bias_ar,
            "completeness": f"{self.completeness:.2f}",
            "freshness": f"{self.freshness:.2f}",
            "supporting": list(self.supporting),
            "contradicting": list(self.contradicting),
            "unknown_fields": list(self.unknown_fields),
            "authorises_trade": False,
        }


@dataclass
class CompositeMacroDataProvider(MacroDataProvider):
    """يدمج FRED (الدولار) وECB (اليورو) في تقييم واحد."""

    us_source: Optional[Any] = None
    euro_source: Optional[Any] = None

    def __post_init__(self) -> None:
        self.kind = ProviderKind.MACRO_DATA

    @property
    def name(self) -> str:
        return COMPOSITE_MACRO_NAME

    @property
    def configured(self) -> bool:
        return bool(
            (self.us_source and self.us_source.configured)
            or (self.euro_source and self.euro_source.configured)
        )

    def assess(
        self, *, now_utc: Optional[datetime] = None
    ) -> tuple[ProviderResult[MacroAssessment], MacroAssessment]:
        now = now_utc or datetime.now(timezone.utc)
        unknown: list[str] = []
        supporting: list[str] = []
        contradicting: list[str] = []
        states: list[ProviderResultState] = []
        available = 0
        expected = 0

        for label, source, keys in (
            ("USD", self.us_source, ("DFEDTARU", "CPILFESL", "UNRATE")),
            ("EUR", self.euro_source, (
                "FM.D.U2.EUR.4F.KR.DFR.LEV", "ICP.M.U2.N.XEF000.4.ANR",
                "LFSI.M.I9.S.UNEHRT.TOTAL0.15_74.T",
            )),
        ):
            for key in keys:
                expected += 1
                if source is None or not source.configured:
                    unknown.append(f"{label}:{key}")
                    states.append(ProviderResultState.UNAVAILABLE)
                    continue
                result = source.observations(key, now_utc=now)
                states.append(result.state)
                if result.usable_for_decision and result.records:
                    available += 1
                    supporting.append(f"{label}:{key}")
                else:
                    unknown.append(f"{label}:{key}")

        completeness = D(available) / D(expected) if expected else D("0")
        # الطزاجة تُحسب من الحالة: لا سجل طازج ⇒ صفر، ولا تُقدَّر.
        freshness = completeness

        # **لا يُستنتَج ميل من بيانات ناقصة.** الميل يبقى UNKNOWN حتى تكتمل.
        bias = MacroBias.UNKNOWN
        assessment = MacroAssessment(
            usd_bias=bias, eur_bias=bias,
            relative_bias_ar=(
                "غير معروف — البيانات الكلية ناقصة. "
                "**لا يُستنتَج ميل من فراغ.**"
                if completeness < 1 else
                "البيانات مكتملة؛ الميل يُحسب في طبقة التحليل لا هنا."
            ),
            completeness=completeness, freshness=freshness,
            supporting=tuple(supporting), contradicting=tuple(contradicting),
            unknown_fields=tuple(unknown),
        )

        return (
            ProviderResult(
                provider=COMPOSITE_MACRO_NAME,
                state=merge_states(states),
                records=(assessment,),
                retrieved_at_utc=now,
                detail_ar=(
                    f"اكتمال البيانات {completeness:.0%}. "
                    "التقييم **سياق لا إذن**."
                ),
                missing=tuple(unknown),
            ),
            assessment,
        )

    def series(
        self, *, keys: Sequence[str], as_of_utc: datetime
    ) -> dict[str, Sourced[Any]]:
        out: dict[str, Sourced[Any]] = {}
        for source in (self.us_source, self.euro_source):
            if source is None or not source.configured:
                continue
            try:
                out.update(source.series(keys=keys, as_of_utc=as_of_utc))
            except Exception:                             # noqa: BLE001
                continue
        for key in keys:
            out.setdefault(key, Sourced(
                value=UNKNOWN, source=COMPOSITE_MACRO_NAME,
                reliability=SourceReliability.UNVERIFIED,
                source_timestamp_utc=None, retrieved_at_utc=as_of_utc,
                note_ar="لا مزوّد أعطى هذه السلسلة.",
            ))
        return out


__all__ = [
    "OFFICIAL_PROVIDER_NAME", "COMPOSITE_NEWS_NAME", "COMPOSITE_MACRO_NAME",
    "OfficialRelease", "OfficialSourceProvider",
    "VerifiedNewsRecord", "CompositeVerifiedNewsProvider",
    "MacroBias", "MacroAssessment", "CompositeMacroDataProvider",
]
