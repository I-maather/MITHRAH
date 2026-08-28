"""المصادقة والجلسة والحسابات — بلا أي اتصال شبكي."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.brokers.capital.endpoints import (
    DEMO_BASE_URL,
    LIVE_BASE_URL,
    PATH_SESSION,
    CapitalEnvironment,
    is_live_url,
)
from app.brokers.capital.errors import (
    CapitalAuthError,
    CapitalAuthLockout,
    CapitalMalformedResponse,
)
from app.brokers.capital.safety import LIVE_API_ENABLED, LiveApiBlocked, assert_url_allowed
from app.brokers.capital.session import MAX_AUTH_FAILURES, SESSION_TTL, CapitalSession
from app.brokers.capital.transport import ApiResponse
from app.clock import now_utc
from app.secretstore.redaction import MASK, REGISTRY, redact, redact_headers
from tests.capital_fixtures import (
    ACCOUNT_ID,
    FAKE_CST,
    FAKE_XST,
    MASKED_ACCOUNT,
    accounts_body,
    build_adapter,
    build_session,
    build_transport,
    preferences_body,
    session_response,
)


# --- المصادقة ---------------------------------------------------------------

def test_successful_demo_session_captures_tokens_in_memory_only():
    session, _guarded, _fixture = build_session()
    tokens = session.login()
    assert tokens.cst == FAKE_CST
    assert tokens.security_token == FAKE_XST
    assert session.state_for_report()["tokens_persisted"] is False


def test_session_headers_include_all_three_required_headers():
    session, _g, _f = build_session()
    session.login()
    headers = session.auth_headers()
    assert set(headers) >= {"X-CAP-API-KEY", "CST", "X-SECURITY-TOKEN"}


def test_invalid_api_key_is_rejected_without_revealing_anything():
    transport = build_transport()
    transport.register("POST", PATH_SESSION, lambda _c: ApiResponse(401, {}, {"errorCode": "error.invalid.details"}))
    session, _g, _f = build_session(transport)
    with pytest.raises(CapitalAuthError) as exc:
        session.login()
    message = str(exc.value)
    assert "fixture-api-key" not in message
    assert "fixture-api-password" not in message


def test_invalid_api_custom_password_is_rejected():
    transport = build_transport()
    transport.register("POST", PATH_SESSION, lambda _c: ApiResponse(403, {}, {}))
    session, _g, _f = build_session(transport)
    with pytest.raises(CapitalAuthError):
        session.login()


def test_session_without_tokens_in_headers_is_malformed():
    transport = build_transport()
    transport.register("POST", PATH_SESSION, lambda _c: ApiResponse(200, {}, {"accountType": "CFD"}))
    session, _g, _f = build_session(transport)
    with pytest.raises(CapitalMalformedResponse):
        session.login()


def test_repeated_authentication_failure_locks_out_and_stops_trying():
    transport = build_transport()
    transport.register("POST", PATH_SESSION, lambda _c: ApiResponse(401, {}, {}))
    session, _g, fixture = build_session(transport)
    for _ in range(MAX_AUTH_FAILURES):
        with pytest.raises(CapitalAuthError):
            session.login()
    assert session.is_locked_out
    calls_before = len(fixture.calls)
    with pytest.raises(CapitalAuthLockout):
        session.login()
    assert len(fixture.calls) == calls_before, "لا يجوز إرسال طلب جديد بعد الإقفال"


def test_expired_session_is_detected():
    session, _g, _f = build_session()
    tokens = session.login()
    assert not tokens.is_expired(now_utc())
    assert tokens.is_expired(now_utc() + SESSION_TTL + timedelta(seconds=1))


def test_session_renews_before_expiry_margin():
    session, _g, fixture = build_session()
    session.login()
    logins_before = sum(1 for c in fixture.calls if c["method"] == "POST")
    session.tokens.last_used_utc = now_utc() - timedelta(minutes=9)
    session.ensure_session()
    logins_after = sum(1 for c in fixture.calls if c["method"] == "POST")
    assert logins_after == logins_before + 1


def test_ping_keeps_session_alive_and_clears_on_401():
    session, _g, transport_fixture = build_session()
    session.login()
    assert session.ping() is True
    transport_fixture.register("GET", "/api/v1/ping", lambda _c: ApiResponse(401, {}, {}))
    assert session.ping() is False
    assert session.tokens is None


def test_logout_forgets_tokens_from_the_redaction_registry():
    session, _g, _f = build_session()
    session.login()
    assert FAKE_CST in REGISTRY.known_values()
    session.logout()
    assert session.tokens is None
    assert FAKE_CST not in REGISTRY.known_values()


# --- حجب الرموز -------------------------------------------------------------

def test_cst_is_redacted_everywhere():
    session, _g, _f = build_session()
    session.login()
    assert MASK in redact(f"CST={FAKE_CST}")
    assert FAKE_CST not in redact(f"the token is {FAKE_CST} ok")
    assert redact_headers({"CST": FAKE_CST})["CST"] == MASK


def test_security_token_is_redacted_everywhere():
    session, _g, _f = build_session()
    session.login()
    assert FAKE_XST not in redact({"X-SECURITY-TOKEN": FAKE_XST})["X-SECURITY-TOKEN"]
    assert FAKE_XST not in redact(f"header X-SECURITY-TOKEN: {FAKE_XST}")


def test_tokens_never_appear_in_session_repr():
    session, _g, _f = build_session()
    tokens = session.login()
    assert FAKE_CST not in repr(tokens)
    assert FAKE_XST not in str(tokens)
    assert "REDACTED" in repr(tokens)


# --- رفض العنوان الحقيقي -----------------------------------------------------

def test_live_api_is_locked_in_source():
    assert LIVE_API_ENABLED is False


def test_live_url_is_recognised_and_rejected():
    assert is_live_url(LIVE_BASE_URL) is True
    assert is_live_url(DEMO_BASE_URL) is False
    with pytest.raises(LiveApiBlocked):
        assert_url_allowed(LIVE_BASE_URL + "/api/v1/session")


def test_unknown_host_is_treated_as_live_and_blocked():
    with pytest.raises(LiveApiBlocked):
        assert_url_allowed("https://evil.example.com/api/v1/positions")


def test_live_environment_session_cannot_be_constructed():
    from app.brokers.capital.transport import FixtureTransport

    with pytest.raises(LiveApiBlocked):
        CapitalSession(
            transport=FixtureTransport(),
            secrets=None,
            environment=CapitalEnvironment.LIVE,
        )


# --- الحسابات ---------------------------------------------------------------

def test_account_list_and_masking():
    adapter, _g, _f = build_adapter()
    adapter.connect()
    accounts = adapter.list_accounts()
    assert len(accounts) == 1
    assert accounts[0].account_id == ACCOUNT_ID
    assert accounts[0].masked_id == MASKED_ACCOUNT
    assert ACCOUNT_ID not in str(adapter.get_accounts())


def test_explicit_account_selection_by_masked_id():
    adapter, _g, _f = build_adapter()
    adapter.connect()
    account = adapter.select_account(MASKED_ACCOUNT)
    assert account.account_id == ACCOUNT_ID


def test_ambiguous_account_selection_is_refused_not_guessed():
    from app.brokers.base import BrokerRejected

    body = accounts_body()
    second = dict(body["accounts"][0])
    second["accountId"] = "9999999999999999"
    second["preferred"] = False
    body["accounts"][0]["preferred"] = False
    body["accounts"].append(second)
    adapter, _g, _f = build_adapter(build_transport(accounts=body))
    adapter.connect()
    with pytest.raises(BrokerRejected, match="صريحاً"):
        adapter.select_account()


def test_account_currency_and_balances_are_reported():
    adapter, _g, _f = build_adapter()
    adapter.connect()
    account = adapter.select_account()
    balances = adapter.get_balances(account.account_id)
    assert account.currency == "USD"
    assert balances.account_id == MASKED_ACCOUNT
    assert balances.available_for_new_trade > 0


def test_insufficient_available_funds_is_visible():
    adapter, _g, _f = build_adapter(build_transport(accounts=accounts_body(available=0.0)))
    adapter.connect()
    adapter.select_account()
    balances = adapter.get_balances("x")
    assert balances.available_for_new_trade == 0


def test_preferences_are_read_only_and_expose_hedging_mode():
    adapter, _g, _f = build_adapter(build_transport(preferences=preferences_body(hedging=True)))
    adapter.connect()
    preferences = adapter.get_preferences()
    assert preferences.hedging_mode is True
    assert preferences.leverage_for("CURRENCIES") is not None


def test_updating_preferences_is_blocked():
    from app.brokers.capital.safety import ExecutionLocked

    adapter, _g, _f = build_adapter()
    adapter.connect()
    with pytest.raises(ExecutionLocked):
        adapter.update_preferences(hedgingMode=True)


def test_demo_topup_is_blocked():
    from app.brokers.capital.safety import ExecutionLocked
    from app.money import D

    adapter, _g, _f = build_adapter()
    adapter.connect()
    with pytest.raises(ExecutionLocked):
        adapter.top_up_demo(D("1000"))
