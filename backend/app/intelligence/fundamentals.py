"""
FUNDAMENTAL AND MACRO ANALYSIS — للفوركس، «التحليل المالي» يعني السياق
الاقتصادي الكلي والنقدي، لا قوائم مالية لشركة.

هذه الوحدة **لا تعتمد صفقة أبداً**. هي مُدخَل واحد مضبوط ضمن مدخلات أخرى،
ونتيجتها تدخل مصفوفة التناقضات ودرجة الجودة — لا مسار تنفيذ.

كل قيمة تأتي من مزوّد بنسب كامل. الحقل الناقص يبقى `UNKNOWN`،
والثقة تنخفض باكتمال البيانات لا بقوة الرأي.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional

from ..money import D
from .providers import ProviderRegistry
from .snapshot import UNKNOWN, Sourced, _Unknown, is_unknown


class Bias(str, Enum):
    STRONGLY_BULLISH = "STRONGLY_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONGLY_BEARISH = "STRONGLY_BEARISH"
    UNKNOWN = "UNKNOWN"


BIAS_NAME_AR: dict[Bias, str] = {
    Bias.STRONGLY_BULLISH: "صاعد بقوة",
    Bias.BULLISH: "صاعد",
    Bias.NEUTRAL: "محايد",
    Bias.BEARISH: "هابط",
    Bias.STRONGLY_BEARISH: "هابط بقوة",
    Bias.UNKNOWN: "غير معلوم",
}

BIAS_SCORE: dict[Bias, int] = {
    Bias.STRONGLY_BULLISH: 2,
    Bias.BULLISH: 1,
    Bias.NEUTRAL: 0,
    Bias.BEARISH: -1,
    Bias.STRONGLY_BEARISH: -2,
    Bias.UNKNOWN: 0,
}

#: الحقول التي تُطلب من مزوّدي الاقتصاد الكلي والسياق الأساسي.
REQUIRED_MACRO_KEYS: tuple[str, ...] = (
    "fed_policy_stance",
    "ecb_policy_stance",
    "rate_differential",
    "inflation_direction_us",
    "inflation_direction_ea",
    "labour_direction_us",
    "labour_direction_ea",
    "growth_direction_us",
    "growth_direction_ea",
    "bond_yield_direction",
    "risk_sentiment",
    "usd_strength",
    "eur_strength",
)

#: الحد الأدنى لنسبة اكتمال البيانات كي تُعتبر الثقة صالحة للاستعمال.
MIN_COMPLETENESS_FOR_CONFIDENCE = D("0.60")


def _as_bias(value: Any) -> Bias:
    """تحويل قيمة مزوّد إلى انحياز مُعدَّد. أي قيمة غير معروفة ⇒ UNKNOWN."""
    if is_unknown(value) or value is None:
        return Bias.UNKNOWN
    if isinstance(value, Bias):
        return value
    text = str(value).strip().upper()
    mapping = {
        "HAWKISH": Bias.BULLISH,          # للعملة نفسها
        "VERY_HAWKISH": Bias.STRONGLY_BULLISH,
        "DOVISH": Bias.BEARISH,
        "VERY_DOVISH": Bias.STRONGLY_BEARISH,
        "NEUTRAL": Bias.NEUTRAL,
        "RISING": Bias.BULLISH,
        "FALLING": Bias.BEARISH,
        "STABLE": Bias.NEUTRAL,
        "STRENGTHENING": Bias.BULLISH,
        "WEAKENING": Bias.BEARISH,
        "RISK_ON": Bias.BULLISH,
        "RISK_OFF": Bias.BEARISH,
    }
    return mapping.get(text, Bias.UNKNOWN)


def _combine(scores: list[int]) -> Bias:
    if not scores:
        return Bias.UNKNOWN
    total = sum(scores)
    if total >= 3:
        return Bias.STRONGLY_BULLISH
    if total >= 1:
        return Bias.BULLISH
    if total <= -3:
        return Bias.STRONGLY_BEARISH
    if total <= -1:
        return Bias.BEARISH
    return Bias.NEUTRAL


@dataclass(frozen=True)
class FundamentalAssessment:
    eur_bias: Bias
    usd_bias: Bias
    relative_bias: Bias                 # انحياز EUR/USD نفسه
    confidence: Decimal                 # 0..1، مشتقّ من اكتمال البيانات وحده
    completeness: Decimal               # 0..1
    supporting_ar: tuple[str, ...]
    contradicting_ar: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    provider_configured: bool

    @property
    def usable(self) -> bool:
        """هل يصلح هذا التقييم كمدخل في القرار أصلاً؟"""
        return (
            self.provider_configured
            and self.relative_bias is not Bias.UNKNOWN
            and self.completeness >= MIN_COMPLETENESS_FOR_CONFIDENCE
        )

    def as_dict(self) -> dict:
        return {
            "eur_bias": self.eur_bias.value,
            "eur_bias_ar": BIAS_NAME_AR[self.eur_bias],
            "usd_bias": self.usd_bias.value,
            "usd_bias_ar": BIAS_NAME_AR[self.usd_bias],
            "relative_bias": self.relative_bias.value,
            "relative_bias_ar": BIAS_NAME_AR[self.relative_bias],
            "confidence": f"{self.confidence:.2f}",
            "completeness": f"{self.completeness:.2f}",
            "usable": self.usable,
            "supporting_ar": list(self.supporting_ar),
            "contradicting_ar": list(self.contradicting_ar),
            "unknown_fields": list(self.unknown_fields),
            "provider_configured": self.provider_configured,
        }


def assess_fundamentals(
    values: Mapping[str, Sourced[Any]], *, provider_configured: bool
) -> FundamentalAssessment:
    """
    يبني الانحياز من قيم منسوبة فقط. لا يخترع حقلاً غائباً، ولا يفترض «محايد»
    مكان «غير معلوم» — الفرق بينهما هو الفرق بين معرفة وجهل.
    """
    unknown: list[str] = []
    known: dict[str, Bias] = {}
    for key in REQUIRED_MACRO_KEYS:
        sourced = values.get(key)
        if sourced is None or not sourced.known:
            unknown.append(key)
            continue
        bias = _as_bias(sourced.value)
        if bias is Bias.UNKNOWN:
            unknown.append(key)
            continue
        known[key] = bias

    completeness = D(len(known)) / D(len(REQUIRED_MACRO_KEYS))

    if not provider_configured or not known:
        return FundamentalAssessment(
            eur_bias=Bias.UNKNOWN,
            usd_bias=Bias.UNKNOWN,
            relative_bias=Bias.UNKNOWN,
            confidence=D("0"),
            completeness=completeness,
            supporting_ar=(),
            contradicting_ar=(),
            unknown_fields=tuple(unknown),
            provider_configured=provider_configured,
        )

    eur_keys = (
        "ecb_policy_stance", "inflation_direction_ea", "labour_direction_ea",
        "growth_direction_ea", "eur_strength",
    )
    usd_keys = (
        "fed_policy_stance", "inflation_direction_us", "labour_direction_us",
        "growth_direction_us", "usd_strength",
    )

    eur_scores = [BIAS_SCORE[known[k]] for k in eur_keys if k in known]
    usd_scores = [BIAS_SCORE[known[k]] for k in usd_keys if k in known]
    eur_bias = _combine(eur_scores)
    usd_bias = _combine(usd_scores)

    # EUR/USD يصعد حين يقوى اليورو أو يضعف الدولار.
    relative_score = sum(eur_scores) - sum(usd_scores)
    if "rate_differential" in known:
        relative_score += BIAS_SCORE[known["rate_differential"]]
    relative = _combine([relative_score])

    supporting: list[str] = []
    contradicting: list[str] = []
    for k, b in sorted(known.items()):
        line = f"{k}: {BIAS_NAME_AR[b]}"
        expected_positive = k in eur_keys or k == "rate_differential"
        contributes_up = (BIAS_SCORE[b] > 0) if expected_positive else (BIAS_SCORE[b] < 0)
        if BIAS_SCORE[b] == 0:
            continue
        if (relative_score > 0) == contributes_up:
            supporting.append(line)
        else:
            contradicting.append(line)

    # الثقة مشتقّة من **اكتمال البيانات**، لا من حجم الانحياز.
    confidence = completeness
    if contradicting:
        confidence = confidence * (
            D(len(supporting)) / D(len(supporting) + len(contradicting))
        )

    return FundamentalAssessment(
        eur_bias=eur_bias,
        usd_bias=usd_bias,
        relative_bias=relative,
        confidence=confidence,
        completeness=completeness,
        supporting_ar=tuple(supporting),
        contradicting_ar=tuple(contradicting),
        unknown_fields=tuple(unknown),
        provider_configured=provider_configured,
    )


def gather_fundamentals(
    registry: ProviderRegistry, *, base: str = "EUR", quote: str = "USD", now: datetime
) -> dict[str, Sourced[Any]]:
    """يجمع من مزوّدَي الكلي والسياق الأساسي معاً، بلا اختراع حقول."""
    out: dict[str, Sourced[Any]] = {}
    out.update(registry.macro.series(keys=REQUIRED_MACRO_KEYS, as_of_utc=now))
    ctx = registry.fundamentals.context(base=base, quote=quote, as_of_utc=now)
    for k, v in ctx.items():
        if v.known:
            out[k] = v
    return out


__all__ = [
    "Bias",
    "BIAS_NAME_AR",
    "BIAS_SCORE",
    "REQUIRED_MACRO_KEYS",
    "MIN_COMPLETENESS_FOR_CONFIDENCE",
    "FundamentalAssessment",
    "assess_fundamentals",
    "gather_fundamentals",
]
