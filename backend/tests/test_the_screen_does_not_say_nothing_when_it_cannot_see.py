"""
سطحُ المراقبة لا يقول «لا شيء» حين يعجز عن القراءة.

يوم 2026-09-04 كان على الحساب خمسة مراكز مفتوحة وصفقتان مغلقتان بنتيجةٍ
محقّقة ‎−0.35‎ دولار، وطبقةُ الجوال تقول «لا مركز مفتوح. لم يُرسَل أي أمر،
والتنفيذ مقفول». الجملة كُتبت يوم كانت صادقة، وبقيت بعد أن كذبت.

وهذه الاختبارات تحرس الفرق الذي كلّف ذلك: بين **صفرٍ قِيس** و**عجزٍ عن
القياس**.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.money import D
from app.portfolio.book import (
    DEFAULT_MAX_AGE,
    PORTFOLIO_BROKER_UNREACHABLE,
    PORTFOLIO_OK,
    ClosedTrade,
    OpenPosition,
    read_portfolio,
    unavailable,
)

NOW = datetime(2026, 9, 4, 16, 30, tzinfo=timezone.utc)


def _position(symbol: str, quantity: str, *, entry="1.35", stop=None) -> OpenPosition:
    return OpenPosition(
        symbol=symbol,
        quantity=D(quantity),
        entry_price=D(entry),
        stop_price=D(stop) if stop is not None else None,
    )


class _Broker:
    """وسيطٌ يقول ما يُملى عليه — أو ينهار حين يُطلب منه ذلك."""

    def __init__(self, positions=(), transactions=(), raises=False):
        self._positions = list(positions)
        self._transactions = list(transactions)
        self._raises = raises

    def list_open_positions_detailed(self):
        if self._raises:
            raise ConnectionError("الشبكة سقطت")
        return list(self._positions)

    def list_recent_transactions(self):
        return list(self._transactions)

    def get_balances(self, account_id):  # noqa: ARG002
        raise NotImplementedError


# --- الفرق بين الصفر والعجز -------------------------------------------------


def test_a_failed_read_is_not_zero_positions():
    snapshot = read_portfolio(_Broker(raises=True), account_id="acct", at=NOW)

    assert snapshot.ok is False
    assert snapshot.reason_code == PORTFOLIO_BROKER_UNREACHABLE
    # **الحقل الحاسم**: لا يقول «صفر»، يقول «لا أعرف».
    assert snapshot.open_count is None
    assert snapshot.error_ar


def test_a_real_empty_account_is_a_measured_zero():
    snapshot = read_portfolio(_Broker(positions=()), account_id="acct", at=NOW)

    assert snapshot.ok is True
    assert snapshot.reason_code == PORTFOLIO_OK
    assert snapshot.open_count == 0


def test_unavailable_carries_its_reason():
    snapshot = unavailable(
        at=NOW, reason_code=PORTFOLIO_BROKER_UNREACHABLE, error_ar="سقطت الشبكة"
    )
    assert snapshot.open_count is None
    assert "سقطت" in snapshot.error_ar


# --- التعرّض ----------------------------------------------------------------


def test_two_positions_on_one_symbol_are_summed():
    snapshot = read_portfolio(
        _Broker(positions=(_position("GBPUSD", "-200"), _position("GBPUSD", "-200"))),
        account_id="acct",
        at=NOW,
    )
    assert snapshot.exposure_by_symbol() == {"GBPUSD": D("-400")}
    assert snapshot.open_count == 2
    assert snapshot.holds("gbpusd") is True


def test_a_symbol_with_no_position_is_not_held():
    snapshot = read_portfolio(
        _Broker(positions=(_position("GBPUSD", "-200"),)), account_id="a", at=NOW
    )
    assert snapshot.holds("EURUSD") is False


# --- الحماية ----------------------------------------------------------------


def test_a_position_without_a_broker_stop_is_named_unprotected():
    protected = _position("EURUSD", "300", entry="1.16194", stop="1.15935")
    naked = _position("GOLD", "-0.01", entry="4420.85")
    snapshot = read_portfolio(
        _Broker(positions=(protected, naked)), account_id="a", at=NOW
    )

    assert protected.is_protected is True
    assert naked.is_protected is False
    assert [p.symbol for p in snapshot.unprotected] == ["GOLD"]


def test_risk_at_stop_is_price_distance_times_size():
    position = _position("GBPUSD", "-200", entry="1.34997", stop="1.35364")
    # ‏(1.35364 − 1.34997) × 200 = 0.734
    assert abs(position.risk_at_stop - Decimal("0.734")) < Decimal("0.001")


def test_risk_at_stop_is_unknown_without_a_stop():
    assert _position("GOLD", "-0.01").risk_at_stop is None


# --- الاتجاه والنتيجة -------------------------------------------------------


def test_a_negative_quantity_reads_as_a_short():
    assert _position("GBPUSD", "-200").direction == "SELL"
    assert _position("EURUSD", "300").direction == "BUY"


def test_a_closed_trade_reports_its_realised_result():
    losing = ClosedTrade(symbol="GBPUSD", realised_pnl=D("-0.34"), currency="USD")
    winning = ClosedTrade(symbol="EURUSD", realised_pnl=D("1.20"), currency="USD")
    unknown = ClosedTrade(symbol="GOLD")

    assert losing.is_win is False
    assert winning.is_win is True
    # لا يُخمَّن ربحٌ من غياب رقم.
    assert unknown.is_win is None


def test_realised_total_sums_the_closed_trades():
    snapshot = read_portfolio(
        _Broker(
            transactions=(
                ClosedTrade(symbol="GBPUSD", realised_pnl=D("-0.34")),
                ClosedTrade(symbol="EURUSD", realised_pnl=D("-0.01")),
            )
        ),
        account_id="acct",
        at=NOW,
    )
    # الرقم الذي يقوله دفتر الحساب فعلاً في ذلك اليوم.
    assert snapshot.realised_pnl_total == D("-0.35")


# --- الحداثة ----------------------------------------------------------------


def test_a_snapshot_knows_when_it_went_stale():
    snapshot = read_portfolio(_Broker(), account_id="a", at=NOW)

    assert snapshot.is_stale(NOW) is False
    assert snapshot.is_stale(NOW + DEFAULT_MAX_AGE + timedelta(seconds=1)) is True
    assert snapshot.age_seconds(NOW + timedelta(seconds=45)) == 45


def test_the_day_that_broke_the_screen():
    """اللقطة نفسها التي كان الجوال يعرض مكانها «لا مركز مفتوح»."""
    snapshot = read_portfolio(
        _Broker(
            positions=(
                _position("GBPUSD", "-200", entry="1.35111", stop="1.354779"),
                _position("GOLD", "-0.01", entry="4420.85", stop="4479.797"),
                _position("EURUSD", "300", entry="1.16194", stop="1.159347"),
                _position("GBPUSD", "-200", entry="1.35213", stop="1.355799"),
                _position("GBPUSD", "-200", entry="1.35203", stop="1.355478"),
            ),
            transactions=(
                ClosedTrade(symbol="GBPUSD", realised_pnl=D("-0.34")),
                ClosedTrade(symbol="EURUSD", realised_pnl=D("-0.01")),
            ),
        ),
        account_id="acct",
        at=NOW,
    )

    assert snapshot.open_count == 5
    assert snapshot.exposure_by_symbol()["GBPUSD"] == D("-600")
    assert snapshot.realised_pnl_total == D("-0.35")
    assert snapshot.unprotected == ()
