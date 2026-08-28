"""الأسواق والأسعار والبث — بلا شبكة."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.brokers.capital.adapter import (
    DEFAULT_DISCOVERY_ALLOWLIST,
    DEFAULT_EXECUTION_ALLOWLIST,
    InstrumentNotAllowed,
)
from app.brokers.capital.errors import CapitalMalformedResponse, CapitalTransportError
from app.brokers.capital.endpoints import market_path, prices_path
from app.brokers.capital.streaming import (
    MAX_SUBSCRIPTIONS,
    MockStreamingClient,
    StreamingState,
    TooManySubscriptions,
)
from app.clock import now_utc
from app.contracts import AssetClass, Broker
from app.marketdata.service import DataVerdict, assess_quote
from app.money import D
from tests.capital_fixtures import (
    build_adapter,
    build_transport,
    eurusd_market_body,
    generic_market_body,
    prices_body,
)


def connected(transport=None):
    adapter, guarded, fixture = build_adapter(transport)
    adapter.connect()
    return adapter, guarded, fixture


# --- تفاصيل السوق -----------------------------------------------------------

def test_epic_search_returns_summaries():
    transport = build_transport()
    transport.register_json(
        "GET", "/api/v1/markets",
        {"markets": [{"epic": "EURUSD", "instrumentName": "EUR/USD",
                      "instrumentType": "CURRENCIES", "marketStatus": "TRADEABLE",
                      "bid": 1.0854, "offer": 1.08546}]},
    )
    adapter, _g, _f = connected(transport)
    results = adapter.search_markets("EUR")
    assert results[0].epic == "EURUSD"


def test_market_details_expose_every_field_the_cost_model_needs():
    adapter, _g, _f = connected()
    details = adapter.get_instrument_details("EURUSD")
    assert details.broker is Broker.CAPITAL_COM
    assert details.asset_class is AssetClass.CFD_CURRENCY
    assert details.min_quantity == D("100")
    assert details.quantity_increment == D("1")
    assert details.margin_factor == D("1")
    assert details.margin_factor_unit == "PERCENTAGE"
    assert details.min_stop_distance == D("0.0010")
    assert details.min_guaranteed_stop_distance == D("0.0030")
    assert details.guaranteed_stop_available is True
    assert details.pip_size == D("0.0001")
    assert details.quote_currency == "USD"
    assert details.is_cfd is True


def test_guaranteed_stop_unavailable_is_reported_not_assumed():
    transport = build_transport(markets={"EURUSD": eurusd_market_body(guaranteed_stop=False)})
    adapter, _g, _f = connected(transport)
    assert adapter.get_instrument_details("EURUSD").guaranteed_stop_available is False


def test_missing_min_deal_size_is_malformed_not_guessed():
    body = eurusd_market_body()
    del body["dealingRules"]["minDealSize"]
    transport = build_transport(markets={"EURUSD": body})
    adapter, _g, _f = connected(transport)
    with pytest.raises(CapitalMalformedResponse):
        adapter.get_market("EURUSD")


def test_market_closed_is_visible_in_status():
    transport = build_transport(markets={"EURUSD": eurusd_market_body(status="CLOSED")})
    adapter, _g, _f = connected(transport)
    status = adapter.get_market_status()
    assert status.is_open is False
    assert "CLOSED" in status.reason_ar


def test_missing_bid_or_ask_is_rejected():
    body = eurusd_market_body()
    body["snapshot"]["bid"] = None
    transport = build_transport(markets={"EURUSD": body})
    adapter, _g, _f = connected(transport)
    with pytest.raises(CapitalTransportError):
        adapter.get_market_data("EURUSD")


def test_wide_spread_is_rejected_by_the_data_gate():
    transport = build_transport(markets={"EURUSD": eurusd_market_body(bid=1.0800, offer=1.0900)})
    adapter, _g, _f = connected(transport)
    quote = adapter.get_market_data("EURUSD")
    assert assess_quote(quote, now=now_utc()).verdict is DataVerdict.SPREAD_TOO_WIDE


def test_stale_quote_is_rejected_by_the_data_gate():
    adapter, _g, _f = connected()
    quote = adapter.get_market_data("EURUSD")
    later = quote.timestamp_utc + timedelta(minutes=5)
    assert assess_quote(quote, now=later).verdict is DataVerdict.STALE


def test_fresh_quote_passes_the_data_gate():
    adapter, _g, _f = connected()
    quote = adapter.get_market_data("EURUSD")
    assert assess_quote(quote, now=quote.timestamp_utc).tradable


# --- قوائم الأدوات ----------------------------------------------------------

def test_discovery_allowlist_is_exactly_the_four_instruments():
    assert DEFAULT_DISCOVERY_ALLOWLIST == frozenset({"EURUSD", "GBPUSD", "USDJPY", "GOLD"})


def test_execution_allowlist_is_eurusd_only():
    assert DEFAULT_EXECUTION_ALLOWLIST == frozenset({"EURUSD"})


def test_instrument_outside_discovery_allowlist_never_reaches_the_wire():
    adapter, _g, fixture = connected()
    calls_before = len(fixture.calls)
    with pytest.raises(InstrumentNotAllowed):
        adapter.get_market("BTCUSD")
    assert len(fixture.calls) == calls_before


def test_instrument_outside_execution_allowlist_cannot_build_a_payload():
    adapter, _g, _f = connected()
    from app.contracts import Side

    with pytest.raises(InstrumentNotAllowed):
        adapter.build_position_payload(
            epic="GBPUSD", direction=Side.BUY, size=D("100"),
            stop_distance=D("0.0050"), profit_distance=D("0.0100"),
            guaranteed_stop=False,
        )


def test_all_four_discovery_instruments_can_be_read():
    markets = {
        "EURUSD": eurusd_market_body(),
        "GBPUSD": generic_market_body("GBPUSD", bid=1.2700, offer=1.27008),
        "USDJPY": generic_market_body("USDJPY", bid=150.10, offer=150.11),
        "GOLD": generic_market_body("GOLD", type_="COMMODITIES", bid=2400.0, offer=2400.4),
    }
    adapter, _g, _f = connected(build_transport(markets=markets))
    for epic in markets:
        assert adapter.get_market(epic).epic == epic


# --- الشموع التاريخية -------------------------------------------------------

def test_candles_parse_bid_and_ask_sides():
    adapter, _g, _f = connected()
    candles = adapter.get_candles("EURUSD", max_bars=5)
    assert len(candles) == 5
    assert candles[0].open_ask > candles[0].open_bid
    assert candles[0].snapshot_time_utc.tzinfo is not None


def test_candle_without_timestamp_is_malformed():
    body = prices_body(1)
    del body["prices"][0]["snapshotTimeUTC"]
    del body["prices"][0]["snapshotTime"]
    adapter, _g, _f = connected(build_transport(prices=body))
    with pytest.raises(CapitalMalformedResponse):
        adapter.get_candles("EURUSD")


def test_candle_with_scalar_price_instead_of_bid_ask_is_malformed():
    body = prices_body(1)
    body["prices"][0]["openPrice"] = 1.085
    adapter, _g, _f = connected(build_transport(prices=body))
    with pytest.raises(CapitalMalformedResponse):
        adapter.get_candles("EURUSD")


# --- البث -------------------------------------------------------------------

def test_websocket_subscribe_and_quote_flow():
    client = MockStreamingClient()
    client.connect()
    client.subscribe(["EURUSD"])
    quote = client.feed({"payload": {"epic": "EURUSD", "bid": 1.0854, "ofr": 1.08546}})
    assert quote.epic == "EURUSD"
    assert client.state.fresh_quote("EURUSD") is not None


def test_websocket_disconnect_blocks_subscription():
    client = MockStreamingClient()
    client.connect()
    client.drop()
    assert client.connected is False
    with pytest.raises(CapitalTransportError):
        client.subscribe(["EURUSD"])


def test_websocket_reconnect_restores_subscriptions():
    client = MockStreamingClient()
    client.connect()
    client.subscribe(["EURUSD", "GBPUSD"])
    client.drop()
    client.reconnect()
    assert client.connected is True
    assert client.state.reconnects == 1
    assert client.state.subscriptions == {"EURUSD", "GBPUSD"}


def test_maximum_instrument_subscriptions_is_enforced():
    state = StreamingState()
    with pytest.raises(TooManySubscriptions):
        state.add_subscriptions([f"EPIC{i}" for i in range(MAX_SUBSCRIPTIONS + 1)])


def test_stale_streamed_quote_is_not_returned():
    client = MockStreamingClient()
    client.connect()
    old = now_utc() - timedelta(minutes=10)
    client.feed({"payload": {"epic": "EURUSD", "bid": 1.0, "ofr": 1.1}}, received_at=old)
    assert client.state.fresh_quote("EURUSD") is None


def test_malformed_stream_message_is_rejected():
    client = MockStreamingClient()
    client.connect()
    with pytest.raises(CapitalMalformedResponse):
        client.feed({"payload": {"epic": "EURUSD"}})


def test_ping_requires_open_channel():
    client = MockStreamingClient()
    assert client.ping() is False
    client.connect()
    assert client.ping() is True
