"""العمولات والحجم — القلب الحسابي للنظام."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.money import D
from app.contracts import Broker
from app.risk.constitution import MODE_SPECS, RiskLimits, RiskMode
from app.risk.costs import (
    IBKR_PRO_FIXED_US_STOCK,
    IBKR_PRO_TIERED_US_STOCK,
    estimate_trade_cost,
)
from app.risk.sizing import (
    REJECT_BELOW_MIN_ORDER,
    REJECT_COST_DOMINATED,
    REJECT_INVALID_STOP,
    size_position,
)


def test_tiered_minimum_per_order_applies(schedule):
    # 10 أسهم × 0.0035 = 0.035 => يُرفع إلى الحد الأدنى 0.35
    c = schedule.commission(D("10"), D("640"), is_fractional=False)
    assert c == D("0.35")


def test_one_percent_cap_beats_minimum_on_tiny_orders(schedule):
    # قيمة الصفقة 10 دولار => السقف 0.10 يهزم الحد الأدنى 0.35
    c = schedule.commission(D("1"), D("10"), is_fractional=False)
    assert c == D("0.10")


def test_fixed_minimum_is_one_dollar():
    c = IBKR_PRO_FIXED_US_STOCK.commission(D("10"), D("640"), is_fractional=False)
    assert c == D("1.00")


def test_fractional_minimum_is_a_floor_not_a_replacement(schedule):
    """
    القراءة المتحفظة: 0.01 أرضية مطلقة، والحد الأدنى للأمر 0.35 يظل سارياً.
    لو انعكس هذا لاحقاً بدليل رسمي، سيسقط هذا الاختبار عمداً ويُجبرنا على المراجعة.
    """
    c = schedule.commission(D("0.05"), D("640"), is_fractional=True)
    # قيمة الصفقة 32 دولار => السقف 0.32، الحد الأدنى 0.35 => النتيجة 0.32
    assert c == D("0.32")
    assert c > D("0.01")


def test_regulatory_fees_only_on_sell(schedule):
    fees = schedule.regulatory_fees_on_sell(D("10"), D("640"))
    assert fees > 0
    assert schedule.regulatory_fees_on_sell(D("0"), D("640")) == 0


def test_total_risk_includes_every_friction(schedule, assumptions):
    est = estimate_trade_cost(
        quantity=D("1"), entry_price=D("100"), stop_price=D("98"),
        schedule=schedule, assumptions=assumptions, is_fractional=False,
    )
    assert est.price_risk == D("2.00")
    assert est.total_risk > est.price_risk
    assert est.total_costs == (
        est.entry_commission + est.exit_commission + est.regulatory_fees
        + est.spread_cost + est.slippage_cost + est.conversion_cost
    )


def test_stop_above_entry_is_rejected(schedule, assumptions):
    with pytest.raises(ValueError):
        estimate_trade_cost(
            quantity=D("1"), entry_price=D("100"), stop_price=D("101"),
            schedule=schedule, assumptions=assumptions, is_fractional=False,
        )


def test_sizing_never_exceeds_risk_budget(schedule, assumptions):
    res = size_position(
        entry_price=D("640"), stop_price=D("630"), risk_budget=D("25.00"),
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("5000"),
    )
    assert res.approved
    assert res.estimate.total_risk <= D("25.00")


def test_sizing_is_maximal_within_budget(schedule, assumptions):
    """الكمية المختارة يجب ألا يمكن زيادتها خطوة واحدة دون تجاوز الميزانية."""
    budget = D("25.00")
    res = size_position(
        entry_price=D("640"), stop_price=D("630"), risk_budget=budget,
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("5000"),
    )
    bigger = estimate_trade_cost(
        quantity=res.quantity + D("0.0001"), entry_price=D("640"), stop_price=D("630"),
        schedule=schedule, assumptions=assumptions, is_fractional=True,
    )
    assert bigger.total_risk > budget


def test_invalid_stop_rejected(schedule, assumptions):
    res = size_position(
        entry_price=D("100"), stop_price=D("100"), risk_budget=D("5"),
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("1000"),
    )
    assert not res.approved and res.reason_code == REJECT_INVALID_STOP


def test_150_dollar_account_cannot_produce_a_viable_trade(schedule, assumptions):
    """
    الحقيقة المالية الأساسية لهذا المشروع:
    برأس مال 150 دولاراً، أي صفقة على SPY تُرفض لأن الاحتكاك يسيطر على المخاطرة.
    هذا الاختبار يوثّق النتيجة ويمنع أي تخفيف صامت لمعايير الأمان لاحقاً.
    """
    # ⚠️ **أثرٌ حقيقيٌّ لرفع ١٥ سبتمبر، مذكورٌ لا مطموس.**
    #
    # قبل الرفع كانت ميزانيةُ `VALIDATION` عند مرجع ١٥٠ تساوي ٣٫٠٠ فلا
    # تتجاوز الاحتكاك. وبعده صارت ٦٫٠٠ فتتجاوزه عند ستوب ١٫٥٪ — أي أنّ
    # ١٥٠ دولاراً **صارت تُنتج صفقةً** في التجريبي.
    #
    # والضمانُ الذي يحمي المال الحقيقي لم يتغيّر، وهو ما يُفحَص هنا.
    # والتغيُّرُ في التجريبي يفحصه الاختبارُ التالي مباشرةً كي يُرى.
    for mode in (RiskMode.CONSERVATIVE_LIVE,):
        limits = RiskLimits.for_mode(mode, D("150.00"), Broker.IBKR)
        for stop_pct in (D("0.01"), D("0.015"), D("0.02")):
            res = size_position(
                entry_price=D("640"),
                stop_price=D("640") * (Decimal("1") - stop_pct),
                risk_budget=limits.max_risk_per_trade,
                schedule=schedule, assumptions=assumptions,
                fractional_allowed=True, available_cash=D("150"), limits=limits,
            )
            assert not res.approved, f"صفقة قُبلت خطأً في {mode} عند ستوب {stop_pct}"
            assert res.reason_code in (
                REJECT_COST_DOMINATED, REJECT_BELOW_MIN_ORDER, "ACCOUNT_SIZE_INSUFFICIENT",
                "BREAKEVEN_MOVE_TOO_FAR",
            )


def test_validation_at_the_raised_limits_does_admit_a_trade_at_150(schedule, assumptions):
    """
    **يُثبّت الأثرَ بدل أن يخفيه.**

    هذا ليس احتفاءً بالنتيجة: هو تسجيلٌ أنّ رفعَ المخاطرة وسّع ما يُقبَل،
    وأنّ التوسيع بلا مالٍ حقيقيّ. فإن عاد الرفضُ يوماً، يجب أن يُكسر هذا
    الاختبار فيُسأل: أتغيّر الاحتكاك أم الحدّ؟
    """
    limits = RiskLimits.for_mode(RiskMode.VALIDATION, D("150.00"), Broker.IBKR)
    res = size_position(
        entry_price=D("640"),
        stop_price=D("640") * (Decimal("1") - D("0.015")),
        risk_budget=limits.max_risk_per_trade,
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("150"), limits=limits,
    )
    assert res.approved, res.reason_code
    assert res.quantity > 0
    # والسقفُ الصلب يبقى صلباً مهما اتّسع المقبول — بالمخاطرة الكاملة
    # بعد التكاليف، لا بمخاطرة السعر وحدها.
    assert res.estimate is not None
    assert res.estimate.total_risk <= limits.max_risk_per_trade


def test_commissioning_mode_allows_the_single_integration_trade(schedule, assumptions):
    """
    وضع Commissioning يعطّل الحواجز الاقتصادية عمداً وبموافقة المالكة،
    لأن غرض الصفقة اختبار تكامل لا ربح. لكن السقف المطلق للمخاطرة يبقى سارياً.
    """
    limits = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING, D("150.00"), Broker.IBKR)
    res = size_position(
        entry_price=D("640"), stop_price=D("620.80"),
        risk_budget=limits.max_risk_per_trade,
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("150"), limits=limits,
    )
    assert res.approved, res.reason_ar
    assert D("5.00") <= res.estimate.notional <= D("10.00")
    assert res.estimate.total_risk <= limits.max_risk_per_trade
    assert "الحواجز الاقتصادية معطّلة" in res.reason_ar


def test_commissioning_notional_never_exceeds_ten_dollars(schedule, assumptions):
    limits = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING, D("150.00"), Broker.IBKR)
    res = size_position(
        entry_price=D("640"), stop_price=D("639.00"),
        risk_budget=limits.max_risk_per_trade,
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("150"), limits=limits,
    )
    assert res.estimate is not None
    assert res.estimate.notional <= D("10.00")


def test_economic_guards_are_only_disabled_in_commissioning():
    assert MODE_SPECS[RiskMode.VALIDATION].enforce_economic_viability is True
    assert MODE_SPECS[RiskMode.CONSERVATIVE_LIVE].enforce_economic_viability is True
    assert MODE_SPECS[RiskMode.LIVE_COMMISSIONING].enforce_economic_viability is False
    assert MODE_SPECS[RiskMode.LIVE_COMMISSIONING].max_lifetime_entry_orders == 1
    assert MODE_SPECS[RiskMode.LIVE_COMMISSIONING].requires_per_order_approval is True


def test_ibkr_commissioning_notional_bounds_are_broker_scoped():
    """
    حدود 5–10 دولارات كانت منطق **أسهم IBKR** ولا معنى لها في CFD.
    الدستور 0.2.0 يجعلها سياسة خاصة بالوسيط لا قاعدة عامة.
    """
    ibkr = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING, D("150.00"), Broker.IBKR)
    capital = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING, D("150.00"), Broker.CAPITAL_COM)
    assert ibkr.min_notional_usd == D("5.00")
    assert ibkr.max_notional_usd == D("10.00")
    assert capital.min_notional_usd is None
    assert capital.max_notional_usd is None
    assert capital.use_broker_minimum_quantity is True


def test_larger_account_can_produce_a_viable_trade(schedule, assumptions):
    limits = RiskLimits.from_baseline(D("5000.00"))
    res = size_position(
        entry_price=D("640"), stop_price=D("630.40"),
        risk_budget=limits.target_risk_per_trade,
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("5000"),
    )
    assert res.approved
    assert res.estimate.total_risk <= limits.target_risk_per_trade
    assert res.estimate.total_risk <= limits.max_risk_per_trade


def test_whole_share_sizing_when_fractional_unavailable(schedule, assumptions):
    res = size_position(
        entry_price=D("50"), stop_price=D("49"), risk_budget=D("25.00"),
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=False, available_cash=D("5000"),
    )
    assert res.approved
    assert res.quantity == res.quantity.to_integral_value()


def test_notional_never_exceeds_available_cash(schedule, assumptions):
    res = size_position(
        entry_price=D("640"), stop_price=D("639"), risk_budget=D("500"),
        schedule=schedule, assumptions=assumptions,
        fractional_allowed=True, available_cash=D("200"),
    )
    if res.approved:
        assert res.estimate.notional <= D("200")
