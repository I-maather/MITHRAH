"""
MARKET REGIME CLASSIFICATION — تصنيف نظام السوق، حتمي بالكامل.

المصنِّف يُخرج **الدليل والتناقض** مع كل تصنيف، لا التصنيف وحده.

أربعة أنظمة تعني `NO_TRADE` افتراضياً ولا تُستثنى في أي ملف تداول:
`CHOPPY` · `EVENT_RISK` · `LOW_LIQUIDITY` · `UNKNOWN`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..money import D
from .indicators import IndicatorSet
from .snapshot import Timeframe, _Unknown
from .structure import MultiTimeframeView, StructureState, TrendDirection


class MarketRegime(str, Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    BREAKOUT_PENDING = "BREAKOUT_PENDING"
    BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
    REVERSAL_CANDIDATE = "REVERSAL_CANDIDATE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    CHOPPY = "CHOPPY"
    EVENT_RISK = "EVENT_RISK"
    UNKNOWN = "UNKNOWN"


#: أنظمة لا يُتداول فيها إطلاقاً — في كل الملفات، بلا استثناء.
NO_TRADE_REGIMES: frozenset[MarketRegime] = frozenset({
    MarketRegime.CHOPPY,
    MarketRegime.EVENT_RISK,
    MarketRegime.LOW_LIQUIDITY,
    MarketRegime.UNKNOWN,
})

REGIME_NAME_AR: dict[MarketRegime, str] = {
    MarketRegime.TREND: "اتجاه",
    MarketRegime.RANGE: "نطاق",
    MarketRegime.BREAKOUT_PENDING: "اختراق مُحتمل",
    MarketRegime.BREAKOUT_CONFIRMED: "اختراق مؤكَّد",
    MarketRegime.REVERSAL_CANDIDATE: "مرشَّح انعكاس",
    MarketRegime.HIGH_VOLATILITY: "تقلب مرتفع",
    MarketRegime.LOW_LIQUIDITY: "سيولة منخفضة",
    MarketRegime.CHOPPY: "متذبذب بلا اتجاه",
    MarketRegime.EVENT_RISK: "مخاطرة حدث",
    MarketRegime.UNKNOWN: "غير معلوم",
}

# عتبات معلنة — لا أرقام سحرية داخل الدوال.
ADX_TREND_MIN = D("22")
ADX_RANGE_MAX = D("18")
VOL_PERCENTILE_HIGH = D("90")
VOL_PERCENTILE_LOW = D("10")
SPREAD_TO_ATR_ILLIQUID = D("0.25")


@dataclass(frozen=True)
class RegimeAssessment:
    regime: MarketRegime
    name_ar: str
    evidence_ar: tuple[str, ...]
    contradictions_ar: tuple[str, ...]
    tradable: bool
    reason_ar: str

    def as_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "name_ar": self.name_ar,
            "evidence_ar": list(self.evidence_ar),
            "contradictions_ar": list(self.contradictions_ar),
            "tradable": self.tradable,
            "reason_ar": self.reason_ar,
        }


def classify_regime(
    view: MultiTimeframeView,
    *,
    spread_to_atr: Decimal | _Unknown,
    in_event_window: bool,
    event_reason_ar: str = "",
) -> RegimeAssessment:
    """
    ترتيب الفحص مقصود: المخاطر الحاجبة أولاً، ثم التصنيف الإيجابي.
    حدث عالي الأثر يتقدّم على كل شيء — لا يُنافسه أي دليل فني.
    """
    evidence: list[str] = []
    contradictions: list[str] = []

    daily = view.analyses.get(Timeframe.D1)
    h4 = view.analyses.get(Timeframe.H4)

    def result(regime: MarketRegime, reason: str) -> RegimeAssessment:
        return RegimeAssessment(
            regime=regime,
            name_ar=REGIME_NAME_AR[regime],
            evidence_ar=tuple(evidence),
            contradictions_ar=tuple(contradictions),
            tradable=regime not in NO_TRADE_REGIMES,
            reason_ar=reason,
        )

    # 1) مخاطرة الحدث تتقدّم على كل تحليل فني.
    if in_event_window:
        evidence.append(event_reason_ar or "نافذة حدث عالي الأثر.")
        return result(MarketRegime.EVENT_RISK, "حدث عالي الأثر — لا تداول مهما كان الإعداد.")

    # 2) نقص البيانات = غير معلوم، لا «محايد».
    if daily is None or h4 is None:
        contradictions.append("بيانات الإطار اليومي أو H4 غير متوفرة.")
        return result(MarketRegime.UNKNOWN, "لا يمكن تصنيف النظام بلا D1 وH4.")

    incomplete = view.incomplete_timeframes()
    if incomplete:
        contradictions.append(
            "أطر ناقصة: " + "، ".join(tf.value for tf in incomplete)
        )
        return result(MarketRegime.UNKNOWN, "بيانات ناقصة — التصنيف غير ممكن.")

    ind: IndicatorSet = daily.indicators
    if isinstance(ind.adx, _Unknown) or isinstance(ind.volatility_percentile, _Unknown):
        contradictions.append("ADX أو المئين التقلبي غير محسوب على D1.")
        return result(MarketRegime.UNKNOWN, "مؤشرات النظام غير متوفرة.")

    # 3) السيولة: السبريد نسبةً إلى التقلب.
    if isinstance(spread_to_atr, _Unknown):
        contradictions.append("نسبة السبريد إلى ATR غير معلومة.")
        return result(MarketRegime.UNKNOWN, "لا يمكن تقييم السيولة.")
    if spread_to_atr >= SPREAD_TO_ATR_ILLIQUID:
        evidence.append(f"السبريد يعادل {spread_to_atr:.2f} من ATR — سيولة رديئة.")
        return result(MarketRegime.LOW_LIQUIDITY, "تكلفة الدخول مرتفعة نسبةً إلى الحركة المتاحة.")

    # 4) تقلب شاذ.
    if ind.volatility_percentile >= VOL_PERCENTILE_HIGH:
        evidence.append(f"المئين التقلبي {ind.volatility_percentile:.0f} — تقلب شاذ.")
        return result(MarketRegime.HIGH_VOLATILITY, "التقلب خارج نطاقه المعتاد.")
    if ind.volatility_percentile <= VOL_PERCENTILE_LOW:
        evidence.append(f"المئين التقلبي {ind.volatility_percentile:.0f} — حركة شبه معدومة.")
        return result(MarketRegime.LOW_LIQUIDITY, "الحركة المتاحة لا تغطي التكاليف.")

    # 5) اختراق البنية.
    if daily.structure in (
        StructureState.BREAK_OF_STRUCTURE_UP,
        StructureState.BREAK_OF_STRUCTURE_DOWN,
    ):
        evidence.append(f"كسر بنية على D1: {daily.structure.value}.")
        if ind.adx >= ADX_TREND_MIN:
            evidence.append(f"ADX {ind.adx:.0f} يدعم الاستمرار.")
            return result(MarketRegime.BREAKOUT_CONFIRMED, "كسر بنية مع قوة اتجاه كافية.")
        contradictions.append(f"ADX {ind.adx:.0f} دون عتبة الاتجاه {ADX_TREND_MIN}.")
        return result(MarketRegime.BREAKOUT_PENDING, "كسر بنية بلا قوة مؤكِّدة بعد.")

    # 6) اتجاه واضح.
    if ind.adx >= ADX_TREND_MIN and daily.trend in (TrendDirection.UP, TrendDirection.DOWN):
        evidence.append(f"D1 {daily.trend.value} وADX {ind.adx:.0f}.")
        if h4.trend is not daily.trend and h4.trend in (TrendDirection.UP, TrendDirection.DOWN):
            contradictions.append(f"H4 {h4.trend.value} يخالف D1 {daily.trend.value}.")
            return result(
                MarketRegime.REVERSAL_CANDIDATE,
                "الإطار الهيكلي يخالف النظام الأساسي — مرشّح انعكاس لا اتجاه.",
            )
        evidence.append(f"H4 {h4.trend.value} متوافق أو محايد.")
        return result(MarketRegime.TREND, "نظام اتجاهي واضح على الإطار الحاكم.")

    # 7) نطاق.
    if ind.adx <= ADX_RANGE_MAX and daily.structure is StructureState.RANGE_BOUND:
        evidence.append(f"ADX {ind.adx:.0f} منخفض وبنية D1 نطاقية.")
        return result(MarketRegime.RANGE, "نطاق محدَّد بحدود قابلة للقياس.")

    # 8) ما تبقّى: تذبذب — وهو NO_TRADE، لا «فرصة صغيرة».
    contradictions.append(
        f"ADX {ind.adx:.0f} بين عتبتي النطاق والاتجاه، وبنية D1 {daily.structure.value}."
    )
    return result(MarketRegime.CHOPPY, "لا اتجاه ولا نطاق — تذبذب. القرار NO_TRADE.")


__all__ = [
    "MarketRegime",
    "RegimeAssessment",
    "NO_TRADE_REGIMES",
    "REGIME_NAME_AR",
    "ADX_TREND_MIN",
    "ADX_RANGE_MAX",
    "VOL_PERCENTILE_HIGH",
    "VOL_PERCENTILE_LOW",
    "SPREAD_TO_ATR_ILLIQUID",
    "classify_regime",
]
