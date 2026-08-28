"""
DETERMINISTIC QUALITY SCORE — درجة جودة شفافة من 0 إلى 100.

**لا يولّد هذه الدرجة نموذج لغوي.** كل نقطة لها مصدر مُسمّى وقاعدة مكتوبة،
ويمكن إعادة إنتاج الدرجة كاملة من نفس اللقطة.

القاعدة الأهم في هذا الملف:

    **فشل بوابة إلزامية لا يُعوَّض بدرجة عالية في مكان آخر.**

الدرجة **لا تُستشار أصلاً** إذا سقطت بوابة إلزامية. هذا مفروض بالبنية:
`evaluate_quality()` تعيد `mandatory_failure` ودرجةً معاً، و`pipeline.py`
يفحص `mandatory_failure` **قبل** أن ينظر إلى الرقم.
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

MAX_SCORE = 100


class ScoreCategory(str, Enum):
    DATA_INTEGRITY = "DATA_INTEGRITY"
    NEWS_CALENDAR_SAFETY = "NEWS_CALENDAR_SAFETY"
    HTF_REGIME_CLARITY = "HTF_REGIME_CLARITY"
    STRATEGY_REGIME_FIT = "STRATEGY_REGIME_FIT"
    STRUCTURE_QUALITY = "STRUCTURE_QUALITY"
    ENTRY_CONFIRMATION = "ENTRY_CONFIRMATION"
    FUNDAMENTAL_COMPATIBILITY = "FUNDAMENTAL_COMPATIBILITY"
    VOLATILITY_SUITABILITY = "VOLATILITY_SUITABILITY"
    SPREAD_AND_COST = "SPREAD_AND_COST"
    STOP_VALIDITY = "STOP_VALIDITY"
    NET_REWARD_RISK = "NET_REWARD_RISK"
    CONTRADICTION_PENALTY = "CONTRADICTION_PENALTY"


#: أوزان معلنة. مجموع الفئات الموجبة = 100 بالضبط، والعقوبة تُطرح بعدها.
CATEGORY_WEIGHTS: dict[ScoreCategory, int] = {
    ScoreCategory.DATA_INTEGRITY: 12,
    ScoreCategory.NEWS_CALENDAR_SAFETY: 10,
    ScoreCategory.HTF_REGIME_CLARITY: 14,
    ScoreCategory.STRATEGY_REGIME_FIT: 12,
    ScoreCategory.STRUCTURE_QUALITY: 10,
    ScoreCategory.ENTRY_CONFIRMATION: 8,
    ScoreCategory.FUNDAMENTAL_COMPATIBILITY: 8,
    ScoreCategory.VOLATILITY_SUITABILITY: 6,
    ScoreCategory.SPREAD_AND_COST: 8,
    ScoreCategory.STOP_VALIDITY: 6,
    ScoreCategory.NET_REWARD_RISK: 6,
}

assert sum(CATEGORY_WEIGHTS.values()) == MAX_SCORE, "الأوزان يجب أن تساوي 100 بالضبط."

CATEGORY_NAME_AR: dict[ScoreCategory, str] = {
    ScoreCategory.DATA_INTEGRITY: "سلامة البيانات",
    ScoreCategory.NEWS_CALENDAR_SAFETY: "أمان الأخبار والتقويم",
    ScoreCategory.HTF_REGIME_CLARITY: "وضوح نظام الإطار الأعلى",
    ScoreCategory.STRATEGY_REGIME_FIT: "ملاءمة الاستراتيجية للنظام",
    ScoreCategory.STRUCTURE_QUALITY: "جودة البنية",
    ScoreCategory.ENTRY_CONFIRMATION: "تأكيد الدخول",
    ScoreCategory.FUNDAMENTAL_COMPATIBILITY: "توافق الأساسيات",
    ScoreCategory.VOLATILITY_SUITABILITY: "ملاءمة التقلب",
    ScoreCategory.SPREAD_AND_COST: "السبريد وتكلفة التنفيذ",
    ScoreCategory.STOP_VALIDITY: "صحة الوقف",
    ScoreCategory.NET_REWARD_RISK: "العائد/المخاطرة الصافي",
    ScoreCategory.CONTRADICTION_PENALTY: "عقوبة التناقضات",
}


class MandatoryFailure(str, Enum):
    """
    أسباب `NO_TRADE` التي **لا تُعوَّض بأي درجة**.
    وجود أي منها يعني أن الرقم لا يُستشار أصلاً.
    """

    MISSING_CRITICAL_DATA = "MISSING_CRITICAL_DATA"
    HIGH_IMPACT_BLACKOUT = "HIGH_IMPACT_BLACKOUT"
    INVALID_STOP = "INVALID_STOP"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    REWARD_RISK_BELOW_PROFILE = "REWARD_RISK_BELOW_PROFILE"
    RISK_ENGINE_VETO = "RISK_ENGINE_VETO"
    NO_TRADE_REGIME = "NO_TRADE_REGIME"
    NO_STRATEGY_MATCH = "NO_STRATEGY_MATCH"
    STRATEGY_NOT_APPROVED = "STRATEGY_NOT_APPROVED"
    MARKET_CLOSED = "MARKET_CLOSED"
    UNRESOLVED_CONTRADICTION = "UNRESOLVED_CONTRADICTION"
    VERIFICATION_MISMATCH = "VERIFICATION_MISMATCH"


MANDATORY_FAILURE_AR: dict[MandatoryFailure, str] = {
    MandatoryFailure.MISSING_CRITICAL_DATA: "بيانات حرجة ناقصة — لا تُقدَّر ولا تُستبدل.",
    MandatoryFailure.HIGH_IMPACT_BLACKOUT: "نافذة حجب حدث عالي الأثر.",
    MandatoryFailure.INVALID_STOP: "وقف غير صالح.",
    MandatoryFailure.SPREAD_TOO_WIDE: "السبريد أوسع من الحد.",
    MandatoryFailure.REWARD_RISK_BELOW_PROFILE: "العائد/المخاطرة الصافي دون متطلب الملف.",
    MandatoryFailure.RISK_ENGINE_VETO: "نقض من محرك المخاطر.",
    MandatoryFailure.NO_TRADE_REGIME: "نظام سوق لا يُتداول فيه.",
    MandatoryFailure.NO_STRATEGY_MATCH: "لا استراتيجية مطابقة للنظام.",
    MandatoryFailure.STRATEGY_NOT_APPROVED: "الاستراتيجية ليست معتمدة.",
    MandatoryFailure.MARKET_CLOSED: "السوق غير مفتوح.",
    MandatoryFailure.UNRESOLVED_CONTRADICTION: "تناقض جوهري غير محلول.",
    MandatoryFailure.VERIFICATION_MISMATCH: "اختلاف بين الحساب الأساسي والمراجع المستقل.",
}


@dataclass(frozen=True)
class ScoreLine:
    """نقطة واحدة في الدرجة، مع مصدرها — كل نقطة قابلة للتتبع."""

    category: ScoreCategory
    awarded: int
    maximum: int
    reason_ar: str
    source_ar: str

    def as_dict(self) -> dict:
        return {
            "category": self.category.value,
            "category_ar": CATEGORY_NAME_AR[self.category],
            "awarded": self.awarded,
            "maximum": self.maximum,
            "reason_ar": self.reason_ar,
            "source_ar": self.source_ar,
        }


@dataclass(frozen=True)
class QualityScore:
    total: int
    lines: tuple[ScoreLine, ...]
    mandatory_failures: tuple[MandatoryFailure, ...]

    @property
    def has_mandatory_failure(self) -> bool:
        return bool(self.mandatory_failures)

    def meets(self, threshold: int) -> bool:
        """
        العتبة تُفحص **فقط** بعد التأكد من عدم وجود فشل إلزامي.
        الدالة تعيد False دائماً عند وجود فشل إلزامي — حتى لو كانت الدرجة 100.
        """
        if self.has_mandatory_failure:
            return False
        return self.total >= threshold

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "max": MAX_SCORE,
            "has_mandatory_failure": self.has_mandatory_failure,
            "mandatory_failures": [
                {"code": f.value, "reason_ar": MANDATORY_FAILURE_AR[f]}
                for f in self.mandatory_failures
            ],
            "lines": [l.as_dict() for l in self.lines],
        }


@dataclass(frozen=True)
class ScoreInputs:
    """
    كل مدخلات الدرجة، كلها حتمية ومحسوبة سابقاً.
    لا نص حر، ولا رأي، ولا مخرج نموذج لغوي.
    """

    data_health_passed: bool
    data_unknown_count: int
    calendar_passed: bool
    news_passed: bool
    regime: RegimeAssessment
    view: MultiTimeframeView
    strategy_matched: bool
    strategy_approved: bool
    strategy_regime_compatible: bool
    entry_confirmed: bool
    fundamentals: Optional[FundamentalAssessment]
    intended_direction: TrendDirection
    volatility_percentile: Decimal | _Unknown
    spread_to_atr: Decimal | _Unknown
    stop_valid: bool
    stop_respects_broker_minimum: bool
    net_reward_risk: Decimal | _Unknown
    required_reward_risk: Decimal
    contradiction_penalty: int
    unresolved_material_contradiction: bool


def evaluate_quality(inp: ScoreInputs) -> QualityScore:
    lines: list[ScoreLine] = []
    failures: list[MandatoryFailure] = []

    def add(cat: ScoreCategory, awarded: int, reason: str, source: str) -> None:
        lines.append(ScoreLine(cat, awarded, CATEGORY_WEIGHTS[cat], reason, source))

    # 1. سلامة البيانات
    if inp.data_health_passed and inp.data_unknown_count == 0:
        add(ScoreCategory.DATA_INTEGRITY, 12, "كل الفحوص اجتازت ولا حقل UNKNOWN.", "DataHealthGate")
    elif inp.data_health_passed:
        add(
            ScoreCategory.DATA_INTEGRITY, 6,
            f"اجتاز الفحص لكن {inp.data_unknown_count} حقل غير معلوم.", "DataHealthGate",
        )
    else:
        add(ScoreCategory.DATA_INTEGRITY, 0, "بوابة سلامة البيانات لم تُجتَز.", "DataHealthGate")
        failures.append(MandatoryFailure.MISSING_CRITICAL_DATA)

    # 2. أمان الأخبار والتقويم
    if inp.calendar_passed and inp.news_passed:
        add(ScoreCategory.NEWS_CALENDAR_SAFETY, 10, "لا حجب ولا خبر حاجب.", "CalendarGate + NewsGate")
    else:
        add(ScoreCategory.NEWS_CALENDAR_SAFETY, 0, "حجب حدث أو خبر عالي الأثر.", "CalendarGate + NewsGate")
        failures.append(MandatoryFailure.HIGH_IMPACT_BLACKOUT)

    # 3. وضوح نظام الإطار الأعلى
    if not inp.regime.tradable:
        add(ScoreCategory.HTF_REGIME_CLARITY, 0, f"النظام {inp.regime.regime.value}.", "RegimeClassifier")
        failures.append(MandatoryFailure.NO_TRADE_REGIME)
    else:
        aligned = inp.view.aligned_directional(inp.intended_direction)
        conflicting = inp.view.conflicting_directional(inp.intended_direction)
        if not conflicting and len(aligned) >= 3:
            add(ScoreCategory.HTF_REGIME_CLARITY, 14,
                f"{len(aligned)} أطر اتجاهية متوافقة بلا مخالف.", "MultiTimeframeView")
        elif not conflicting:
            add(ScoreCategory.HTF_REGIME_CLARITY, 9,
                f"{len(aligned)} أطر متوافقة، لا مخالف.", "MultiTimeframeView")
        elif len(aligned) > len(conflicting):
            add(ScoreCategory.HTF_REGIME_CLARITY, 4,
                f"{len(conflicting)} إطار مخالف مقابل {len(aligned)} متوافق.", "MultiTimeframeView")
        else:
            add(ScoreCategory.HTF_REGIME_CLARITY, 0,
                f"{len(conflicting)} إطار مخالف — لا وضوح.", "MultiTimeframeView")

    # 4. ملاءمة الاستراتيجية للنظام
    if not inp.strategy_matched:
        add(ScoreCategory.STRATEGY_REGIME_FIT, 0, "لا استراتيجية مطابقة.", "StrategyRegistry")
        failures.append(MandatoryFailure.NO_STRATEGY_MATCH)
    elif not inp.strategy_regime_compatible:
        add(ScoreCategory.STRATEGY_REGIME_FIT, 0, "الاستراتيجية لا تعلن توافقها مع النظام.", "StrategyRegistry")
        failures.append(MandatoryFailure.NO_STRATEGY_MATCH)
    else:
        add(ScoreCategory.STRATEGY_REGIME_FIT, 12, "الاستراتيجية تعلن توافقها مع النظام.", "StrategyRegistry")
        if not inp.strategy_approved:
            failures.append(MandatoryFailure.STRATEGY_NOT_APPROVED)

    # 5. جودة البنية
    incomplete = inp.view.incomplete_timeframes()
    if incomplete:
        add(ScoreCategory.STRUCTURE_QUALITY, 0,
            "أطر ناقصة: " + "، ".join(tf.value for tf in incomplete), "MultiTimeframeView")
    else:
        clear = sum(
            1 for a in inp.view.analyses.values()
            if a.is_directional and a.structure.value not in ("UNCLEAR",)
        )
        awarded = 10 if clear >= 4 else (6 if clear >= 3 else 2)
        add(ScoreCategory.STRUCTURE_QUALITY, awarded, f"{clear} أطر ببنية واضحة.", "StructureClassifier")

    # 6. تأكيد الدخول
    add(
        ScoreCategory.ENTRY_CONFIRMATION,
        8 if inp.entry_confirmed else 0,
        "شمعة تأكيد موجودة." if inp.entry_confirmed else "لا تأكيد دخول.",
        "EntrySetupValidator",
    )

    # 7. توافق الأساسيات
    f = inp.fundamentals
    if f is None or not f.usable:
        add(ScoreCategory.FUNDAMENTAL_COMPATIBILITY, 0,
            "الأساسيات غير متاحة أو غير كافية — لا نقاط، ولا افتراض حياد.",
            "FundamentalAssessment")
    else:
        want_up = inp.intended_direction is TrendDirection.UP
        score = {Bias.STRONGLY_BULLISH: 2, Bias.BULLISH: 1, Bias.NEUTRAL: 0,
                 Bias.BEARISH: -1, Bias.STRONGLY_BEARISH: -2, Bias.UNKNOWN: 0}[f.relative_bias]
        aligned_score = score if want_up else -score
        if aligned_score >= 2:
            add(ScoreCategory.FUNDAMENTAL_COMPATIBILITY, 8, "الأساسيات تدعم الاتجاه بقوة.", "FundamentalAssessment")
        elif aligned_score == 1:
            add(ScoreCategory.FUNDAMENTAL_COMPATIBILITY, 5, "الأساسيات تدعم الاتجاه.", "FundamentalAssessment")
        elif aligned_score == 0:
            add(ScoreCategory.FUNDAMENTAL_COMPATIBILITY, 3, "الأساسيات محايدة.", "FundamentalAssessment")
        else:
            add(ScoreCategory.FUNDAMENTAL_COMPATIBILITY, 0, "الأساسيات تخالف الاتجاه.", "FundamentalAssessment")

    # 8. ملاءمة التقلب
    if is_unknown(inp.volatility_percentile):
        add(ScoreCategory.VOLATILITY_SUITABILITY, 0, "المئين التقلبي غير معلوم.", "Indicators")
    else:
        v = inp.volatility_percentile
        if D("25") <= v <= D("75"):
            add(ScoreCategory.VOLATILITY_SUITABILITY, 6, f"تقلب معتدل ({v:.0f}).", "Indicators")
        elif D("15") <= v <= D("85"):
            add(ScoreCategory.VOLATILITY_SUITABILITY, 3, f"تقلب مقبول ({v:.0f}).", "Indicators")
        else:
            add(ScoreCategory.VOLATILITY_SUITABILITY, 0, f"تقلب متطرف ({v:.0f}).", "Indicators")

    # 9. السبريد والتكلفة
    if is_unknown(inp.spread_to_atr):
        add(ScoreCategory.SPREAD_AND_COST, 0, "نسبة السبريد إلى ATR غير معلومة.", "Indicators")
        failures.append(MandatoryFailure.MISSING_CRITICAL_DATA)
    else:
        r = inp.spread_to_atr
        if r <= D("0.05"):
            add(ScoreCategory.SPREAD_AND_COST, 8, f"السبريد {r:.3f} من ATR — ممتاز.", "Indicators")
        elif r <= D("0.12"):
            add(ScoreCategory.SPREAD_AND_COST, 5, f"السبريد {r:.3f} من ATR — مقبول.", "Indicators")
        elif r < D("0.25"):
            add(ScoreCategory.SPREAD_AND_COST, 1, f"السبريد {r:.3f} من ATR — مرتفع.", "Indicators")
        else:
            add(ScoreCategory.SPREAD_AND_COST, 0, f"السبريد {r:.3f} من ATR — مفرط.", "Indicators")
            failures.append(MandatoryFailure.SPREAD_TOO_WIDE)

    # 10. صحة الوقف
    if inp.stop_valid and inp.stop_respects_broker_minimum:
        add(ScoreCategory.STOP_VALIDITY, 6, "الوقف صحيح فنياً ويحترم حد الوسيط.", "PositionConstruction")
    else:
        add(ScoreCategory.STOP_VALIDITY, 0, "الوقف غير صالح أو دون حد الوسيط.", "PositionConstruction")
        failures.append(MandatoryFailure.INVALID_STOP)

    # 11. العائد/المخاطرة الصافي
    if is_unknown(inp.net_reward_risk):
        add(ScoreCategory.NET_REWARD_RISK, 0, "R:R الصافي غير محسوب.", "CostModel")
        failures.append(MandatoryFailure.MISSING_CRITICAL_DATA)
    else:
        rr = inp.net_reward_risk
        if rr < inp.required_reward_risk:
            add(ScoreCategory.NET_REWARD_RISK, 0,
                f"R:R الصافي {rr:.2f} دون متطلب الملف {inp.required_reward_risk:.2f}.", "CostModel")
            failures.append(MandatoryFailure.REWARD_RISK_BELOW_PROFILE)
        elif rr >= inp.required_reward_risk + D("0.75"):
            add(ScoreCategory.NET_REWARD_RISK, 6, f"R:R الصافي {rr:.2f} — هامش مريح.", "CostModel")
        else:
            add(ScoreCategory.NET_REWARD_RISK, 3, f"R:R الصافي {rr:.2f} فوق المتطلب.", "CostModel")

    # 12. عقوبة التناقضات
    penalty = max(0, inp.contradiction_penalty)
    lines.append(
        ScoreLine(
            ScoreCategory.CONTRADICTION_PENALTY,
            -penalty,
            0,
            f"خصم {penalty} نقطة لتناقضات مسجَّلة." if penalty else "لا تناقضات مادية.",
            "ContradictionEngine",
        )
    )
    if inp.unresolved_material_contradiction:
        failures.append(MandatoryFailure.UNRESOLVED_CONTRADICTION)

    positive = sum(l.awarded for l in lines if l.awarded > 0)
    total = max(0, min(MAX_SCORE, positive - penalty))

    # إزالة التكرار مع الحفاظ على الترتيب
    seen: set[MandatoryFailure] = set()
    unique: list[MandatoryFailure] = []
    for f_ in failures:
        if f_ not in seen:
            seen.add(f_)
            unique.append(f_)

    return QualityScore(total=total, lines=tuple(lines), mandatory_failures=tuple(unique))


__all__ = [
    "MAX_SCORE",
    "ScoreCategory",
    "CATEGORY_WEIGHTS",
    "CATEGORY_NAME_AR",
    "MandatoryFailure",
    "MANDATORY_FAILURE_AR",
    "ScoreLine",
    "QualityScore",
    "ScoreInputs",
    "evaluate_quality",
]
