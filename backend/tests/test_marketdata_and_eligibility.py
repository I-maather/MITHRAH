from __future__ import annotations

from datetime import timedelta

from app.brokers.mock import make_quote
from app.contracts import AccountKind, AssetClass, ClientClassification, DataSource, InstrumentDetails, OrderType
from app.eligibility.allowlist import (
    ALLOWLIST,
    CLOSING_BLACKOUT,
    DATA_NOT_TRADABLE,
    EXPLICITLY_DENIED,
    MARKET_CLOSED,
    NOT_IN_ALLOWLIST,
    NO_RELIABLE_STOP,
    OPENING_BLACKOUT,
    PERMISSIONS_INSUFFICIENT,
    check_eligibility,
)
from app.marketdata.service import DataVerdict, assess_quote
from app.money import D
from tests.conftest import MID_SESSION, make_balances, make_permissions


def details(now=MID_SESSION, **kw):
    base = dict(
        symbol="SPY", conid="756733", asset_class=AssetClass.ETF, currency="USD", exchange="ARCA",
        min_quantity=D("0.0001"), supports_fractional=True, supports_stop_orders=True,
        supports_stop_on_fractional=True,
        supported_order_types=(OrderType.MARKET, OrderType.LIMIT, OrderType.STOP),
        as_of_utc=now,
    )
    base.update(kw)
    return InstrumentDetails(**base)


# --- market data ------------------------------------------------------------

def test_missing_quote_is_not_tradable():
    assert assess_quote(None, now=MID_SESSION).verdict is DataVerdict.MISSING


def test_stale_quote_is_rejected():
    q = make_quote("SPY", "639.99", "640.00", at=MID_SESSION - timedelta(minutes=5), source=DataSource.REALTIME)
    assert assess_quote(q, now=MID_SESSION).verdict is DataVerdict.STALE


def test_delayed_source_is_rejected_for_execution():
    q = make_quote("SPY", "639.99", "640.00", at=MID_SESSION, source=DataSource.DELAYED)
    assert assess_quote(q, now=MID_SESSION).verdict is DataVerdict.NOT_REALTIME


def test_historical_source_is_rejected_for_execution():
    q = make_quote("SPY", "639.99", "640.00", at=MID_SESSION, source=DataSource.HISTORICAL)
    assert assess_quote(q, now=MID_SESSION).verdict is DataVerdict.NOT_REALTIME


def test_wide_spread_is_rejected():
    q = make_quote("SPY", "630.00", "640.00", at=MID_SESSION, source=DataSource.REALTIME)
    assert assess_quote(q, now=MID_SESSION).verdict is DataVerdict.SPREAD_TOO_WIDE


def test_crossed_market_is_rejected():
    q = make_quote("SPY", "640.10", "640.00", at=MID_SESSION, source=DataSource.REALTIME)
    assert assess_quote(q, now=MID_SESSION).verdict in (
        DataVerdict.CROSSED_MARKET, DataVerdict.SPREAD_TOO_WIDE
    )


def test_future_timestamp_is_rejected_as_clock_error():
    q = make_quote("SPY", "639.99", "640.00", at=MID_SESSION + timedelta(minutes=2), source=DataSource.REALTIME)
    assert assess_quote(q, now=MID_SESSION).verdict is DataVerdict.FUTURE_TIMESTAMP


def test_fresh_realtime_quote_is_tradable():
    q = make_quote("SPY", "639.99", "640.00", at=MID_SESSION, source=DataSource.REALTIME)
    assert assess_quote(q, now=MID_SESSION).tradable


# --- eligibility ------------------------------------------------------------

def eligible_args(now=MID_SESSION, **kw):
    base = dict(
        symbol="SPY",
        quote=make_quote("SPY", "639.99", "640.00", at=now, source=DataSource.REALTIME),
        details=details(now), permissions=make_permissions(at=now),
        balances=make_balances("5000.00", at=now),
        market_is_open=True, minutes_since_open=90, minutes_to_close=300, now=now,
    )
    base.update(kw)
    return base


def test_happy_path_is_eligible():
    r = check_eligibility(**eligible_args())
    assert r.eligible and r.fractional_allowed


def test_symbol_outside_allowlist_is_rejected():
    r = check_eligibility(**eligible_args(symbol="TSLA"))
    assert not r.eligible and r.reason_code == NOT_IN_ALLOWLIST


def test_explicit_denylist_symbols_are_rejected():
    for symbol in ("XAUUSD", "EURUSD", "BTCUSD"):
        r = check_eligibility(**eligible_args(symbol=symbol))
        assert not r.eligible and r.reason_code == EXPLICITLY_DENIED


def test_allowlist_contains_only_usd_etfs():
    for entry in ALLOWLIST.values():
        assert entry.currency == "USD"
        assert entry.asset_class in (AssetClass.ETF, AssetClass.STOCK)


def test_closed_market_rejected():
    r = check_eligibility(**eligible_args(market_is_open=False))
    assert not r.eligible and r.reason_code == MARKET_CLOSED


def test_opening_blackout_rejected():
    r = check_eligibility(**eligible_args(minutes_since_open=10))
    assert not r.eligible and r.reason_code == OPENING_BLACKOUT


def test_closing_blackout_rejected():
    r = check_eligibility(**eligible_args(minutes_to_close=5))
    assert not r.eligible and r.reason_code == CLOSING_BLACKOUT


def test_margin_account_rejected():
    r = check_eligibility(**eligible_args(
        permissions=make_permissions(account_kind=AccountKind.MARGIN, margin_enabled=True)
    ))
    assert not r.eligible and r.reason_code == PERMISSIONS_INSUFFICIENT


def test_professional_classification_rejected():
    r = check_eligibility(**eligible_args(
        permissions=make_permissions(classification=ClientClassification.PROFESSIONAL)
    ))
    assert not r.eligible and r.reason_code == PERMISSIONS_INSUFFICIENT


def test_options_permission_rejected():
    r = check_eligibility(**eligible_args(permissions=make_permissions(options=True)))
    assert not r.eligible and r.reason_code == PERMISSIONS_INSUFFICIENT


def test_instrument_without_stop_support_rejected():
    r = check_eligibility(**eligible_args(details=details(supports_stop_orders=False)))
    assert not r.eligible and r.reason_code == NO_RELIABLE_STOP


def test_fractional_disabled_when_stop_not_supported_on_fractions():
    """
    الحالة الحاسمة: الكسور مدعومة، لكن أوامر الوقف غير مدعومة عليها.
    النظام لا يخترع Synthetic Stop — يتراجع إلى الأسهم الكاملة.
    """
    r = check_eligibility(**eligible_args(details=details(supports_stop_on_fractional=False)))
    assert r.eligible
    assert not r.fractional_allowed


def test_stale_data_blocks_eligibility():
    stale = make_quote("SPY", "639.99", "640.00",
                       at=MID_SESSION - timedelta(minutes=10), source=DataSource.REALTIME)
    r = check_eligibility(**eligible_args(quote=stale))
    assert not r.eligible and r.reason_code == DATA_NOT_TRADABLE


def test_zero_settled_cash_blocks():
    r = check_eligibility(**eligible_args(balances=make_balances("0.00")))
    assert not r.eligible
