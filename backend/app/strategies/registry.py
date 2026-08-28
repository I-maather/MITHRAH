"""
STRATEGY REGISTRY — سجل الاستراتيجيات المُصدَّرة بإصدارات.

القواعد، حرفياً:

  * كل الاستراتيجيات تبدأ في حالة `RESEARCH`.
  * **لا تصبح استراتيجية حيّة لمجرد أنها تُنتج إشارة.**
  * كل استراتيجية تعلن: الأنظمة المتوافقة · الأنظمة غير المتوافقة ·
    متطلبات الأطر الزمنية · قواعد الدخول والإبطال والوقف والخروج.
  * **تُختار استراتيجية واحدة بالضبط** لكل قرار.
  * **لا تُدمج استراتيجيات حتى تُنتج إحداها الجواب المرغوب.**
  * لا اختراع استراتيجية في وقت التشغيل.
  * لا تغيير معامل بلا إصدار جديد وتحقق كامل.

المطابقة الأولية المقصودة:
  TREND               → TREND_PULLBACK
  BREAKOUT_CONFIRMED  → BREAKOUT_RETEST
  RANGE               → RANGE_MEAN_REVERSION
  CHOPPY / EVENT_RISK / LOW_LIQUIDITY / UNKNOWN → NO_TRADE
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Optional

from ..contracts import StrategyState
from ..intelligence.regime import MarketRegime
from ..intelligence.snapshot import Timeframe
from ..money import D


class StrategyRegistryError(RuntimeError):
    """يُرفع عند محاولة اختراع استراتيجية أو تعديل معامل بلا إصدار."""


@dataclass(frozen=True)
class TimeframeRequirement:
    timeframe: Timeframe
    min_bars: int
    purpose_ar: str


@dataclass(frozen=True)
class StrategyDefinition:
    """
    تعريف مجمّد لاستراتيجية بإصدار محدد.

    `is_reversal` مهم: الإطار الأدنى لا يتجاوز نظام الإطار الأعلى إلا في
    استراتيجية انعكاس **مُتحقَّق منها استقلالاً**، ولا توجد واحدة معتمدة.
    """

    name: str
    version: str
    state: StrategyState
    title_ar: str
    thesis_ar: str

    compatible_regimes: frozenset[MarketRegime]
    incompatible_regimes: frozenset[MarketRegime]
    timeframe_requirements: tuple[TimeframeRequirement, ...]

    entry_rules_ar: tuple[str, ...]
    invalidation_rules_ar: tuple[str, ...]
    stop_rules_ar: tuple[str, ...]
    exit_rules_ar: tuple[str, ...]

    parameters: dict[str, str]
    is_reversal: bool = False
    validation_notes_ar: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        overlap = self.compatible_regimes & self.incompatible_regimes
        if overlap:
            raise StrategyRegistryError(
                f"{self.name} يعلن نظاماً متوافقاً وغير متوافق في آن: {overlap}"
            )

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def is_live_eligible(self) -> bool:
        """الحالة `APPROVED` وحدها تسمح — ولا استراتيجية معتمدة اليوم."""
        return self.state is StrategyState.APPROVED

    def fingerprint(self) -> str:
        payload = {
            "name": self.name,
            "version": self.version,
            "state": self.state.value,
            "compatible": sorted(r.value for r in self.compatible_regimes),
            "incompatible": sorted(r.value for r in self.incompatible_regimes),
            "timeframes": [
                {"tf": t.timeframe.value, "min_bars": t.min_bars}
                for t in self.timeframe_requirements
            ],
            "entry": list(self.entry_rules_ar),
            "invalidation": list(self.invalidation_rules_ar),
            "stop": list(self.stop_rules_ar),
            "exit": list(self.exit_rules_ar),
            "parameters": dict(sorted(self.parameters.items())),
            "is_reversal": self.is_reversal,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(blob).hexdigest()

    def accepts(self, regime: MarketRegime) -> bool:
        return regime in self.compatible_regimes and regime not in self.incompatible_regimes

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "key": self.key,
            "state": self.state.value,
            "title_ar": self.title_ar,
            "thesis_ar": self.thesis_ar,
            "compatible_regimes": sorted(r.value for r in self.compatible_regimes),
            "incompatible_regimes": sorted(r.value for r in self.incompatible_regimes),
            "timeframe_requirements": [
                {
                    "timeframe": t.timeframe.value,
                    "min_bars": t.min_bars,
                    "purpose_ar": t.purpose_ar,
                }
                for t in self.timeframe_requirements
            ],
            "entry_rules_ar": list(self.entry_rules_ar),
            "invalidation_rules_ar": list(self.invalidation_rules_ar),
            "stop_rules_ar": list(self.stop_rules_ar),
            "exit_rules_ar": list(self.exit_rules_ar),
            "parameters": dict(self.parameters),
            "is_reversal": self.is_reversal,
            "live_eligible": self.is_live_eligible,
            "fingerprint": self.fingerprint(),
            "validation_notes_ar": list(self.validation_notes_ar),
        }


_ALL_REGIMES = frozenset(MarketRegime)
_NEVER = frozenset({
    MarketRegime.CHOPPY,
    MarketRegime.EVENT_RISK,
    MarketRegime.LOW_LIQUIDITY,
    MarketRegime.UNKNOWN,
    MarketRegime.HIGH_VOLATILITY,
})


TREND_PULLBACK = StrategyDefinition(
    name="TREND_PULLBACK",
    version="1.0.0",
    state=StrategyState.RESEARCH,
    title_ar="ارتداد داخل اتجاه",
    thesis_ar=(
        "في نظام اتجاهي واضح على الإطار الحاكم، الدخول يكون على تصحيح ضحل "
        "في اتجاه النظام، لا على اختراق قمة."
    ),
    compatible_regimes=frozenset({MarketRegime.TREND}),
    incompatible_regimes=_NEVER
    | frozenset({MarketRegime.RANGE, MarketRegime.REVERSAL_CANDIDATE, MarketRegime.BREAKOUT_PENDING}),
    timeframe_requirements=(
        TimeframeRequirement(Timeframe.D1, 120, "تحديد النظام الحاكم"),
        TimeframeRequirement(Timeframe.H4, 120, "تأكيد الاتجاه الهيكلي"),
        TimeframeRequirement(Timeframe.H1, 120, "سياق الإعداد"),
        TimeframeRequirement(Timeframe.M15, 120, "إعداد الدخول"),
    ),
    entry_rules_ar=(
        "نظام D1 اتجاهي وADX ≥ العتبة المعلنة.",
        "H4 في اتجاه D1 أو محايد — لا يخالفه.",
        "تصحيح على M15 نحو المتوسط السريع دون كسر آخر قاع تأرجح.",
        "شمعة تأكيد في اتجاه النظام على M15.",
    ),
    invalidation_rules_ar=(
        "إغلاق M15 تحت آخر قاع تأرجح (للاتجاه الصاعد).",
        "انقلاب اتجاه H4 ضد D1 ⇒ الإعداد يسقط فوراً.",
    ),
    stop_rules_ar=(
        "الوقف خلف آخر قاع تأرجح مضافاً إليه احتياطي انزلاق.",
        "**لا تُضيَّق مسافة وقف صحيحة فنياً لجعل الصفقة تناسب حد المخاطرة.**",
    ),
    exit_rules_ar=(
        "جني أرباح إلزامي عند مضاعف معلن من مسافة الوقف.",
        "الإغلاق قبل نهاية الجلسة — لا تبييت في أي ملف.",
    ),
    parameters={"adx_min": "22", "sma_fast": "20", "sma_slow": "50", "swing_strength": "2"},
    validation_notes_ar=(
        "لا Backtest على بيانات EUR/USD حقيقية بعد — لا توجد بيانات في المستودع.",
        "الحالة RESEARCH ولا تتغيّر إلا بإصدار جديد بعد اجتياز البوابات الإحدى عشرة.",
    ),
)


BREAKOUT_RETEST = StrategyDefinition(
    name="BREAKOUT_RETEST",
    version="1.0.0",
    state=StrategyState.RESEARCH,
    title_ar="إعادة اختبار اختراق",
    thesis_ar=(
        "بعد كسر بنية مؤكَّد، الدخول يكون على إعادة اختبار المستوى المكسور "
        "لا على الاختراق نفسه — لتفادي الاختراق الكاذب."
    ),
    compatible_regimes=frozenset({MarketRegime.BREAKOUT_CONFIRMED}),
    incompatible_regimes=_NEVER
    | frozenset({MarketRegime.RANGE, MarketRegime.TREND, MarketRegime.REVERSAL_CANDIDATE}),
    timeframe_requirements=(
        TimeframeRequirement(Timeframe.D1, 120, "تأكيد كسر البنية"),
        TimeframeRequirement(Timeframe.H4, 120, "تحديد المستوى المكسور"),
        TimeframeRequirement(Timeframe.M15, 120, "إعادة الاختبار والدخول"),
    ),
    entry_rules_ar=(
        "كسر بنية مؤكَّد على D1 مع ADX داعم.",
        "عودة السعر إلى المستوى المكسور دون إغلاق تحته (لاختراق صاعد).",
        "شمعة رفض عند المستوى على M15.",
    ),
    invalidation_rules_ar=(
        "إغلاق M15 داخل النطاق السابق ⇒ الاختراق كاذب والإعداد يسقط.",
    ),
    stop_rules_ar=(
        "الوقف تحت المستوى المكسور مضافاً إليه احتياطي انزلاق.",
        "لا تضييق للوقف لأغراض الحجم.",
    ),
    exit_rules_ar=(
        "جني أرباح إلزامي عند ارتفاع النطاق المكسور أو مضاعف معلن.",
        "لا تبييت.",
    ),
    parameters={"adx_min": "22", "retest_tolerance_atr": "0.5", "swing_strength": "2"},
    validation_notes_ar=("RESEARCH — لا Backtest ولا Shadow بعد.",),
)


RANGE_MEAN_REVERSION = StrategyDefinition(
    name="RANGE_MEAN_REVERSION",
    version="1.0.0",
    state=StrategyState.RESEARCH,
    title_ar="ارتداد إلى المتوسط داخل نطاق",
    thesis_ar=(
        "داخل نطاق محدَّد الحدود وADX منخفض، الدخول من حافة النطاق نحو وسطه."
    ),
    compatible_regimes=frozenset({MarketRegime.RANGE}),
    incompatible_regimes=_NEVER
    | frozenset({
        MarketRegime.TREND,
        MarketRegime.BREAKOUT_CONFIRMED,
        MarketRegime.BREAKOUT_PENDING,
        MarketRegime.REVERSAL_CANDIDATE,
    }),
    timeframe_requirements=(
        TimeframeRequirement(Timeframe.D1, 120, "إثبات النطاق"),
        TimeframeRequirement(Timeframe.H1, 120, "تحديد الحدود"),
        TimeframeRequirement(Timeframe.M15, 120, "الدخول من الحافة"),
    ),
    entry_rules_ar=(
        "ADX على D1 دون عتبة النطاق وبنية نطاقية.",
        "السعر عند حافة النطاق مع زخم متطرف (RSI).",
        "شمعة رفض عند الحافة على M15.",
    ),
    invalidation_rules_ar=(
        "إغلاق خارج النطاق ⇒ النظام تغيّر والإعداد يسقط.",
    ),
    stop_rules_ar=("الوقف خارج حافة النطاق مضافاً إليه احتياطي انزلاق.",),
    exit_rules_ar=("الهدف وسط النطاق أو الحافة المقابلة. لا تبييت.",),
    parameters={"adx_max": "18", "rsi_low": "30", "rsi_high": "70"},
    validation_notes_ar=("RESEARCH — لا Backtest ولا Shadow بعد.",),
)


class StrategyDefinitionRegistry:
    """
    سجل **تعريفات** الاستراتيجيات المُصدَّرة.

    ⚠️ لا يُخلط مع `app.strategies.base.StrategyRegistry`، وهو سجل الاستراتيجيات
    **القابلة للتنفيذ** في خط 0.1.0. هذا السجل يحمل التعريف والعقد والحالة
    والإصدار؛ ذاك يحمل الكائن الذي يولّد إشارة.

    سجل مغلق. لا يقبل تسجيلاً في وقت التشغيل من مصدر غير موثوق، ولا يقبل
    استراتيجيتين بالمفتاح نفسه، ويرفض اختيار أكثر من واحدة لقرار واحد.
    """

    def __init__(self, definitions: Optional[list[StrategyDefinition]] = None) -> None:
        self._by_key: dict[str, StrategyDefinition] = {}
        for d in definitions if definitions is not None else DEFAULT_DEFINITIONS:
            self.register(d)

    def register(self, definition: StrategyDefinition) -> None:
        if definition.key in self._by_key:
            raise StrategyRegistryError(f"استراتيجية مسجَّلة مسبقاً: {definition.key}")
        self._by_key[definition.key] = definition

    def all(self) -> tuple[StrategyDefinition, ...]:
        return tuple(self._by_key[k] for k in sorted(self._by_key))

    def get(self, name: str, version: str) -> StrategyDefinition:
        key = f"{name}@{version}"
        if key not in self._by_key:
            raise StrategyRegistryError(f"استراتيجية غير معروفة: {key}. لا اختراع في وقت التشغيل.")
        return self._by_key[key]

    def approved(self) -> tuple[StrategyDefinition, ...]:
        return tuple(d for d in self.all() if d.is_live_eligible)

    def candidates_for(self, regime: MarketRegime) -> tuple[StrategyDefinition, ...]:
        return tuple(d for d in self.all() if d.accepts(regime))

    def as_dict(self) -> dict:
        return {
            "strategies": [d.as_dict() for d in self.all()],
            "approved_count": len(self.approved()),
            "note_ar": (
                "لا استراتيجية معتمدة. الحالة RESEARCH لا تسمح بإرسال أمر مهما "
                "كانت جودة الإشارة."
            ),
        }


DEFAULT_DEFINITIONS: list[StrategyDefinition] = [
    TREND_PULLBACK,
    BREAKOUT_RETEST,
    RANGE_MEAN_REVERSION,
]


@dataclass(frozen=True)
class StrategyMatch:
    """نتيجة المطابقة. استراتيجية واحدة أو لا شيء — لا دمج ولا تصويت."""

    matched: Optional[StrategyDefinition]
    regime: MarketRegime
    reason_ar: str
    rejected_ar: tuple[str, ...] = ()

    @property
    def has_match(self) -> bool:
        return self.matched is not None

    def as_dict(self) -> dict:
        return {
            "matched": self.matched.key if self.matched else None,
            "matched_title_ar": self.matched.title_ar if self.matched else None,
            "matched_state": self.matched.state.value if self.matched else None,
            "regime": self.regime.value,
            "reason_ar": self.reason_ar,
            "rejected_ar": list(self.rejected_ar),
        }


def match_strategy(registry: StrategyDefinitionRegistry, regime: MarketRegime) -> StrategyMatch:
    """
    مطابقة حتمية: نظام واحد ⇒ مرشّح واحد على الأكثر.
    وجود مرشّحين لنظام واحد خطأ تكوين يُرفَض صراحةً بدل أن يُحلّ بتصويت.
    """
    from .registry import _NEVER as never  # نفس المجموعة، صراحةً للقراءة

    candidates = registry.candidates_for(regime)
    rejected = [
        f"{d.key}: النظام {regime.value} غير متوافق."
        for d in registry.all()
        if d not in candidates
    ]

    if regime in never:
        return StrategyMatch(
            matched=None,
            regime=regime,
            reason_ar=f"النظام {regime.value} يعني NO_TRADE في كل الملفات — لا مطابقة.",
            rejected_ar=tuple(rejected),
        )
    if not candidates:
        return StrategyMatch(
            matched=None,
            regime=regime,
            reason_ar=f"لا استراتيجية تعلن توافقها مع النظام {regime.value}.",
            rejected_ar=tuple(rejected),
        )
    if len(candidates) > 1:
        raise StrategyRegistryError(
            f"أكثر من استراتيجية للنظام {regime.value}: "
            + "، ".join(d.key for d in candidates)
            + ". لا تُدمج استراتيجيات ولا يُصوَّت بينها."
        )

    matched = candidates[0]
    return StrategyMatch(
        matched=matched,
        regime=regime,
        reason_ar=(
            f"{matched.title_ar} ({matched.key}) هي المرشّحة للنظام {regime.value}. "
            f"حالتها {matched.state.value}."
        ),
        rejected_ar=tuple(rejected),
    )


__all__ = [
    "StrategyDefinition",
    "TimeframeRequirement",
    "StrategyDefinitionRegistry",
    "StrategyRegistryError",
    "StrategyMatch",
    "match_strategy",
    "TREND_PULLBACK",
    "BREAKOUT_RETEST",
    "RANGE_MEAN_REVERSION",
    "DEFAULT_DEFINITIONS",
]
