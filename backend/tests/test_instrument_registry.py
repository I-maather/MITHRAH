"""
سجلّ اقتصاديات الأدوات — **المقيس وحده يُنفَّذ عليه.**

القاعدة تضيّق وتوسّع بمبدأ واحد: أداةٌ تصير قابلة للتنفيذ حين **تُقاس**،
لا حين تُضاف إلى قائمة. فتُمنع `EURUSD` نفسها ما دامت اقتصادياتها من صفحةٍ
عامة، وتُسمح `GOLD` متى قِيست من الحساب.
"""
from __future__ import annotations

import json

import pytest

from app.risk.capital_costs import ValueProvenance
from app.risk.instrument_registry import InstrumentRegistry

MEASURED = {
    "epic": "GBPUSD",
    "pip_size": "0.0001",
    "lot_size": "1",
    "min_deal_size": "100",
    "size_increment": "1",
    "margin_factor": "1",
    "margin_factor_unit": "PERCENTAGE",
    "min_stop_distance": "0.01",
    # **الوحدة كما يعيدها الوسيط.** رقمٌ بلا وحدةٍ ليس قياساً — وهو
    # الملف الذي جعل ٠٫٠١٪ تُقرأ ١٠٠ نقطة.
    "min_stop_distance_unit": "PERCENTAGE",
    "min_guaranteed_stop_distance": None,
    "guaranteed_stop_available": False,
    "quote_currency": "USD",
    "overnight_fee_rate_daily": None,
    "spread_price": "0.00009",
    "spread_samples": 5,
    "provenance": "BROKER_DISCOVERY",
    "measured_at_utc": "2026-09-02T10:00:00+00:00",
}


def registry(**overrides):
    row = {**MEASURED, **overrides}
    return InstrumentRegistry.from_dict({"instruments": {row["epic"]: row}})


def test_a_measured_instrument_becomes_executable():
    reg = registry()
    assert reg.executable_epics() == {"GBPUSD"}
    assert reg.why_not("GBPUSD") == "GBPUSD: قابلة للتنفيذ."


def test_an_assumed_instrument_never_becomes_executable():
    """
    **هذا هو التضييق.** `EURUSD` اليوم اقتصادياتها من صفحة كابيتال العامة
    (`PROVISIONAL_PUBLIC_SITE`) لا من الحساب — ولا يجوز أن تمرّ لأنها
    «كانت في القائمة دائماً».
    """
    reg = registry(epic="EURUSD", provenance="PROVISIONAL_PUBLIC_SITE")
    assert reg.executable_epics() == frozenset()
    assert "مفترضة لا مقيسة" in reg.why_not("EURUSD")


def test_an_unknown_minimum_stop_is_not_executable():
    """
    بلا حدٍّ معلوم يُرسَل الأمر ليُرفَض عند الوسيط — وهو العطل الذي كلّفنا
    ليلة 09-01 كاملة.
    """
    reg = registry(min_stop_distance=None)
    assert reg.executable_epics() == frozenset()
    assert "أدنى مسافة وقف غير معلومة" in reg.why_not("GBPUSD")


def test_a_spread_never_observed_is_not_executable():
    reg = registry(spread_price=None, spread_samples=0)
    assert reg.executable_epics() == frozenset()


def test_the_measured_spread_replaces_the_assumption_and_says_so():
    model = registry().cost_model_for("GBPUSD")
    assert model is not None
    assert str(model.assumptions.spread_price) == "0.00009"
    assert model.assumptions.spread_provenance is ValueProvenance.BROKER_DISCOVERY


def test_measuring_outside_the_discovery_list_does_not_widen_anything():
    """
    قياسُ أداةٍ لم يُسمح باكتشافها لا يجعلها قابلة للتنفيذ. التوسيع يقع
    داخل ما سُمح به، لا حوله.
    """
    reg = registry(epic="BTCUSD")
    assert reg.executable_epics(within=["EURUSD", "GBPUSD", "USDJPY", "GOLD"]) == frozenset()
    assert reg.executable_epics() == {"BTCUSD"}


def test_a_missing_file_yields_nothing_and_invents_nothing(tmp_path):
    reg = InstrumentRegistry.load(tmp_path / "no-such-file.json")
    assert len(reg) == 0
    assert reg.cost_model_for("EURUSD") is None
    assert "لا قياس" in reg.why_not("EURUSD")


def test_a_corrupt_file_is_not_guessed_from(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    assert len(InstrumentRegistry.load(path)) == 0


def test_a_row_missing_a_required_field_is_dropped_not_completed(tmp_path):
    """صفٌّ ناقص يُتجاهَل. وإكمالُه بالتخمين يُنتج حجماً محسوباً على وهم."""
    row = {k: v for k, v in MEASURED.items() if k != "pip_size"}
    reg = InstrumentRegistry.from_dict({"instruments": {"GBPUSD": row}})
    assert len(reg) == 0


def test_the_round_trip_survives_a_real_file(tmp_path):
    path = tmp_path / "econ.json"
    path.write_text(
        json.dumps({"instruments": {"GBPUSD": MEASURED}}, ensure_ascii=False),
        encoding="utf-8",
    )
    reg = InstrumentRegistry.load(path)
    model = reg.cost_model_for("GBPUSD")
    assert model is not None
    # القيم تصل كما قيست — لا تقريب ولا تحويل صامت.
    assert str(model.economics.min_stop_distance) == "0.01"
    assert str(model.economics.pip_size) == "0.0001"
