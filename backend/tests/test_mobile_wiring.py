"""
اختبارات وصل طبقة الجوال بالخادم.

`app/mobile/` كُتبت واختُبرت في 0.4.0 ثم **لم تُركَّب**. فكانت اختباراتها
تمرّ كلها بينما لا يوجد تحت `/api/mobile/v1/` مسارٌ واحد — وحدةٌ سليمة
وغير موصولة. هذه الاختبارات تفحص **الوصلة** لا الوحدة.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, system
from app.mobile.pairing import assert_payload_carries_no_secret
from app.mobile.routes import MobileRuntime, set_runtime
from app.mobile.security import (
    NEVER_ON_DEVICE,
    MobileSecurityService,
)
from app.mobile.state import build_mobile_state
from app.mobile.store import MobileStateStore, MobileStoreError

POSIX = os.name == "posix"


@pytest.fixture
def wired(tmp_path: Path):
    """خادم موصول بمخزن معزول لكل اختبار."""
    path = tmp_path / "mobile-state.json"
    store = MobileStateStore(path)
    service = MobileSecurityService(store=store)
    set_runtime(
        MobileRuntime(security=service, state_source=lambda: build_mobile_state(system()))
    )
    return TestClient(app), service, path


def enrol(client: TestClient, service: MobileSecurityService, name: str = "Mesa"):
    challenge = service.create_enrollment_challenge()
    response = client.post(
        "/api/mobile/v1/enroll/complete",
        json={
            "challenge_id": challenge.challenge_id,
            "public_identity": "PUBLIC-KEY-FINGERPRINT",
            "device_name": name,
        },
    )
    return challenge, response


# ---------------------------------------------------------------------------
# 1. المسارات مركَّبة فعلاً
# ---------------------------------------------------------------------------

def test_mobile_domain_is_actually_mounted(wired):
    """
    الاختبار الذي كان غائباً. كل اختبارات 0.4.0 كانت تستدعي `MobileApi`
    مباشرةً، فلم يكشف أيٌّ منها أن الخادم لا يعرفها.
    """
    client, _, _ = wired
    response = client.get("/api/mobile/v1/describe")
    assert response.status_code == 200
    assert response.json()["prefix"] == "/api/mobile/v1"


def test_describe_declares_no_trading_route(wired):
    client, _, _ = wired
    body = client.get("/api/mobile/v1/describe").json()
    assert body["trading_routes"] == []


# ---------------------------------------------------------------------------
# 2. المصادقة تفشل مغلقة
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["status", "risk", "profiles", "audit/recent"])
def test_read_without_token_is_rejected(wired, route):
    client, _, _ = wired
    assert client.get(f"/api/mobile/v1/{route}").status_code == 401


def test_malformed_authorization_header_is_rejected(wired):
    client, service, _ = wired
    _, response = enrol(client, service)
    token = response.json()["access_token"]
    for header in (token, f"Basic {token}", "Bearer", "Bearer   "):
        assert client.get(
            "/api/mobile/v1/status", headers={"Authorization": header}
        ).status_code == 401, header


def test_token_is_not_accepted_from_query_string(wired):
    """
    الرمز يُقرأ من الترويسة **حصراً**: المسار يُسجَّل في سجلّات الوسطاء،
    والمعامل يظهر في `Referer`.
    """
    client, service, _ = wired
    _, response = enrol(client, service)
    token = response.json()["access_token"]
    assert client.get(f"/api/mobile/v1/status?token={token}").status_code == 401


# ---------------------------------------------------------------------------
# 3. التسجيل — لمرة واحدة وقصير العمر
# ---------------------------------------------------------------------------

def test_enrolment_issues_tokens_and_masks_identity(wired):
    client, service, _ = wired
    _, response = enrol(client, service)
    body = response.json()
    assert response.status_code == 200
    assert body["authorises_execution"] is False
    assert body["device"]["public_identity_masked"].endswith("…")
    # البصمة الخام لا تُعاد أبداً.
    assert "PUBLIC-KEY-FINGERPRINT" not in json.dumps(body)


def test_challenge_cannot_be_replayed(wired):
    client, service, _ = wired
    challenge, first = enrol(client, service)
    assert first.status_code == 200
    second = client.post(
        "/api/mobile/v1/enroll/complete",
        json={
            "challenge_id": challenge.challenge_id,
            "public_identity": "ANOTHER-DEVICE-KEY",
            "device_name": "Intruder",
        },
    )
    assert second.status_code == 401


def test_expired_challenge_is_rejected(wired, tmp_path):
    """«قصير العمر» و«لمرة واحدة» شرطان مختلفان — وهذا يفحص الأول."""
    path = tmp_path / "expiring.json"
    moment = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    clock = {"now": moment}
    service = MobileSecurityService(
        store=MobileStateStore(path), clock=lambda: clock["now"]
    )
    set_runtime(MobileRuntime(security=service, state_source=dict))
    client = TestClient(app)
    challenge = service.create_enrollment_challenge()

    clock["now"] = moment + timedelta(minutes=3)
    response = client.post(
        "/api/mobile/v1/enroll/complete",
        json={
            "challenge_id": challenge.challenge_id,
            "public_identity": "PUBLIC-KEY-FINGERPRINT",
            "device_name": "Late",
        },
    )
    assert response.status_code == 401


def test_unknown_challenge_is_rejected(wired):
    client, _, _ = wired
    response = client.post(
        "/api/mobile/v1/enroll/complete",
        json={
            "challenge_id": "does-not-exist",
            "public_identity": "PUBLIC-KEY-FINGERPRINT",
            "device_name": "Ghost",
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 4. لا مسار تنفيذ — عبر HTTP هذه المرة
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "route",
    [
        "orders/create", "trade/submit", "position/open", "position/close",
        "leverage/set", "preferences/update", "commissioning/start",
        "activate-key", "deposit", "withdraw",
    ],
)
def test_no_execution_route_exists_over_http(wired, route):
    client, service, _ = wired
    _, response = enrol(client, service)
    token = response.json()["access_token"]
    result = client.post(
        f"/api/mobile/v1/{route}",
        headers={"Authorization": f"Bearer {token}"},
        json={"epic": "EURUSD", "size": 100},
    )
    assert result.status_code == 403


def test_only_three_mutating_routes_are_accepted(wired):
    client, service, _ = wired
    _, response = enrol(client, service)
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    for route in ("pause/request", "killswitch/activate"):
        assert client.post(
            f"/api/mobile/v1/{route}", headers=headers, json={}
        ).status_code == 200, route


def test_kill_switch_response_says_it_cannot_be_undone_from_mobile(wired):
    client, service, _ = wired
    _, response = enrol(client, service)
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    body = client.post(
        "/api/mobile/v1/killswitch/activate", headers=headers, json={}
    ).json()
    assert "لا يُلغى من الجوال" in body["note_ar"]


# ---------------------------------------------------------------------------
# 5. تدوير الرموز
# ---------------------------------------------------------------------------

def test_refresh_rotates_and_old_token_dies(wired):
    client, service, _ = wired
    _, response = enrol(client, service)
    refresh = response.json()["refresh_token"]

    rotated = client.post("/api/mobile/v1/token/refresh", json={"refresh_token": refresh})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != refresh

    reused = client.post("/api/mobile/v1/token/refresh", json={"refresh_token": refresh})
    assert reused.status_code == 401


def test_revoked_device_loses_access_immediately(wired):
    client, service, _ = wired
    _, response = enrol(client, service)
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/mobile/v1/status", headers=headers).status_code == 200

    client.post("/api/mobile/v1/device/revoke", headers=headers, json={})
    # الإلغاء لا ينتظر انتهاء مهلة الرمز.
    assert client.get("/api/mobile/v1/status", headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# 6. لا سرّ في أي استجابة
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["status", "risk", "profiles", "trades", "audit/recent"])
def test_no_secret_name_appears_in_any_response(wired, route):
    client, service, _ = wired
    _, response = enrol(client, service)
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    blob = json.dumps(
        client.get(f"/api/mobile/v1/{route}", headers=headers).json(), ensure_ascii=False
    )
    for name in NEVER_ON_DEVICE:
        assert name not in blob, f"{route} كان سيحمل {name}"
    assert "data/private" not in blob


def test_qr_payload_carries_no_secret(wired):
    _, service, _ = wired
    challenge = service.create_enrollment_challenge()
    payload = challenge.qr_payload(backend_url="http://100.64.0.1:8000")
    assert payload["contains_secret"] is False
    assert_payload_carries_no_secret(payload)
    blob = json.dumps(payload, ensure_ascii=False)
    for name in NEVER_ON_DEVICE:
        assert name not in blob


def test_pairing_guard_rejects_a_payload_carrying_a_secret_name():
    """الحارس يفحص ما يُطبَع فعلاً، لا ما يفترض الاختبار أنه سيُطبَع."""
    with pytest.raises(SystemExit):
        assert_payload_carries_no_secret(
            {"contains_secret": False, "note": "CAPITAL_API_KEY"}
        )


def test_pairing_guard_rejects_payload_that_does_not_declare_itself_clean():
    with pytest.raises(SystemExit):
        assert_payload_carries_no_secret({"v": 1})


# ---------------------------------------------------------------------------
# 7. الاستمرارية — الجهاز ينجو من إعادة التشغيل
# ---------------------------------------------------------------------------

def test_device_survives_a_restart(wired):
    """
    بلا هذا، تُعاد عملية مسح QR بعد كل إعادة تشغيل للخادم — وعلى خادم
    يُحدَّث دورياً يعني ذلك أن الاقتران لا يستقرّ أبداً.
    """
    client, service, path = wired
    _, response = enrol(client, service, name="Mesa")
    token = response.json()["access_token"]

    revived = MobileSecurityService(store=MobileStateStore(path))
    assert [d.name for d in revived.devices()] == ["Mesa"]
    # والرمز نفسه ما زال يصادق بعد «إعادة التشغيل».
    assert revived.authenticate(token) is not None


def test_state_file_is_owner_only(wired):
    client, service, path = wired
    enrol(client, service)
    if POSIX:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(not POSIX, reason="صلاحيات POSIX")
def test_world_readable_state_file_is_refused(tmp_path):
    """
    ملفٌ يقرأه غيرك يحوي رموز تجديد تعيش ثلاثين يوماً. يُرفَض ولا يُقرأ.
    """
    path = tmp_path / "loose.json"
    path.write_text(
        json.dumps({"schema": 1, "devices": [], "tokens": [], "challenges": []}),
        encoding="utf-8",
    )
    path.chmod(0o644)
    with pytest.raises(MobileStoreError):
        MobileStateStore(path).load()


def test_corrupt_state_file_raises_instead_of_starting_empty(tmp_path):
    """
    تجاهلُ ملفٍ تالف يعني إقلاع الخادم بلا أجهزة، فتظنّ المالكة أن جوالها
    أُلغي. الصمت هنا أسوأ من السقوط.
    """
    path = tmp_path / "corrupt.json"
    path.write_text("{ليس JSON", encoding="utf-8")
    if POSIX:
        path.chmod(0o600)
    with pytest.raises(MobileStoreError):
        MobileStateStore(path).load()


def test_unknown_schema_is_refused(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema": 99, "devices": []}), encoding="utf-8")
    if POSIX:
        path.chmod(0o600)
    with pytest.raises(MobileStoreError):
        MobileStateStore(path).load()


def test_expired_tokens_are_not_written_to_disk(tmp_path):
    """رمزٌ لا يصلح لا يُحفَظ: لا فائدة منه، وحفظُه يوسّع ما قد يُسرَّب."""
    moment = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    clock = {"now": moment}
    path = tmp_path / "pruned.json"
    service = MobileSecurityService(
        store=MobileStateStore(path), clock=lambda: clock["now"]
    )
    challenge = service.create_enrollment_challenge()
    device = service.complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="PUBLIC-KEY-FINGERPRINT",
        device_name="Mesa",
    )
    assert device is not None

    clock["now"] = moment + timedelta(days=40)   # بعد انتهاء رمز التجديد
    service.revoke_device(device.device_id, reason="اختبار")   # يُحفَظ من جديد
    assert json.loads(path.read_text(encoding="utf-8"))["tokens"] == []


# ---------------------------------------------------------------------------
# 8. مصدر الحالة لا يكذب بالفراغ
# ---------------------------------------------------------------------------

def test_unwired_sections_say_so_instead_of_returning_empty():
    """
    القاموس الفارغ يُقرأ في الواجهة «لا يوجد شيء»، والفرق بين «لا صفقات»
    و«لم نسأل» هو الفرق بين معلومة وجهل.
    """
    state = build_mobile_state(system())
    for section in ("decision", "intelligence", "position", "performance", "providers"):
        assert state[section]["available"] is False
        assert state[section]["reason_ar"], section


def test_status_and_risk_are_wired():
    state = build_mobile_state(system())
    assert state["status"]["available"] is True
    assert state["risk"]["available"] is True
    assert state["profiles"]["available"] is True


def test_state_never_authorises_execution():
    state = build_mobile_state(system())
    assert state["status"]["authorises_execution"] is False
    assert state["profiles"]["changeable_from_mobile"] is False
