"""
وحدةُ قاعدةٍ تُطرَح — والنظام يرفض كل إشاراته وهو يعمل «بلا خطأ».

## ما وقع فعلاً

`GET /markets/{epic}` عند Capital.com يعيد:

    "minStopOrProfitDistance": {"unit": "PERCENTAGE", "value": 0.01}

وكان القارئ يأخذ `value` ويطرح `unit`، فيُخزَّن `0.01` ويُقارَن بمسافة وقفٍ
**بوحدة السعر**. وعلى EUR/USD عند 1.16 ذلك ١٠٠ نقطة، والحدُّ الحقيقي
**١٫١٦ نقطة**: تضخيمٌ بنحو ٨٦٠ ضعفاً.

**الأثر مقيسٌ لا مُقدَّر** — من سجلّ التدقيق الحيّ بين ٣٠ أغسطس و٣ سبتمبر
٢٠٢٦ (٦٠٠٨ دورة قرار): ٤٨٦ إشارة وُلِدت، و٤٨٦ رُفضت عند
`BROKER_MIN_STOP_DISTANCE_VIOLATION`. مئةٌ بالمئة. ولم تبلغ ولا إشارةٌ
واحدة بوابةَ المخاطر، فبدا النظام «يعمل ولا يجد فرصاً».

## القيم كما يعيدها الوسيط (قياسٌ مباشر 2026-09-03، حساب Demo)

| الأداة | القاعدة | السعر | الحدّ الحقيقي |
|---|---|---|---|
| EURUSD | PERCENTAGE 0.01 | 1.16292 | 1.16 نقطة |
| GBPUSD | PERCENTAGE 0.01 | 1.35281 | 1.35 نقطة |
| USDJPY | PERCENTAGE 0.01 | 155.736 | 1.56 نقطة |
| GOLD   | PERCENTAGE 0.001 | 4472.63 | 4.47 (بحجم نقطة 0.01) |

## ما تحرسه هذه الفحوص

١. أن الوحدة **تُقرأ وتُحفَظ**، لا تُطرح.
٢. أن الحلّ إلى وحدة السعر يقع في موضعٍ واحد وبسعرٍ مرجعي حاضر.
٣. أن قياساً من الوسيط **بلا وحدة** لا يُعامَل سعراً — بل يُسمّى
   `INSTRUMENT_SPEC_UNRESOLVED` ويُعاد قياسه.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.brokers.capital.models import CapitalMarket, DealingRules, RuleDistance
from app.money import D
from app.risk.capital_costs import InstrumentEconomics, ValueProvenance
from app.risk.instrument_registry import InstrumentRegistry

from .capital_fixtures import eurusd_market_body


def _body_with(rule: dict) -> dict:
    body = eurusd_market_body()
    body["dealingRules"]["minStopOrProfitDistance"] = rule
    return body


# ---------------------------------------------------------------------------
# ١ · الوحدة تُقرأ ولا تُطرح
# ---------------------------------------------------------------------------

def test_the_unit_survives_parsing():
    rules = DealingRules.parse(
        _body_with({"unit": "PERCENTAGE", "value": 0.01})["dealingRules"]
    )
    assert isinstance(rules.min_stop_or_profit_distance, RuleDistance)
    assert rules.min_stop_or_profit_distance.value == D("0.01")
    assert rules.min_stop_or_profit_distance.unit == "PERCENTAGE"


def test_a_percentage_rule_becomes_a_price_only_with_a_price():
    rule = RuleDistance(value=D("0.01"), unit="PERCENTAGE")
    assert rule.to_price(D("1.16292")) == D("0.01") / D("100") * D("1.16292")
    # بلا سعرٍ مرجعي لا يُختلق رقم.
    assert rule.to_price(None) is None


def test_a_points_rule_is_already_a_price():
    assert RuleDistance(value=D("0.0010"), unit="POINTS").to_price(D("1.16")) == D("0.0010")


def test_a_rule_without_a_unit_is_not_resolvable():
    rule = RuleDistance(value=D("0.01"), unit=None)
    assert not rule.resolvable
    assert rule.to_price(D("1.16")) is None


# ---------------------------------------------------------------------------
# ٢ · الطفرة التي كانت تمرّ
# ---------------------------------------------------------------------------

def test_the_percentage_rule_is_not_read_as_a_raw_price():
    """
    **الفحص الذي يعضّ.** لو عاد القارئ إلى أخذ `value` وحدها لصار الحدُّ
    على اليورو ١٠٠ نقطة — وهو ما كان.
    """
    market = CapitalMarket.parse(_body_with({"unit": "PERCENTAGE", "value": 0.01}))
    resolved = market.dealing_rules.min_stop_or_profit_distance.to_price(D("1.16292"))
    assert resolved is not None
    pips = resolved / D("0.0001")
    assert D("1") < pips < D("2"), f"الحدّ {pips} نقطة — القيمة قُرئت بغير وحدتها."
    assert pips != D("100")


def test_the_adapter_never_hands_on_a_value_without_its_unit():
    """
    حارسٌ ساكن على المحوّل: كل مسافةٍ تُمرَّر إلى `InstrumentDetails` تحمل
    وحدتها. وبدونه يعود العطل بصمتٍ في أوّل إعادة كتابة.
    """
    from app.brokers.capital import adapter as adapter_module

    source = (adapter_module.__file__ or "")
    text = open(source, encoding="utf-8").read()
    assert "min_stop_distance_unit=" in text
    assert "min_guaranteed_stop_distance_unit=" in text


# ---------------------------------------------------------------------------
# ٣ · قياسٌ محفوظ بلا وحدة لا يُنفَّذ عليه
# ---------------------------------------------------------------------------

_ROW = {
    "epic": "EURUSD", "pip_size": "0.0001", "lot_size": "1",
    "min_deal_size": "100", "size_increment": "100",
    "margin_factor": "3.333333", "margin_factor_unit": "PERCENTAGE",
    "min_stop_distance": "0.01", "spread_price": "0.00007",
    "quote_currency": "USD", "provenance": "BROKER_DISCOVERY",
    "spread_samples": 5, "measured_at_utc": "2026-09-03T00:00:00+00:00",
}


def test_a_stored_measurement_without_a_unit_is_not_executable():
    reg = InstrumentRegistry.from_dict({"instruments": {"EURUSD": dict(_ROW)}})
    assert reg.executable_epics() == frozenset()
    assert "بوحدةٍ مجهولة" in reg.why_not("EURUSD")
    assert "discover_instrument_economics" in reg.why_not("EURUSD")


def test_the_same_measurement_with_its_unit_is_executable():
    row = dict(_ROW, min_stop_distance_unit="PERCENTAGE")
    reg = InstrumentRegistry.from_dict({"instruments": {"EURUSD": row}})
    assert reg.executable_epics() == frozenset({"EURUSD"})
    econ = reg.get("EURUSD").economics
    assert econ.min_stop_price_at(D("1.16292")) == D("0.01") / D("100") * D("1.16292")


def test_a_value_we_wrote_ourselves_is_still_a_price():
    """
    الصرامة موضعُها القياس من الوسيط. وما نكتبه نحن — افتراضاتٌ مبدئية
    وقيمُ اختبار — بوحدة السعر بالتعريف، فلا يُعطَّل به شيء.
    """
    econ = InstrumentEconomics(
        epic="X", pip_size=D("0.0001"), lot_size=D("1"), min_deal_size=D("100"),
        size_increment=D("1"), margin_factor=D("1"), margin_factor_unit="PERCENTAGE",
        min_stop_distance=D("0.0005"), min_guaranteed_stop_distance=None,
        guaranteed_stop_available=False, quote_currency="USD",
        overnight_fee_rate_daily=None, provenance=ValueProvenance.PROVISIONAL_PUBLIC_SITE,
    )
    assert not econ.stop_spec_unresolved
    assert econ.min_stop_price_at(D("1.16")) == D("0.0005")


@pytest.mark.parametrize(
    "unit,value,price,expected_pips",
    [
        ("PERCENTAGE", "0.01", "1.16292", "1.16292"),
        ("PERCENTAGE", "0.01", "1.35281", "1.35281"),
    ],
)
def test_the_measured_broker_values_land_where_the_broker_says(unit, value, price, expected_pips):
    econ = InstrumentEconomics(
        epic="EURUSD", pip_size=D("0.0001"), lot_size=D("1"), min_deal_size=D("100"),
        size_increment=D("100"), margin_factor=D("3.333333"),
        margin_factor_unit="PERCENTAGE", min_stop_distance=D(value),
        min_guaranteed_stop_distance=None, guaranteed_stop_available=True,
        quote_currency="USD", overnight_fee_rate_daily=None,
        provenance=ValueProvenance.BROKER_DISCOVERY, min_stop_distance_unit=unit,
    )
    pips = econ.min_stop_price_at(D(price)) / econ.pip_size
    assert pips == D(expected_pips)
