"""
Trade cost model — عقود التكلفة الحقيقية.

كل رقم هنا مصدره وثيقة IBKR رسمية موثقة في docs/DATA_SOURCES.md.
لا يُسمح بتعديل هذه الأرقام إلا مع تحديث المصدر وتاريخ التحقق.

المرجع الرسمي (تم التحقق 2026-08-28):
  https://www.interactivebrokers.com/en/pricing/commissions-stocks.php

IBKR Pro — US Stocks/ETFs
  Fixed : USD 0.005 / share, minimum USD 1.00 per order, maximum 1% of trade value
  Tiered: USD 0.0035 / share (<=300k shares/mo), minimum USD 0.35 per order,
          maximum 1% of trade value, + exchange & regulatory fees passed through
  Regulatory (on SELLS only):
          SEC Transaction Fee      = USD 0.0000206 * value of aggregate sales
          FINRA Trading Activity   = USD 0.000195  * quantity sold
  Fractional trades: same commission schedule, minimum USD 0.01 per fractional trade.

IBKR Lite (commission-free) is "US Residents Only" and is therefore NOT
available to the owner of this system (resident of Saudi Arabia).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from ..money import D, money_ceil, safe_div

PricingPlan = Literal["FIXED", "TIERED"]


@dataclass(frozen=True)
class CommissionSchedule:
    """A broker commission schedule. Immutable, sourced, dated."""

    name: str
    per_share: Decimal
    min_per_order: Decimal
    max_pct_of_trade_value: Decimal
    fractional_min_per_order: Decimal
    sec_fee_rate: Decimal          # on sale proceeds
    finra_taf_per_share: Decimal   # on shares sold
    finra_taf_max: Decimal
    passes_through_regulatory_fees: bool
    source_url: str
    verified_on: str

    def commission(self, quantity: Decimal, price: Decimal, *, is_fractional: bool) -> Decimal:
        """
        Broker commission for one order leg (excludes regulatory fees).

        ترتيب التطبيق (القراءة المتحفظة — انظر OPEN-IBKR-01 في KNOWN_LIMITATIONS.md):
          1. العمولة الخام = per_share × الكمية
          2. تُرفع إلى الحد الأدنى للأمر (0.35 Tiered / 1.00 Fixed)
             — الحد الأدنى للأمر يسري على الأوامر الكسرية أيضاً
          3. تُخفض إلى سقف 1% من قيمة الصفقة
          4. لا تقل أبداً عن 0.01 للأمر الكسري

        القراءة المتساهلة (أن 0.01 يحل محل 0.35 للأوامر الكسرية) لم نجد لها
        نصاً رسمياً صريحاً، ولذلك لا يُبنى عليها أي قرار مخاطرة قبل التحقق
        من كشف عمولات فعلي في حساب Paper/Live.
        """
        quantity = D(quantity)
        price = D(price)
        if quantity <= 0 or price <= 0:
            return Decimal("0")

        trade_value = quantity * price
        raw = self.per_share * quantity
        cap = self.max_pct_of_trade_value * trade_value

        commission = max(raw, self.min_per_order)
        # The 1%-of-trade-value maximum caps the per-order minimum too.
        commission = min(commission, cap)
        if is_fractional:
            commission = max(commission, self.fractional_min_per_order)
        return money_ceil(commission)

    def regulatory_fees_on_sell(self, quantity: Decimal, price: Decimal) -> Decimal:
        """SEC + FINRA TAF. Charged on the SELL leg only."""
        quantity = D(quantity)
        price = D(price)
        if quantity <= 0 or price <= 0:
            return Decimal("0")
        sec = self.sec_fee_rate * (quantity * price)
        taf = min(self.finra_taf_per_share * quantity, self.finra_taf_max)
        return money_ceil(sec + taf)


IBKR_PRO_FIXED_US_STOCK = CommissionSchedule(
    name="IBKR Pro Fixed — US Stocks/ETFs",
    per_share=D("0.005"),
    min_per_order=D("1.00"),
    max_pct_of_trade_value=D("0.01"),
    fractional_min_per_order=D("0.01"),
    sec_fee_rate=D("0.0000206"),
    finra_taf_per_share=D("0.000195"),
    finra_taf_max=D("8.30"),
    passes_through_regulatory_fees=True,
    source_url="https://www.interactivebrokers.com/en/pricing/commissions-stocks.php",
    verified_on="2026-08-28",
)

IBKR_PRO_TIERED_US_STOCK = CommissionSchedule(
    name="IBKR Pro Tiered — US Stocks/ETFs (<=300k shares/month)",
    per_share=D("0.0035"),
    min_per_order=D("0.35"),
    max_pct_of_trade_value=D("0.01"),
    fractional_min_per_order=D("0.01"),
    sec_fee_rate=D("0.0000206"),
    finra_taf_per_share=D("0.000195"),
    finra_taf_max=D("8.30"),
    passes_through_regulatory_fees=True,
    source_url="https://www.interactivebrokers.com/en/pricing/commissions-stocks.php",
    verified_on="2026-08-28",
)

SCHEDULES: dict[PricingPlan, CommissionSchedule] = {
    "FIXED": IBKR_PRO_FIXED_US_STOCK,
    "TIERED": IBKR_PRO_TIERED_US_STOCK,
}


@dataclass(frozen=True)
class CostAssumptions:
    """
    Non-commission frictions. Deliberately pessimistic defaults.
    Every one of these must be *measured* from paper/shadow fills before Live.
    """

    spread_abs: Decimal              # full quoted spread in price units
    slippage_pct_per_leg: Decimal    # fraction of price, per leg
    currency_conversion_pct: Decimal # fraction of notional, if base currency != USD

    @staticmethod
    def default() -> "CostAssumptions":
        return CostAssumptions(
            spread_abs=D("0.01"),
            slippage_pct_per_leg=D("0.0005"),   # 5 bps per leg
            currency_conversion_pct=D("0"),     # account is USD-funded
        )


@dataclass(frozen=True)
class TradeCostEstimate:
    """Full round-trip cost + worst-case loss for ONE candidate position."""

    quantity: Decimal
    entry_price: Decimal
    stop_price: Decimal
    notional: Decimal

    entry_commission: Decimal
    exit_commission: Decimal
    regulatory_fees: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    conversion_cost: Decimal
    price_risk: Decimal

    @property
    def total_costs(self) -> Decimal:
        return (
            self.entry_commission
            + self.exit_commission
            + self.regulatory_fees
            + self.spread_cost
            + self.slippage_cost
            + self.conversion_cost
        )

    @property
    def total_risk(self) -> Decimal:
        """Worst-case USD loss if the stop is hit. THIS is what the constitution limits."""
        return self.price_risk + self.total_costs

    @property
    def cost_ratio(self) -> Decimal:
        """Share of the risk budget consumed by friction rather than by the trade idea."""
        return safe_div(self.total_costs, self.total_risk, Decimal("1"))

    @property
    def breakeven_move_pct(self) -> Decimal:
        """How far price must move, as a fraction, just to cover round-trip friction."""
        return safe_div(self.total_costs, self.notional, Decimal("1"))


def estimate_trade_cost(
    *,
    quantity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    schedule: CommissionSchedule,
    assumptions: CostAssumptions,
    is_fractional: bool,
) -> TradeCostEstimate:
    """
    Long-only worst case: we buy at entry_price and are stopped out at stop_price,
    paying commissions both ways plus spread, slippage and regulatory fees.
    """
    quantity = D(quantity)
    entry_price = D(entry_price)
    stop_price = D(stop_price)

    if stop_price >= entry_price:
        raise ValueError("stop_price must be strictly below entry_price for a long position")

    notional = quantity * entry_price
    price_risk = money_ceil((entry_price - stop_price) * quantity)

    entry_commission = schedule.commission(quantity, entry_price, is_fractional=is_fractional)
    exit_commission = schedule.commission(quantity, stop_price, is_fractional=is_fractional)
    regulatory = (
        schedule.regulatory_fees_on_sell(quantity, stop_price)
        if schedule.passes_through_regulatory_fees
        else Decimal("0")
    )
    # We cross the spread on entry and again on exit -> one full spread, conservatively.
    spread_cost = money_ceil(assumptions.spread_abs * quantity)
    slippage_cost = money_ceil(
        assumptions.slippage_pct_per_leg * entry_price * quantity
        + assumptions.slippage_pct_per_leg * stop_price * quantity
    )
    conversion_cost = money_ceil(assumptions.currency_conversion_pct * notional)

    return TradeCostEstimate(
        quantity=quantity,
        entry_price=entry_price,
        stop_price=stop_price,
        notional=notional,
        entry_commission=entry_commission,
        exit_commission=exit_commission,
        regulatory_fees=regulatory,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        conversion_cost=conversion_cost,
        price_risk=price_risk,
    )
