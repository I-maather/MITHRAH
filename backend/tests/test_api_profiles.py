"""
اختبارات واجهة برمجة الملفات والاستخبارات.

الغرض المزدوج: أن تعمل الواجهة، وأن **لا** تفتح أي منها مساراً للتنفيذ.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.profiles import (
    GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD,
    NEVER_WEAKENED_BY_PROFILE,
    PROFILE_UPGRADE_COOLING_HOURS,
    TradingProfile,
)

client = TestClient(app)


def test_profiles_endpoint_publishes_all_three_profiles():
    data = client.get("/api/profiles").json()
    names = {p["profile"] for p in data["available_profiles"]}
    assert names == {"CAPITAL_PRESERVATION", "BALANCED", "ACTIVE_CONTROLLED"}


def test_profiles_endpoint_shows_selected_effective_pending_and_cooling():
    data = client.get("/api/profiles").json()
    for key in (
        "selected_profile", "effective_profile", "pending_profile",
        "cooling_remaining_seconds", "cooling_remaining_ar",
        "change_blocked_reason", "change_blocked_reason_ar",
    ):
        assert key in data


def test_profiles_are_ordered_from_least_to_most_risk():
    data = client.get("/api/profiles").json()
    ranks = [p["risk_rank"] for p in data["available_profiles"]]
    assert ranks == sorted(ranks)


def test_global_loss_constitution_is_published_and_identical_for_all():
    data = client.get("/api/profiles").json()
    g = data["global_loss_constitution"]
    assert g["absolute_loss_boundary"] == f"{GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD:.2f}"
    assert g["operational_drawdown_stop"] == "6.50"
    assert g["gap_slippage_reserve"] == "1.00"
    assert g["cooling_hours"] == PROFILE_UPGRADE_COOLING_HOURS
    for p in data["available_profiles"]:
        assert p["limits"]["absolute_loss_boundary"] == "7.50"
        assert p["limits"]["operational_drawdown_stop"] == "6.50"


def test_endpoint_publishes_what_a_profile_can_never_weaken():
    data = client.get("/api/profiles").json()
    assert data["never_weakened_by_profile"] == list(NEVER_WEAKENED_BY_PROFILE)
    assert "حماية Kill Switch" in data["never_weakened_by_profile"]
    assert "متطلبات جودة البيانات" in data["never_weakened_by_profile"]


def test_exact_limits_are_published_for_every_profile():
    data = client.get("/api/profiles").json()
    by_name = {p["profile"]: p["limits"] for p in data["available_profiles"]}

    cp = by_name["CAPITAL_PRESERVATION"]
    assert cp["max_risk_per_trade"] == "0.50"
    assert cp["max_daily_loss"] == "0.75"
    assert cp["max_weekly_loss"] == "1.50"
    assert cp["min_net_reward_risk"] == "1.75"
    assert cp["min_quality_score"] == 90

    b = by_name["BALANCED"]
    assert b["max_risk_per_trade"] == "0.75"
    assert b["max_daily_loss"] == "1.50"
    assert b["max_weekly_loss"] == "3.00"
    assert b["min_quality_score"] == 85

    a = by_name["ACTIVE_CONTROLLED"]
    assert a["max_risk_per_trade"] == "1.50"
    assert a["max_daily_loss"] == "1.50"
    assert a["max_weekly_loss"] == "3.00"
    assert a["full_risk_loss_ends_day"] is True


def test_no_profile_permits_overnight_or_weekend_holding():
    data = client.get("/api/profiles").json()
    for p in data["available_profiles"]:
        assert p["limits"]["allow_overnight"] is False
        assert p["limits"]["allow_weekend_hold"] is False
        assert p["limits"]["allowed_instruments"] == ["EURUSD"]


def test_unknown_profile_is_rejected():
    r = client.post("/api/profiles/select", json={"profile": "HIGH_RISK"})
    assert r.status_code == 400


def test_upgrade_without_owner_confirmation_is_refused():
    r = client.post(
        "/api/profiles/select",
        json={"profile": "ACTIVE_CONTROLLED", "owner_confirmed": False},
    )
    body = r.json()
    assert body["accepted"] is False
    assert body["refusal"] in (
        "OWNER_CONFIRMATION_MISSING", "KILL_SWITCH_ACTIVE", "ACTIVE_LOSS_LOCK",
        "RISK_ENGINE_UNHEALTHY",
    )


def test_selecting_a_profile_never_enables_live_trading():
    r = client.post(
        "/api/profiles/select",
        json={"profile": "BALANCED", "owner_confirmed": True, "owner_reference": "T"},
    )
    body = r.json()
    assert body["live_trading_enabled"] is False
    assert "لا يفتح التداول الحقيقي" in body["note_ar"]


def test_intelligence_endpoint_names_every_missing_provider_exactly():
    data = client.get("/api/intelligence").json()
    missing = data["providers"]["missing"]
    for name in (
        "EconomicCalendarProvider",
        "MacroDataProvider",
        "VerifiedNewsProvider",
        "MarketDataProvider",
        "FundamentalContextProvider",
    ):
        assert name in missing
    assert data["providers"]["live_eligible_by_providers"] is False


def test_intelligence_endpoint_lists_all_seventeen_stages_even_before_a_run():
    data = client.get("/api/intelligence").json()
    assert data["available"] is False
    assert len(data["stages"]) == 17
    assert all(s["name_ar"] for s in data["stages"])


def test_intelligence_endpoint_reports_no_approved_strategy():
    data = client.get("/api/intelligence").json()
    strategies = data["strategies"]
    assert strategies["approved_count"] == 0
    assert all(s["state"] == "RESEARCH" for s in strategies["strategies"])
    assert all(s["live_eligible"] is False for s in strategies["strategies"])


def test_every_strategy_declares_its_regimes_and_rules():
    data = client.get("/api/intelligence").json()
    for s in data["strategies"]["strategies"]:
        assert s["compatible_regimes"]
        assert s["incompatible_regimes"]
        assert s["entry_rules_ar"]
        assert s["invalidation_rules_ar"]
        assert s["stop_rules_ar"]
        assert s["exit_rules_ar"]
        assert s["timeframe_requirements"]
        assert s["fingerprint"]


def test_no_endpoint_can_submit_an_order():
    """لا يوجد مسار في الواجهة يرسل أمراً — لا للملفات ولا للاستخبارات."""
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    for suspicious in ("/api/order", "/api/orders", "/api/trade", "/api/execute"):
        assert suspicious not in paths
    for path in paths:
        assert "submit" not in path
        assert "execute" not in path


def test_profile_endpoints_do_not_expose_any_credential():
    body = client.get("/api/profiles").text + client.get("/api/intelligence").text
    for forbidden in ("CAPITAL_API_KEY", "X-SECURITY-TOKEN", "CST", "password"):
        assert forbidden not in body
