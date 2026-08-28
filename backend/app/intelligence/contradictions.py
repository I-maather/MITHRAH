"""
CONTRADICTION ENGINE — مصفوفة التناقضات الصريحة.

لكل تناقض:
  · الطرفان بالاسم
  · درجة الخطورة
  · هل هو قابل للحل؟
  · **الحل الحتمي المكتوب مسبقاً**
  · هل يمنع التداول إن بقي غير محلول وكان مادياً؟

**لا يُطلب من نموذج لغوي أن «يقرّر حدسياً» بين أدلة متناقضة — أبداً.**
كل حل هنا مكتوب في الكود قبل وقوع التناقض، ومُختبَر.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..money import D
from .fundamentals import Bias, FundamentalAssessment
from .regime import MarketRegime, RegimeAssessment
from .snapshot import _Unknown, is_unknown
from .structure import MultiTimeframeView, TrendDirection


class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # يمنع دائماً
    MAJOR = "MAJOR"         # يمنع إن لم يُحلّ
    MINOR = "MINOR"         # يخصم نقاطاً فقط


SEVERITY_PENALTY: dict[Severity, int] = {
    Severity.CRITICAL: 40,
    Severity.MAJOR: 15,
    Severity.MINOR: 5,
}

SEVERITY_AR: dict[Severity, str] = {
    Severity.CRITICAL: "حرج",
    Severity.MAJOR: "جوهري",
    Severity.MINOR: "طفيف",
}


class ContradictionKind(str, Enum):
    TECHNICAL_VS_MACRO = "TECHNICAL_VS_MACRO"
    HTF_VS_LTF = "HTF_VS_LTF"
    BREAKOUT_VS_SPREAD = "BREAKOUT_VS_SPREAD"
    ENTRY_VS_EVENT = "ENTRY_VS_EVENT"
    RR_BEFORE_VS_AFTER_COSTS = "RR_BEFORE_VS_AFTER_COSTS"
    STRATEGY_VS_REGIME = "STRATEGY_VS_REGIME"
    FRESH_PRICE_VS_STALE_CANDLES = "FRESH_PRICE_VS_STALE_CANDLES"


@dataclass(frozen=True)
class Contradiction:
    kind: ContradictionKind
    side_a_ar: str
    side_b_ar: str
    severity: Severity
    resolvable: bool
    resolution_ar: str
    blocks_trading: bool

    @property
    def penalty(self) -> int:
        return SEVERITY_PENALTY[self.severity]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "side_a_ar": self.side_a_ar,
            "side_b_ar": self.side_b_ar,
            "severity": self.severity.value,
            "severity_ar": SEVERITY_AR[self.severity],
            "resolvable": self.resolvable,
            "resolution_ar": self.resolution_ar,
            "blocks_trading": self.blocks_trading,
            "penalty": self.penalty,
        }


@dataclass(frozen=True)
class ContradictionReport:
    items: tuple[Contradiction, ...]

    @property
    def total_penalty(self) -> int:
        return sum(c.penalty for c in self.items)

    @property
    def blocking(self) -> tuple[Contradiction, ...]:
        return tuple(c for c in self.items if c.blocks_trading)

    @property
    def has_unresolved_material(self) -> bool:
        return any(c.blocks_trading for c in self.items)

    def as_dict(self) -> dict:
        return {
            "count": len(self.items),
            "total_penalty": self.total_penalty,
            "blocking_count": len(self.blocking),
            "has_unresolved_material": self.has_unresolved_material,
            "items": [c.as_dict() for c in self.items],
        }


@dataclass(frozen=True)
class ContradictionInputs:
    intended_direction: TrendDirection
    view: MultiTimeframeView
    regime: RegimeAssessment
    fundamentals: Optional[FundamentalAssessment]
    strategy_declares_regime_compatible: bool
    strategy_key: str
    spread_to_atr: Decimal | _Unknown
    gross_reward_risk: Decimal | _Unknown
    net_reward_risk: Decimal | _Unknown
    required_reward_risk: Decimal
    minutes_to_next_high_impact_event: Optional[int]
    quote_age_seconds: Optional[float]
    oldest_candle_age_seconds: Optional[float]


#: نافذة اعتبار الحدث «قريباً» حتى لو لم نكن داخل الحجب الرسمي.
EVENT_PROXIMITY_MINUTES = 90

#: الفارق المسموح بين عمر السعر وعمر آخر شمعة قبل اعتبارهما غير متسقين.
MAX_PRICE_CANDLE_AGE_GAP_SECONDS = 900


def detect_contradictions(inp: ContradictionInputs) -> ContradictionReport:
    """
    كل فرع هنا مكتوب مسبقاً. لا يوجد مسار يستدعي حكماً بشرياً أو لغوياً
    في لحظة القرار.
    """
    items: list[Contradiction] = []
    want_up = inp.intended_direction is TrendDirection.UP

    # 1. إعداد فني صاعد مقابل انحياز كلي هابط بقوة (والعكس)
    f = inp.fundamentals
    if f is not None and f.usable:
        strongly_against = (
            (want_up and f.relative_bias is Bias.STRONGLY_BEARISH)
            or (not want_up and f.relative_bias is Bias.STRONGLY_BULLISH)
        )
        mildly_against = (
            (want_up and f.relative_bias is Bias.BEARISH)
            or (not want_up and f.relative_bias is Bias.BULLISH)
        )
        if strongly_against:
            items.append(Contradiction(
                kind=ContradictionKind.TECHNICAL_VS_MACRO,
                side_a_ar=f"إعداد فني {'صاعد' if want_up else 'هابط'}",
                side_b_ar=f"انحياز كلي مُتحقَّق منه معاكس بقوة ({f.relative_bias.value})",
                severity=Severity.MAJOR,
                resolvable=False,
                resolution_ar=(
                    "الأساسيات المُتحقَّق منها المعاكسة بقوة تُبطل الإعداد الفني. "
                    "لا تُرجَّح كفة الفني لأنه «أوضح» — القرار NO_TRADE."
                ),
                blocks_trading=True,
            ))
        elif mildly_against:
            items.append(Contradiction(
                kind=ContradictionKind.TECHNICAL_VS_MACRO,
                side_a_ar="إعداد فني",
                side_b_ar=f"انحياز كلي معاكس ({f.relative_bias.value})",
                severity=Severity.MINOR,
                resolvable=True,
                resolution_ar="يُخصم من الدرجة ولا يمنع وحده. العتبة العالية للملف هي الحكم.",
                blocks_trading=False,
            ))

    # 2. اتجاه إطار أعلى مقابل إشارة إطار أدنى معاكسة
    conflicting = inp.view.conflicting_directional(inp.intended_direction)
    higher = [tf for tf in conflicting if tf.value in ("W1", "D1", "H4")]
    if higher:
        items.append(Contradiction(
            kind=ContradictionKind.HTF_VS_LTF,
            side_a_ar="أطر أعلى معاكسة: " + "، ".join(tf.value for tf in higher),
            side_b_ar=f"إشارة دخول {'صاعدة' if want_up else 'هابطة'} على إطار أدنى",
            severity=Severity.CRITICAL,
            resolvable=False,
            resolution_ar=(
                "الإطار الأدنى **لا يتجاوز** نظام الإطار الأعلى إلا في استراتيجية "
                "انعكاس مُتحقَّق منها استقلالاً — ولا توجد استراتيجية انعكاس معتمدة. "
                "القرار NO_TRADE."
            ),
            blocks_trading=True,
        ))

    # 3. إشارة اختراق مقابل سبريد شاذ
    if inp.regime.regime in (MarketRegime.BREAKOUT_CONFIRMED, MarketRegime.BREAKOUT_PENDING):
        if is_unknown(inp.spread_to_atr):
            items.append(Contradiction(
                kind=ContradictionKind.BREAKOUT_VS_SPREAD,
                side_a_ar="إشارة اختراق",
                side_b_ar="السبريد نسبةً إلى ATR غير معلوم",
                severity=Severity.CRITICAL,
                resolvable=False,
                resolution_ar="لا يُدخَل اختراق بتكلفة تنفيذ مجهولة.",
                blocks_trading=True,
            ))
        elif inp.spread_to_atr >= D("0.12"):
            items.append(Contradiction(
                kind=ContradictionKind.BREAKOUT_VS_SPREAD,
                side_a_ar="إشارة اختراق",
                side_b_ar=f"سبريد {inp.spread_to_atr:.3f} من ATR",
                severity=Severity.MAJOR,
                resolvable=False,
                resolution_ar=(
                    "اتساع السبريد عند الاختراق علامة سيولة رديئة لا علامة قوة. "
                    "القرار NO_TRADE."
                ),
                blocks_trading=True,
            ))

    # 4. دخول صالح مقابل حدث عالي الأثر قريب
    m = inp.minutes_to_next_high_impact_event
    if m is not None and 0 <= m <= EVENT_PROXIMITY_MINUTES:
        items.append(Contradiction(
            kind=ContradictionKind.ENTRY_VS_EVENT,
            side_a_ar="إعداد دخول صالح",
            side_b_ar=f"حدث عالي الأثر بعد {m} دقيقة",
            severity=Severity.CRITICAL,
            resolvable=False,
            resolution_ar=(
                "قرب الحدث يتقدّم على جودة الإعداد. لا صفقة تُفتح لتُترك لتقلب حدث."
            ),
            blocks_trading=True,
        ))

    # 5. R:R موجب قبل التكاليف وسالب/غير كافٍ بعدها
    if not is_unknown(inp.gross_reward_risk) and not is_unknown(inp.net_reward_risk):
        if (
            inp.gross_reward_risk >= inp.required_reward_risk
            and inp.net_reward_risk < inp.required_reward_risk
        ):
            items.append(Contradiction(
                kind=ContradictionKind.RR_BEFORE_VS_AFTER_COSTS,
                side_a_ar=f"R:R قبل التكاليف {inp.gross_reward_risk:.2f} كافٍ",
                side_b_ar=f"R:R بعد التكاليف {inp.net_reward_risk:.2f} دون المتطلب "
                          f"{inp.required_reward_risk:.2f}",
                severity=Severity.CRITICAL,
                resolvable=False,
                resolution_ar=(
                    "**الرقم بعد التكاليف هو الحقيقي دائماً.** "
                    "لا يُختار الأفضل من الرقمين. القرار NO_TRADE."
                ),
                blocks_trading=True,
            ))

    # 6. استراتيجية اتجاه على نظام نطاق (وأي عدم توافق معلن)
    if not inp.strategy_declares_regime_compatible:
        items.append(Contradiction(
            kind=ContradictionKind.STRATEGY_VS_REGIME,
            side_a_ar=f"الاستراتيجية {inp.strategy_key}",
            side_b_ar=f"النظام {inp.regime.regime.value}",
            severity=Severity.CRITICAL,
            resolvable=False,
            resolution_ar=(
                "الاستراتيجية لا تعلن توافقها مع هذا النظام. "
                "لا تُطبَّق استراتيجية خارج نظامها المعلن."
            ),
            blocks_trading=True,
        ))

    # 7. سعر وسيط حديث مقابل شموع قديمة
    if inp.quote_age_seconds is not None and inp.oldest_candle_age_seconds is not None:
        gap = inp.oldest_candle_age_seconds - inp.quote_age_seconds
        if gap > MAX_PRICE_CANDLE_AGE_GAP_SECONDS:
            items.append(Contradiction(
                kind=ContradictionKind.FRESH_PRICE_VS_STALE_CANDLES,
                side_a_ar=f"سعر الوسيط عمره {inp.quote_age_seconds:.0f} ثانية",
                side_b_ar=f"آخر شمعة عمرها {inp.oldest_candle_age_seconds:.0f} ثانية",
                severity=Severity.CRITICAL,
                resolvable=False,
                resolution_ar=(
                    "خلط سعر حديث بشموع قديمة يُنتج تحليلاً يبدو متسقاً وهو ليس كذلك. "
                    "تُعاد بناء اللقطة كاملة أو لا قرار."
                ),
                blocks_trading=True,
            ))

    return ContradictionReport(items=tuple(items))


__all__ = [
    "Severity",
    "SEVERITY_PENALTY",
    "SEVERITY_AR",
    "ContradictionKind",
    "Contradiction",
    "ContradictionReport",
    "ContradictionInputs",
    "EVENT_PROXIMITY_MINUTES",
    "MAX_PRICE_CANDLE_AGE_GAP_SECONDS",
    "detect_contradictions",
]
