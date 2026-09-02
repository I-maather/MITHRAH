"""
نموذج تكلفة Capital.com (CFD).

هذا نموذج **مختلف جوهرياً** عن نموذج IBKR. لا يُعاد استعمال أي استنتاج
من نموذج الأسهم هنا، وخصوصاً استنتاج «الحد الأدنى 255–380 دولاراً»:
ذلك الرقم كان مشتقاً من الحد الأدنى لعمولة IBKR (0.35 دولار للساق)،
و Capital.com لا يفرض عمولة على فوركس CFD بل يتقاضى عبر السبريد.

ثلاث قيم لا يجوز الخلط بينها أبداً:
  1. **قيمة التعرّض (Notional)** — حجم السوق الذي نتحرك معه.
  2. **الهامش المحجوز (Margin)** — النقد المجمَّد لفتح المركز. ليس خسارة.
  3. **الخسارة النقدية عند الوقف (All-in risk)** — ما نخسره فعلاً إن ضُرب الوقف.

عرض أي واحدة منها مكان الأخرى خطأ جسيم، لذلك تُعرض الثلاث منفصلة دائماً.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..contracts import StopKind
from ..money import D, money_ceil, safe_div


class ValueProvenance(str, Enum):
    """
    من أين جاء الرقم. أي حساب يعتمد على قيمة `PROVISIONAL_PUBLIC_SITE`
    يجب أن يُعرض موسوماً بأنه مبدئي، ولا يُبنى عليه قرار تنفيذ.
    """

    BROKER_DISCOVERY = "BROKER_DISCOVERY"
    PROVISIONAL_PUBLIC_SITE = "PROVISIONAL_PUBLIC_SITE"
    CONFIGURED_ASSUMPTION = "CONFIGURED_ASSUMPTION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class InstrumentEconomics:
    """
    خصائص الأداة الاقتصادية كما يعلنها الوسيط.
    كل حقل يحمل مصدره، فلا يختلط المُكتشَف بالمُفترَض.
    """

    epic: str
    pip_size: Decimal
    lot_size: Decimal
    min_deal_size: Decimal
    size_increment: Decimal
    margin_factor: Decimal
    margin_factor_unit: str
    min_stop_distance: Optional[Decimal]
    min_guaranteed_stop_distance: Optional[Decimal]
    guaranteed_stop_available: bool
    #: عملة التسعير **كما أعلنها الوسيط**. `None` = لم يُعلنها — ولا تُملأ
    #: بعملة الحساب صامتة، فذلك تأكيدُ ما لم يُقرأ.
    quote_currency: Optional[str]
    overnight_fee_rate_daily: Optional[Decimal]
    provenance: ValueProvenance = ValueProvenance.UNKNOWN

    @property
    def margin_rate(self) -> Decimal:
        """يعيد المعامل ككسر عشري بغض النظر عن وحدته المعلنة."""
        if self.margin_factor_unit.upper() in {"PERCENTAGE", "PERCENT", "%"}:
            return self.margin_factor / D(100)
        return self.margin_factor

    @property
    def is_provisional(self) -> bool:
        return self.provenance is not ValueProvenance.BROKER_DISCOVERY


#: افتراضات **مبدئية** من صفحة Capital.com العامة لزوج EUR/USD.
#: مصدرها الموقع العام لا حساب المالكة، ولذلك مُعلَّمة PROVISIONAL.
#: يجب استبدالها بقيم GET /markets/{epic} من حساب Demo قبل أي قرار.
PROVISIONAL_EURUSD = InstrumentEconomics(
    epic="EURUSD",
    pip_size=D("0.0001"),
    lot_size=D("1"),
    min_deal_size=D("100"),          # الموقع العام: أقل كمية 100
    size_increment=D("1"),
    margin_factor=D("1"),            # الموقع العام: هامش 1%
    margin_factor_unit="PERCENTAGE",
    min_stop_distance=None,          # غير معلوم قبل الاكتشاف
    min_guaranteed_stop_distance=None,
    guaranteed_stop_available=False,  # لا يُفترض التوفر — يُثبت بالاكتشاف
    quote_currency="USD",
    overnight_fee_rate_daily=None,
    provenance=ValueProvenance.PROVISIONAL_PUBLIC_SITE,
)


@dataclass(frozen=True)
class CfdCostAssumptions:
    """
    افتراضات غير معلنة من الوسيط. متحفظة عمداً، وكلها قابلة للضبط.
    """

    spread_price: Decimal                      # السبريد بوحدة السعر
    slippage_reserve_pips: Decimal             # احتياطي انزلاق (للوقف العادي فقط)
    guaranteed_stop_premium_pips: Optional[Decimal]
    currency_conversion_pct: Decimal           # كسر من المبلغ المحوَّل
    nights_held: int
    spread_provenance: ValueProvenance = ValueProvenance.CONFIGURED_ASSUMPTION

    @staticmethod
    def default() -> "CfdCostAssumptions":
        return CfdCostAssumptions(
            spread_price=D("0.00006"),                # 0.6 نقطة — افتراض مبدئي
            slippage_reserve_pips=D("1.0"),
            guaranteed_stop_premium_pips=None,        # غير معلوم حتى الاكتشاف
            currency_conversion_pct=D("0"),
            nights_held=0,
            spread_provenance=ValueProvenance.CONFIGURED_ASSUMPTION,
        )


@dataclass(frozen=True)
class CfdTradeEconomics:
    """
    النتيجة الكاملة لصفقة CFD مقترحة. كل قيمة منفصلة وواضحة الدلالة.
    """

    epic: str
    size: Decimal
    entry_price: Decimal
    stop_distance_price: Decimal
    take_profit_distance_price: Decimal
    stop_kind: StopKind

    notional_exposure: Decimal
    margin_required: Decimal

    pip_value: Decimal
    stop_distance_pips: Decimal
    take_profit_distance_pips: Decimal

    price_loss_at_stop: Decimal
    spread_cost: Decimal
    guaranteed_stop_premium: Decimal
    slippage_reserve: Decimal
    overnight_cost: Decimal
    conversion_cost: Decimal

    gross_reward_at_target: Decimal
    provisional: bool
    provenance_notes: tuple[str, ...]

    # -- التكاليف ------------------------------------------------------
    @property
    def total_costs(self) -> Decimal:
        return (
            self.spread_cost
            + self.guaranteed_stop_premium
            + self.slippage_reserve
            + self.overnight_cost
            + self.conversion_cost
        )

    @property
    def all_in_risk(self) -> Decimal:
        """الخسارة النقدية الكاملة إن ضُرب الوقف. **ليست** الهامش ولا التعرّض."""
        return self.price_loss_at_stop + self.total_costs

    @property
    def net_reward(self) -> Decimal:
        """العائد بعد خصم التكاليف التي تُدفع في كل الأحوال."""
        recurring = self.spread_cost + self.guaranteed_stop_premium + self.overnight_cost + self.conversion_cost
        return self.gross_reward_at_target - recurring

    @property
    def net_reward_risk_ratio(self) -> Decimal:
        return safe_div(self.net_reward, self.all_in_risk, D("0"))

    @property
    def breakeven_move_pips(self) -> Decimal:
        return safe_div(self.total_costs, self.pip_value, D("0"))

    @property
    def cost_ratio(self) -> Decimal:
        return safe_div(self.total_costs, self.all_in_risk, D("1"))

    @property
    def margin_as_pct_of_equity(self) -> Optional[Decimal]:
        return None  # يُحسب في طبقة أعلى حيث يُعرف رأس المال

    def as_display_dict(self) -> dict:
        """
        العرض الإلزامي: التعرّض والهامش والخسارة **منفصلة**.
        هذا القاموس هو ما تستهلكه الواجهة وتقرير المعاينة.
        """
        return {
            "epic": self.epic,
            "size_broker_units": str(self.size),
            "notional_exposure": f"{self.notional_exposure:.2f}",
            "margin_required": f"{self.margin_required:.2f}",
            "all_in_risk_at_stop": f"{self.all_in_risk:.2f}",
            "pip_value": f"{self.pip_value:.4f}",
            "stop_distance_pips": f"{self.stop_distance_pips:.1f}",
            "stop_kind": self.stop_kind.value,
            "spread_cost": f"{self.spread_cost:.4f}",
            "guaranteed_stop_premium": f"{self.guaranteed_stop_premium:.4f}",
            "slippage_reserve": f"{self.slippage_reserve:.4f}",
            "overnight_cost": f"{self.overnight_cost:.4f}",
            "conversion_cost": f"{self.conversion_cost:.4f}",
            "total_costs": f"{self.total_costs:.4f}",
            "net_reward": f"{self.net_reward:.2f}",
            "net_reward_risk_ratio": f"{self.net_reward_risk_ratio:.2f}",
            "breakeven_move_pips": f"{self.breakeven_move_pips:.1f}",
            "provisional": self.provisional,
            "provenance_notes": list(self.provenance_notes),
        }


class CapitalComCostModel:
    """
    نموذج تكلفة Capital.com. لا يعرف شيئاً عن IBKR ولا يشاركه أي ثابت.
    """

    broker_name = "CAPITAL_COM"

    def __init__(
        self,
        economics: InstrumentEconomics,
        assumptions: Optional[CfdCostAssumptions] = None,
    ) -> None:
        self.economics = economics
        self.assumptions = assumptions or CfdCostAssumptions.default()

    # ------------------------------------------------------------------
    def with_discovered(self, economics: InstrumentEconomics) -> "CapitalComCostModel":
        """يعيد نسخة تستخدم قيماً مُكتشَفة من الوسيط بدل الافتراضات المبدئية."""
        return CapitalComCostModel(economics, self.assumptions)

    def pip_value(self, size: Decimal) -> Decimal:
        """قيمة النقطة بعملة التسعير لكمية معيّنة."""
        return size * self.economics.lot_size * self.economics.pip_size

    def notional(self, size: Decimal, price: Decimal) -> Decimal:
        return size * self.economics.lot_size * price

    def margin(self, size: Decimal, price: Decimal) -> Decimal:
        return self.notional(size, price) * self.economics.margin_rate

    def pips_to_price(self, pips: Decimal) -> Decimal:
        return pips * self.economics.pip_size

    def price_to_pips(self, price_distance: Decimal) -> Decimal:
        return safe_div(price_distance, self.economics.pip_size, D("0"))

    # ------------------------------------------------------------------
    def estimate(
        self,
        *,
        size: Decimal,
        entry_price: Decimal,
        stop_distance_pips: Decimal,
        take_profit_distance_pips: Decimal,
        stop_kind: StopKind = StopKind.NORMAL,
        nights_held: Optional[int] = None,
    ) -> CfdTradeEconomics:
        size = D(size)
        entry_price = D(entry_price)
        stop_distance_pips = D(stop_distance_pips)
        take_profit_distance_pips = D(take_profit_distance_pips)

        if size <= 0:
            raise ValueError("الكمية يجب أن تكون موجبة.")
        if entry_price <= 0:
            raise ValueError("سعر الدخول يجب أن يكون موجباً.")
        if stop_distance_pips <= 0:
            raise ValueError("مسافة الوقف يجب أن تكون موجبة — لا صفقة بلا وقف.")
        if stop_kind is StopKind.NONE:
            raise ValueError("لا يُسمح بصفقة بلا وقف خسارة.")

        notes: list[str] = []
        provisional = self.economics.is_provisional
        if provisional:
            notes.append(
                f"خصائص الأداة مصدرها {self.economics.provenance.value} — مبدئية حتى اكتشاف Demo."
            )
        if self.assumptions.spread_provenance is not ValueProvenance.BROKER_DISCOVERY:
            provisional = True
            notes.append("السبريد مفترض ولم يُقس من الوسيط بعد.")

        pip_value = self.pip_value(size)
        notional_exposure = self.notional(size, entry_price)
        margin_required = self.margin(size, entry_price)

        stop_distance_price = self.pips_to_price(stop_distance_pips)
        tp_distance_price = self.pips_to_price(take_profit_distance_pips)

        price_loss_at_stop = money_ceil(stop_distance_price * size * self.economics.lot_size)
        # السبريد يُدفع مرة واحدة في الجولة الكاملة (دخول عند الطلب، خروج عند العرض).
        spread_cost = money_ceil(self.assumptions.spread_price * size * self.economics.lot_size)

        if stop_kind is StopKind.GUARANTEED:
            if not self.economics.guaranteed_stop_available:
                raise ValueError(
                    "الوقف المضمون غير متاح لهذه الأداة حسب بيانات الوسيط الحالية."
                )
            premium_pips = self.assumptions.guaranteed_stop_premium_pips
            if premium_pips is None:
                provisional = True
                notes.append(
                    "تكلفة الوقف المضمون غير معلومة — تُحتسب صفراً مؤقتاً وهذا يقلّل تقدير المخاطرة."
                )
                guaranteed_stop_premium = D("0")
            else:
                guaranteed_stop_premium = money_ceil(premium_pips * pip_value)
            slippage_reserve = D("0")  # الوقف المضمون يلغي مخاطر الانزلاق بالتعريف
            notes.append("وقف مضمون: لا احتياطي انزلاق.")
        else:
            guaranteed_stop_premium = D("0")
            slippage_reserve = money_ceil(self.assumptions.slippage_reserve_pips * pip_value)
            notes.append(
                "وقف عادي: الخسارة قد تتجاوز التقدير عند الفجوات — احتياطي الانزلاق تقدير لا ضمان."
            )

        nights = self.assumptions.nights_held if nights_held is None else nights_held
        if nights > 0:
            rate = self.economics.overnight_fee_rate_daily
            if rate is None:
                provisional = True
                notes.append(
                    "رسوم التبييت غير معلومة — تُحتسب صفراً مؤقتاً، ولا يجوز التبييت قبل معرفتها."
                )
                overnight_cost = D("0")
            else:
                overnight_cost = money_ceil(abs(rate) * notional_exposure * D(nights))
        else:
            overnight_cost = D("0")

        if self.assumptions.currency_conversion_pct > 0:
            conversion_cost = money_ceil(
                self.assumptions.currency_conversion_pct * notional_exposure
            )
            notes.append("تكلفة تحويل عملة مُطبَّقة: عملة التسعير تختلف عن عملة الحساب.")
        else:
            conversion_cost = D("0")

        gross_reward = money_ceil(tp_distance_price * size * self.economics.lot_size)

        return CfdTradeEconomics(
            epic=self.economics.epic,
            size=size,
            entry_price=entry_price,
            stop_distance_price=stop_distance_price,
            take_profit_distance_price=tp_distance_price,
            stop_kind=stop_kind,
            notional_exposure=notional_exposure,
            margin_required=margin_required,
            pip_value=pip_value,
            stop_distance_pips=stop_distance_pips,
            take_profit_distance_pips=take_profit_distance_pips,
            price_loss_at_stop=price_loss_at_stop,
            spread_cost=spread_cost,
            guaranteed_stop_premium=guaranteed_stop_premium,
            slippage_reserve=slippage_reserve,
            overnight_cost=overnight_cost,
            conversion_cost=conversion_cost,
            gross_reward_at_target=gross_reward,
            provisional=provisional,
            provenance_notes=tuple(notes),
        )

    # ------------------------------------------------------------------
    def max_stop_pips_within_risk(
        self,
        *,
        size: Decimal,
        entry_price: Decimal,
        risk_budget: Decimal,
        stop_kind: StopKind = StopKind.NORMAL,
        max_pips: Decimal = D("500"),
    ) -> Optional[Decimal]:
        """
        أكبر مسافة وقف (بالنقاط) تُبقي الخسارة الكاملة ضمن الميزانية
        عند الكمية الدنيا للوسيط. تعيد None إن كانت أصغر مسافة ممكنة تتجاوزها.

        نبحث على شبكة نصف نقطة لأن مسافات الوقف عملياً ليست مستمرة.
        """
        step = D("0.5")
        best: Optional[Decimal] = None
        pips = step
        while pips <= max_pips:
            economics = self.estimate(
                size=size,
                entry_price=entry_price,
                stop_distance_pips=pips,
                take_profit_distance_pips=pips * D("2"),
                stop_kind=stop_kind,
            )
            if economics.all_in_risk <= risk_budget:
                best = pips
                pips += step
                continue
            break
        return best

    def minimum_possible_risk(
        self, *, entry_price: Decimal, stop_kind: StopKind = StopKind.NORMAL
    ) -> Decimal:
        """
        أصغر خسارة ممكنة أصلاً: الكمية الدنيا للوسيط مع أصغر مسافة وقف مسموحة.
        إن تجاوزت هذه القيمة ميزانية المخاطرة ⇒ NO_TRADE: ACCOUNT_SIZE_INSUFFICIENT.
        """
        min_stop_price = self.economics.min_stop_distance
        min_pips = (
            self.price_to_pips(min_stop_price) if min_stop_price is not None else D("1")
        )
        if min_pips <= 0:
            min_pips = D("1")
        economics = self.estimate(
            size=self.economics.min_deal_size,
            entry_price=entry_price,
            stop_distance_pips=min_pips,
            take_profit_distance_pips=min_pips * D("2"),
            stop_kind=stop_kind,
        )
        return economics.all_in_risk


def with_discovered_spread(
    assumptions: CfdCostAssumptions, spread_price: Decimal
) -> CfdCostAssumptions:
    """يرقّي السبريد من افتراض إلى قيمة مُكتشَفة من الوسيط."""
    return replace(
        assumptions,
        spread_price=D(spread_price),
        spread_provenance=ValueProvenance.BROKER_DISCOVERY,
    )
