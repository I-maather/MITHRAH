"""
نموذج تكلفة Capital.com — القلب الحسابي للهجرة.

الأمثلة كلها EUR/USD بكمية 100 (الكمية الدنيا حسب الموقع العام) وبمسافات
وقف 25 و50 و75 نقطة كما طُلب صراحةً.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.contracts import Broker, StopKind
from app.money import D
from app.risk.capital_costs import (
    PROVISIONAL_EURUSD,
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
    with_discovered_spread,
)
from app.risk.constitution import RiskLimits, RiskMode
from app.risk.cost_router import (
    UnsupportedBroker,
    build_cost_bundle,
    economics_from_instrument,
    supported_brokers,
)
from tests.capital_fixtures import build_adapter

ENTRY = D("1.08546")


def discovered_economics(**overrides) -> InstrumentEconomics:
    base = dict(
        epic="EURUSD",
        pip_size=D("0.0001"),
        lot_size=D("1"),
        min_deal_size=D("100"),
        size_increment=D("1"),
        margin_factor=D("1"),
        margin_factor_unit="PERCENTAGE",
        min_stop_distance=D("0.0010"),
        min_guaranteed_stop_distance=D("0.0030"),
        guaranteed_stop_available=True,
        quote_currency="USD",
        overnight_fee_rate_daily=D("0.00007"),
        provenance=ValueProvenance.BROKER_DISCOVERY,
    )
    base.update(overrides)
    return InstrumentEconomics(**base)


def model(**overrides) -> CapitalComCostModel:
    assumptions = overrides.pop("assumptions", None) or with_discovered_spread(
        CfdCostAssumptions.default(), D("0.00006")
    )
    return CapitalComCostModel(discovered_economics(**overrides), assumptions)


# --- التفريق بين القيم الثلاث -----------------------------------------------

def test_notional_margin_and_risk_are_three_different_numbers():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("50"), take_profit_distance_pips=D("100"),
    )
    assert economics.notional_exposure == pytest.approx(Decimal("108.546"), rel=1e-9)
    assert economics.margin_required == pytest.approx(Decimal("1.08546"), rel=1e-9)
    assert economics.all_in_risk < D("1.00")
    # ثلاث قيم مختلفة تماماً — الخلط بينها هو الخطأ الذي يمنعه هذا الاختبار.
    assert economics.notional_exposure != economics.margin_required
    assert economics.margin_required != economics.all_in_risk
    assert economics.notional_exposure > economics.margin_required > economics.all_in_risk


def test_display_dict_shows_the_three_values_separately():
    display = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("50"), take_profit_distance_pips=D("100"),
    ).as_display_dict()
    for key in ("notional_exposure", "margin_required", "all_in_risk_at_stop"):
        assert key in display
    assert display["notional_exposure"] != display["all_in_risk_at_stop"]


def test_pip_value_for_100_units_is_one_cent():
    assert model().pip_value(D("100")) == D("0.01")


# --- الأمثلة المطلوبة: 25 / 50 / 75 نقطة -------------------------------------

@pytest.mark.parametrize(
    "pips,expected_price_loss",
    [(D("25"), D("0.25")), (D("50"), D("0.50")), (D("75"), D("0.75"))],
)
def test_worked_examples_price_loss(pips, expected_price_loss):
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=pips, take_profit_distance_pips=pips * 2,
    )
    assert economics.price_loss_at_stop == expected_price_loss


def test_25_pip_stop_fits_inside_the_preferred_050_cap():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
    )
    assert economics.all_in_risk <= D("0.50")


def test_50_pip_stop_fits_inside_the_absolute_075_cap():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("50"), take_profit_distance_pips=D("100"),
    )
    assert economics.all_in_risk <= D("0.75")


def test_75_pip_stop_exceeds_the_075_cap_once_costs_are_included():
    """
    75 نقطة = 0.75 دولار خسارة سعر وحدها، وأي تكلفة فوقها تتجاوز السقف.
    هذا بالضبط سبب حساب التكاليف داخل المخاطرة لا خارجها.
    """
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("75"), take_profit_distance_pips=D("150"),
    )
    assert economics.price_loss_at_stop == D("0.75")
    assert economics.all_in_risk > D("0.75")


# --- مكوّنات التكلفة ---------------------------------------------------------

def test_spread_cost_is_included():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("50"), take_profit_distance_pips=D("100"),
    )
    assert economics.spread_cost > 0
    assert economics.all_in_risk > economics.price_loss_at_stop


def test_slippage_reserve_applies_to_normal_stops_only():
    normal = model().estimate(
        size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
        take_profit_distance_pips=D("100"), stop_kind=StopKind.NORMAL,
    )
    guaranteed = model(
        assumptions=with_discovered_spread(
            CfdCostAssumptions(
                spread_price=D("0.00006"), slippage_reserve_pips=D("1.0"),
                guaranteed_stop_premium_pips=D("3"), currency_conversion_pct=D("0"),
                nights_held=0,
            ),
            D("0.00006"),
        )
    ).estimate(
        size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
        take_profit_distance_pips=D("100"), stop_kind=StopKind.GUARANTEED,
    )
    assert normal.slippage_reserve > 0
    assert guaranteed.slippage_reserve == 0
    assert guaranteed.guaranteed_stop_premium > 0


def test_guaranteed_stop_premium_unknown_is_flagged_provisional():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
        take_profit_distance_pips=D("100"), stop_kind=StopKind.GUARANTEED,
    )
    assert economics.provisional is True
    assert any("الوقف المضمون غير معلومة" in n for n in economics.provenance_notes)


def test_guaranteed_stop_unavailable_is_refused():
    with pytest.raises(ValueError, match="غير متاح"):
        model(guaranteed_stop_available=False).estimate(
            size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
            take_profit_distance_pips=D("100"), stop_kind=StopKind.GUARANTEED,
        )


def test_overnight_cost_applies_only_when_holding_overnight():
    flat = model().estimate(
        size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
        take_profit_distance_pips=D("100"), nights_held=0,
    )
    overnight = model().estimate(
        size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
        take_profit_distance_pips=D("100"), nights_held=3,
    )
    assert flat.overnight_cost == 0
    assert overnight.overnight_cost > 0
    assert overnight.all_in_risk > flat.all_in_risk


def test_unknown_overnight_fee_is_flagged_and_not_invented():
    economics = model(overnight_fee_rate_daily=None).estimate(
        size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
        take_profit_distance_pips=D("100"), nights_held=2,
    )
    assert economics.overnight_cost == 0
    assert economics.provisional is True
    assert any("التبييت غير معلومة" in n for n in economics.provenance_notes)


def test_currency_conversion_cost_applies_when_configured():
    assumptions = CfdCostAssumptions(
        spread_price=D("0.00006"), slippage_reserve_pips=D("1"),
        guaranteed_stop_premium_pips=None, currency_conversion_pct=D("0.005"),
        nights_held=0, spread_provenance=ValueProvenance.BROKER_DISCOVERY,
    )
    economics = CapitalComCostModel(discovered_economics(), assumptions).estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
    )
    assert economics.conversion_cost > 0
    assert any("تحويل عملة" in n for n in economics.provenance_notes)


def test_no_stop_is_refused():
    with pytest.raises(ValueError):
        model().estimate(
            size=D("100"), entry_price=ENTRY, stop_distance_pips=D("0"),
            take_profit_distance_pips=D("100"),
        )
    with pytest.raises(ValueError):
        model().estimate(
            size=D("100"), entry_price=ENTRY, stop_distance_pips=D("50"),
            take_profit_distance_pips=D("100"), stop_kind=StopKind.NONE,
        )


# --- مقاييس مشتقة ------------------------------------------------------------

def test_net_reward_and_ratio_are_after_costs():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
    )
    assert economics.net_reward < economics.gross_reward_at_target
    assert economics.net_reward_risk_ratio < D("2")


def test_breakeven_move_is_expressed_in_pips():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
    )
    assert economics.breakeven_move_pips > 0
    assert economics.breakeven_move_pips < D("10")


def test_minimum_possible_risk_uses_broker_minimum_size():
    minimum = model().minimum_possible_risk(entry_price=ENTRY)
    assert minimum > 0
    assert minimum < D("0.50")


def test_max_stop_pips_within_a_075_budget():
    pips = model().max_stop_pips_within_risk(
        size=D("100"), entry_price=ENTRY, risk_budget=D("0.75")
    )
    assert pips is not None
    assert D("60") <= pips <= D("75")


def test_no_stop_distance_fits_an_impossible_budget():
    assert model().max_stop_pips_within_risk(
        size=D("100"), entry_price=ENTRY, risk_budget=D("0.001")
    ) is None


# --- المصدر والمبدئية ---------------------------------------------------------

def test_public_site_assumptions_are_marked_provisional():
    assert PROVISIONAL_EURUSD.is_provisional is True
    assert PROVISIONAL_EURUSD.provenance is ValueProvenance.PROVISIONAL_PUBLIC_SITE
    assert PROVISIONAL_EURUSD.guaranteed_stop_available is False


def test_provisional_economics_flag_the_result():
    economics = CapitalComCostModel(PROVISIONAL_EURUSD).estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
    )
    assert economics.provisional is True


def test_discovered_values_clear_the_provisional_flag():
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
    )
    assert economics.provisional is False


def test_margin_factor_in_percent_and_ratio_agree():
    as_percent = discovered_economics(margin_factor=D("1"), margin_factor_unit="PERCENTAGE")
    as_ratio = discovered_economics(margin_factor=D("0.01"), margin_factor_unit="RATIO")
    assert as_percent.margin_rate == as_ratio.margin_rate == D("0.01")


# --- التوجيه حسب الوسيط -------------------------------------------------------

def test_ibkr_cost_model_is_untouched_and_still_routed():
    bundle = build_cost_bundle(Broker.IBKR)
    assert bundle.ibkr_schedule is not None
    assert bundle.capital_model is None
    assert bundle.is_cfd is False


def test_capital_cost_model_is_routed_for_capital_com():
    bundle = build_cost_bundle(Broker.CAPITAL_COM)
    assert bundle.capital_model is not None
    assert bundle.ibkr_schedule is None
    assert bundle.is_cfd is True


def test_both_brokers_are_supported_simultaneously():
    assert set(supported_brokers()) >= {Broker.CAPITAL_COM, Broker.IBKR}


def test_economics_built_from_live_instrument_details():
    adapter, _g, _f = build_adapter()
    adapter.connect()
    details = adapter.get_instrument_details("EURUSD")
    economics = economics_from_instrument(details)
    assert economics.epic == "EURUSD"
    assert economics.min_deal_size == D("100")
    assert economics.provenance is ValueProvenance.BROKER_DISCOVERY


def test_missing_pip_size_refuses_to_build_a_cost_model():
    adapter, _g, _f = build_adapter()
    adapter.connect()
    details = adapter.get_instrument_details("EURUSD").model_copy(update={"pip_size": None})
    with pytest.raises(UnsupportedBroker, match="حجم النقطة"):
        economics_from_instrument(details)


def test_ibkr_255_380_conclusion_is_not_reused_for_capital_com():
    """
    استنتاج 0.1.0 (الحد الأدنى 255–380 دولاراً) كان مشتقاً من الحد الأدنى
    لعمولة IBKR. Capital.com لا يفرض عمولة على فوركس CFD، لذلك لا يجوز نقله.
    هذا الاختبار يوثّق الفرق عددياً.
    """
    limits = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("150.00"), Broker.CAPITAL_COM)
    economics = model().estimate(
        size=D("100"), entry_price=ENTRY,
        stop_distance_pips=D("25"), take_profit_distance_pips=D("50"),
    )
    # عند 150 دولاراً، صفقة Capital.com الدنيا تقع ضمن حد 1.50 دولار.
    assert economics.all_in_risk <= limits.max_risk_per_trade
    assert economics.all_in_risk <= D("0.50")
