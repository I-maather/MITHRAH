"""
THRESHOLDS — الحد الأدنى لحقوق الملكية، وسلسلة الخسائر المأذون بها.

## الخطأ الأول الذي يعالجه هذا الملف

قال التقرير السابق إن **150 دولاراً هي الحد الأدنى بالضبط**، لأنها النقطة التي
يتساوى عندها السقف الدولاري مع النسبة. وهذا خلط بين ثلاثة أشياء مختلفة:

    1. الحد الأدنى لحقوق الملكية **لسيناريو معيّن**
       = الخسارة الكلية ÷ نسبة الملف
       (خسارة 0.54 في المتوازن ⇒ 0.54 ÷ 0.005 = **108 دولاراً**)

    2. حقوق الملكية التي يصبح عندها **السقف الدولاري** هو القيد
       = السقف ÷ النسبة
       (0.75 ÷ 0.005 = **150 دولاراً**)

    3. رأس المال **المخطَّط** = 150 دولاراً — قرار المالكة، لا نتيجة حساب

الرقمان (1) و(2) تصادفا في مثال واحد فحُسبا واحداً. عند 120 دولاراً يكون
الحد الفعّال 0.60 دولار، وخسارة 0.54 **تمرّ** — والادعاء بأن 150 هي الحد
الأدنى كان خاطئاً.

## الخطأ الثاني

قيل «12 خسارة متتالية حتى حد 6.50». والصحيح أن 12 × 0.54 = **6.48**، وهو
**لا يتجاوز** 6.50 — الخسارة الثالثة عشرة هي التي تتجاوزه. والأهم أن حدوداً
أخرى تتدخّل قبل ذلك أو بعده بحسب حجم الخسارة، وأنّ **عدد أوامر الدخول اليومي
محدود بواحد** في كل الملفات — وهو قيد كثيراً ما يسبق حد الخسارة اليومي.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..money import D
from . import (
    GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD,
    GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD,
    PROFILE_SPECS,
    ProfileLimits,
    TradingProfile,
)

#: أيام التداول في الأسبوع لسوق الفوركس (الاثنين–الجمعة).
TRADING_DAYS_PER_WEEK = 5


# ---------------------------------------------------------------------------
# 1. الحد الأدنى لحقوق الملكية
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EquityThreshold:
    """
    ثلاثة أرقام **لا يجوز الخلط بينها**، ولكلٍّ معنى مختلف.
    """

    profile: TradingProfile
    all_in_risk: Decimal

    #: السقف الدولاري الثابت للملف — لا يزيد مهما زاد رأس المال.
    fixed_cap: Decimal
    #: نسبة حقوق الملكية المسموح المخاطرة بها في الصفقة الواحدة.
    percentage: Decimal

    #: (1) أقل حقوق ملكية تجعل النسبة تسمح بهذه الخسارة تحديداً.
    minimum_equity_from_percentage: Optional[Decimal]
    #: (2) حقوق الملكية التي يبدأ عندها السقف الدولاري في الحكم بدل النسبة.
    cap_binding_equity: Decimal
    #: هل يتجاوز حجم الخسارة السقف الدولاري نفسه؟
    exceeds_fixed_cap: bool

    def as_dict(self) -> dict:
        def s(v: Optional[Decimal]) -> Optional[str]:
            return f"{v:.2f}" if v is not None else None

        return {
            "profile": self.profile.value,
            "all_in_risk": f"{self.all_in_risk:.4f}",
            "fixed_cap": s(self.fixed_cap),
            "percentage": f"{self.percentage * 100:.2f}%",
            "minimum_equity_from_percentage": s(self.minimum_equity_from_percentage),
            "cap_binding_equity": s(self.cap_binding_equity),
            "exceeds_fixed_cap": self.exceeds_fixed_cap,
            "possible_at_any_equity": not self.exceeds_fixed_cap,
        }

    def reason_ar(self) -> str:
        if self.exceeds_fixed_cap:
            return (
                f"الخسارة {self.all_in_risk:.4f} تتجاوز السقف الدولاري الثابت "
                f"{self.fixed_cap:.2f}. **لا توجد حقوق ملكية تُصلح هذا** — "
                "السقف لا يرتفع بزيادة رأس المال."
            )
        return (
            f"يلزم **{self.minimum_equity_from_percentage:.2f} دولاراً** على "
            f"الأقل كي تسمح نسبة {self.percentage * 100:.2f}% بخسارة "
            f"{self.all_in_risk:.4f}. وابتداءً من "
            f"{self.cap_binding_equity:.2f} دولاراً يصبح السقف الدولاري "
            f"{self.fixed_cap:.2f} هو القيد بدل النسبة."
        )


def minimum_equity_for(
    profile: TradingProfile, all_in_risk: Decimal
) -> EquityThreshold:
    """
    يحسب العتبات الثلاث لسيناريو خسارة واحد.

    الحد الفعّال في الكود هو `min(السقف الدولاري، حقوق الملكية × النسبة)`.
    ومنه يتبع مباشرةً:

      * إن كانت الخسارة > السقف الدولاري ⇒ **مستحيلة عند أي حقوق ملكية**،
        لأن الحد لا يتجاوز السقف أبداً.
      * وإلا فالحد الأدنى = الخسارة ÷ النسبة.
    """
    if all_in_risk <= 0:
        raise ValueError("الخسارة الكلية يجب أن تكون موجبة.")
    spec = PROFILE_SPECS[profile]
    cap = spec.max_risk_per_trade_usd
    pct = spec.max_risk_pct_of_current_equity

    exceeds = all_in_risk > cap
    minimum = None if exceeds else (all_in_risk / pct)
    return EquityThreshold(
        profile=profile,
        all_in_risk=all_in_risk,
        fixed_cap=cap,
        percentage=pct,
        minimum_equity_from_percentage=minimum,
        cap_binding_equity=cap / pct,
        exceeds_fixed_cap=exceeds,
    )


def scenario_fits_at_equity(
    profile: TradingProfile, all_in_risk: Decimal, equity: Decimal
) -> bool:
    """هل تمرّ هذه الخسارة عند حقوق ملكية معيّنة؟ يستعمل الحدّ الفعّال نفسه."""
    if equity <= 0:
        return False
    return all_in_risk <= ProfileLimits.for_profile(profile, equity).max_risk_per_trade


# ---------------------------------------------------------------------------
# 2. سلسلة الخسائر المأذون بها
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LossSequence:
    """
    أقصى عدد خسائر **كاملة المخاطرة** مأذون بها، تحت كل حدّ على حدة.

    الحدود لا تُجمع — **الأشد يفوز**، وهو ما يظهر في `binding_constraint`.
    """

    profile: TradingProfile
    loss_per_trade: Decimal
    equity_used: Decimal

    max_entry_orders_per_day: int
    daily_limit: Decimal
    weekly_limit: Decimal
    operational_stop: Decimal
    absolute_boundary: Decimal

    losses_per_day_by_limit: int
    losses_per_day_effective: int
    losses_per_week_by_limit: int
    losses_per_week_effective: int
    losses_until_operational_stop: int
    losses_until_absolute_boundary: int

    cumulative_at_operational_limit: Decimal
    trading_days_to_operational_stop: Optional[int]
    binding_constraint: str
    binding_ar: str
    #: هل السيناريو مسموح أصلاً بحدّ الصفقة الواحدة؟ إن كان لا، فالأعداد أدناه
    #: نظرية ولا تصف تداولاً ممكناً.
    scenario_permitted: bool = True

    def as_dict(self) -> dict:
        return {
            "profile": self.profile.value,
            "loss_per_trade": f"{self.loss_per_trade:.4f}",
            "equity_used": f"{self.equity_used:.2f}",
            "max_entry_orders_per_day": self.max_entry_orders_per_day,
            "daily_limit": f"{self.daily_limit:.2f}",
            "weekly_limit": f"{self.weekly_limit:.2f}",
            "operational_stop": f"{self.operational_stop:.2f}",
            "absolute_boundary": f"{self.absolute_boundary:.2f}",
            "losses_per_day_by_limit": self.losses_per_day_by_limit,
            "losses_per_day_effective": self.losses_per_day_effective,
            "losses_per_week_by_limit": self.losses_per_week_by_limit,
            "losses_per_week_effective": self.losses_per_week_effective,
            "losses_until_operational_stop": self.losses_until_operational_stop,
            "losses_until_absolute_boundary": self.losses_until_absolute_boundary,
            "cumulative_at_operational_limit":
                f"{self.cumulative_at_operational_limit:.4f}",
            "trading_days_to_operational_stop": self.trading_days_to_operational_stop,
            "binding_constraint": self.binding_constraint,
            "binding_ar": self.binding_ar,
            "scenario_permitted": self.scenario_permitted,
        }


def _whole_losses_within(limit: Decimal, loss: Decimal) -> int:
    """
    كم خسارة كاملة تدخل **دون تجاوز** الحد.

    القسمة الصحيحة هنا مقصودة: 6.50 ÷ 0.54 = 12.03… ⇒ **12** خسارة مجموعها
    6.48، وهو لا يتجاوز 6.50. الثالثة عشرة (7.02) هي التي تتجاوز.
    """
    if loss <= 0:
        raise ValueError("الخسارة يجب أن تكون موجبة.")
    return int(limit // loss)


def loss_sequence_limits(
    profile: TradingProfile,
    loss_per_trade: Decimal,
    *,
    equity: Decimal,
) -> LossSequence:
    """
    يحسب سقف سلسلة الخسائر تحت **كل** الحدود معاً: عدد أوامر الدخول اليومي،
    والحد اليومي، والأسبوعي، وحدّ التوقّف التشغيلي، والحد المطلق.
    """
    spec = PROFILE_SPECS[profile]
    limits = ProfileLimits.for_profile(profile, equity)

    per_day_by_limit = _whole_losses_within(spec.max_daily_loss_usd, loss_per_trade)
    per_day_effective = min(per_day_by_limit, spec.max_entry_orders_per_day)

    per_week_by_limit = _whole_losses_within(spec.max_weekly_loss_usd, loss_per_trade)
    per_week_effective = min(per_week_by_limit, per_day_effective * TRADING_DAYS_PER_WEEK)

    until_operational = _whole_losses_within(
        GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD, loss_per_trade
    )
    until_absolute = _whole_losses_within(
        GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD, loss_per_trade
    )

    days = (
        None if per_day_effective <= 0
        else -(-until_operational // per_day_effective)   # سقف القسمة
    )

    # أي قيد يُوقف التداول أولاً؟ يُقاس بعدد الخسائر المسموح بها.
    if per_week_by_limit < per_day_effective * TRADING_DAYS_PER_WEEK:
        binding = "WEEKLY_LOSS_LIMIT"
        binding_ar = (
            f"الحد الأسبوعي {spec.max_weekly_loss_usd:.2f} يوقف التداول عند "
            f"{per_week_by_limit} خسارة في الأسبوع — قبل استيفاء أيام الأسبوع."
        )
    elif per_day_by_limit > spec.max_entry_orders_per_day:
        binding = "MAX_ENTRY_ORDERS_PER_DAY"
        binding_ar = (
            f"عدد أوامر الدخول اليومي ({spec.max_entry_orders_per_day}) هو القيد "
            f"اليومي الفعلي — الحد اليومي {spec.max_daily_loss_usd:.2f} يتّسع "
            f"لـ{per_day_by_limit} خسارة لكن التواتر لا يسمح بها."
        )
    else:
        binding = "DAILY_LOSS_LIMIT"
        binding_ar = (
            f"الحد اليومي {spec.max_daily_loss_usd:.2f} يوقف اليوم عند "
            f"{per_day_by_limit} خسارة."
        )

    return LossSequence(
        profile=profile,
        loss_per_trade=loss_per_trade,
        equity_used=limits.equity_used,
        max_entry_orders_per_day=spec.max_entry_orders_per_day,
        daily_limit=spec.max_daily_loss_usd,
        weekly_limit=spec.max_weekly_loss_usd,
        operational_stop=GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD,
        absolute_boundary=GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD,
        losses_per_day_by_limit=per_day_by_limit,
        losses_per_day_effective=per_day_effective,
        losses_per_week_by_limit=per_week_by_limit,
        losses_per_week_effective=per_week_effective,
        losses_until_operational_stop=until_operational,
        losses_until_absolute_boundary=until_absolute,
        cumulative_at_operational_limit=until_operational * loss_per_trade,
        trading_days_to_operational_stop=days,
        binding_constraint=binding,
        binding_ar=binding_ar,
        scenario_permitted=(loss_per_trade <= limits.max_risk_per_trade),
    )


__all__ = [
    "TRADING_DAYS_PER_WEEK",
    "EquityThreshold",
    "minimum_equity_for",
    "scenario_fits_at_equity",
    "LossSequence",
    "loss_sequence_limits",
]
