"""
سُلَّم الأحجام — **المخاطرة تُقاس على كل حجمٍ ممكن، لا على الأصغر وحده.**

## السؤال الذي يجيبه

كان السؤال في مسار الـCFD: «هل الخسارة الكاملة **عند الكمية الدنيا** تقع
ضمن الميزانية؟» — وهو سؤالٌ ناقص من طرفين:

1. **من فوق:** الكمية الدنيا ليست الكمية الوحيدة. الوسيط يعلن
   `minSizeIncrement`، فالأحجام الممكنة على اليورو ١٠٠ ثم ٢٠٠ ثم ٣٠٠…
   وعلى الذهب ٠٫٠١ ثم ٠٫٠٢… وأخذُ الأصغر دائماً يترك ميزانية المخاطرة
   المعتمدة غير مستعملة: وقفٌ بعشرين نقطة على اليورو يخاطر بـ٠٫٢٢ دولار
   عند ١٠٠ وحدة، والهدف المعتمد ٠٫٧٥ — أي أن ثلثي الفرصة يُهدَر بلا قرار.
2. **من تحت:** الهدف ٠٫٧٥ كان يُستعمل **سقف رفض**، فإشارةٌ خسارتها الدنيا
   القابلة للتنفيذ ١٫٠٠ دولار تُرفض — وهي تحت الحدّ الصلب ١٫٥٠ الذي
   اعتمدته المالكة. رفضٌ بلا سببٍ في السياسة.

⇒ هنا تُبنى **قائمة الأحجام القابلة للتنفيذ فعلاً**، وتُحسب الخسارة الكاملة
عند كلٍّ منها (سعرٌ + سبريد + انزلاق + تحويل + تبييت)، ثم يُختار **الأقرب
إلى الهدف** مما لا يتجاوز الحدّ الصلب ولا حدود المحفظة.

## التمييز الذي يقوم عليه كل شيء

* `Target Risk` — المخاطرة المفضّلة. **تفضيلٌ لا سقف.**
* `Hard Ceiling` — الأصغر بين الحدّ الصلب للصفقة وما تبقّى من اليوم
  والأسبوع والإجمالي. **سقفٌ لا يُتجاوَز.**

والرفض لا يقع إلا إذا لم يوجد حجمٌ واحد تحت السقف — ويُقال حينها أي قيدٍ
ربط، وأي أحجامٍ جُرِّبت، وكم كانت خسارة كلٍّ منها.

## وما لا يفعله

لا يوسّع وقفاً، ولا يغيّر إبطالاً، ولا يبدّل إطاراً ولا أداة كي تمرّ صفقة.
المتغيّر الوحيد هو **الكمية** — وهي وحدها ما يسمح الوسيط بتغييره.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..money import D

#: رموز الرفض — **مفصولة عمداً**. «لا صفقة» ليست سبباً؛ كل قيدٍ يُسمّى
#: باسمه كي يُقرأ توزيعُها في تقرير المشاركة اليومية.
BROKER_MIN_STOP_DISTANCE_VIOLATION = "BROKER_MIN_STOP_DISTANCE_VIOLATION"
BROKER_MIN_QUANTITY_RISK_EXCEEDED = "BROKER_MIN_QUANTITY_RISK_EXCEEDED"
POSITION_SIZE_ROUNDED_TO_ZERO = "POSITION_SIZE_ROUNDED_TO_ZERO"
INSTRUMENT_SPEC_UNRESOLVED = "INSTRUMENT_SPEC_UNRESOLVED"
CONVERSION_COST_UNMEASURED = "CONVERSION_COST_UNMEASURED"
TIMEFRAME_MISMATCH = "TIMEFRAME_MISMATCH"
PORTFOLIO_LIMIT_EXCEEDED = "PORTFOLIO_LIMIT_EXCEEDED"
#: لم تُقرأ حقيقةُ المحفظة من الوسيط — فلا تُعرَف حدود التعرّض.
#: حارسٌ أعمى ليس حارساً: يُفشَل مغلقاً ولا يُفتَح مركز.
RECONCILIATION_NOT_READY = "RECONCILIATION_NOT_READY"

#: صفقةٌ مغلقةٌ بلا نتيجةٍ معروفة. لا يُفتَح مركزٌ جديد فوق حسابٍ لا نعرف
#: كم خسر فيه اليوم — والجهلُ هنا يُحجَب به ولا يُحسَب صفراً.
REALISED_PNL_INCOMPLETE = "REALISED_PNL_INCOMPLETE"

#: تعذّرت قراءةُ حقوق الملكية من الوسيط. لا يُستبدَل الرصيد بالأساس ولا
#: بصفر: حاجزُ التراجع يقيس مسافةً، ومسافةٌ إلى رقمٍ مخترَعٍ ليست مسافة.
EQUITY_UNKNOWN = "EQUITY_UNKNOWN"

#: لقطةُ الحساب أقدمُ من العتبة. رصيدٌ عمره دقائق ليس رصيدَ الآن، وقرارٌ
#: عليه قرارٌ على ماضٍ.
RISK_STATE_STALE = "RISK_STATE_STALE"
#: للأداة تعرّضٌ قائم ولا تُجيز الاستراتيجية الإضافة عليه.
DUPLICATE_INSTRUMENT_EXPOSURE = "DUPLICATE_INSTRUMENT_EXPOSURE"
#: عددُ المراكز بلغ السقف المعلن في الدستور.
POSITION_COUNT_EXCEEDED = "POSITION_COUNT_EXCEEDED"
#: **الرمز نفسه الذي يستعمله المحرّك.** رمزان لسببٍ واحد يجعلان تقرير
#: الرفض يقسم السبب الواحد قسمين، ويبدو كلٌّ منهما نصف ما هو.
MARGIN_EXCEEDS_AVAILABLE = "MARGIN_EXCEEDS_AVAILABLE_FUNDS"

#: أقصى عدد درجاتٍ تُجرَّب. حدٌّ تشغيلي لا سياسة: السلّم يتوقّف عملياً عند
#: أوّل حجمٍ يتجاوز السقف لأن الخسارة تزيد مع الكمية زيادةً غير متناقصة.
MAX_LADDER_STEPS = 64


@dataclass(frozen=True)
class SizeCandidate:
    size: Decimal
    economics: object
    all_in_risk: Decimal
    margin_required: Decimal
    feasible: bool
    blocked_by: Optional[str] = None

    def as_row(self) -> dict:
        return {
            "size": str(self.size),
            "all_in_risk": f"{self.all_in_risk:.4f}",
            "margin": f"{self.margin_required:.4f}",
            "feasible": self.feasible,
            "blocked_by": self.blocked_by,
        }


@dataclass(frozen=True)
class LadderResult:
    chosen: Optional[SizeCandidate]
    candidates: tuple[SizeCandidate, ...]
    target_risk: Decimal
    hard_ceiling: Decimal
    reason_code: Optional[str] = None
    reason_ar: str = ""

    @property
    def approved(self) -> bool:
        return self.chosen is not None

    def trace_ar(self) -> str:
        """أثرٌ يُقرأ: ماذا جُرِّب، وبكم، ولماذا وقف."""
        rows = " · ".join(
            f"{c.size}⇒{c.all_in_risk:.2f}$" + ("" if c.feasible else "✗")
            for c in self.candidates[:12]
        )
        return (
            f"الهدف {self.target_risk:.2f} · السقف الصلب {self.hard_ceiling:.2f} · "
            f"الأحجام المجرَّبة: {rows or '—'}"
        )


def build_ladder(
    *,
    cost_model,
    entry_price: Decimal,
    stop_distance_pips: Decimal,
    take_profit_distance_pips: Decimal,
    stop_kind,
    target_risk: Decimal,
    hard_ceiling: Decimal,
    available_margin: Decimal,
    max_steps: int = MAX_LADDER_STEPS,
) -> LadderResult:
    """
    يبني قائمة الأحجام ويختار الأقرب إلى الهدف تحت السقف الصلب.

    السقف الصلب هنا **مُحتسَبٌ سلفاً**: الأصغر بين الحدّ الصلب للصفقة وما
    تبقّى من اليوم والأسبوع والإجمالي. فلا تُعاد سياسةُ الحدود هنا، ولا
    يستطيع هذا الملف أن يرفعها.
    """
    econ = cost_model.economics
    step = D(econ.size_increment or 0)
    smallest = D(econ.min_deal_size or 0)
    target_risk = D(target_risk)
    hard_ceiling = D(hard_ceiling)
    available_margin = D(available_margin)

    if smallest <= 0:
        return LadderResult(
            None, (), target_risk, hard_ceiling,
            POSITION_SIZE_ROUNDED_TO_ZERO,
            f"{econ.epic}: أصغر كمية معلَنة {econ.min_deal_size} — لا كمية قابلة للتنفيذ.",
        )
    if step <= 0:
        # درجةٌ صفرية ليست «كمية واحدة ممكنة»: هي مواصفةٌ ناقصة. تُعامَل
        # معاملة السلّم ذي الدرجة الواحدة، ويُقال ذلك.
        step = smallest

    max_size = getattr(econ, "max_deal_size", None)
    candidates: list[SizeCandidate] = []
    size = smallest
    steps = 0
    while steps < max_steps:
        steps += 1
        if max_size is not None and D(max_size) > 0 and size > D(max_size):
            break
        try:
            e = cost_model.estimate(
                size=size,
                entry_price=entry_price,
                stop_distance_pips=stop_distance_pips,
                take_profit_distance_pips=take_profit_distance_pips,
                stop_kind=stop_kind,
            )
        except (ValueError, ArithmeticError):
            break

        risk = D(e.all_in_risk)
        margin = D(e.margin_required)
        blocked = None
        if risk > hard_ceiling:
            blocked = BROKER_MIN_QUANTITY_RISK_EXCEEDED
        elif margin > available_margin:
            blocked = MARGIN_EXCEEDS_AVAILABLE
        candidates.append(
            SizeCandidate(
                size=size, economics=e, all_in_risk=risk,
                margin_required=margin, feasible=blocked is None, blocked_by=blocked,
            )
        )
        # الخسارة تزيد مع الكمية زيادةً غير متناقصة ⇒ أوّل تجاوزٍ للسقف
        # ينهي السلّم. (والهامش كذلك.)
        if blocked is not None:
            break
        size = size + step

    feasible = [c for c in candidates if c.feasible]
    if not feasible:
        first = candidates[0] if candidates else None
        if first is None:
            return LadderResult(
                None, tuple(candidates), target_risk, hard_ceiling,
                POSITION_SIZE_ROUNDED_TO_ZERO,
                f"{econ.epic}: تعذّر حساب اقتصاديات أي حجم.",
            )
        code = first.blocked_by or BROKER_MIN_QUANTITY_RISK_EXCEEDED
        if code == MARGIN_EXCEEDS_AVAILABLE:
            msg = (
                f"{econ.epic}: الهامش المطلوب {first.margin_required:.2f} عند الكمية الدنيا "
                f"({first.size}) يتجاوز المتاح {available_margin:.2f} دولار."
            )
        else:
            msg = (
                f"{econ.epic}: الخسارة الكاملة {first.all_in_risk:.2f} دولار عند الكمية "
                f"الدنيا للوسيط ({first.size}) تتجاوز السقف الصلب {hard_ceiling:.2f}. "
                "ولا كمية أصغر — الوسيط لا يقبلها. "
                f"(الهدف {target_risk:.2f} ليس سبب الرفض؛ السقف هو.)"
            )
        return LadderResult(None, tuple(candidates), target_risk, hard_ceiling, code, msg)

    # **الأقرب إلى الهدف.** وعند التساوي في البُعد تُفضَّل المخاطرة الأصغر.
    chosen = min(feasible, key=lambda c: (abs(c.all_in_risk - target_risk), c.all_in_risk))
    return LadderResult(chosen, tuple(candidates), target_risk, hard_ceiling)


__all__ = [
    "SizeCandidate",
    "LadderResult",
    "build_ladder",
    "BROKER_MIN_STOP_DISTANCE_VIOLATION",
    "BROKER_MIN_QUANTITY_RISK_EXCEEDED",
    "POSITION_SIZE_ROUNDED_TO_ZERO",
    "INSTRUMENT_SPEC_UNRESOLVED",
    "CONVERSION_COST_UNMEASURED",
    "TIMEFRAME_MISMATCH",
    "PORTFOLIO_LIMIT_EXCEEDED",
    "MARGIN_EXCEEDS_AVAILABLE",
]
