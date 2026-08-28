"""
استجابات Capital.com بالشكل الرسمي — للاختبارات فقط.

كل بنية هنا مبنية على أسماء الحقول الموثّقة في https://open-api.capital.com/
(تُحقق 2026-08-28). **لا اختبار يفتح اتصالاً شبكياً.**
"""
from __future__ import annotations

from typing import Any, Optional

from app.brokers.capital.endpoints import (
    PATH_ACCOUNT_PREFERENCES,
    PATH_ACCOUNTS,
    PATH_ENCRYPTION_KEY,
    PATH_PING,
    PATH_POSITIONS,
    PATH_SESSION,
    PATH_WORKING_ORDERS,
    CapitalEnvironment,
    confirm_path,
    market_path,
    prices_path,
)
from app.brokers.capital.ratelimit import RateLimiter
from app.brokers.capital.safety import ExecutionLock
from app.brokers.capital.session import CapitalSession
from app.brokers.capital.transport import ApiResponse, FixtureTransport, GuardedTransport
from app.secretstore.provider import InMemorySecretProvider

FAKE_API_KEY = "fixture-api-key-0000000000"
FAKE_IDENTIFIER = "fixture-owner@example.test"
FAKE_PASSWORD = "fixture-api-password-1111"
FAKE_CST = "fixture-cst-token-aaaaaaaaaaaaaaaa"
FAKE_XST = "fixture-security-token-bbbbbbbbbbbb"

ACCOUNT_ID = "1234567890123456"
MASKED_ACCOUNT = "****3456"


def secrets() -> InMemorySecretProvider:
    return InMemorySecretProvider(
        {
            "CAPITAL_API_KEY": FAKE_API_KEY,
            "CAPITAL_IDENTIFIER": FAKE_IDENTIFIER,
            "CAPITAL_API_PASSWORD": FAKE_PASSWORD,
        }
    )


# ---------------------------------------------------------------------------
# أجسام الاستجابات
# ---------------------------------------------------------------------------

def session_response(*, cst: str = FAKE_CST, xst: str = FAKE_XST) -> ApiResponse:
    return ApiResponse(
        status=200,
        headers={"CST": cst, "X-SECURITY-TOKEN": xst},
        body={
            "accountType": "CFD",
            "currentAccountId": ACCOUNT_ID,
            "currencyIsoCode": "USD",
            "currencySymbol": "$",
            "streamingHost": "wss://api-streaming-capital.backend-capital.com/connect",
        },
    )


def accounts_body(*, currency: str = "USD", available: float = 150.0) -> dict:
    return {
        "accounts": [
            {
                "accountId": ACCOUNT_ID,
                "accountName": "Demo Account",
                "status": "ENABLED",
                "accountType": "CFD",
                "preferred": True,
                "balance": {
                    "balance": 150.0,
                    "deposit": 150.0,
                    "profitLoss": 0.0,
                    "available": available,
                },
                "currency": currency,
                "symbol": "$",
            }
        ]
    }


def preferences_body(*, hedging: bool = False, leverage: float = 100.0) -> dict:
    return {
        "hedgingMode": hedging,
        "leverages": {
            "CURRENCIES": {"current": leverage, "available": [50, 100, 200]},
            "SHARES": {"current": 5, "available": [1, 2, 5]},
            "COMMODITIES": {"current": 20, "available": [10, 20]},
            "INDICES": {"current": 20, "available": [10, 20]},
            "CRYPTOCURRENCIES": {"current": 2, "available": [1, 2]},
        },
    }


def eurusd_market_body(
    *,
    bid: float = 1.08540,
    offer: float = 1.08546,
    status: str = "TRADEABLE",
    min_deal_size: float = 100.0,
    min_size_increment: float = 1.0,
    margin_factor: float = 1.0,
    guaranteed_stop: bool = True,
    min_stop_distance: Optional[float] = 0.0010,
    min_gsl_distance: Optional[float] = 0.0030,
    overnight_fee: Optional[float] = 0.00007,
) -> dict:
    dealing: dict[str, Any] = {
        "minDealSize": {"unit": "AMOUNT", "value": min_deal_size},
        "maxDealSize": {"unit": "AMOUNT", "value": 1_000_000.0},
        "minSizeIncrement": {"unit": "AMOUNT", "value": min_size_increment},
        "marketOrderPreference": "AVAILABLE_DEFAULT_ON",
        "trailingStopsPreference": "AVAILABLE",
    }
    if min_stop_distance is not None:
        dealing["minStopOrProfitDistance"] = {"unit": "POINTS", "value": min_stop_distance}
        dealing["maxStopOrProfitDistance"] = {"unit": "POINTS", "value": 1.0}
    if min_gsl_distance is not None:
        dealing["minGuaranteedStopDistance"] = {"unit": "POINTS", "value": min_gsl_distance}

    return {
        "instrument": {
            "epic": "EURUSD",
            "symbol": "EUR/USD",
            "name": "EUR/USD",
            "type": "CURRENCIES",
            "currencies": [{"code": "USD", "name": "USD", "isDefault": True}],
            "lotSize": 1,
            "guaranteedStopAllowed": guaranteed_stop,
            "streamingPricesAvailable": True,
            "marginFactor": margin_factor,
            "marginFactorUnit": "PERCENTAGE",
            "overnightFee": overnight_fee,
        },
        "dealingRules": dealing,
        "snapshot": {
            "marketStatus": status,
            "bid": bid,
            "offer": offer,
            "high": 1.0900,
            "low": 1.0800,
            "percentageChange": 0.12,
            "updateTime": "2026-08-28T12:00:00",
            "delayTime": 0,
        },
    }


def generic_market_body(epic: str, *, type_: str = "CURRENCIES", bid: float = 1.0, offer: float = 1.1) -> dict:
    body = eurusd_market_body(bid=bid, offer=offer)
    body["instrument"]["epic"] = epic
    body["instrument"]["symbol"] = epic
    body["instrument"]["name"] = epic
    body["instrument"]["type"] = type_
    return body


def prices_body(count: int = 5) -> dict:
    prices = []
    for i in range(count):
        base = 1.0850 + i * 0.0005
        prices.append(
            {
                "snapshotTime": f"2026-08-28T{i:02d}:00:00",
                "snapshotTimeUTC": f"2026-08-28T{i:02d}:00:00Z",
                "openPrice": {"bid": base, "ask": base + 0.00006},
                "highPrice": {"bid": base + 0.001, "ask": base + 0.00106},
                "lowPrice": {"bid": base - 0.001, "ask": base - 0.00094},
                "closePrice": {"bid": base + 0.0003, "ask": base + 0.00036},
                "lastTradedVolume": 1000 + i,
            }
        )
    return {"instrumentType": "CURRENCIES", "prices": prices}


def positions_body(*, with_position: bool = False, stop_level: Optional[float] = 1.0800) -> dict:
    if not with_position:
        return {"positions": []}
    return {
        "positions": [
            {
                "position": {
                    "contractSize": 1,
                    "createdDate": "2026-08-28T12:00:00",
                    "createdDateUTC": "2026-08-28T12:00:00Z",
                    "dealId": "deal-abc-123",
                    "dealReference": "ref-abc-123",
                    "size": 100,
                    "direction": "BUY",
                    "level": 1.08546,
                    "stopLevel": stop_level,
                    "profitLevel": 1.09046,
                    "guaranteedStop": False,
                    "currency": "USD",
                    "upl": -0.02,
                },
                "market": {"epic": "EURUSD", "instrumentName": "EUR/USD", "marketStatus": "TRADEABLE"},
            }
        ]
    }


def confirm_body(
    *,
    deal_reference: str = "ref-abc-123",
    deal_status: str = "ACCEPTED",
    deal_id: Optional[str] = "deal-abc-123",
    reason: Optional[str] = None,
) -> dict:
    body = {
        "date": "2026-08-28T12:00:00.000",
        "status": "OPEN" if deal_status == "ACCEPTED" else "REJECTED",
        "dealStatus": deal_status,
        "epic": "EURUSD",
        "dealReference": deal_reference,
        "dealId": deal_id,
        "affectedDeals": [{"dealId": deal_id, "status": "OPENED"}] if deal_id else [],
        "level": 1.08546,
        "size": 100,
        "direction": "BUY",
        "guaranteedStop": False,
    }
    if reason:
        body["reason"] = reason
    return body


# ---------------------------------------------------------------------------
# تركيب ناقل جاهز
# ---------------------------------------------------------------------------

def build_transport(
    *,
    session_resp: Optional[ApiResponse] = None,
    accounts: Optional[dict] = None,
    preferences: Optional[dict] = None,
    markets: Optional[dict[str, dict]] = None,
    prices: Optional[dict] = None,
    positions: Optional[dict] = None,
    confirms: Optional[dict[str, dict]] = None,
    encryption_key: bool = False,
) -> FixtureTransport:
    transport = FixtureTransport()
    transport.register("POST", PATH_SESSION, lambda _c: session_resp or session_response())
    transport.register_json("DELETE", PATH_SESSION, {})
    transport.register_json("GET", PATH_PING, {"status": "OK"})
    if encryption_key:
        transport.register_json(
            "GET", PATH_ENCRYPTION_KEY, {"encryptionKey": "AAAA", "timeStamp": 1756000000000}
        )
    else:
        transport.register_json("GET", PATH_ENCRYPTION_KEY, {}, status=404)

    transport.register_json("GET", PATH_ACCOUNTS, accounts if accounts is not None else accounts_body())
    transport.register_json(
        "GET", PATH_ACCOUNT_PREFERENCES, preferences if preferences is not None else preferences_body()
    )
    for epic, body in (markets or {"EURUSD": eurusd_market_body()}).items():
        transport.register_json("GET", market_path(epic), body)
        transport.register_json("GET", prices_path(epic), prices if prices is not None else prices_body())
    transport.register_json(
        "GET", PATH_POSITIONS, positions if positions is not None else positions_body()
    )
    transport.register_json("GET", PATH_WORKING_ORDERS, {"workingOrders": []})
    for reference, body in (confirms or {}).items():
        transport.register_json("GET", confirm_path(reference), body)
    return transport


class FakeClock:
    """
    ساعة قابلة للتحكم: النوم يقدّمها بدل الانتظار الحقيقي،
    فتُختبر حدود الطلبات بلا إبطاء المجموعة.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build_session(
    transport: Optional[FixtureTransport] = None,
    *,
    environment: CapitalEnvironment = CapitalEnvironment.DEMO,
    lock: Optional[ExecutionLock] = None,
) -> tuple[CapitalSession, GuardedTransport, FixtureTransport]:
    fixture = transport or build_transport()
    clock = FakeClock()
    guarded = GuardedTransport(
        inner=fixture,
        execution_lock=lock or ExecutionLock.locked(),
        rate_limiter=RateLimiter(clock=clock, sleeper=clock.sleep),
    )
    session = CapitalSession(
        transport=guarded,
        secrets=secrets(),
        environment=environment,
        use_encrypted_password=False,
    )
    return session, guarded, fixture


def build_adapter(transport: Optional[FixtureTransport] = None, **kwargs):
    from app.brokers.capital.adapter import CapitalComAdapter

    session, guarded, fixture = build_session(transport)
    adapter = CapitalComAdapter(session=session, execution_lock=ExecutionLock.locked(), **kwargs)
    return adapter, guarded, fixture
