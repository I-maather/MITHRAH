"""
سقفُ المراكز يعدّ ما يملكه الحساب، لا ما يتذكّره جدولٌ فارغ.

`load_session_state` تبني `open_symbols` من `TradeRow` حيث
`closed_at_utc IS NULL`، والجدول لا يُكتَب فيه عند فتح مركز. فقرأ الشرط
`open_positions >= max_open_positions` صفراً دائماً.

والأثر مقيس: يوم 2026-09-04 بلغت المراكز عند الوسيط **خمسة** والسقف
المعلن ثلاثة، ولم يمنع شيء.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tests.runtime_fixtures import passing_startup

from app.money import D
from app.portfolio.book import OpenPosition
from app.risk.engine import SessionRiskState
from app.risk.size_ladder import RECONCILIATION_NOT_READY
from app.runtime import heartbeat as hb
from app.scheduling import SafeScheduler

NOW = datetime(2026, 9, 4, 16, 30, tzinfo=timezone.utc)


class _Candle:
    start_utc = NOW
    open = high = low = close = D("1.16")
    volume = D("1")


class _Broker:
    """وسيطٌ يملك مراكز وأوامر — أو يعجز عن قولها."""

    def __init__(self, positions=(), orders=(), blind=False):
        self._positions = list(positions)
        self._orders = list(orders)
        self._blind = blind

    def health_check(self):
        return True

    def get_candles(self, symbol, *, resolution="DAY", max_bars=200):
        return [_Candle() for _ in range(200)]

    def list_open_positions_detailed(self):
        if self._blind:
            raise ConnectionError("لا شبكة")
        return list(self._positions)

    def get_positions(self, account_id=""):
        if self._blind:
            raise ConnectionError("لا شبكة")
        return list(self._positions)

    def get_orders(self, account_id=""):
        if self._blind:
            raise ConnectionError("لا شبكة")
        return list(self._orders)

    def get_balances(self, account_id=""):
        return SimpleNamespace(account_id="T", total_cash=D("300"), settled_cash=D("300"))


class _Pipeline:
    def __init__(self):
        self.calls = []

    def run(self, *, symbol, bars, state, macro):
        self.calls.append({"symbol": symbol, "state": state})
        return SimpleNamespace(
            decision=SimpleNamespace(name="NO_TRADE"), reason_code="NO_SETUP",
            reason_ar="", stage="strategy", at_utc=NOW,
        )


def _state(monkeypatch, broker):
    monkeypatch.setattr(
        hb, "load_session_state",
        lambda *a, **k: SessionRiskState(
            baseline_equity=D("300"), current_equity=D("300"),
            realized_pnl_today=D("0"), realized_pnl_week=D("0"),
            unrealized_pnl=D("0"), open_positions=0,
            entry_orders_today=0, consecutive_losses=0,
        ),
    )
    return SimpleNamespace(
        locally_paused=False,
        broker=broker,
        kill_switch=SimpleNamespace(is_active=False, state=SimpleNamespace(current_event=None)),
        limits=SimpleNamespace(
            allowed_instruments=frozenset({"EURUSD"}), baseline_equity=D("300")
        ),
        db_session=None,
        last_bars={},
        pipeline=_Pipeline(),
        scheduler=SafeScheduler(),
        session_state=None,
        last_result=None,
        startup=passing_startup(),
        last_scan=[],
        portfolio=None,
        providers=SimpleNamespace(calendar=None),
    )


def _run(state):
    hb.register_runtime_jobs(state)
    state.scheduler.tick()
    return state.last_result


def _position(symbol: str, quantity: str) -> OpenPosition:
    return OpenPosition(symbol=symbol, quantity=D(quantity), entry_price=D("1.35"))


def test_the_open_count_comes_from_the_broker_not_from_an_empty_table(monkeypatch):
    broker = _Broker(positions=(
        _position("GBPUSD", "-200"),
        _position("GOLD", "-0.01"),
        _position("EURUSD", "300"),
    ))
    state = _state(monkeypatch, broker)
    _run(state)

    # الجدول المحلي فارغ، والحساب يحمل ثلاثة. المحرّك يجب أن يرى ثلاثة.
    assert state.session_state.open_positions == 3
    assert set(state.session_state.open_symbols) == {"GBPUSD", "GOLD", "EURUSD"}


def test_a_pending_order_is_reserved_exposure(monkeypatch):
    """أمرٌ معلّقٌ تعرّضٌ محجوز — وإلا مرّت إشارتان متزامنتان فوق السقف."""
    broker = _Broker(
        positions=(_position("GBPUSD", "-200"),),
        orders=(SimpleNamespace(symbol="EURUSD"),),
    )
    state = _state(monkeypatch, broker)
    _run(state)

    assert state.session_state.open_positions == 2
    assert set(state.session_state.open_symbols) == {"GBPUSD", "EURUSD"}


def test_a_blind_cycle_opens_nothing(monkeypatch):
    """حارسٌ أعمى ليس حارساً: تعذّرت القراءة ⇒ لا فتحَ مركز."""
    state = _state(monkeypatch, _Broker(blind=True))
    result = _run(state)

    assert result.reason_code == RECONCILIATION_NOT_READY
    assert state.pipeline.calls == [], "قُيّم رمزٌ والمحفظة مجهولة"


def test_management_keeps_reading_while_entry_is_paused(monkeypatch):
    """
    الإيقاف يمنع الدخول لا الرؤية.

    كان `locally_paused` يعود قبل كل شيء، فتتوقّف قراءةُ المراكز والمطابقة
    معه — وبقيت خمسةُ مراكز ساعاتٍ بلا مراقبة.
    """
    broker = _Broker(positions=(_position("GBPUSD", "-200"),))
    state = _state(monkeypatch, broker)
    state.locally_paused = True
    result = _run(state)

    assert result.reason_code == "LOCALLY_PAUSED"
    assert state.portfolio is not None and state.portfolio.ok
    assert state.portfolio.open_count == 1, "المحفظة لم تُقرأ أثناء الإيقاف"
    assert state.pipeline.calls == [], "فُتح تقييمٌ والدخول موقوف"
