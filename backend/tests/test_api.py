from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import KILL_PHRASE, RESET_PHRASE, app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("BROKER_MODE", "MOCK")
    monkeypatch.setenv("LIVE_TRADING", "false")
    import app.config as config
    import app.db.session as dbs
    import app.main as main

    config.get_settings.cache_clear()
    dbs.ENGINE = dbs.make_engine(f"sqlite:///{tmp_path/'t.db'}")
    dbs.SessionLocal.configure(bind=dbs.ENGINE)
    main._SYSTEM = None
    with TestClient(app) as c:
        yield c
    main._SYSTEM = None
    config.get_settings.cache_clear()


def test_health_reports_mock_broker_and_live_off(client):
    r = client.get("/api/health").json()
    assert r["broker_name"] == "MOCK"
    assert r["broker_is_live"] is False
    assert r["audit_chain_ok"] is True


def test_today_shows_riyadh_12_hour_times(client):
    r = client.get("/api/today").json()
    assert r["live_trading_enabled"] is False
    assert ("ص" in r["now_riyadh"]) or ("م" in r["now_riyadh"])
    assert r["limits"]["total"] == "7.50"
    assert r["limits"]["daily"] == "1.50"
    assert r["limits"]["weekly"] == "4.50"
    assert r["limits"]["target_risk_per_trade"] == "0.38"
    assert r["limits"]["max_risk_per_trade"] == "0.75"
    assert r["equity"]["baseline"] == "150.00"
    assert r["risk_mode"] == "VALIDATION"


def test_risk_mode_defaults_to_validation_and_is_not_changeable_from_ui(client):
    r = client.get("/api/settings").json()
    assert r["risk_mode"] == "VALIDATION"
    assert r["risk_mode_changeable_from_ui"] is False
    assert r["baseline_equity_usd"] == "150.00"


def test_all_four_modes_are_published_with_their_limits(client):
    r = client.get("/api/risk").json()
    modes = r["modes"]
    assert set(modes) == {
        "VALIDATION", "LIVE_COMMISSIONING", "CONSERVATIVE_LIVE", "LOCKED_REVIEW"
    }
    assert modes["CONSERVATIVE_LIVE"]["max_risk_pct"] == "1.00"
    assert modes["CONSERVATIVE_LIVE"]["weekly_loss_pct"] == "2.00"
    assert modes["LIVE_COMMISSIONING"]["max_lifetime_entry_orders"] == 1
    assert modes["LIVE_COMMISSIONING"]["requires_per_order_approval"] is True
    assert modes["LIVE_COMMISSIONING"]["enforce_economic_viability"] is False
    assert r["economic_guards_enforced"] is True


def test_risk_constitution_is_not_editable_from_the_api(client):
    r = client.get("/api/risk").json()
    assert r["editable_from_ui"] is False
    assert r["constitution_fingerprint"]
    # لا يوجد أي endpoint للكتابة على الحدود
    routes = {route.path for route in app.routes}
    assert not any("limits" in p and p != "/api/risk" for p in routes)


def test_kill_switch_requires_exact_phrase(client):
    bad = client.post("/api/risk/kill-switch",
                      json={"reason_ar": "سبب كافٍ للمراجعة", "confirm_phrase": "أوقف"})
    assert bad.status_code == 400
    good = client.post("/api/risk/kill-switch",
                       json={"reason_ar": "أوقف مؤقتاً لمراجعة الإعدادات", "confirm_phrase": KILL_PHRASE})
    assert good.status_code == 200 and good.json()["active"] is True


def test_reset_requires_acknowledgement_and_phrase(client):
    client.post("/api/risk/kill-switch",
                json={"reason_ar": "إيقاف للاختبار الآن", "confirm_phrase": KILL_PHRASE})
    r1 = client.post("/api/risk/kill-switch/reset", json={
        "approved_by": "Maather", "reason_ar": "راجعت السبب بالكامل",
        "confirm_phrase": RESET_PHRASE, "acknowledged_review": False,
    })
    assert r1.status_code == 400
    r2 = client.post("/api/risk/kill-switch/reset", json={
        "approved_by": "Maather", "reason_ar": "راجعت السبب بالكامل",
        "confirm_phrase": "خطأ", "acknowledged_review": True,
    })
    assert r2.status_code == 400
    r3 = client.post("/api/risk/kill-switch/reset", json={
        "approved_by": "Maather", "reason_ar": "راجعت السبب بالكامل وأعتمد الاستئناف",
        "confirm_phrase": RESET_PHRASE, "acknowledged_review": True,
    })
    assert r3.status_code == 200 and r3.json()["active"] is False


def test_strategies_endpoint_shows_no_approved_strategy(client):
    r = client.get("/api/strategies").json()
    assert r["active_count"] == 0
    assert r["strategies"][0]["state"] == "RESEARCH"


def test_opportunities_never_render_a_buy_call(client):
    r = client.get("/api/opportunities").json()
    for row in r["allowlist"]:
        assert "status_ar" in row and "rationale_ar" in row
        assert "اشترِ" not in row["status_ar"]
    assert any(d["symbol"] == "XAUUSD" for d in r["denylist"])


def test_audit_endpoint_verifies_chain(client):
    r = client.get("/api/audit").json()
    assert r["chain_ok"] is True
    assert r["checked"] >= 1


def test_settings_endpoint_marks_constitution_read_only(client):
    r = client.get("/api/settings").json()
    assert r["risk_constitution_editable"] is False
    assert r["mode"] == "PAPER/MOCK"
