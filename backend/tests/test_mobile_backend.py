"""
اختبارات طبقة الجوال الخلفية: التسجيل، الرموز، الصلاحيات، الإشعارات، المجال.

**لا شبكة · لا Keychain · لا APNs حقيقية.**
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.mobile.api import (
    API_PREFIX,
    FORBIDDEN_ROUTE_TOKENS,
    READ_ROUTES,
    RISK_REDUCING_ROUTES,
    MobileApi,
    MobileApiError,
    assert_response_is_clean,
    describe_api,
)
from app.mobile.notifications import (
    APNS_CREDENTIAL_NAMES,
    FORBIDDEN_PAYLOAD_KEYS,
    NOT_YET_AUTHORISED,
    PRIVATE_LOCK_SCREEN_BODY,
    DeliveryState,
    MockApnsProvider,
    Notification,
    NotificationService,
    NotificationType,
    PrivacyViolation,
    assert_payload_is_private,
)
from app.mobile.security import (
    ACCESS_TOKEN_TTL,
    ENROLLMENT_CHALLENGE_TTL,
    FORBIDDEN_MOBILE_ACTIONS,
    NEVER_ON_DEVICE,
    PROFILE_UPGRADE_COOLING,
    MobilePermission,
    MobileSecurityService,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def service(times=None):
    box = {"now": NOW}
    svc = MobileSecurityService(clock=lambda: box["now"])
    svc._test_clock = box                      # type: ignore[attr-defined]
    return svc


def enrolled(svc):
    challenge = svc.create_enrollment_challenge()
    return svc.complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="device-public-key-fingerprint",
        device_name="iPhone المالكة",
    )


# ===========================================================================
# 1. التسجيل
# ===========================================================================

def test_qr_payload_carries_no_secret():
    """
    رمز QR يُصوَّر ويُشارَك شاشةً. محتواه يجب أن يكون **عديم القيمة**.
    """
    svc = service()
    payload = svc.create_enrollment_challenge().qr_payload(
        backend_url="http://127.0.0.1:8000"
    )
    blob = repr(payload)
    for name in NEVER_ON_DEVICE:
        assert name not in blob
    assert "capital" not in blob.lower()
    # الحقول الأربعة لا غير. `contains_secret` حُذف في الإصدار 2 واستُبدل
    # بحارس أقوى: أي حقل زائد يُرفَض بوجوده لا باعترافه.
    assert set(payload) == {"v", "b", "c", "e"}


def test_challenge_is_single_use():
    """
    الاستعمال الثاني يفشل **حتى قبل انتهاء المهلة** — هذا هو الفرق بين
    «قصير العمر» و«لمرة واحدة».
    """
    svc = service()
    challenge = svc.create_enrollment_challenge()
    first = svc.complete_enrollment(
        challenge_id=challenge.challenge_id, public_identity="a", device_name="A"
    )
    second = svc.complete_enrollment(
        challenge_id=challenge.challenge_id, public_identity="b", device_name="B"
    )
    assert first is not None
    assert second is None


def test_challenge_expires():
    svc = service()
    challenge = svc.create_enrollment_challenge()
    svc._test_clock["now"] = NOW + ENROLLMENT_CHALLENGE_TTL + timedelta(seconds=1)
    assert svc.complete_enrollment(
        challenge_id=challenge.challenge_id, public_identity="a", device_name="A"
    ) is None


def test_public_identity_is_hashed_never_stored_raw():
    svc = service()
    device = enrolled(svc)
    assert "device-public-key-fingerprint" not in device.public_identity
    assert len(device.public_identity) == 64          # SHA-256 hex


def test_device_dict_never_exposes_the_full_identity_or_push_token():
    svc = service()
    device = enrolled(svc)
    svc.register_push_token(device.device_id, "apns-token-abcdef123456")
    data = device.as_dict()
    assert "apns-token-abcdef123456" not in repr(data)
    assert data["has_push_token"] is True
    assert data["public_identity_masked"].endswith("…")


# ===========================================================================
# 2. الرموز
# ===========================================================================

def test_access_token_expires():
    svc = service()
    device = enrolled(svc)
    access, _refresh = svc.issue_tokens(device.device_id)
    assert svc.authenticate(access.token) is not None
    svc._test_clock["now"] = NOW + ACCESS_TOKEN_TTL + timedelta(seconds=1)
    assert svc.authenticate(access.token) is None


def test_refresh_rotation_invalidates_the_old_token():
    svc = service()
    device = enrolled(svc)
    _access, refresh = svc.issue_tokens(device.device_id)
    rotated = svc.rotate_refresh(refresh.token)
    assert rotated is not None
    # إعادة استعمال القديم مؤشّر سرقة — يُرفض ويُسجَّل.
    assert svc.rotate_refresh(refresh.token) is None
    assert any(e.action == "REFRESH_REUSE_DETECTED" for e in svc.audit())


def test_revocation_kills_all_tokens_immediately():
    """الإلغاء لا ينتظر انتهاء المهلة."""
    svc = service()
    device = enrolled(svc)
    access, _ = svc.issue_tokens(device.device_id)
    assert svc.authenticate(access.token) is not None
    svc.revoke_device(device.device_id, reason="فقدان الجهاز")
    assert svc.authenticate(access.token) is None


def test_unknown_token_fails_closed():
    assert service().authenticate("made-up-token") is None


def test_every_security_action_is_audited():
    svc = service()
    device = enrolled(svc)
    svc.revoke_device(device.device_id, reason="اختبار")
    actions = {e.action for e in svc.audit()}
    assert {"ENROLLMENT_CHALLENGE_CREATED", "DEVICE_ENROLLED", "DEVICE_REVOKED"} <= actions


# ===========================================================================
# 3. الصلاحيات
# ===========================================================================

def test_granted_permissions_never_intersect_forbidden_actions():
    assert not ({p.value for p in MobilePermission} & set(FORBIDDEN_MOBILE_ACTIONS))


@pytest.mark.parametrize("action", [
    "PLACE_TRADE", "CLOSE_POSITION", "CHANGE_QUANTITY", "CHANGE_STOP_LOSS",
    "CHANGE_TAKE_PROFIT", "CHANGE_LEVERAGE", "REACTIVATE_BROKER_KEY",
    "APPROVE_CONTINUOUS_LIVE", "FUND_ACCOUNT",
])
def test_forbidden_action_is_declared(action):
    assert action in FORBIDDEN_MOBILE_ACTIONS


def test_profile_upgrade_only_starts_a_server_side_cooling_period():
    """الهاتف **يطلب** ولا يفعّل، ولا يستطيع تقصير التبريد."""
    svc = service()
    device = enrolled(svc)
    ok, message = svc.request_profile_upgrade(device.device_id, target_profile="BALANCED")
    assert ok and "تبريد" in message
    remaining = svc.upgrade_cooling_remaining(device.device_id)
    assert remaining == PROFILE_UPGRADE_COOLING

    svc._test_clock["now"] = NOW + timedelta(hours=23)
    assert svc.upgrade_cooling_remaining(device.device_id).total_seconds() > 0
    svc._test_clock["now"] = NOW + timedelta(hours=25)
    assert svc.upgrade_cooling_remaining(device.device_id).total_seconds() == 0


# ===========================================================================
# 4. مجال الجوال
# ===========================================================================

def api_with_device():
    svc = service()
    device = enrolled(svc)
    access, _ = svc.issue_tokens(device.device_id)
    api = MobileApi(security=svc, state_source=lambda: {
        "status": {"system": "IDLE"},
        "decision": {"final": "NO_TRADE"},
        "risk": {"used": "0.00"},
    }, clock=lambda: NOW)
    return api, svc, device, access.token


def test_there_is_no_trading_route():
    """القائمة نفسها هي الحد. لا مسار تداول، ولا مسار يزيد المخاطرة."""
    assert describe_api()["trading_routes"] == []
    for route in READ_ROUTES + RISK_REDUCING_ROUTES:
        for token in FORBIDDEN_ROUTE_TOKENS:
            assert token not in route


def test_all_eleven_read_routes_are_present():
    assert set(READ_ROUTES) == {
        "status", "intelligence/latest", "decision/latest", "risk", "profiles",
        "positions/current", "trades", "performance", "providers/health",
        "notifications", "audit/recent",
    }


def test_only_three_mutation_routes_and_all_reduce_risk():
    assert set(RISK_REDUCING_ROUTES) == {
        "pause/request", "killswitch/activate", "device/revoke",
    }


def test_prefix_is_versioned():
    assert API_PREFIX == "/api/mobile/v1"


def test_unauthenticated_request_is_refused():
    api, *_ = api_with_device()
    with pytest.raises(MobileApiError) as caught:
        api.handle("GET", "status", token="nope")
    assert caught.value.status == 401


@pytest.mark.parametrize("route", READ_ROUTES)
def test_each_read_route_answers_and_declares_no_execution(route):
    api, _svc, _device, token = api_with_device()
    response = api.handle("GET", route, token=token)
    assert response.status == 200
    assert response.body["authorises_execution"] is False


@pytest.mark.parametrize("route", [
    "orders", "trade/submit", "position/close", "leverage", "preferences",
    "broker/key/activate", "commissioning/approve",
])
def test_a_trading_route_is_refused(route):
    api, _svc, _device, token = api_with_device()
    with pytest.raises(MobileApiError) as caught:
        api.handle("POST", route, token=token)
    assert caught.value.status in (403, 404)


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_mutating_http_methods_are_refused(method):
    api, _svc, _device, token = api_with_device()
    with pytest.raises(MobileApiError) as caught:
        api.handle(method, "status", token=token)
    assert caught.value.status == 405


def test_pause_and_kill_switch_are_accepted_and_audited():
    api, svc, _device, token = api_with_device()
    assert api.handle("POST", "pause/request", token=token).body["accepted"] is True
    assert api.handle("POST", "killswitch/activate", token=token).body["accepted"] is True
    actions = {e.action for e in svc.audit()}
    assert {"MOBILE_PAUSE_REQUESTED", "MOBILE_KILL_SWITCH"} <= actions


def test_kill_switch_cannot_be_deactivated_from_mobile():
    api, _svc, _device, token = api_with_device()
    body = api.handle("POST", "killswitch/activate", token=token).body
    assert "لا يُلغى من الجوال" in body["note_ar"]
    with pytest.raises(MobileApiError):
        api.handle("POST", "killswitch/deactivate", token=token)


def test_private_report_paths_are_never_returned():
    """`data/private/` لا يُقدَّم عبر مجال الجوال بحال."""
    with pytest.raises(MobileApiError):
        assert_response_is_clean({"path": "data/private/capital_live/x.md"})
    with pytest.raises(MobileApiError):
        assert_response_is_clean({"k": "CAPITAL_API_KEY"})


def test_a_state_source_leaking_a_private_path_is_blocked_at_the_boundary():
    svc = service()
    device = enrolled(svc)
    access, _ = svc.issue_tokens(device.device_id)
    api = MobileApi(
        security=svc,
        state_source=lambda: {"status": {"report": "data/private/capital_live/x.md"}},
        clock=lambda: NOW,
    )
    with pytest.raises(MobileApiError) as caught:
        api.handle("GET", "status", token=access.token)
    assert caught.value.status == 500


# ===========================================================================
# 5. الإشعارات
# ===========================================================================

def notification(kind=NotificationType.STALE_DATA, detail="تفاصيل داخلية"):
    return Notification(
        type=kind, created_utc=NOW, in_app_detail_ar=detail, dedup_key=f"k:{kind.value}"
    )


def test_lock_screen_text_is_private_and_constant():
    """
    النص **ثابت** ولا يعتمد على محتوى الإشعار — فلا يمكن أن يتسرّب رقم عبره
    ولو بالخطأ.
    """
    a = notification(NotificationType.STOP_LOSS_EVENT, "خسارة 0.54 دولار")
    b = notification(NotificationType.DAILY_SUMMARY, "الرصيد 212.34")
    assert a.lock_screen_payload()["aps"]["alert"]["body"] == PRIVATE_LOCK_SCREEN_BODY
    assert a.lock_screen_payload()["aps"] == b.lock_screen_payload()["aps"]
    assert "0.54" not in repr(a.lock_screen_payload())
    assert "212.34" not in repr(b.lock_screen_payload())


@pytest.mark.parametrize("key", FORBIDDEN_PAYLOAD_KEYS)
def test_forbidden_payload_key_is_rejected(key):
    with pytest.raises(PrivacyViolation):
        assert_payload_is_private({"aps": {"alert": {"body": f"the {key} is 5"}}})


def test_delivery_uses_the_mock_provider_only():
    apns = MockApnsProvider()
    svc = NotificationService(apns=apns, clock=lambda: NOW)
    receipt = svc.send(notification(), device_id="d1", apns_token="tok-1")
    assert receipt.state is DeliveryState.DELIVERED
    assert apns.name == "MockApnsProvider"
    assert len(apns.sent) == 1


def test_duplicate_within_the_window_is_suppressed():
    svc = NotificationService(apns=MockApnsProvider(), clock=lambda: NOW)
    first = svc.send(notification(), device_id="d1", apns_token="t")
    second = svc.send(notification(), device_id="d1", apns_token="t")
    assert first.state is DeliveryState.DELIVERED
    assert second.state is DeliveryState.SUPPRESSED_DUPLICATE


def test_bad_device_token_is_not_retried():
    apns = MockApnsProvider(fail_tokens=frozenset({"bad"}))
    svc = NotificationService(apns=apns, clock=lambda: NOW)
    receipt = svc.send(notification(), device_id="d1", apns_token="bad")
    assert receipt.state is DeliveryState.INVALID_TOKEN
    assert receipt.attempts == 1


def test_token_rotation_invalidates_the_old_token():
    svc = NotificationService(apns=MockApnsProvider(), clock=lambda: NOW)
    svc.rotate_token("old", "new")
    receipt = svc.send(notification(), device_id="d1", apns_token="old")
    assert receipt.state is DeliveryState.INVALID_TOKEN


def test_trade_submitted_is_not_authorised_yet():
    svc = NotificationService(apns=MockApnsProvider(), clock=lambda: NOW)
    receipt = svc.send(
        notification(NotificationType.TRADE_SUBMITTED), device_id="d1", apns_token="t"
    )
    assert receipt.state is DeliveryState.FAILED
    assert NotificationType.TRADE_SUBMITTED in NOT_YET_AUTHORISED


def test_all_fifteen_notification_types_exist():
    assert len(NotificationType) == 15


def test_apns_credentials_are_named_only_never_created():
    assert APNS_CREDENTIAL_NAMES == (
        "APNS_KEY_ID", "APPLE_TEAM_ID", "IOS_BUNDLE_ID", "APNS_PRIVATE_KEY_P8_PATH",
    )


def test_notification_delivery_is_never_required_for_safety():
    """
    توثيق تنفيذي: فشل التسليم يُسجَّل **ولا يرفع استثناء** ولا يوقف شيئاً.
    وقف الخسارة لدى الوسيط لا في الهاتف.
    """
    svc = NotificationService(
        apns=MockApnsProvider(fail_tokens=frozenset({"t"})), clock=lambda: NOW
    )
    receipt = svc.send(notification(), device_id="d1", apns_token="t")
    assert receipt.state is DeliveryState.INVALID_TOKEN     # سُجِّل، ولم يُرفع
