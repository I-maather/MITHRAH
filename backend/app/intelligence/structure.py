"""
MULTI-TIMEFRAME STRUCTURE — تحليل البنية عبر تسلسل هرمي مقصود.

التسلسل ليس «تصويت مؤشرات»:

    W1   سياق بعيد المدى فقط
    D1   نظام السوق الأساسي
    H4   الاتجاه الهيكلي
    H1   سياق الإعداد
    M15  إعداد الدخول
    M5   التوقيت فقط — **لا يحدّد الاتجاه أبداً**

**لا يُشترط توافق كل الأطر.** بدلاً من ذلك تُعرَّف قواعد المحاذاة صراحةً لكل
استراتيجية. والإطار الأدنى **لا يتجاوز** نظام الإطار الأعلى إلا إذا كانت
الاستراتيجية المختارة استراتيجية انعكاس **مُتحقَّق منها استقلالاً** —
ولا توجد استراتيجية انعكاس معتمدة افتراضياً.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from ..money import D
from .indicators import IndicatorSet, compute_indicators
from .snapshot import (
    UNKNOWN,
    Candle,
    Timeframe,
    TIMEFRAME_ORDER,
    TIMEFRAME_ROLE_AR,
    TimeframeSeries,
    _Unknown,
)

#: الأطر التي يُسمح لها بتحديد الاتجاه. M5 ليست منها — بالتصميم.
DIRECTIONAL_TIMEFRAMES: frozenset[Timeframe] = frozenset(
    {Timeframe.W1, Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15}
)

TIMING_ONLY_TIMEFRAMES: frozenset[Timeframe] = frozenset({Timeframe.M5})


class TrendDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


class StructureState(str, Enum):
    HIGHER_HIGHS_HIGHER_LOWS = "HIGHER_HIGHS_HIGHER_LOWS"
    LOWER_HIGHS_LOWER_LOWS = "LOWER_HIGHS_LOWER_LOWS"
    RANGE_BOUND = "RANGE_BOUND"
    BREAK_OF_STRUCTURE_UP = "BREAK_OF_STRUCTURE_UP"
    BREAK_OF_STRUCTURE_DOWN = "BREAK_OF_STRUCTURE_DOWN"
    UNCLEAR = "UNCLEAR"


class MomentumState(str, Enum):
    OVERBOUGHT = "OVERBOUGHT"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    OVERSOLD = "OVERSOLD"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: Decimal
    is_high: bool


@dataclass(frozen=True)
class Zone:
    """منطقة دعم أو مقاومة، مبنية من قمم/قيعان متكررة لا من رسم يدوي."""

    low: Decimal
    high: Decimal
    touches: int
    is_support: bool

    def contains(self, price: Decimal) -> bool:
        return self.low <= price <= self.high

    def as_dict(self) -> dict:
        return {
            "low": str(self.low),
            "high": str(self.high),
            "touches": self.touches,
            "kind": "support" if self.is_support else "resistance",
        }


def find_swings(candles: Sequence[Candle], strength: int = 2) -> tuple[SwingPoint, ...]:
    """
    قمة تأرجح: أعلى من `strength` شمعة على كل جانب. قاع بالمثل.
    خوارزمية حتمية بحتة — لا تقدير ولا تنعيم.
    """
    out: list[SwingPoint] = []
    n = len(candles)
    for i in range(strength, n - strength):
        window = candles[i - strength: i + strength + 1]
        c = candles[i]
        if all(c.high >= w.high for w in window) and any(c.high > w.high for w in window):
            out.append(SwingPoint(i, c.high, True))
        if all(c.low <= w.low for w in window) and any(c.low < w.low for w in window):
            out.append(SwingPoint(i, c.low, False))
    return tuple(out)


def classify_structure(swings: Sequence[SwingPoint]) -> StructureState:
    highs = [s for s in swings if s.is_high][-3:]
    lows = [s for s in swings if not s.is_high][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return StructureState.UNCLEAR

    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price

    if hh and hl:
        return StructureState.HIGHER_HIGHS_HIGHER_LOWS
    if lh and ll:
        return StructureState.LOWER_HIGHS_LOWER_LOWS
    if hh and ll:
        return StructureState.UNCLEAR      # توسّع — لا بنية واضحة
    return StructureState.RANGE_BOUND


def detect_break_of_structure(
    candles: Sequence[Candle], swings: Sequence[SwingPoint]
) -> Optional[StructureState]:
    """كسر بنية = إغلاق فوق آخر قمة تأرجح أو تحت آخر قاع تأرجح."""
    if not candles:
        return None
    highs = [s for s in swings if s.is_high]
    lows = [s for s in swings if not s.is_high]
    last_close = candles[-1].close
    if highs and last_close > highs[-1].price:
        return StructureState.BREAK_OF_STRUCTURE_UP
    if lows and last_close < lows[-1].price:
        return StructureState.BREAK_OF_STRUCTURE_DOWN
    return None


def build_zones(
    swings: Sequence[SwingPoint], tolerance: Decimal, min_touches: int = 2
) -> tuple[Zone, ...]:
    """يجمّع نقاط التأرجح المتقاربة في مناطق. `tolerance` عادةً كسر من ATR."""
    zones: list[Zone] = []
    for is_high in (True, False):
        pts = sorted((s.price for s in swings if s.is_high is is_high))
        i = 0
        while i < len(pts):
            group = [pts[i]]
            j = i + 1
            while j < len(pts) and pts[j] - group[0] <= tolerance:
                group.append(pts[j])
                j += 1
            if len(group) >= min_touches:
                zones.append(
                    Zone(low=group[0], high=group[-1], touches=len(group), is_support=not is_high)
                )
            i = j
    return tuple(zones)


def trend_from_moving_averages(
    last_close: Decimal | _Unknown, ind: IndicatorSet
) -> TrendDirection:
    if (
        isinstance(last_close, _Unknown)
        or isinstance(ind.sma_fast, _Unknown)
        or isinstance(ind.sma_slow, _Unknown)
    ):
        return TrendDirection.UNKNOWN
    if ind.sma_fast > ind.sma_slow and last_close > ind.sma_slow:
        return TrendDirection.UP
    if ind.sma_fast < ind.sma_slow and last_close < ind.sma_slow:
        return TrendDirection.DOWN
    return TrendDirection.SIDEWAYS


def momentum_state(ind: IndicatorSet) -> MomentumState:
    if isinstance(ind.rsi, _Unknown):
        return MomentumState.UNKNOWN
    r = ind.rsi
    if r >= D("70"):
        return MomentumState.OVERBOUGHT
    if r >= D("55"):
        return MomentumState.BULLISH
    if r <= D("30"):
        return MomentumState.OVERSOLD
    if r <= D("45"):
        return MomentumState.BEARISH
    return MomentumState.NEUTRAL


@dataclass(frozen=True)
class TimeframeAnalysis:
    """تحليل إطار واحد. `is_directional` يمنع M5 من التأثير على الاتجاه."""

    timeframe: Timeframe
    role_ar: str
    is_directional: bool
    trend: TrendDirection
    structure: StructureState
    momentum: MomentumState
    indicators: IndicatorSet
    swings: tuple[SwingPoint, ...]
    zones: tuple[Zone, ...]
    last_close: Decimal | _Unknown
    distance_to_invalidation: Decimal | _Unknown
    data_complete: bool
    notes_ar: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "timeframe": self.timeframe.value,
            "role_ar": self.role_ar,
            "is_directional": self.is_directional,
            "trend": self.trend.value,
            "structure": self.structure.value,
            "momentum": self.momentum.value,
            "indicators": self.indicators.as_dict(),
            "swings": len(self.swings),
            "zones": [z.as_dict() for z in self.zones],
            "last_close": (
                "UNKNOWN" if isinstance(self.last_close, _Unknown) else str(self.last_close)
            ),
            "distance_to_invalidation": (
                "UNKNOWN"
                if isinstance(self.distance_to_invalidation, _Unknown)
                else str(self.distance_to_invalidation)
            ),
            "data_complete": self.data_complete,
            "notes_ar": list(self.notes_ar),
        }


def analyse_timeframe(series: TimeframeSeries, *, min_bars: int = 60) -> TimeframeAnalysis:
    tf = series.timeframe
    candles = series.candles
    ind = compute_indicators(tf, candles)
    swings = find_swings(candles)
    structure = classify_structure(swings)
    bos = detect_break_of_structure(candles, swings)
    if bos is not None:
        structure = bos

    last_close = candles[-1].close if candles else UNKNOWN
    tolerance = ind.atr / D("2") if not isinstance(ind.atr, _Unknown) else D("0.0005")
    zones = build_zones(swings, tolerance)

    # مسافة الإبطال = المسافة إلى آخر قاع تأرجح (لاتجاه صاعد) أو قمة (لهابط).
    invalidation: Decimal | _Unknown = UNKNOWN
    trend = trend_from_moving_averages(last_close, ind)
    if not isinstance(last_close, _Unknown):
        lows = [s.price for s in swings if not s.is_high]
        highs = [s.price for s in swings if s.is_high]
        if trend is TrendDirection.UP and lows:
            invalidation = last_close - lows[-1]
        elif trend is TrendDirection.DOWN and highs:
            invalidation = highs[-1] - last_close

    notes: list[str] = []
    complete = series.complete and len(candles) >= min_bars
    if not complete:
        notes.append(
            f"بيانات {tf.value} غير مكتملة: {len(candles)} شمعة والمطلوب {min_bars}."
        )
    if tf in TIMING_ONLY_TIMEFRAMES:
        notes.append("هذا الإطار للتوقيت فقط ولا يُستعمل في تحديد الاتجاه.")

    return TimeframeAnalysis(
        timeframe=tf,
        role_ar=TIMEFRAME_ROLE_AR[tf],
        is_directional=tf in DIRECTIONAL_TIMEFRAMES,
        trend=trend,
        structure=structure,
        momentum=momentum_state(ind),
        indicators=ind,
        swings=swings,
        zones=zones,
        last_close=last_close,
        distance_to_invalidation=invalidation,
        data_complete=complete,
        notes_ar=tuple(notes),
    )


@dataclass(frozen=True)
class MultiTimeframeView:
    """كل الأطر معاً، مع النظام الحاكم من D1 والاتجاه الهيكلي من H4."""

    analyses: dict[Timeframe, TimeframeAnalysis]

    @property
    def regime_timeframe(self) -> Timeframe:
        return Timeframe.D1

    @property
    def primary_regime_trend(self) -> TrendDirection:
        a = self.analyses.get(Timeframe.D1)
        return a.trend if a else TrendDirection.UNKNOWN

    @property
    def structural_trend(self) -> TrendDirection:
        a = self.analyses.get(Timeframe.H4)
        return a.trend if a else TrendDirection.UNKNOWN

    @property
    def entry_trend(self) -> TrendDirection:
        a = self.analyses.get(Timeframe.M15)
        return a.trend if a else TrendDirection.UNKNOWN

    def incomplete_timeframes(self) -> tuple[Timeframe, ...]:
        return tuple(tf for tf, a in self.analyses.items() if not a.data_complete)

    def aligned_directional(self, direction: TrendDirection) -> tuple[Timeframe, ...]:
        return tuple(
            tf
            for tf, a in self.analyses.items()
            if a.is_directional and a.trend is direction
        )

    def conflicting_directional(self, direction: TrendDirection) -> tuple[Timeframe, ...]:
        opposite = (
            TrendDirection.DOWN if direction is TrendDirection.UP else TrendDirection.UP
        )
        return tuple(
            tf
            for tf, a in self.analyses.items()
            if a.is_directional and a.trend is opposite
        )

    def as_dict(self) -> dict:
        return {
            "primary_regime_trend": self.primary_regime_trend.value,
            "structural_trend": self.structural_trend.value,
            "entry_trend": self.entry_trend.value,
            "incomplete": [tf.value for tf in self.incomplete_timeframes()],
            "timeframes": {
                tf.value: a.as_dict()
                for tf, a in sorted(self.analyses.items(), key=lambda kv: TIMEFRAME_ORDER.index(kv[0]))
            },
        }


def analyse_all(
    series_by_tf: dict[Timeframe, TimeframeSeries], *, min_bars: int = 60
) -> MultiTimeframeView:
    return MultiTimeframeView(
        analyses={
            tf: analyse_timeframe(s, min_bars=min_bars) for tf, s in series_by_tf.items()
        }
    )


__all__ = [
    "TrendDirection",
    "StructureState",
    "MomentumState",
    "SwingPoint",
    "Zone",
    "TimeframeAnalysis",
    "MultiTimeframeView",
    "DIRECTIONAL_TIMEFRAMES",
    "TIMING_ONLY_TIMEFRAMES",
    "find_swings",
    "classify_structure",
    "detect_break_of_structure",
    "build_zones",
    "momentum_state",
    "trend_from_moving_averages",
    "analyse_timeframe",
    "analyse_all",
]
