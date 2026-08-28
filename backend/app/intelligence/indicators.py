"""
INDICATORS — مؤشرات محسوبة محلياً من شموع مُتحقَّق منها.

قاعدتان:

1. **لا يُضاف مؤشر لزيادة مظهر الذكاء.** كل مؤشر هنا له غرض استراتيجي محدد.
2. **لا مؤشرات مكرَّرة تقيس الشيء نفسه.** (لذلك يوجد ATR وحده لقياس التقلب
   السعري، وADX وحده لقياس قوة الاتجاه، ولا يوجد MACD بجانب RSI بجانب
   Stochastic — ثلاثتها زخم، والتكرار يوهم بتأكيد غير موجود.)

كل مؤشر يعلن: الصيغة · المعاملات · الإطار الزمني · الغرض · حالة التحقق ·
الاختبارات · الإصدار. غير المعلن لا يُستعمل.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from ..money import D
from .snapshot import UNKNOWN, Candle, Timeframe, _Unknown

ZERO = Decimal("0")


class IndicatorValidation(str, Enum):
    TESTED = "TESTED"           # له اختبار وحدة بقيم مرجعية محسوبة يدوياً
    RESEARCH = "RESEARCH"       # محسوب لكن لم يُعتمد للاستعمال في قرار
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class IndicatorSpec:
    """بطاقة تعريف المؤشر. أي مؤشر بلا بطاقة لا يدخل قراراً."""

    key: str
    name_ar: str
    version: str
    formula: str
    parameters: dict[str, int | str]
    purpose_ar: str
    validation: IndicatorValidation
    test_names: tuple[str, ...]
    #: المؤشر الذي قد يُظن أنه يقيس الشيء نفسه — للتوثيق ومنع التكرار.
    not_duplicated_by_ar: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name_ar": self.name_ar,
            "version": self.version,
            "formula": self.formula,
            "parameters": dict(self.parameters),
            "purpose_ar": self.purpose_ar,
            "validation": self.validation.value,
            "tests": list(self.test_names),
            "not_duplicated_by_ar": self.not_duplicated_by_ar,
        }


INDICATOR_SPECS: dict[str, IndicatorSpec] = {
    "sma": IndicatorSpec(
        key="sma",
        name_ar="المتوسط المتحرك البسيط",
        version="1.0.0",
        formula="SMA(n) = مجموع الإغلاقات الأخيرة n ÷ n",
        parameters={"periods": "20/50/200 حسب الإطار"},
        purpose_ar="تحديد اتجاه السياق وموضع السعر منه — لا يُستعمل كإشارة دخول وحده.",
        validation=IndicatorValidation.TESTED,
        test_names=("test_sma_matches_hand_computed_value",),
        not_duplicated_by_ar="لا يوجد EMA في النظام: متوسطان بنفس الغرض يوهمان بتأكيد.",
    ),
    "atr": IndicatorSpec(
        key="atr",
        name_ar="المدى الحقيقي المتوسط",
        version="1.0.0",
        formula="TR = max(H−L, |H−C₋₁|, |L−C₋₁|) ; ATR(n) = متوسط TR لآخر n",
        parameters={"period": 14},
        purpose_ar="قياس التقلب السعري: مسافة الوقف، وحجم السبريد نسبةً إليه.",
        validation=IndicatorValidation.TESTED,
        test_names=("test_atr_matches_hand_computed_value",),
        not_duplicated_by_ar="المقياس الوحيد للتقلب. لا Bollinger ولا StdDev بجانبه.",
    ),
    "rsi": IndicatorSpec(
        key="rsi",
        name_ar="مؤشر القوة النسبية",
        version="1.0.0",
        formula="RSI = 100 − 100/(1+RS) ; RS = متوسط المكاسب ÷ متوسط الخسائر",
        parameters={"period": 14},
        purpose_ar="حالة الزخم فقط: تشبّع في الارتداد داخل نظام النطاق.",
        validation=IndicatorValidation.TESTED,
        test_names=("test_rsi_bounds_and_direction",),
        not_duplicated_by_ar="المقياس الوحيد للزخم. لا MACD ولا Stochastic بجانبه.",
    ),
    "adx": IndicatorSpec(
        key="adx",
        name_ar="مؤشر متوسط الحركة الاتجاهية",
        version="1.0.0",
        formula="DI± من حركة الاتجاه المنعّمة ; DX = 100·|DI⁺−DI⁻|/(DI⁺+DI⁻) ; ADX = متوسط DX",
        parameters={"period": 14},
        purpose_ar="قوة الاتجاه — الفارق بين TREND وRANGE. لا يعطي اتجاهاً، يعطي قوة.",
        validation=IndicatorValidation.TESTED,
        test_names=("test_adx_is_higher_in_a_trend_than_in_a_range",),
        not_duplicated_by_ar="المقياس الوحيد لقوة الاتجاه.",
    ),
    "volatility_percentile": IndicatorSpec(
        key="volatility_percentile",
        name_ar="المئين التقلبي",
        version="1.0.0",
        formula="ترتيب ATR الحالي بين قيم ATR التاريخية ÷ العدد × 100",
        parameters={"lookback": 100},
        purpose_ar="هل التقلب الحالي شاذ؟ يغذّي HIGH_VOLATILITY وتمديد نافذة الأخبار.",
        validation=IndicatorValidation.TESTED,
        test_names=("test_volatility_percentile_is_bounded",),
    ),
}


def spec(key: str) -> IndicatorSpec:
    return INDICATOR_SPECS[key]


# ---------------------------------------------------------------------------
# الحسابات — كلها Decimal، وكلها تعيد UNKNOWN عند نقص البيانات
# ---------------------------------------------------------------------------

def sma(closes: Sequence[Decimal], period: int) -> Decimal | _Unknown:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(closes) < period:
        return UNKNOWN
    window = closes[-period:]
    return sum(window, ZERO) / D(period)


def true_ranges(candles: Sequence[Candle]) -> list[Decimal]:
    out: list[Decimal] = []
    for i in range(1, len(candles)):
        c, prev = candles[i], candles[i - 1]
        out.append(
            max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        )
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> Decimal | _Unknown:
    trs = true_ranges(candles)
    if len(trs) < period:
        return UNKNOWN
    window = trs[-period:]
    return sum(window, ZERO) / D(period)


def rsi(closes: Sequence[Decimal], period: int = 14) -> Decimal | _Unknown:
    if len(closes) < period + 1:
        return UNKNOWN
    gains = ZERO
    losses = ZERO
    for i in range(len(closes) - period, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains += change
        else:
            losses += -change
    avg_gain = gains / D(period)
    avg_loss = losses / D(period)
    if avg_loss == 0:
        return D("100") if avg_gain > 0 else D("50")
    rs = avg_gain / avg_loss
    return D("100") - (D("100") / (D("1") + rs))


def adx(candles: Sequence[Candle], period: int = 14) -> Decimal | _Unknown:
    """
    ADX بمتوسط بسيط (لا Wilder) — مقصود: قابل للتحقق يدوياً في اختبار،
    والغرض تصنيف قوة الاتجاه لا التداول على قيمة دقيقة.
    """
    if len(candles) < period * 2 + 1:
        return UNKNOWN
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    trs = true_ranges(candles)
    for i in range(1, len(candles)):
        up = candles[i].high - candles[i - 1].high
        down = candles[i - 1].low - candles[i].low
        plus_dm.append(up if (up > down and up > 0) else ZERO)
        minus_dm.append(down if (down > up and down > 0) else ZERO)

    dxs: list[Decimal] = []
    for end in range(period, len(trs) + 1):
        tr_sum = sum(trs[end - period:end], ZERO)
        if tr_sum == 0:
            continue
        pdi = D("100") * sum(plus_dm[end - period:end], ZERO) / tr_sum
        mdi = D("100") * sum(minus_dm[end - period:end], ZERO) / tr_sum
        denom = pdi + mdi
        if denom == 0:
            continue
        dxs.append(D("100") * abs(pdi - mdi) / denom)

    if len(dxs) < period:
        return UNKNOWN
    return sum(dxs[-period:], ZERO) / D(period)


def volatility_percentile(
    candles: Sequence[Candle], period: int = 14, lookback: int = 100
) -> Decimal | _Unknown:
    """أين يقع ATR الحالي بين قيم ATR السابقة؟ 0 = أهدأ ما رأينا، 100 = أعنف."""
    if len(candles) < period + 2:
        return UNKNOWN
    values: list[Decimal] = []
    start = max(period + 1, len(candles) - lookback)
    for end in range(start, len(candles) + 1):
        v = atr(candles[:end], period)
        if not isinstance(v, _Unknown):
            values.append(v)
    if len(values) < 2:
        return UNKNOWN
    current = values[-1]
    below = sum(1 for v in values[:-1] if v <= current)
    return D("100") * D(below) / D(len(values) - 1)


def spread_to_atr_ratio(spread: Decimal, atr_value: Decimal | _Unknown) -> Decimal | _Unknown:
    """السبريد نسبةً إلى التقلب — أهم من السبريد المطلق."""
    if isinstance(atr_value, _Unknown) or atr_value <= 0:
        return UNKNOWN
    return spread / atr_value


@dataclass(frozen=True)
class IndicatorSet:
    """كل المؤشرات لإطار زمني واحد، مع الشفافية الكاملة عمّا تعذّر حسابه."""

    timeframe: Timeframe
    sma_fast: Decimal | _Unknown
    sma_slow: Decimal | _Unknown
    atr: Decimal | _Unknown
    rsi: Decimal | _Unknown
    adx: Decimal | _Unknown
    volatility_percentile: Decimal | _Unknown
    bars_used: int

    @property
    def unknown_keys(self) -> tuple[str, ...]:
        return tuple(
            k
            for k in ("sma_fast", "sma_slow", "atr", "rsi", "adx", "volatility_percentile")
            if isinstance(getattr(self, k), _Unknown)
        )

    def as_dict(self) -> dict:
        def fmt(v):
            return "UNKNOWN" if isinstance(v, _Unknown) else f"{v:.5f}"

        return {
            "timeframe": self.timeframe.value,
            "sma_fast": fmt(self.sma_fast),
            "sma_slow": fmt(self.sma_slow),
            "atr": fmt(self.atr),
            "rsi": fmt(self.rsi),
            "adx": fmt(self.adx),
            "volatility_percentile": fmt(self.volatility_percentile),
            "bars_used": self.bars_used,
            "unknown": list(self.unknown_keys),
        }


def compute_indicators(
    timeframe: Timeframe,
    candles: Sequence[Candle],
    *,
    fast: int = 20,
    slow: int = 50,
    atr_period: int = 14,
) -> IndicatorSet:
    closes = [c.close for c in candles]
    return IndicatorSet(
        timeframe=timeframe,
        sma_fast=sma(closes, fast),
        sma_slow=sma(closes, slow),
        atr=atr(candles, atr_period),
        rsi=rsi(closes, 14),
        adx=adx(candles, 14),
        volatility_percentile=volatility_percentile(candles, atr_period),
        bars_used=len(candles),
    )


__all__ = [
    "IndicatorSpec",
    "IndicatorValidation",
    "INDICATOR_SPECS",
    "IndicatorSet",
    "spec",
    "sma",
    "atr",
    "rsi",
    "adx",
    "true_ranges",
    "volatility_percentile",
    "spread_to_atr_ratio",
    "compute_indicators",
]
