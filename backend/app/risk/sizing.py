"""
Position sizing — الحجم يُحسب بعد الرسوم، لا قبلها.

المبدأ: نبحث عن أكبر كمية تجعل
    (خسارة السعر حتى الستوب) + (كل الاحتكاك ذهاباً وإياباً) <= ميزانية المخاطرة
ثم نطبّق فحوصاً إضافية حسب وضع المخاطرة. إن لم توجد كمية صالحة => NO_TRADE.

الحواجز الاقتصادية (COST_DOMINATED / BREAKEVEN_MOVE_TOO_FAR) قابلة للتعطيل
في وضع LIVE_COMMISSIONING فقط، لأن غرض تلك الصفقة اختبار تكامل لا ربح.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..money import D, quantize_qty
from .constitution import DEFAULT_LIMITS, RiskLimits
from .costs import CommissionSchedule, CostAssumptions, TradeCostEstimate, estimate_trade_cost

WHOLE_SHARE = Decimal("1")
FRACTIONAL_GRANULARITY = Decimal("0.0001")
IBKR_FRACTIONAL_MIN_ORDER_USD = Decimal("1.00")

REJECT_ACCOUNT_SIZE_INSUFFICIENT = "ACCOUNT_SIZE_INSUFFICIENT"
REJECT_COST_DOMINATED = "COST_DOMINATED"
REJECT_BREAKEVEN_TOO_FAR = "BREAKEVEN_MOVE_TOO_FAR"
REJECT_BELOW_MIN_ORDER = "BELOW_BROKER_MIN_ORDER"
REJECT_BELOW_MODE_MIN_NOTIONAL = "BELOW_MODE_MIN_NOTIONAL"
REJECT_NOTIONAL_EXCEEDS_CASH = "NOTIONAL_EXCEEDS_SETTLED_CASH"
REJECT_INVALID_STOP = "INVALID_STOP"


@dataclass(frozen=True)
class SizingResult:
    approved: bool
    reason_code: Optional[str]
    reason_ar: str
    quantity: Decimal
    estimate: Optional[TradeCostEstimate]
    risk_budget: Decimal

    @property
    def notional(self) -> Decimal:
        return self.estimate.notional if self.estimate else Decimal("0")


def _largest_quantity_within_budget(
    *,
    entry_price: Decimal,
    stop_price: Decimal,
    risk_budget: Decimal,
    schedule: CommissionSchedule,
    assumptions: CostAssumptions,
    fractional_allowed: bool,
    max_notional: Decimal,
) -> Optional[Decimal]:
    """
    Monotone binary search. total_risk(q) is non-decreasing in q
    (price risk linear; commission = clamp(linear, flat-min, linear-cap)).
    """
    granularity = FRACTIONAL_GRANULARITY if fractional_allowed else WHOLE_SHARE

    def total_risk(q: Decimal) -> Decimal:
        return estimate_trade_cost(
            quantity=q,
            entry_price=entry_price,
            stop_price=stop_price,
            schedule=schedule,
            assumptions=assumptions,
            is_fractional=fractional_allowed,
        ).total_risk

    lo = granularity
    if total_risk(lo) > risk_budget:
        return None

    hi = quantize_qty(max_notional / entry_price, granularity)
    if hi < lo:
        return None
    if total_risk(hi) <= risk_budget:
        return hi

    steps = 0
    while hi - lo > granularity and steps < 200:
        steps += 1
        mid = quantize_qty((lo + hi) / 2, granularity)
        if mid <= lo:
            break
        if total_risk(mid) <= risk_budget:
            lo = mid
        else:
            hi = mid
    return lo


def size_position(
    *,
    entry_price,
    stop_price,
    risk_budget,
    schedule: CommissionSchedule,
    assumptions: CostAssumptions,
    fractional_allowed: bool,
    available_cash,
    limits: RiskLimits = DEFAULT_LIMITS,
    broker_min_order_usd: Decimal = IBKR_FRACTIONAL_MIN_ORDER_USD,
) -> SizingResult:
    entry_price = D(entry_price)
    stop_price = D(stop_price)
    risk_budget = D(risk_budget)
    available_cash = D(available_cash)

    def reject(code: str, message: str, estimate=None) -> SizingResult:
        return SizingResult(
            approved=False, reason_code=code, reason_ar=message,
            quantity=Decimal("0"), estimate=estimate, risk_budget=risk_budget,
        )

    if stop_price >= entry_price or stop_price <= 0:
        return reject(
            REJECT_INVALID_STOP,
            "وقف الخسارة غير صالح: يجب أن يكون أقل من سعر الدخول وأكبر من صفر.",
        )

    # سقف قيمة الصفقة: النقد المتاح، وسقف الوضع إن وُجد (Commissioning: 10 دولارات)
    notional_ceiling = available_cash
    if limits.max_notional_usd is not None:
        notional_ceiling = min(notional_ceiling, limits.max_notional_usd)

    quantity = _largest_quantity_within_budget(
        entry_price=entry_price,
        stop_price=stop_price,
        risk_budget=risk_budget,
        schedule=schedule,
        assumptions=assumptions,
        fractional_allowed=fractional_allowed,
        max_notional=notional_ceiling,
    )

    if quantity is None or quantity <= 0:
        return reject(
            REJECT_ACCOUNT_SIZE_INSUFFICIENT,
            "لا توجد كمية قابلة للتنفيذ ضمن ميزانية المخاطرة: "
            f"أصغر كمية ممكنة تتجاوز {risk_budget:.2f} دولار بسبب العمولات والاحتكاك.",
        )

    estimate = estimate_trade_cost(
        quantity=quantity, entry_price=entry_price, stop_price=stop_price,
        schedule=schedule, assumptions=assumptions, is_fractional=fractional_allowed,
    )

    if estimate.notional > available_cash:
        return reject(REJECT_NOTIONAL_EXCEEDS_CASH,
                      "قيمة الصفقة تتجاوز النقد المسوّى المتاح.", estimate)

    if estimate.notional < broker_min_order_usd:
        return reject(
            REJECT_BELOW_MIN_ORDER,
            f"قيمة الصفقة {estimate.notional:.2f} دولار أقل من الحد الأدنى "
            f"لأمر الوسيط ({broker_min_order_usd} دولار).",
            estimate,
        )

    if limits.min_notional_usd is not None and estimate.notional < limits.min_notional_usd:
        return reject(
            REJECT_BELOW_MODE_MIN_NOTIONAL,
            f"قيمة الصفقة {estimate.notional:.2f} دولار أقل من الحد الأدنى لوضع "
            f"{limits.mode.value} ({limits.min_notional_usd} دولار).",
            estimate,
        )

    if limits.enforce_economic_viability:
        if estimate.cost_ratio > limits.max_cost_ratio_of_risk:
            return reject(
                REJECT_COST_DOMINATED,
                f"الاحتكاك يلتهم {estimate.cost_ratio * 100:.1f}% من ميزانية المخاطرة "
                f"(الحد {limits.max_cost_ratio_of_risk * 100:.0f}%). هذه تكلفة مقنّعة وليست فرصة.",
                estimate,
            )
        if estimate.breakeven_move_pct > limits.max_breakeven_move_pct:
            return reject(
                REJECT_BREAKEVEN_TOO_FAR,
                f"السعر يحتاج حركة {estimate.breakeven_move_pct * 100:.2f}% لمجرد تغطية الرسوم "
                f"(الحد {limits.max_breakeven_move_pct * 100:.2f}%).",
                estimate,
            )

    note = ""
    if not limits.enforce_economic_viability:
        note = (
            f" ⚠️ الحواجز الاقتصادية معطّلة في وضع {limits.mode.value}: "
            f"الاحتكاك {estimate.total_costs:.2f} دولار ({estimate.cost_ratio * 100:.0f}% من المخاطرة) "
            "وهو رسوم اختبار معلومة سلفاً وليس رهاناً على السوق."
        )

    return SizingResult(
        approved=True,
        reason_code=None,
        reason_ar=(
            f"الكمية {quantity} بقيمة {estimate.notional:.2f} دولار، "
            f"أقصى خسارة متوقعة {estimate.total_risk:.2f} دولار ضمن ميزانية {risk_budget:.2f} دولار."
            + note
        ),
        quantity=quantity,
        estimate=estimate,
        risk_budget=risk_budget,
    )
