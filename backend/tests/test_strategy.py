from __future__ import annotations

from datetime import timedelta

import pytest

from app.brokers.mock import make_quote
from app.contracts import DataSource, Side, StrategyState
from app.money import D
from app.strategies.base import StrategyRegistry
from app.strategies.trend_pullback_v1 import TrendPullbackV1, average_true_range, sma
from tests.conftest import MID_SESSION, uptrend_bars


def quote():
    return make_quote("SPY", "639.99", "640.00", at=MID_SESSION, source=DataSource.REALTIME)


def test_strategy_ships_as_research_not_approved():
    """
    بوابة الاعتماد: الاستراتيجية الوحيدة لم تجتز Backtest، فحالتها RESEARCH.
    لو غُيّرت إلى APPROVED دون أدلة، يسقط هذا الاختبار.
    """
    meta = TrendPullbackV1.metadata
    assert meta.state is StrategyState.RESEARCH
    assert "لا يوجد" in meta.backtest_evidence_ar


def test_metadata_is_complete():
    m = TrendPullbackV1.metadata
    assert m.name and m.version and m.hypothesis_ar
    assert m.entry_conditions_ar and m.exit_conditions_ar and m.invalidations_ar
    assert m.no_trade_conditions_ar and m.changelog_ar
    assert m.min_bars_required > 0


def test_signal_generated_on_valid_pullback():
    s = TrendPullbackV1().evaluate(symbol="SPY", bars=uptrend_bars(), quote=quote(), now=MID_SESSION)
    assert s is not None
    assert s.side is Side.BUY
    assert s.stop_price < s.entry_price < s.take_profit_price
    assert s.reward_risk_ratio >= D("1.5")


def test_deterministic_same_inputs_same_output():
    bars = uptrend_bars()
    a = TrendPullbackV1().evaluate(symbol="SPY", bars=bars, quote=quote(), now=MID_SESSION)
    b = TrendPullbackV1().evaluate(symbol="SPY", bars=bars, quote=quote(), now=MID_SESSION)
    assert a == b
    assert a.inputs_digest == b.inputs_digest


def test_different_bars_give_different_digest():
    a = TrendPullbackV1().evaluate(symbol="SPY", bars=uptrend_bars(), quote=quote(), now=MID_SESSION)
    b = TrendPullbackV1().evaluate(
        symbol="SPY", bars=uptrend_bars(start=D("500.00")), quote=quote(), now=MID_SESSION
    )
    assert a.inputs_digest != b.inputs_digest


def test_no_signal_when_not_enough_bars():
    assert TrendPullbackV1().evaluate(
        symbol="SPY", bars=uptrend_bars(n=10), quote=quote(), now=MID_SESSION
    ) is None


def test_no_signal_on_symbol_outside_strategy_markets():
    assert TrendPullbackV1().evaluate(
        symbol="TSLA", bars=uptrend_bars("TSLA"), quote=quote(), now=MID_SESSION
    ) is None


def test_no_signal_in_downtrend():
    bars = uptrend_bars()
    reversed_bars = list(reversed(bars))
    # إعادة ترتيب زمني تصاعدي مع أسعار هابطة
    fixed = [
        b.model_copy(update={"start_utc": bars[i].start_utc})
        for i, b in enumerate(reversed_bars)
    ]
    assert TrendPullbackV1().evaluate(
        symbol="SPY", bars=fixed, quote=quote(), now=MID_SESSION
    ) is None


def test_sma_and_atr_math():
    assert sma([D("1"), D("2"), D("3")], 3) == D("2")
    assert sma([D("1")], 3) is None
    bars = uptrend_bars(n=30)
    assert average_true_range(bars, 14) > 0
    assert average_true_range(bars[:5], 14) is None


# --- registry ---------------------------------------------------------------

def test_registry_exposes_only_approved_strategies():
    reg = StrategyRegistry()
    reg.register(TrendPullbackV1())
    assert len(reg.all()) == 1
    assert reg.active() == []


def test_registry_rejects_duplicate_registration():
    reg = StrategyRegistry()
    reg.register(TrendPullbackV1())
    with pytest.raises(ValueError):
        reg.register(TrendPullbackV1())
