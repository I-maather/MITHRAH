"""
NEWS VERIFICATION — ستة مستويات، وقاعدة واحدة لا تُخترق.

    الخبر **لا يُنشئ صفقة أبداً**، مهما كان مستوى تحققه.
    أقصى ما يفعله الخبر المتحقَّق منه هو **رفع** الحظر الذي فرضه خبرٌ آخر.
    وأقصى ما يفعله الخبر غير المتحقَّق منه هو **الحجب**.

الاتجاه أحادي عمداً: الأخبار قناة **تقييد** لا قناة إشارة. سببه أن الربط بين
خبر واتجاه سعر ليس حتمياً — «تضخم أعلى من المتوقع» قد يرفع الدولار أو يخفضه
بحسب ما كان مُسعَّراً سلفاً. ونظامٌ يشتري على عنوان خبر يقامر على تفسير.

## المستويات

    OFFICIAL_PRIMARY        من المصدر الرسمي نفسه (الفيدرالي، ECB…)
    MULTI_SOURCE_VERIFIED   نطاقان مستقلان على الأقل، متوافقان
    TRUSTED_SINGLE_SOURCE   نطاق واحد من قائمة الثقة المُعلَنة
    AGGREGATED_UNVERIFIED   مُجمِّع (Finnhub مثلاً) بلا تأكيد مستقل
    UNVERIFIED              لا شيء مما سبق
    CONTRADICTED            مصدران يتناقضان في الاتجاه أو القيمة

## الاستقلال

نطاقان ليسا مستقلين إذا كان أحدهما ينقل عن الآخر. نكشف ذلك بثلاث علامات:
بصمة النص الخام نفسها · ذكر النطاق الآخر في حقل المصدر · فارق زمني أقل من
عتبة النقل. **الكشف ليس كاملاً** — ولذلك التصنيف الناتج يبقى محافظاً.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Sequence

from .provenance import Provenance, source_domain


class VerificationLevel(str, Enum):
    OFFICIAL_PRIMARY = "OFFICIAL_PRIMARY"
    MULTI_SOURCE_VERIFIED = "MULTI_SOURCE_VERIFIED"
    TRUSTED_SINGLE_SOURCE = "TRUSTED_SINGLE_SOURCE"
    AGGREGATED_UNVERIFIED = "AGGREGATED_UNVERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"


#: المستويات التي يجوز أن **ترفع** حظراً فرضه خبر آخر.
MAY_LIFT_A_BLOCK: frozenset[VerificationLevel] = frozenset({
    VerificationLevel.OFFICIAL_PRIMARY,
    VerificationLevel.MULTI_SOURCE_VERIFIED,
})

#: **لا مستوى** يجيز إنشاء صفقة. الثابت موجود ليُختبَر أنه فارغ.
MAY_CREATE_A_TRADE: frozenset[VerificationLevel] = frozenset()

assert not MAY_CREATE_A_TRADE, "لا مستوى تحقق يُنشئ صفقة — بالتصميم."


@dataclass(frozen=True)
class DomainPolicy:
    """
    سياسة الثقة بالنطاقات — **مُعلَنة وقابلة للضبط**، لا مبثوثة في الكود.

    النطاقات الرسمية محدودة ومعروفة ومملوكة لجهات إصدار. أما «الموثوقة» فهي
    قرار المالكة، ويُراجَع. لا نطاق يدخل بحكم الشهرة.
    """

    official_domains: frozenset[str] = frozenset({
        "federalreserve.gov",
        "ecb.europa.eu",
        "bls.gov",
        "bea.gov",
        "treasury.gov",
        "census.gov",
        "europa.eu",
        "ec.europa.eu",
    })
    trusted_domains: frozenset[str] = frozenset()
    #: مُجمِّعون معروفون: لا يُصنَّفون مصدراً مستقلاً بحال.
    aggregator_domains: frozenset[str] = frozenset({
        "finnhub.io",
    })
    version: str = "1.0.0"

    def classify_domain(self, domain: Optional[str]) -> VerificationLevel:
        if not domain:
            return VerificationLevel.UNVERIFIED
        normalized = domain.lower().removeprefix("www.")
        if any(
            normalized == d or normalized.endswith("." + d)
            for d in self.official_domains
        ):
            return VerificationLevel.OFFICIAL_PRIMARY
        if any(
            normalized == d or normalized.endswith("." + d)
            for d in self.aggregator_domains
        ):
            return VerificationLevel.AGGREGATED_UNVERIFIED
        if any(
            normalized == d or normalized.endswith("." + d)
            for d in self.trusted_domains
        ):
            return VerificationLevel.TRUSTED_SINGLE_SOURCE
        return VerificationLevel.UNVERIFIED

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "official_domains": sorted(self.official_domains),
            "trusted_domains": sorted(self.trusted_domains),
            "aggregator_domains": sorted(self.aggregator_domains),
        }


#: أقصى فارق زمني يُعتبر عنده خبران «حدثاً واحداً».
DEFAULT_CORROBORATION_WINDOW = timedelta(minutes=30)

#: تحت هذا الفارق مع تطابق العنوان، يُرجَّح النقل لا التأكيد المستقل.
SYNDICATION_WINDOW = timedelta(minutes=2)

#: كلمات اتجاه صريحة تُستعمل لكشف التناقض.
_UP_WORDS = ("raises", "hike", "higher", "beats", "above", "surge", "rises",
             "رفع", "أعلى", "ارتفاع", "تجاوز")
_DOWN_WORDS = ("cuts", "cut", "lower", "misses", "below", "falls", "drops",
               "خفض", "أدنى", "انخفاض", "دون")


def _direction(text: str) -> Optional[str]:
    low = text.lower()
    up = any(w in low for w in _UP_WORDS)
    down = any(w in low for w in _DOWN_WORDS)
    if up and not down:
        return "UP"
    if down and not up:
        return "DOWN"
    return None


def _normalise_headline(text: str) -> str:
    return re.sub(r"[^a-z0-9؀-ۿ ]+", " ", text.lower()).strip()


#: كلمات وظيفية لا تحمل تمييزاً. تُسقَط قبل المقارنة.
_STOPWORDS = frozenset({
    "by", "the", "a", "an", "of", "to", "in", "on", "for", "at", "and", "as",
    "is", "was", "its", "it", "from", "with", "after", "over",
    "في", "من", "على", "عن", "إلى", "بعد", "مع",
})


def _tokens(text: str) -> set[str]:
    """
    كلمات مميّزة. الحد الأدنى حرفان **لا أربعة**: `ECB` و`Fed` و`CPI` و`GDP`
    هي أكثر الكلمات تمييزاً في عنوان مالي، وإسقاطها لقصرها يجعل عنوانين عن
    الحدث نفسه يبدوان غريبين.
    """
    return {
        t for t in _normalise_headline(text).split()
        if len(t) >= 2 and t not in _STOPWORDS
    }


def _token_overlap(a: str, b: str) -> float:
    """
    **معامل التداخل** لا Jaccard: التقاطع مقسوماً على أصغر المجموعتين.

    Jaccard يعاقب العنوان الأطول على كونه أكثر تفصيلاً — و«ECB raises rates by
    25 basis points» أطول من «ECB raises rates by 25bp» لأنه أوضح، لا لأنه عن
    حدث آخر. ويُشترط تقاطع كلمتين على الأقل كي لا يتطابق عنوانان قصيران
    بالصدفة.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    shared = ta & tb
    if len(shared) < 2:
        return 0.0
    return len(shared) / min(len(ta), len(tb))


@dataclass(frozen=True)
class NewsCandidate:
    """خبر خام قبل التصنيف."""

    headline: str
    provenance: Provenance
    summary: str = ""
    currencies: tuple[str, ...] = ()

    @property
    def domain(self) -> Optional[str]:
        return self.provenance.domain or source_domain(self.provenance.original_url)


@dataclass(frozen=True)
class VerificationOutcome:
    level: VerificationLevel
    reason_ar: str
    corroborating_domains: tuple[str, ...] = ()
    contradicting_domains: tuple[str, ...] = ()
    suspected_syndication: bool = False

    @property
    def may_create_trade(self) -> bool:
        """**ثابتة False.** موجودة كي تُختبَر لا كي تُستشار."""
        return False

    @property
    def may_lift_block(self) -> bool:
        return self.level in MAY_LIFT_A_BLOCK

    def as_dict(self) -> dict:
        return {
            "level": self.level.value,
            "reason_ar": self.reason_ar,
            "corroborating_domains": list(self.corroborating_domains),
            "contradicting_domains": list(self.contradicting_domains),
            "suspected_syndication": self.suspected_syndication,
            "may_create_trade": False,
            "may_lift_block": self.may_lift_block,
        }


def classify_news(
    candidate: NewsCandidate,
    others: Sequence[NewsCandidate],
    *,
    policy: Optional[DomainPolicy] = None,
    corroboration_window: timedelta = DEFAULT_CORROBORATION_WINDOW,
    min_overlap: float = 0.5,
) -> VerificationOutcome:
    """
    يصنّف خبراً واحداً في ضوء بقية الأخبار المتاحة.

    الترتيب مقصود: **التناقض يُفحص أولاً**. خبرٌ رسمي يناقضه رسميٌّ آخر ليس
    «رسمياً» — هو تناقض يجب أن يوقف، لا أن يمرّ بأعلى درجة ثقة.
    """
    policy = policy or DomainPolicy()
    domain = candidate.domain
    base_level = policy.classify_domain(domain)

    matches: list[NewsCandidate] = []
    contradicting: list[str] = []
    syndication_suspected = False

    own_direction = _direction(candidate.headline + " " + candidate.summary)
    own_time = candidate.provenance.event_timestamp_utc

    for other in others:
        if other is candidate:
            continue
        other_domain = other.domain
        if not other_domain or other_domain == domain:
            continue
        if _token_overlap(candidate.headline, other.headline) < min_overlap:
            continue

        other_time = other.provenance.event_timestamp_utc
        if own_time and other_time and abs(own_time - other_time) > corroboration_window:
            continue

        other_direction = _direction(other.headline + " " + other.summary)
        if own_direction and other_direction and own_direction != other_direction:
            contradicting.append(other_domain)
            continue

        # كشف النقل: بصمة خام واحدة، أو ذكر النطاق الآخر، أو تزامن شديد.
        same_payload = (
            candidate.provenance.raw_checksum == other.provenance.raw_checksum
        )
        names_the_other = bool(
            other.provenance.original_source
            and domain
            and domain.split(".")[0] in other.provenance.original_source.lower()
        )
        too_simultaneous = bool(
            own_time and other_time and abs(own_time - other_time) < SYNDICATION_WINDOW
            and _token_overlap(candidate.headline, other.headline) > 0.9
        )
        if same_payload or names_the_other or too_simultaneous:
            syndication_suspected = True
            continue

        matches.append(other)

    if contradicting:
        return VerificationOutcome(
            VerificationLevel.CONTRADICTED,
            "مصدران يتناقضان في الاتجاه — لا يُحسم بالترجيح، ويبقى الحظر.",
            contradicting_domains=tuple(sorted(set(contradicting))),
            suspected_syndication=syndication_suspected,
        )

    if base_level is VerificationLevel.OFFICIAL_PRIMARY:
        return VerificationOutcome(
            VerificationLevel.OFFICIAL_PRIMARY,
            f"من مصدر رسمي مُعلَن ({domain}).",
            suspected_syndication=syndication_suspected,
        )

    independent = tuple(sorted({m.domain for m in matches if m.domain}))
    if len(independent) >= 1:
        return VerificationOutcome(
            VerificationLevel.MULTI_SOURCE_VERIFIED,
            f"نطاق مستقل إضافي أكّد الحدث: {'، '.join(independent)}.",
            corroborating_domains=independent,
            suspected_syndication=syndication_suspected,
        )

    if base_level is VerificationLevel.TRUSTED_SINGLE_SOURCE:
        return VerificationOutcome(
            VerificationLevel.TRUSTED_SINGLE_SOURCE,
            f"نطاق موثوق واحد بلا تأكيد مستقل ({domain}).",
            suspected_syndication=syndication_suspected,
        )
    if base_level is VerificationLevel.AGGREGATED_UNVERIFIED:
        return VerificationOutcome(
            VerificationLevel.AGGREGATED_UNVERIFIED,
            "عنوان من مُجمِّع بلا تأكيد مستقل — يحجب ولا يُنشئ صفقة.",
            suspected_syndication=syndication_suspected,
        )
    return VerificationOutcome(
        VerificationLevel.UNVERIFIED,
        "لا مصدر رسمي ولا موثوق ولا تأكيد مستقل.",
        suspected_syndication=syndication_suspected,
    )


__all__ = [
    "VerificationLevel",
    "MAY_LIFT_A_BLOCK",
    "MAY_CREATE_A_TRADE",
    "DomainPolicy",
    "NewsCandidate",
    "VerificationOutcome",
    "classify_news",
    "DEFAULT_CORROBORATION_WINDOW",
    "SYNDICATION_WINDOW",
]
