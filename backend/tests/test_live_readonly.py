"""
اختبارات الاكتشاف الحقيقي — قراءة فقط.

**اعتمادات وهمية · استجابات مُقلَّدة · لا شبكة · لا Keychain.**
كل قيمة هنا مكتوبة صراحةً في هذا الملف ولا معنى لها خارجه.
"""
from __future__ import annotations

import ast
import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.live_readonly.allowlist import (
    ALLOWED_GET_EXACT,
    ALLOWED_POST_EXACT,
    BLOCKED_SUBSTRINGS,
    LIVE_BASE_URL,
    LIVE_HOST,
    UNCONDITIONALLY_BLOCKED_METHODS,
    AllowlistViolation,
    assert_allowed,
    describe_allowlist,
    normalize,
)
from app.live_readonly.discovery import (
    DISCOVERY_EPICS,
    EXECUTION_EPICS,
    mask_account_id,
    run_live_discovery,
)
from app.live_readonly.market_data import (
    RESOLUTION_BY_TIMEFRAME,
    LiveReadOnlyMarketDataProvider,
)
from app.live_readonly.report import (
    FORBIDDEN_JSON_KEYS,
    PLANNED_CAPITAL_USD,
    SanitisationError,
    compute_feasibility,
    render_discovery_markdown,
    render_actual_feasibility_markdown,
    render_public_feasibility_markdown,
    write_discovery_json,
)
from app.live_readonly.session import (
    LiveAuthAlreadyAttempted,
    LiveAuthError,
    LiveSession,
)
from app.live_readonly.transport import LiveResponse, LiveTimeout, LiveTransportError
from app.money import D
from app.secretstore.provider import InMemorySecretProvider
from app.secretstore.redaction import REGISTRY
from app.intelligence.snapshot import Timeframe

# اعتمادات وهمية.
FAKE_API_KEY = "dummy-live-key-QQQQ0001"
FAKE_IDENTIFIER = "dummy.live@example.invalid"
FAKE_PASSWORD = "dummy-live-password-QQQQ0001"
FAKE_CST = "dummy-live-cst-QQQQ"
FAKE_TOKEN = "dummy-live-token-QQQQ"
FAKE_ACCOUNT_ID = "9988776655"


@pytest.fixture(autouse=True)
def _clean_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


def secrets() -> InMemorySecretProvider:
    return InMemorySecretProvider({
        "CAPITAL_API_KEY": FAKE_API_KEY,
        "CAPITAL_IDENTIFIER": FAKE_IDENTIFIER,
        "CAPITAL_API_PASSWORD": FAKE_PASSWORD,
    })


def rsa_key_b64() -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


# ---------------------------------------------------------------------------
# ناقل مُقلَّد يفرض القائمة البيضاء نفسها
# ---------------------------------------------------------------------------

class MockLiveTransport:
    """
    يستدعي `assert_allowed()` تماماً كالناقل الحقيقي، ثم يرد من جدول.
    **لا شبكة.**
    """

    def __init__(self, routes: dict | None = None, *, max_session_posts: int = 1) -> None:
        self.routes = routes or {}
        self.sent: list[tuple[str, str]] = []
        self.raw: list[dict] = []
        self.max_session_posts = max_session_posts
        self._session_posts = 0
        self.raise_timeout_on: set[str] = set()

    @property
    def name(self) -> str:
        return "mock-live"

    @property
    def session_posts(self) -> int:
        return self._session_posts

    def send(self, method, url, *, headers=None, params=None, json=None, timeout=None):
        target = assert_allowed(method, url)
        if target.method == "POST" and target.path in ALLOWED_POST_EXACT:
            if self._session_posts >= self.max_session_posts:
                raise AllowlistViolation("استُهلكت محاولة المصادقة الوحيدة.")
            self._session_posts += 1
        self.sent.append(target.operation)
        self.raw.append({"method": target.method, "url": url,
                         "headers": dict(headers or {}), "json": dict(json or {})})
        if target.path in self.raise_timeout_on:
            raise LiveTimeout("مهلة اتصال (ReadTimeout).")
        handler = self.routes.get(target.operation)
        if handler is None:
            return LiveResponse(404, {}, {"errorCode": "error.not.found"})
        return handler() if callable(handler) else handler


def account_body() -> dict:
    return {"accounts": [{
        "accountId": FAKE_ACCOUNT_ID, "accountName": "Main", "preferred": True,
        "accountType": "CFD", "currency": "USD", "status": "ENABLED",
        "balance": {"balance": 212.34, "available": 210.00, "profitLoss": -2.34,
                    "deposit": 200.0},
    }]}


def prefs_body() -> dict:
    return {"hedgingMode": False, "leverages": {
        "CURRENCIES": {"current": 30, "max": 30},
        "COMMODITIES": {"current": 20, "max": 20},
    }}


def market_body(epic="EURUSD", bid=1.08540, offer=1.08546) -> dict:
    return {
        "instrument": {
            "epic": epic, "name": epic, "marginFactor": 3.34,
            "marginFactorUnit": "PERCENTAGE", "onePipMeans": "0.0001",
            "contractSize": 1, "unit": "AMOUNT", "type": "CURRENCIES",
            "guaranteedStopAllowed": True, "guaranteedStopPremium": 0.0002,
            "overnightFee": {"longRate": -0.0000411, "shortRate": 0.0000123,
                             "swapChargeTimestamp": "22:00"},
            "openingHours": {"mon": ["00:00-23:59"], "tue": ["00:00-23:59"]},
        },
        "snapshot": {
            "marketStatus": "TRADEABLE", "bid": bid, "offer": offer,
            "updateTime": datetime.now(timezone.utc).isoformat(),
        },
        "dealingRules": {
            "minDealSize": {"unit": "AMOUNT", "value": 100},
            "minSizeIncrement": {"unit": "AMOUNT", "value": 1},
            "minNormalStopOrLimitDistance": {"unit": "POINTS", "value": 10},
            "minControlledRiskStopDistance": {"unit": "POINTS", "value": 30},
        },
    }


def prices_body(count=10) -> dict:
    rows = []
    for i in range(count):
        rows.append({
            "snapshotTimeUTC": f"2026-08-{10 + i:02d}T00:00:00",
            "openPrice": {"bid": 1.0850, "ask": 1.0851},
            "highPrice": {"bid": 1.0870, "ask": 1.0871},
            "lowPrice": {"bid": 1.0840, "ask": 1.0841},
            "closePrice": {"bid": 1.0860, "ask": 1.0861},
            "lastTradedVolume": 1000,
        })
    return {"prices": rows}


def ok_session_response() -> LiveResponse:
    return LiveResponse(200, {"CST": FAKE_CST, "X-SECURITY-TOKEN": FAKE_TOKEN},
                        {"accountType": "CFD", "currencyIsoCode": "USD"})


def full_routes(key_b64: str) -> dict:
    routes = {
        ("GET", "/api/v1/session/encryptionKey"):
            LiveResponse(200, {}, {"encryptionKey": key_b64, "timeStamp": 1700000000000}),
        ("POST", "/api/v1/session"): ok_session_response,
        ("GET", "/api/v1/accounts"): LiveResponse(200, {}, account_body()),
        ("GET", "/api/v1/accounts/preferences"): LiveResponse(200, {}, prefs_body()),
    }
    for epic in DISCOVERY_EPICS:
        routes[("GET", f"/api/v1/markets/{epic}")] = LiveResponse(200, {}, market_body(epic))
        routes[("GET", f"/api/v1/prices/{epic}")] = LiveResponse(200, {}, prices_body())
    return routes


def authenticated_session(routes=None, **kw):
    key = rsa_key_b64()
    transport = MockLiveTransport(routes or full_routes(key), **kw)
    session = LiveSession(transport=transport, secrets=secrets())
    session.authenticate()
    return session, transport


# ---------------------------------------------------------------------------
# 1. الإقرار الصريح
# ---------------------------------------------------------------------------

def test_command_refuses_without_explicit_acknowledgement(capsys):
    from app.cli import build_parser, cmd_capital_live_discover

    args = build_parser().parse_args(["capital-live-discover"])
    assert args.acknowledge_live_read_only is False
    assert cmd_capital_live_discover(args) == 2
    err = capsys.readouterr().err
    assert "إقرار صريح" in err


def test_acknowledgement_text_states_the_four_required_facts():
    from app.cli import LIVE_ACKNOWLEDGEMENT_AR as text

    assert "الحقيقي" in text
    assert "صلاحية التداول" in text
    assert "قائمة بيضاء" in text
    assert "لا إذن" in text


def test_demo_command_still_rejects_live():
    from app.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["capital-discover", "--environment", "live"])


# ---------------------------------------------------------------------------
# 2. القائمة البيضاء — الطرق
# ---------------------------------------------------------------------------

def test_get_allowlist_accepts_exactly_the_declared_paths():
    for path in ALLOWED_GET_EXACT:
        assert assert_allowed("GET", f"{LIVE_BASE_URL}{path}")


@pytest.mark.parametrize("epic", ["EURUSD", "GBPUSD", "USDJPY", "GOLD"])
def test_market_and_price_patterns_accept_discovery_epics(epic):
    assert assert_allowed("GET", f"{LIVE_BASE_URL}/api/v1/markets/{epic}")
    assert assert_allowed("GET", f"{LIVE_BASE_URL}/api/v1/prices/{epic}")


def test_session_post_is_the_only_allowed_post():
    assert assert_allowed("POST", f"{LIVE_BASE_URL}/api/v1/session")
    for path in ("/api/v1/accounts", "/api/v1/markets/EURUSD", "/api/v1/marketnavigation"):
        with pytest.raises(AllowlistViolation):
            assert_allowed("POST", f"{LIVE_BASE_URL}{path}")


@pytest.mark.parametrize("method", sorted(UNCONDITIONALLY_BLOCKED_METHODS))
def test_blocked_methods_are_rejected_even_on_allowed_paths(method):
    for path in ("/api/v1/accounts", "/api/v1/session", "/api/v1/markets/EURUSD"):
        with pytest.raises(AllowlistViolation) as exc:
            assert_allowed(method, f"{LIVE_BASE_URL}{path}")
        assert method in str(exc.value) or "مرفوضة" in str(exc.value)


def test_put_patch_delete_are_rejected_unconditionally():
    for method in ("PUT", "PATCH", "DELETE"):
        assert method in UNCONDITIONALLY_BLOCKED_METHODS
        with pytest.raises(AllowlistViolation):
            assert_allowed(method, f"{LIVE_BASE_URL}/api/v1/accounts/preferences")


# ---------------------------------------------------------------------------
# 3. القائمة السوداء والالتفاف
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/v1/positions",
    "/api/v1/positions/otc",
    "/api/v1/workingorders",
    "/api/v1/workingorders/otc",
    "/api/v1/accounts/topUp",
    "/api/v1/confirms/abc123",
    "/api/v1/session/switch",
])
def test_forbidden_paths_are_rejected(path):
    for method in ("GET", "POST", "PUT", "DELETE"):
        with pytest.raises(AllowlistViolation):
            assert_allowed(method, f"{LIVE_BASE_URL}{path}")


@pytest.mark.parametrize("path", [
    "/api/v1/%70ositions",                    # ترميز مئوي
    "/api/v1/%2570ositions",                  # ترميز مزدوج
    "/api/v1/markets/../positions",           # مقاطع نسبية
    "/api/v1/markets/%2e%2e/positions",       # مقاطع نسبية مُرمَّزة
    "/api/v1//positions",                     # شرطات مكرّرة
    "/api/v1/positions/",                     # شرطة ذيلية
    "/api/v1/POSITIONS",                      # حالة الأحرف
    "/api/v1\\positions",                     # شرطة خلفية
    "/api/v1/./positions",
])
def test_encoded_and_traversal_bypasses_are_rejected(path):
    with pytest.raises(AllowlistViolation):
        assert_allowed("GET", f"{LIVE_BASE_URL}{path}")


def test_query_string_cannot_smuggle_a_forbidden_action():
    with pytest.raises(AllowlistViolation):
        assert_allowed("GET", f"{LIVE_BASE_URL}/api/v1/markets?searchTerm=positions")
    with pytest.raises(AllowlistViolation):
        assert_allowed("GET", f"{LIVE_BASE_URL}/api/v1/accounts?action=topUp")


def test_unknown_query_parameters_are_rejected():
    with pytest.raises(AllowlistViolation):
        assert_allowed("GET", f"{LIVE_BASE_URL}/api/v1/accounts?whatever=1")
    assert assert_allowed(
        "GET", f"{LIVE_BASE_URL}/api/v1/prices/EURUSD?resolution=DAY&max=10"
    )


def test_trailing_slash_is_normalised_not_treated_as_a_new_path():
    with_slash = normalize("GET", f"{LIVE_BASE_URL}/api/v1/accounts/")
    without = normalize("GET", f"{LIVE_BASE_URL}/api/v1/accounts")
    assert with_slash.path == without.path == "/api/v1/accounts"


def test_query_string_is_stripped_before_path_comparison():
    target = normalize("GET", f"{LIVE_BASE_URL}/api/v1/accounts?pageSize=5")
    assert target.path == "/api/v1/accounts"
    assert target.query_params == ("pageSize",)


def test_only_the_live_host_over_https_is_accepted():
    with pytest.raises(AllowlistViolation):
        assert_allowed("GET", "https://demo-api-capital.backend-capital.com/api/v1/accounts")
    with pytest.raises(AllowlistViolation):
        assert_allowed("GET", f"http://{LIVE_HOST}/api/v1/accounts")
    with pytest.raises(AllowlistViolation):
        assert_allowed("GET", "https://evil.example.com/api/v1/accounts")


def test_no_allowed_path_contains_a_blocked_substring():
    """يمنع أن يُبطل توسيعُ القائمة البيضاء القائمةَ السوداء بالخطأ."""
    allowed = list(ALLOWED_GET_EXACT) + list(ALLOWED_POST_EXACT)
    for path in allowed:
        for needle in BLOCKED_SUBSTRINGS:
            assert needle not in path.lower(), f"{path} يحتوي {needle}"


def test_control_characters_and_absurd_paths_are_rejected():
    for bad in ["/api/v1/accounts\n", "/api/v1/accounts%00", "/api/v1/" + "a" * 600]:
        with pytest.raises(AllowlistViolation):
            assert_allowed("GET", f"{LIVE_BASE_URL}{bad}")


# ---------------------------------------------------------------------------
# 4. الجلسة
# ---------------------------------------------------------------------------

def test_single_authentication_attempt_only():
    session, transport = authenticated_session()
    assert transport.session_posts == 1
    with pytest.raises(LiveAuthAlreadyAttempted):
        session.authenticate()
    assert transport.session_posts == 1


def test_authentication_is_encrypted_only():
    session, transport = authenticated_session()
    payloads = [c["json"] for c in transport.raw if c["json"]]
    assert payloads
    for p in payloads:
        assert p.get("encryptedPassword") is True
        assert p.get("password") != FAKE_PASSWORD      # لم تُرسل كما هي


def test_no_plaintext_fallback_when_encryption_key_is_unavailable():
    routes = {("GET", "/api/v1/session/encryptionKey"): LiveResponse(500, {}, {})}
    transport = MockLiveTransport(routes)
    session = LiveSession(transport=transport, secrets=secrets())
    with pytest.raises(LiveAuthError):
        session.authenticate()
    # لم تُرسل أي محاولة مصادقة أصلاً
    assert transport.session_posts == 0
    assert ("POST", "/api/v1/session") not in transport.sent


def test_401_stops_without_any_retry():
    key = rsa_key_b64()
    routes = full_routes(key)
    routes[("POST", "/api/v1/session")] = LiveResponse(
        401, {}, {"errorCode": "error.invalid.details"}
    )
    transport = MockLiveTransport(routes)
    session = LiveSession(transport=transport, secrets=secrets())
    with pytest.raises(LiveAuthError) as exc:
        session.authenticate()
    assert "401" in str(exc.value)
    assert transport.session_posts == 1
    assert session.authenticated is False


def test_network_timeout_during_authentication_is_reported_not_retried():
    key = rsa_key_b64()
    transport = MockLiveTransport(full_routes(key))
    transport.raise_timeout_on = {"/api/v1/session"}
    session = LiveSession(transport=transport, secrets=secrets())
    with pytest.raises(LiveAuthError):
        session.authenticate()
    assert transport.session_posts == 1


def test_session_never_falls_back_to_demo():
    import app.live_readonly.session as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "demo-api-capital" not in source
    for _, url_call in [(c["method"], c["url"]) for c in
                        authenticated_session()[1].raw]:
        assert url_call.startswith(LIVE_BASE_URL)


def test_tokens_are_discarded_and_never_persisted():
    session, _ = authenticated_session()
    assert session.tokens_retained is True
    session.discard()
    assert session.tokens_retained is False
    assert FAKE_CST not in REGISTRY.known_values()
    assert FAKE_TOKEN not in REGISTRY.known_values()


def test_session_repr_never_exposes_tokens():
    session, _ = authenticated_session()
    assert FAKE_CST not in repr(session)
    assert FAKE_TOKEN not in repr(session)
    assert "REDACTED" in repr(session)


def test_delete_session_is_impossible_by_design():
    """`discard()` لا يستدعي DELETE لأن DELETE مرفوضة دائماً بأمر المالكة."""
    session, transport = authenticated_session()
    session.discard()
    assert ("DELETE", "/api/v1/session") not in transport.sent


# ---------------------------------------------------------------------------
# 5. عزل الاستيراد (AST)
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORT_FRAGMENTS = (
    "execution", "order", "killswitch", "commissioning", "scheduler",
    "adapter", "pipeline.runner",
)


def _imports_of(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
            found.update(a.name for a in node.names)
    return found


@pytest.mark.parametrize("module_name", [
    "app.live_readonly.allowlist",
    "app.live_readonly.transport",
    "app.live_readonly.session",
    "app.live_readonly.discovery",
    "app.live_readonly.report",
    "app.live_readonly.market_data",
])
def test_live_readonly_modules_import_nothing_that_can_mutate(module_name):
    import importlib

    module = importlib.import_module(module_name)
    for name in _imports_of(module):
        lowered = name.lower()
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            assert fragment not in lowered, f"{module_name} يستورد {name}"


def test_live_readonly_package_defines_no_mutating_method():
    import importlib

    forbidden = ("place_order", "close_position", "update_position", "submit",
                 "create_order", "top_up", "set_leverage", "update_preferences")
    for module_name in (
        "app.live_readonly.session", "app.live_readonly.discovery",
        "app.live_readonly.transport", "app.live_readonly.market_data",
    ):
        source = Path(importlib.import_module(module_name).__file__).read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for bad in forbidden:
            assert bad not in names


def test_shadow_mode_still_cannot_import_execution():
    import app.strategies.shadow as shadow

    for name in _imports_of(shadow):
        assert "execution" not in name.lower()
        assert "adapter" not in name.lower()


# ---------------------------------------------------------------------------
# 6. الاكتشاف
# ---------------------------------------------------------------------------

def test_discovery_reads_account_and_all_instruments():
    session, transport = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    assert report.account is not None
    assert report.account.currency == "USD"
    assert report.account.balance == D("212.34")
    assert report.account.hedging_mode is False
    assert report.account.dealing_enabled is True
    assert len(report.instruments) == len(DISCOVERY_EPICS)
    assert all(i.found for i in report.instruments)


def test_discovery_extracts_every_required_instrument_field():
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    eurusd = report.instrument("EURUSD")
    assert eurusd is not None
    assert eurusd.market_status == "TRADEABLE"
    assert eurusd.bid is not None and eurusd.ask is not None
    assert eurusd.spread is not None
    assert eurusd.min_deal_size == D("100")
    assert eurusd.size_increment == D("1")
    assert eurusd.margin_factor == D("3.34")
    assert eurusd.min_stop_distance == D("10")
    assert eurusd.min_guaranteed_stop_distance == D("30")
    assert eurusd.guaranteed_stop_available is True
    assert eurusd.guaranteed_stop_premium == D("0.0002")
    assert eurusd.pip_definition == "0.0001"
    assert eurusd.contract_size == D("1")
    assert eurusd.overnight_fee_long is not None
    assert eurusd.candles_available is True
    assert eurusd.data_age_seconds is not None


def test_discovery_touches_no_forbidden_endpoint():
    session, transport = authenticated_session()
    run_live_discovery(session)
    session.discard()

    for method, path in transport.sent:
        assert method in ("GET", "POST")
        if method == "POST":
            assert path in ALLOWED_POST_EXACT
        for needle in BLOCKED_SUBSTRINGS:
            assert needle not in path.lower()


def test_a_single_failing_instrument_does_not_abort_discovery():
    key = rsa_key_b64()
    routes = full_routes(key)
    routes[("GET", "/api/v1/markets/GOLD")] = LiveResponse(404, {}, {})
    transport = MockLiveTransport(routes)
    session = LiveSession(transport=transport, secrets=secrets())
    session.authenticate()
    report = run_live_discovery(session)
    session.discard()

    assert report.instrument("GOLD").found is False
    assert report.instrument("EURUSD").found is True
    assert any("GOLD" in e for e in report.errors)


def test_discovery_never_authorises_execution():
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    assert report.execution_epics == EXECUTION_EPICS == ("EURUSD",)
    assert report.as_dict()["authorises_execution"] is False
    assert any("لا تأذن بالتنفيذ" in n for n in report.notes)


# ---------------------------------------------------------------------------
# 7. التنقية والإخفاء
# ---------------------------------------------------------------------------

def test_account_id_is_masked_everywhere():
    assert mask_account_id(FAKE_ACCOUNT_ID) == "****6655"
    assert mask_account_id("12") == "**"
    assert mask_account_id(None) == "****"

    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()
    assert report.account.masked_id == "****6655"
    assert FAKE_ACCOUNT_ID not in render_discovery_markdown(report)
    assert FAKE_ACCOUNT_ID not in json.dumps(report.as_dict(), ensure_ascii=False)


def test_no_secret_appears_in_any_report_output(tmp_path):
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    md = render_discovery_markdown(report)
    payload = json.dumps(report.as_dict(), ensure_ascii=False)
    for secret in (FAKE_API_KEY, FAKE_IDENTIFIER, FAKE_PASSWORD,
                   FAKE_CST, FAKE_TOKEN, FAKE_ACCOUNT_ID):
        assert secret not in md
        assert secret not in payload


def test_json_writer_refuses_a_payload_with_a_forbidden_key(tmp_path):
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    class Poisoned:
        def as_dict(self):
            data = report.as_dict()
            data["accountId"] = FAKE_ACCOUNT_ID
            return data

    with pytest.raises(SanitisationError):
        write_discovery_json(Poisoned(), tmp_path / "x.json")


def test_written_json_contains_no_forbidden_key(tmp_path):
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    path = write_discovery_json(report, tmp_path / "out.json")
    text = path.read_text(encoding="utf-8")
    for key in FORBIDDEN_JSON_KEYS:
        assert f'"{key}"' not in text


def test_markdown_marks_the_report_as_locally_sensitive():
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    md = render_discovery_markdown(report)
    assert "معلومة محلية حسّاسة" in md
    assert "لا يُرفع" in md
    assert "212.34" in md            # الرصيد مسموح في التقرير المحلي
    assert "قراءة فقط" in md


def test_discovery_json_path_is_git_ignored():
    gitignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text()
    assert "data/" in gitignore
    # التأكيد الصريح على الشجرة الخاصة — لا على `data/` وحدها.
    assert "data/private/" in gitignore


# ---------------------------------------------------------------------------
# 8. الجدوى
# ---------------------------------------------------------------------------

def test_feasibility_uses_discovered_values():
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    eurusd = report.instrument("EURUSD")
    result = compute_feasibility(eurusd, equity=D("212.34"))
    assert result is not None
    assert result["quantity"] == "100.00"
    assert Decimal(result["notional_exposure"]) > 0
    assert result["required_margin"] is not None
    assert len(result["rows"]) == 3
    assert {r["stop_pips"] for r in result["rows"]} == {25, 50, 75}
    assert set(result["profiles"]) == {
        "CAPITAL_PRESERVATION", "BALANCED", "ACTIVE_CONTROLLED"
    }


def test_feasibility_distinguishes_actual_balance_from_planned_capital():
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()
    eurusd = report.instrument("EURUSD")

    actual = compute_feasibility(eurusd, equity=D("212.34"))
    planned = compute_feasibility(eurusd, equity=PLANNED_CAPITAL_USD)
    assert actual["equity_used"] == "212.34"
    assert planned["equity_used"] == "150.00"

    # عند 212.34 و150 يبقى السقف الدولاري هو القيد (0.35% منهما أكبر من 0.50)،
    # فالحد واحد. الفرق يظهر حين تصبح النسبة هي القيد:
    assert actual["profiles"]["CAPITAL_PRESERVATION"]["max_risk_per_trade"] == "0.50"
    assert planned["profiles"]["CAPITAL_PRESERVATION"]["max_risk_per_trade"] == "0.50"

    small = compute_feasibility(eurusd, equity=D("100.00"))
    assert small["profiles"]["CAPITAL_PRESERVATION"]["max_risk_per_trade"] == "0.35"
    assert small["profiles"]["ACTIVE_CONTROLLED"]["max_risk_per_trade"] == "1.00"


def test_feasibility_returns_none_when_values_are_missing():
    from app.live_readonly.discovery import LiveInstrumentInfo

    assert compute_feasibility(
        LiveInstrumentInfo(epic="EURUSD", found=False), equity=D("150")
    ) is None


def test_feasibility_report_refuses_to_claim_profitability():
    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()
    eurusd = report.instrument("EURUSD")

    private_text = render_actual_feasibility_markdown(
        report, actual=compute_feasibility(eurusd, equity=D("212.34")),
    )
    public_text = render_public_feasibility_markdown(
        planned=compute_feasibility(eurusd, equity=PLANNED_CAPITAL_USD),
    )
    for text in (private_text, public_text):
        assert "ليست توقّع ربح" in text
        assert "الكفاية التقنية ≠ الربحية" in text
        assert "لا يأذن بالتنفيذ" in text

    # التقرير الخاص وحده يحمل الرصيد الفعلي؛ العام لا يحمله بحال.
    assert "212.34" in private_text
    assert "212.34" not in public_text
    assert "150.00" in public_text


# ---------------------------------------------------------------------------
# 9. مزوّد بيانات السوق
# ---------------------------------------------------------------------------

def test_market_data_provider_returns_candles_read_only():
    session, transport = authenticated_session()
    provider = LiveReadOnlyMarketDataProvider(session)
    assert provider.configured is True

    series = provider.candles(
        instrument="EURUSD", timeframe=Timeframe.D1, count=10,
        as_of_utc=datetime.now(timezone.utc),
    )
    assert len(series.candles) == 10
    assert series.complete is True
    assert all(c.is_structurally_valid for c in series.candles)
    session.discard()

    for method, path in transport.sent:
        assert method in ("GET", "POST")


def test_market_data_provider_maps_every_timeframe():
    for tf in Timeframe:
        assert tf in RESOLUTION_BY_TIMEFRAME


def test_market_data_provider_has_no_execution_capability():
    for forbidden in ("place_order", "submit", "execute", "close"):
        assert not hasattr(LiveReadOnlyMarketDataProvider, forbidden)


def test_market_data_provider_reports_incomplete_data_honestly():
    key = rsa_key_b64()
    routes = full_routes(key)
    routes[("GET", "/api/v1/prices/EURUSD")] = LiveResponse(200, {}, prices_body(3))
    transport = MockLiveTransport(routes)
    session = LiveSession(transport=transport, secrets=secrets())
    session.authenticate()

    provider = LiveReadOnlyMarketDataProvider(session)
    series = provider.candles(
        instrument="EURUSD", timeframe=Timeframe.D1, count=10,
        as_of_utc=datetime.now(timezone.utc),
    )
    assert series.complete is False
    assert "أقل من المطلوب" in series.note_ar
    session.discard()


# ---------------------------------------------------------------------------
# 10. وصف القائمة
# ---------------------------------------------------------------------------

def test_allowlist_description_is_printable_and_complete():
    described = describe_allowlist()
    assert described["host"] == LIVE_HOST
    assert "/api/v1/session" in described["post_exact"]
    assert "PUT" in described["blocked_methods"]
    assert "DELETE" in described["blocked_methods"]
    assert "position" in described["blocked_substrings"]
