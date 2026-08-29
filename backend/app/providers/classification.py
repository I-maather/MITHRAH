"""
EVENT CLASSIFICATION — سياسة أهمية **محلية ومُرقَّمة**، لا ثقة عمياء بالمزوّد.

## لماذا لا نثق بحقل `impact` من المزوّد

ثلاثة أسباب عملية:

  1. المزوّدون يختلفون في المقياس (Low/Medium/High مقابل 1/2/3 مقابل نجوم).
  2. المقياس عام لكل الأزواج، ونحن نتداول EUR/USD وحده — «مرتفع الأثر»
     للين الياباني قد لا يعنينا، والعكس.
  3. المزوّد قد يغيّر تصنيفه بلا إعلان، فتتغيّر عتبات الحظر عندنا صامتةً.

فالمزوّد يُعطي **إشارة**، والسياسة المحلية المُرقَّمة تُعطي **القرار**.
والقاعدة: **الأشد يفوز** — إن قال المزوّد HIGH وقالت سياستنا MEDIUM، فالنتيجة
HIGH. تشديدٌ نقبله، وتخفيفٌ لا نقبله.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from ..intelligence.snapshot import EventCategory, ImpactLevel

#: إصدار سياسة التصنيف. يُحفَظ مع كل سجل مُصنَّف كي يُعرَف بأي قواعد صُنِّف.
CLASSIFICATION_POLICY_VERSION = "1.0.0"

#: العملات المسموح تتبّعها في هذه المرحلة.
INITIAL_CURRENCY_ALLOWLIST: tuple[str, ...] = ("USD", "EUR")

#: أنماط الأحداث عالية الأثر. الترتيب مهم: أول تطابق يفوز، والأكثر تحديداً أولاً.
_HIGH_IMPACT_PATTERNS: tuple[tuple[str, EventCategory], ...] = (
    # قرارات البنوك المركزية ومؤتمراتها
    (r"\b(fomc|federal funds|rate decision|interest rate decision)\b", EventCategory.CENTRAL_BANK_RATE),
    (r"\b(ecb|fed)\b.*\b(rate|decision|monetary policy)\b", EventCategory.CENTRAL_BANK_RATE),
    (r"\b(deposit facility|main refinancing|refi rate)\b", EventCategory.CENTRAL_BANK_RATE),
    (r"\b(press conference|monetary policy statement)\b", EventCategory.CENTRAL_BANK_SPEECH),
    (r"\b(powell|lagarde)\b.*\b(speaks|speech|testimony|remarks)\b", EventCategory.CENTRAL_BANK_SPEECH),
    (r"\b(fomc minutes|ecb monetary policy meeting accounts)\b", EventCategory.CENTRAL_BANK_SPEECH),
    # التضخم
    (r"\bcore (cpi|hicp|inflation)\b", EventCategory.INFLATION),
    (r"\b(cpi|hicp)\b", EventCategory.INFLATION),
    (r"\bcore pce\b", EventCategory.INFLATION),
    (r"\bpce price index\b", EventCategory.INFLATION),
    # التوظيف
    (r"\b(non[- ]?farm payrolls?|nfp)\b", EventCategory.NFP),
    (r"\b(unemployment rate|employment change|jobless)\b", EventCategory.EMPLOYMENT),
    # النمو والنشاط
    (r"\b(gdp|gross domestic product)\b", EventCategory.GDP),
    (r"\bretail sales\b", EventCategory.RETAIL_SALES),
    (r"\b(pmi|purchasing managers)\b", EventCategory.PMI),
    # أحداث طارئة غير مجدولة
    (r"\b(emergency|unscheduled|intermeeting)\b.*\b(meeting|decision|cut|hike)\b",
     EventCategory.SYSTEMIC_RISK),
)

_MEDIUM_IMPACT_PATTERNS: tuple[tuple[str, EventCategory], ...] = (
    (r"\b(ppi|producer price)\b", EventCategory.INFLATION),
    (r"\b(trade balance|current account)\b", EventCategory.OTHER),
    (r"\b(consumer confidence|sentiment|ifo|zew)\b", EventCategory.OTHER),
    (r"\b(industrial production|factory orders|durable goods)\b", EventCategory.OTHER),
    (r"\bjobless claims\b", EventCategory.EMPLOYMENT),
)

#: قيم `impact` كما ترد من المزوّدين، بمقاييسها المختلفة.
_PROVIDER_IMPACT_MAP: dict[str, ImpactLevel] = {
    "high": ImpactLevel.HIGH, "3": ImpactLevel.HIGH, "***": ImpactLevel.HIGH,
    "medium": ImpactLevel.MEDIUM, "moderate": ImpactLevel.MEDIUM,
    "2": ImpactLevel.MEDIUM, "**": ImpactLevel.MEDIUM,
    "low": ImpactLevel.LOW, "1": ImpactLevel.LOW, "*": ImpactLevel.LOW,
    "none": ImpactLevel.LOW, "0": ImpactLevel.LOW,
}

_IMPACT_RANK: dict[ImpactLevel, int] = {
    ImpactLevel.UNKNOWN: 0,
    ImpactLevel.LOW: 1,
    ImpactLevel.MEDIUM: 2,
    ImpactLevel.HIGH: 3,
}


def parse_provider_impact(raw: object) -> ImpactLevel:
    """
    يحوّل قيمة المزوّد إلى مستوى داخلي. **غير المعروف ⇒ `UNKNOWN` لا `LOW`**:
    الفرق أن `UNKNOWN` يُعامَل بحذر بينما `LOW` يفتح الباب.
    """
    if raw is None:
        return ImpactLevel.UNKNOWN
    token = str(raw).strip().lower()
    return _PROVIDER_IMPACT_MAP.get(token, ImpactLevel.UNKNOWN)


@dataclass(frozen=True)
class Classification:
    category: EventCategory
    impact: ImpactLevel
    provider_impact: ImpactLevel
    policy_impact: ImpactLevel
    policy_version: str
    matched_rule: Optional[str]
    reason_ar: str

    @property
    def is_high_impact(self) -> bool:
        return self.impact is ImpactLevel.HIGH

    def as_dict(self) -> dict:
        return {
            "category": self.category.value,
            "impact": self.impact.value,
            "provider_impact": self.provider_impact.value,
            "policy_impact": self.policy_impact.value,
            "policy_version": self.policy_version,
            "matched_rule": self.matched_rule,
            "reason_ar": self.reason_ar,
        }


def classify_event(
    name: str,
    *,
    provider_impact: object = None,
    currencies: Sequence[str] = (),
    allowlist: Sequence[str] = INITIAL_CURRENCY_ALLOWLIST,
) -> Classification:
    """
    يصنّف حدثاً باسمه. **الأشد بين المزوّد والسياسة يفوز.**

    التخفيف ممنوع بالبناء: `max()` على الرتبة لا `min()` ولا ترجيح.
    """
    lowered = name.lower()
    provider_level = parse_provider_impact(provider_impact)

    category = EventCategory.OTHER
    policy_level = ImpactLevel.LOW
    matched: Optional[str] = None

    for pattern, cat in _HIGH_IMPACT_PATTERNS:
        if re.search(pattern, lowered):
            category, policy_level, matched = cat, ImpactLevel.HIGH, pattern
            break
    else:
        for pattern, cat in _MEDIUM_IMPACT_PATTERNS:
            if re.search(pattern, lowered):
                category, policy_level, matched = cat, ImpactLevel.MEDIUM, pattern
                break

    # حدث خارج قائمة العملات المسموح تتبّعها لا يُخفَّض أثره — يُصنَّف كما هو،
    # والتصفية تحدث في طبقة الاستعلام لا في التصنيف.
    relevant = not currencies or any(c in allowlist for c in currencies)

    final = (
        provider_level if _IMPACT_RANK[provider_level] > _IMPACT_RANK[policy_level]
        else policy_level
    )

    if final is policy_level and matched:
        reason = f"سياسة محلية v{CLASSIFICATION_POLICY_VERSION} طابقت: `{matched}`."
    elif _IMPACT_RANK[provider_level] > _IMPACT_RANK[policy_level]:
        reason = (
            f"المزوّد صنّفه {provider_level.value} والسياسة المحلية "
            f"{policy_level.value} — **الأشد يفوز**."
        )
    else:
        reason = "لا قاعدة محلية طابقت، ولا تصنيف أشد من المزوّد."
    if not relevant:
        reason += " (عملة خارج قائمة التتبّع الحالية.)"

    return Classification(
        category=category,
        impact=final,
        provider_impact=provider_level,
        policy_impact=policy_level,
        policy_version=CLASSIFICATION_POLICY_VERSION,
        matched_rule=matched,
        reason_ar=reason,
    )


__all__ = [
    "CLASSIFICATION_POLICY_VERSION",
    "INITIAL_CURRENCY_ALLOWLIST",
    "Classification",
    "classify_event",
    "parse_provider_impact",
]
