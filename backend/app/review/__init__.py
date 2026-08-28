"""
POST-TRADE REVIEW & CALIBRATION — المراجعة بعد الصفقة والمعايرة الإحصائية.

قاعدتان تحكمان هذه الحزمة:

1. **ليست كل خسارة فشل استراتيجية.** التصنيف الكسول «خسرنا ⇒ الاستراتيجية سيئة»
   يقود إلى تغيير معاملات بلا سبب، وهو أسوأ من الخسارة نفسها.

2. **المعايرة تقترح ولا تنفّذ.** لا يوجد في هذه الحزمة مسار واحد يزيد مخاطرة،
   أو يغيّر معاملاً حياً، أو يخفض عتبة، أو يفعّل استراتيجية، أو يعطّل Kill Switch،
   أو يوسّع وقفاً، أو يضيف مؤشراً، أو يختار ملفاً أعلى مخاطرة.
   مخرجها **توصيات بحثية نصية** لا غير.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from ..money import D
from ..profiles import TradingProfile


class OutcomeClass(str, Enum):
    """
    تصنيف نتيجة الصفقة. الخسارة الصحيحة نتيجة مقبولة تماماً —
    خسارة ضمن الحد بعد إعداد سليم هي **نجاح تشغيلي**، لا فشل.
    """

    VALID_LOSS = "VALID_LOSS"
    VALID_WIN = "VALID_WIN"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    DATA_FAILURE = "DATA_FAILURE"
    RULE_VIOLATION = "RULE_VIOLATION"
    STRATEGY_MISMATCH = "STRATEGY_MISMATCH"
    ABNORMAL_MARKET_EVENT = "ABNORMAL_MARKET_EVENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNKNOWN = "UNKNOWN"


OUTCOME_AR: dict[OutcomeClass, str] = {
    OutcomeClass.VALID_LOSS: "خسارة صحيحة — الإعداد سليم والنتيجة ضمن التوقع الإحصائي.",
    OutcomeClass.VALID_WIN: "ربح صحيح — لا يثبت وحده صلاحية الاستراتيجية.",
    OutcomeClass.EXECUTION_FAILURE: "فشل تنفيذ — الوسيط أو الأمر لم يتصرف كما هو متوقع.",
    OutcomeClass.DATA_FAILURE: "فشل بيانات — الإعداد بُني على بيانات خاطئة أو قديمة.",
    OutcomeClass.RULE_VIOLATION: "مخالفة قاعدة — النظام لم يتبع قواعده المعلنة.",
    OutcomeClass.STRATEGY_MISMATCH: "عدم ملاءمة — الاستراتيجية طُبِّقت خارج نظامها.",
    OutcomeClass.ABNORMAL_MARKET_EVENT: "حدث سوقي شاذ خارج نطاق النموذج.",
    OutcomeClass.INSUFFICIENT_EVIDENCE: "أدلة غير كافية للتصنيف.",
    OutcomeClass.UNKNOWN: "غير معلوم.",
}


class TradeMode(str, Enum):
    DEMO = "DEMO"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


@dataclass(frozen=True)
class PostTradeRecord:
    """
    سجل مراجعة كامل لصفقة واحدة — Demo أو Shadow أو (مستقبلاً) Live.
    كل حقل هنا إلزامي لأن غيابه يجعل المراجعة تخميناً.
    """

    trade_id: str
    mode: TradeMode
    opened_at_utc: datetime
    closed_at_utc: Optional[datetime]

    snapshot_id: str                 # اللقطة الأصلية غير القابلة للتعديل
    strategy_key: str                # الاسم@الإصدار
    profile: TradingProfile

    entry_reason_ar: str
    contradictions_considered_ar: tuple[str, ...]

    expected_costs: Decimal
    actual_costs: Decimal
    expected_slippage: Decimal
    actual_slippage: Decimal

    max_favorable_excursion: Decimal
    max_adverse_excursion: Decimal

    exit_reason_ar: str
    outcome_money: Decimal
    outcome_r: Decimal               # النتيجة بوحدات المخاطرة

    followed_strategy_rules: bool
    broker_matched_local_expectation: bool
    llm_explanation_accurate: Optional[bool]

    outcome_class: OutcomeClass
    lessons_research_only_ar: tuple[str, ...] = ()

    @property
    def cost_variance(self) -> Decimal:
        return self.actual_costs - self.expected_costs

    @property
    def slippage_variance(self) -> Decimal:
        return self.actual_slippage - self.expected_slippage

    def as_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "mode": self.mode.value,
            "opened_at_utc": self.opened_at_utc.isoformat(),
            "closed_at_utc": self.closed_at_utc.isoformat() if self.closed_at_utc else None,
            "snapshot_id": self.snapshot_id,
            "strategy_key": self.strategy_key,
            "profile": self.profile.value,
            "entry_reason_ar": self.entry_reason_ar,
            "contradictions_considered_ar": list(self.contradictions_considered_ar),
            "expected_costs": f"{self.expected_costs:.4f}",
            "actual_costs": f"{self.actual_costs:.4f}",
            "cost_variance": f"{self.cost_variance:.4f}",
            "expected_slippage": f"{self.expected_slippage:.4f}",
            "actual_slippage": f"{self.actual_slippage:.4f}",
            "slippage_variance": f"{self.slippage_variance:.4f}",
            "max_favorable_excursion": f"{self.max_favorable_excursion:.4f}",
            "max_adverse_excursion": f"{self.max_adverse_excursion:.4f}",
            "exit_reason_ar": self.exit_reason_ar,
            "outcome_money": f"{self.outcome_money:.2f}",
            "outcome_r": f"{self.outcome_r:.2f}",
            "followed_strategy_rules": self.followed_strategy_rules,
            "broker_matched_local_expectation": self.broker_matched_local_expectation,
            "llm_explanation_accurate": self.llm_explanation_accurate,
            "outcome_class": self.outcome_class.value,
            "outcome_class_ar": OUTCOME_AR[self.outcome_class],
            "lessons_research_only_ar": list(self.lessons_research_only_ar),
        }


def classify_outcome(
    *,
    followed_rules: bool,
    broker_matched: bool,
    data_was_valid: bool,
    regime_was_compatible: bool,
    abnormal_event: bool,
    outcome_money: Decimal,
) -> OutcomeClass:
    """
    تصنيف حتمي بترتيب أسبقية: أسباب الفشل الإجرائي تُفحص **قبل** النتيجة المالية،
    كي لا يُصنَّف خطأ تنفيذي رابح على أنه نجاح.
    """
    if not broker_matched:
        return OutcomeClass.EXECUTION_FAILURE
    if not data_was_valid:
        return OutcomeClass.DATA_FAILURE
    if not followed_rules:
        return OutcomeClass.RULE_VIOLATION
    if not regime_was_compatible:
        return OutcomeClass.STRATEGY_MISMATCH
    if abnormal_event:
        return OutcomeClass.ABNORMAL_MARKET_EVENT
    if outcome_money > 0:
        return OutcomeClass.VALID_WIN
    if outcome_money < 0:
        return OutcomeClass.VALID_LOSS
    return OutcomeClass.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# المعايرة
# ---------------------------------------------------------------------------

#: نطاقات الدرجة التي تُقاس فيها المعايرة.
SCORE_BANDS: tuple[tuple[int, int], ...] = ((85, 89), (90, 94), (95, 100))

#: الحد الأدنى للعينة قبل أي استنتاج. أقل من ذلك = لا استنتاج، لا توصية.
MIN_SAMPLE_FOR_INFERENCE = 30


@dataclass(frozen=True)
class BandCalibration:
    band: tuple[int, int]
    sample: int
    wins: int
    losses: int
    net_r: Decimal
    sufficient_sample: bool

    @property
    def win_rate(self) -> Optional[Decimal]:
        if self.sample == 0:
            return None
        return D(self.wins) / D(self.sample)

    def as_dict(self) -> dict:
        return {
            "band": f"{self.band[0]}-{self.band[1]}",
            "sample": self.sample,
            "wins": self.wins,
            "losses": self.losses,
            "net_r": f"{self.net_r:.2f}",
            "win_rate": f"{self.win_rate:.2%}" if self.win_rate is not None else None,
            "sufficient_sample": self.sufficient_sample,
        }


@dataclass(frozen=True)
class CalibrationReport:
    bands: tuple[BandCalibration, ...]
    by_strategy: dict[str, dict]
    research_recommendations_ar: tuple[str, ...]
    #: ثابت بنيوي: لا شيء في هذا التقرير يُطبَّق تلقائياً.
    applied_automatically: bool = False

    def as_dict(self) -> dict:
        return {
            "bands": [b.as_dict() for b in self.bands],
            "by_strategy": self.by_strategy,
            "research_recommendations_ar": list(self.research_recommendations_ar),
            "applied_automatically": self.applied_automatically,
            "note_ar": (
                "توصيات بحثية فقط. أي تغيير يتطلب إصداراً جديداً و Backtest و "
                "Walk-forward و Out-of-sample و Shadow Mode وموافقة المالكة الصريحة."
            ),
        }


@dataclass(frozen=True)
class ScoredOutcome:
    """نتيجة صفقة مقرونة بدرجة جودتها وقت القرار."""

    score: int
    strategy_key: str
    outcome_class: OutcomeClass
    outcome_r: Decimal


class Calibrator:
    """
    يقارن جودة الإعداد المتوقعة بالنتائج الفعلية. **يقترح ولا يطبّق.**

    هذا الصنف لا يملك مرجعاً إلى الدستور ولا إلى الملفات ولا إلى سجل
    الاستراتيجيات ولا إلى Kill Switch — فلا يستطيع تغيير أي منها ولو أراد.
    """

    def __init__(self, min_sample: int = MIN_SAMPLE_FOR_INFERENCE) -> None:
        self.min_sample = min_sample

    def report(self, outcomes: Sequence[ScoredOutcome]) -> CalibrationReport:
        bands: list[BandCalibration] = []
        for low, high in SCORE_BANDS:
            subset = [o for o in outcomes if low <= o.score <= high]
            wins = sum(1 for o in subset if o.outcome_class is OutcomeClass.VALID_WIN)
            losses = sum(1 for o in subset if o.outcome_class is OutcomeClass.VALID_LOSS)
            net = sum((o.outcome_r for o in subset), D("0"))
            bands.append(BandCalibration(
                band=(low, high),
                sample=len(subset),
                wins=wins,
                losses=losses,
                net_r=net,
                sufficient_sample=len(subset) >= self.min_sample,
            ))

        by_strategy: dict[str, dict] = {}
        for key in sorted({o.strategy_key for o in outcomes}):
            subset = [o for o in outcomes if o.strategy_key == key]
            net = sum((o.outcome_r for o in subset), D("0"))
            by_strategy[key] = {
                "sample": len(subset),
                "net_r": f"{net:.2f}",
                "sufficient_sample": len(subset) >= self.min_sample,
                "rule_violations": sum(
                    1 for o in subset if o.outcome_class is OutcomeClass.RULE_VIOLATION
                ),
                "execution_failures": sum(
                    1 for o in subset if o.outcome_class is OutcomeClass.EXECUTION_FAILURE
                ),
                "data_failures": sum(
                    1 for o in subset if o.outcome_class is OutcomeClass.DATA_FAILURE
                ),
            }

        recs: list[str] = []
        for b in bands:
            if not b.sufficient_sample:
                recs.append(
                    f"النطاق {b.band[0]}-{b.band[1]}: العينة {b.sample} دون "
                    f"{self.min_sample} — **لا استنتاج ولا توصية**."
                )
                continue
            if b.net_r < 0:
                recs.append(
                    f"بحث فقط: النطاق {b.band[0]}-{b.band[1]} صافيه {b.net_r:.2f}R سالب "
                    f"على {b.sample} صفقة. يُدرَس سبب ذلك — **ولا يُغيَّر معامل حي**."
                )
        for key, data in by_strategy.items():
            if data["rule_violations"]:
                recs.append(
                    f"تنبيه إجرائي: {key} فيها {data['rule_violations']} مخالفة قاعدة — "
                    "خلل تنفيذي يُصلَح بالكود لا بتغيير الاستراتيجية."
                )
            if data["sufficient_sample"] and D(data["net_r"]) < 0:
                recs.append(
                    f"بحث فقط: {key} صافيها {data['net_r']}R على {data['sample']} صفقة. "
                    "يُقترح إصدار جديد يمرّ بكل بوابات التحقق — لا تعديل مباشر."
                )

        return CalibrationReport(
            bands=tuple(bands),
            by_strategy=by_strategy,
            research_recommendations_ar=tuple(recs),
        )


#: التغييرات التي تتطلب المسار الكامل. مذكورة صراحةً لتُختبَر.
REQUIRED_STEPS_FOR_ANY_CHANGE: tuple[str, ...] = (
    "إصدار جديد للاستراتيجية أو المعامل",
    "Backtest جديد",
    "Walk-forward جديد",
    "اختبار خارج العينة جديد",
    "فترة Shadow Mode جديدة",
    "موافقة صريحة من المالكة",
)


__all__ = [
    "OutcomeClass",
    "OUTCOME_AR",
    "TradeMode",
    "PostTradeRecord",
    "classify_outcome",
    "SCORE_BANDS",
    "MIN_SAMPLE_FOR_INFERENCE",
    "BandCalibration",
    "CalibrationReport",
    "ScoredOutcome",
    "Calibrator",
    "REQUIRED_STEPS_FOR_ANY_CHANGE",
]
