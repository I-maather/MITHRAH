"""
EUR/USD — التنفيذ الملموس لمراحل الإعداد وبناء المركز ونقض المخاطر.

هذا الملف يربط الخط العام بأداة واحدة فقط: **EUR/USD**. لا تعميم مبكر على
أدوات أخرى، ولا معاملات مشتركة تُخفي فروقاً حقيقية بين الأسواق.

نقطة جوهرية تتكرر في الاختبارات:

    **مسافة الوقف تأتي من البنية، لا من ميزانية المخاطرة.**
    إن كانت الخسارة عند الوقف الطبيعي تتجاوز حد الملف، القرار `NO_TRADE`.
    لا يُضيَّق الوقف ولا تُصغَّر الكمية دون حد الوسيط.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..contracts import Side, StopKind
from ..money import D
from ..profiles import ProfileLimits
from ..risk.capital_costs import CapitalComCostModel, InstrumentEconomics
from ..strategies.registry import StrategyDefinition
from .indicators import compute_indicators
from .pipeline import ConstructedPosition, EntrySetup, RiskVeto
from .regime import MarketRegime, RegimeAssessment
from .snapshot import UNKNOWN, MarketSnapshot, Timeframe, _Unknown, is_unknown
from .structure import MultiTimeframeView, TrendDirection, find_swings

#: مضاعف الهدف من مسافة الوقف. معلن، وليس رقماً سحرياً داخل دالة.
TAKE_PROFIT_MULTIPLE = D("2.0")

#: احتياطي يُضاف خلف قاع/قمة التأرجح ليكون الوقف خلف البنية لا عليها.
STOP_BUFFER_ATR_FRACTION = D("0.25")


@dataclass(frozen=True)
class SetupBuilder:
    """
    يبني إعداد دخول من قواعد الاستراتيجية المعلنة فقط.

    لا يعرف حد المخاطرة ولا الملف — بالتصميم. لو عرفهما، لأمكن أن يتشكّل
    الوقف حول الميزانية بدل البنية، وهو بالضبط ما نمنعه.
    """

    swing_strength: int = 2

    def __call__(
        self,
        view: MultiTimeframeView,
        regime: RegimeAssessment,
        definition: StrategyDefinition,
    ) -> Optional[EntrySetup]:
        if regime.regime is not MarketRegime.TREND:
            # الإصدار الأول يبني إعداداً لِـTREND_PULLBACK وحده.
            # بقية الاستراتيجيات مسجَّلة ومُعرَّفة لكنها بلا بانٍ بعد — RESEARCH.
            return None

        m15 = view.analyses.get(Timeframe.M15)
        daily = view.analyses.get(Timeframe.D1)
        if m15 is None or daily is None:
            return None
        if isinstance(m15.last_close, _Unknown) or isinstance(m15.indicators.atr, _Unknown):
            return None

        direction = daily.trend
        if direction not in (TrendDirection.UP, TrendDirection.DOWN):
            return None
        # سياسة CFD الحالية: شراء فقط.
        if direction is not TrendDirection.UP:
            return None

        lows = [s for s in m15.swings if not s.is_high]
        if not lows:
            return None

        entry = m15.last_close
        atr = m15.indicators.atr
        buffer_ = atr * STOP_BUFFER_ATR_FRACTION

        # الوقف خلف آخر قاع تأرجح — هذه هي «المسافة الطبيعية».
        natural_stop = lows[-1].price - buffer_
        if natural_stop >= entry:
            return None

        stop_distance = entry - natural_stop
        take_profit = entry + stop_distance * TAKE_PROFIT_MULTIPLE

        # تأكيد الدخول: شمعة إغلاقها أعلى من افتتاحها في اتجاه النظام.
        confirmed = m15.momentum.value in ("BULLISH", "NEUTRAL")

        return EntrySetup(
            side=Side.BUY,
            entry_price=entry,
            stop_price=natural_stop,
            take_profit_price=take_profit,
            stop_kind=StopKind.NORMAL,
            confirmed=confirmed,
            natural_stop_ar=(
                f"الوقف خلف آخر قاع تأرجح ({lows[-1].price}) مضافاً إليه "
                f"{STOP_BUFFER_ATR_FRACTION} من ATR. **هذه المسافة من البنية، "
                "ولا تُضيَّق لتناسب ميزانية المخاطرة.**"
            ),
            rationale_ar=(
                f"{definition.title_ar}: نظام D1 صاعد، تصحيح على M15 دون كسر آخر قاع، "
                f"هدف عند {TAKE_PROFIT_MULTIPLE}× مسافة الوقف."
            ),
        )


@dataclass(frozen=True)
class PositionConstructor:
    """
    يحوّل إعداد الدخول إلى أرقام نقدية عبر نموذج تكلفة Capital.com.

    يستقبل حد الملف **للفحص فقط**: إن تجاوزت الخسارة الحد، يُعلَّم المركز
    `respects_broker_minimum=False` ويرفضه الخط — ولا يُعدَّل الوقف ولا الكمية.
    """

    cost_model: CapitalComCostModel
    limits: ProfileLimits
    slippage_reserve_pips: Decimal = D("1")

    def __call__(
        self, setup: EntrySetup, snapshot: MarketSnapshot
    ) -> Optional[ConstructedPosition]:
        econ: InstrumentEconomics = self.cost_model.economics
        size = econ.min_deal_size           # الكمية الدنيا للوسيط — لا تُصغَّر
        if size <= 0:
            return None

        stop_price_distance = abs(setup.entry_price - setup.stop_price)
        tp_price_distance = abs(setup.take_profit_price - setup.entry_price)
        stop_pips = self.cost_model.price_to_pips(stop_price_distance)
        tp_pips = self.cost_model.price_to_pips(tp_price_distance)
        if stop_pips <= 0:
            return None

        try:
            e = self.cost_model.estimate(
                size=size,
                entry_price=setup.entry_price,
                stop_distance_pips=stop_pips,
                take_profit_distance_pips=tp_pips,
                stop_kind=setup.stop_kind,
            )
        except ValueError:
            return None

        gross_rr = (
            e.gross_reward_at_target / e.price_loss_at_stop
            if e.price_loss_at_stop > 0
            else D("0")
        )

        # الحد الأدنى لمسافة الوقف لدى الوسيط — قيد حقيقي لا تفضيل.
        # الحدّ يُحلّ إلى سعرٍ ثم إلى نقاط — لا يُقارَن رقمٌ بنسبةٍ بنقاط.
        min_stop_ok = True
        _min_price = econ.min_stop_price_at(setup.entry_price)
        if _min_price is not None:
            min_stop_ok = stop_pips >= (_min_price / econ.pip_size)
        elif econ.stop_spec_unresolved:
            min_stop_ok = False

        within_profile = e.all_in_risk <= self.limits.max_risk_per_trade

        return ConstructedPosition(
            size=size,
            notional=e.notional_exposure,
            margin=e.margin_required,
            pip_value=e.pip_value,
            spread=self.cost_model.assumptions.spread_price,
            price_risk=e.price_loss_at_stop,
            fees=e.spread_cost + e.guaranteed_stop_premium + e.conversion_cost,
            slippage_reserve=e.slippage_reserve,
            all_in_risk=e.all_in_risk,
            gross_reward_risk=gross_rr,
            net_reward_risk=e.net_reward_risk_ratio,
            stop_pips=stop_pips,
            respects_broker_minimum=bool(within_profile and min_stop_ok),
            #: الوقف لم يُمَس إطلاقاً بين البنية والحساب — القيمة ثابتة True هنا
            #: لأن هذا المسار لا يحتوي على أي فرع يعدّل مسافة الوقف.
            stop_was_not_tightened=True,
        )


@dataclass(frozen=True)
class ProfileAwareRiskVeto:
    """
    نقض المخاطر: **الأشد بين الدستور والملف يفوز دائماً.**

    الملف لا يستطيع توسيع حد دستوري، ولا يستطيع الدستور تخفيف عتبة ملف.
    كل حد هنا هو `min()` بين المصدرين.
    """

    limits: ProfileLimits
    constitution_max_risk: Decimal
    day_loss_so_far: Decimal = D("0")
    week_loss_so_far: Decimal = D("0")
    total_drawdown_so_far: Decimal = D("0")
    open_positions: int = 0
    entry_orders_today: int = 0
    full_risk_loss_today: bool = False
    kill_switch_active: bool = False

    def __call__(self, position: ConstructedPosition, setup: EntrySetup) -> RiskVeto:
        remaining_daily = max(D("0"), self.limits.max_daily_loss - self.day_loss_so_far)
        remaining_weekly = max(D("0"), self.limits.max_weekly_loss - self.week_loss_so_far)
        remaining_total = max(
            D("0"), self.limits.operational_drawdown_stop - self.total_drawdown_so_far
        )

        def veto(code: str, msg: str) -> RiskVeto:
            return RiskVeto(False, code, msg, remaining_daily, remaining_weekly)

        if self.kill_switch_active:
            return veto("KILL_SWITCH_ACTIVE", "Kill Switch مفعّل.")
        if self.open_positions >= self.limits.max_open_positions:
            return veto("MAX_OPEN_POSITIONS", "مركز مفتوح بالفعل — الحد مركز واحد.")
        if self.entry_orders_today >= self.limits.max_entry_orders_per_day:
            return veto("MAX_ENTRIES_PER_DAY", "أمر دخول واحد في اليوم مستهلَك.")
        if self.limits.full_risk_loss_ends_day and self.full_risk_loss_today:
            return veto(
                "FULL_RISK_LOSS_ENDS_DAY",
                "خسارة بكامل المخاطرة اليوم تُنهي التداول لهذا اليوم في الملف النشط المحسوب.",
            )

        # الأشد بين الدستور والملف
        effective_cap = min(self.limits.max_risk_per_trade, self.constitution_max_risk)
        cap = min(effective_cap, remaining_daily, remaining_weekly, remaining_total)

        if position.all_in_risk > cap:
            return veto(
                "RISK_EXCEEDS_EFFECTIVE_CAP",
                (
                    f"الخسارة الكلية {position.all_in_risk:.2f} تتجاوز الحد الفعّال "
                    f"{cap:.2f} دولار (الأشد بين الدستور والملف والمتبقي)."
                ),
            )
        if position.net_reward_risk < self.limits.min_net_reward_risk:
            return veto(
                "NET_REWARD_RISK_TOO_LOW",
                (
                    f"R:R الصافي {position.net_reward_risk:.2f} دون متطلب الملف "
                    f"{self.limits.min_net_reward_risk:.2f}."
                ),
            )

        return RiskVeto(
            True,
            "",
            (
                f"ضمن كل الحدود: صفقة {position.all_in_risk:.2f} · حد فعّال {cap:.2f} · "
                f"متبقي يومي {remaining_daily:.2f} · أسبوعي {remaining_weekly:.2f}."
            ),
            remaining_daily,
            remaining_weekly,
        )


__all__ = [
    "TAKE_PROFIT_MULTIPLE",
    "STOP_BUFFER_ATR_FRACTION",
    "SetupBuilder",
    "PositionConstructor",
    "ProfileAwareRiskVeto",
]
