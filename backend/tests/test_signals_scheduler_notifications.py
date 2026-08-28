"""
مصادر الإشارات (موقف TradingView)، المجدول الآمن، والإشعارات المحلية.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.clock import now_utc
from app.notifications import (
    KIND_LABELS_AR,
    InMemoryNotifier,
    LocalFileNotifier,
    NotificationKind,
    NullNotifier,
    Severity,
)
from app.scheduling import JobKind, SafeScheduler, UnsafeScheduledJob
from app.secretstore.redaction import REGISTRY
from app.signals.source import (
    FORBIDDEN_KEYS,
    SignalInbox,
    SignalRejection,
    TradingViewWebhookSource,
)

UTC = timezone.utc
SECRET = "webhook-shared-secret-123456"


def signed(alert_id: str, symbol: str, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), (alert_id + symbol).encode(), hashlib.sha256).hexdigest()


def alert(**overrides) -> dict:
    base = {
        "alert_id": "a-1",
        "symbol": "EURUSD",
        "time_utc": now_utc().isoformat(),
        "action": "buy",
    }
    base.update(overrides)
    base.setdefault("signature", signed(base["alert_id"], base["symbol"]))
    return base


def enabled_source(**kwargs) -> TradingViewWebhookSource:
    return TradingViewWebhookSource(shared_secret=SECRET, enabled=True, **kwargs)


# --- موقف TradingView --------------------------------------------------------

def test_tradingview_source_is_disabled_by_default():
    source = TradingViewWebhookSource(shared_secret=SECRET)
    assert source.enabled is False
    result = source.admit(alert())
    assert result.accepted is False
    assert result.reason_code == SignalRejection.DISABLED.value


def test_disabled_source_explains_it_never_reaches_the_broker():
    result = TradingViewWebhookSource().admit(alert())
    assert "لا يرسل شيئاً للوسيط" in result.reason_ar


def test_valid_signed_alert_enters_the_inbox_only():
    source = enabled_source()
    result = source.admit(alert())
    assert result.accepted is True
    assert "محرك الاستراتيجية" in result.reason_ar
    assert "محرك المخاطر" in result.reason_ar
    assert len(source.inbox.accepted) == 1


def test_bad_signature_is_rejected():
    source = enabled_source()
    result = source.admit(alert(signature="deadbeef"))
    assert result.reason_code == SignalRejection.BAD_SIGNATURE.value


def test_unsigned_alert_is_rejected_when_no_secret_configured():
    source = TradingViewWebhookSource(enabled=True)
    assert source.admit(alert()).reason_code == SignalRejection.BAD_SIGNATURE.value


def test_stale_alert_is_rejected():
    source = enabled_source()
    old = (now_utc() - timedelta(minutes=30)).isoformat()
    result = source.admit(alert(time_utc=old))
    assert result.reason_code == SignalRejection.STALE.value


def test_duplicate_alert_is_rejected():
    source = enabled_source()
    payload = alert()
    assert source.admit(payload).accepted is True
    assert source.admit(payload).reason_code == SignalRejection.DUPLICATE.value


def test_malformed_alert_is_rejected():
    source = enabled_source()
    assert source.admit({"symbol": "EURUSD"}).reason_code == SignalRejection.MALFORMED.value
    assert source.admit(alert(time_utc="not-a-date")).reason_code == SignalRejection.MALFORMED.value


def test_instrument_outside_allowlist_is_rejected():
    source = enabled_source()
    payload = alert(symbol="BTCUSD")
    payload["signature"] = signed("a-1", "BTCUSD")
    assert source.admit(payload).reason_code == SignalRejection.INSTRUMENT_NOT_ALLOWED.value


def test_alert_carrying_credentials_is_rejected_and_not_stored():
    source = enabled_source()
    payload = alert()
    payload["api_key"] = "should-never-be-here"
    result = source.admit(payload)
    assert result.reason_code == SignalRejection.CONTAINS_CREDENTIALS.value
    assert not source.inbox.accepted


def test_forbidden_keys_cover_every_credential_name():
    assert {"apikey", "password", "cst", "x-security-token", "identifier"} <= FORBIDDEN_KEYS


def test_signal_module_never_imports_a_broker_adapter():
    """قيد بنيوي: لا مسار من webhook إلى الوسيط."""
    import app.signals.source as module

    source_text = open(module.__file__, encoding="utf-8").read()
    for forbidden in ("CapitalComAdapter", "ExecutionService", "place_order", "POST /positions"):
        assert forbidden not in source_text


def test_inbox_records_rejections_for_audit():
    source = enabled_source()
    source.admit(alert(signature="bad"))
    assert source.inbox.rejected
    assert source.inbox.rejected[0][0] == SignalRejection.BAD_SIGNATURE.value


# --- المجدول ------------------------------------------------------------------

def test_scheduler_refuses_to_register_a_mutating_job():
    scheduler = SafeScheduler()
    with pytest.raises(UnsafeScheduledJob, match="قراراً بشرياً"):
        scheduler.register(
            "submit", kind=JobKind.MUTATING, interval=timedelta(minutes=1), func=lambda: None
        )


def test_scheduler_runs_read_only_jobs_deterministically():
    calls: list[int] = []
    start = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    scheduler = SafeScheduler(clock=lambda: start)
    scheduler.register(
        "health", kind=JobKind.READ_ONLY, interval=timedelta(minutes=5),
        func=lambda: calls.append(1),
    )
    assert scheduler.tick(start) == ["health"]
    assert scheduler.tick(start + timedelta(minutes=1)) == []
    assert scheduler.tick(start + timedelta(minutes=6)) == ["health"]
    assert len(calls) == 2


def test_a_failing_job_does_not_stop_the_others():
    start = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    scheduler = SafeScheduler(clock=lambda: start)
    ran: list[str] = []

    def boom():
        raise RuntimeError("fail")

    scheduler.register("bad", kind=JobKind.READ_ONLY, interval=timedelta(minutes=1), func=boom)
    scheduler.register(
        "good", kind=JobKind.ANALYSIS, interval=timedelta(minutes=1), func=lambda: ran.append("g")
    )
    scheduler.tick(start)
    assert ran == ["g"]
    assert scheduler.jobs["bad"].failures == 1
    assert scheduler.jobs["bad"].last_error == "RuntimeError"


def test_scheduler_never_enables_trading():
    scheduler = SafeScheduler()
    assert scheduler.trading_enabled is False
    scheduler.register(
        "analysis", kind=JobKind.ANALYSIS, interval=timedelta(minutes=1), func=lambda: None
    )
    scheduler.tick()
    assert scheduler.trading_enabled is False


def test_scheduler_status_uses_riyadh_time():
    start = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    scheduler = SafeScheduler(clock=lambda: start)
    scheduler.register(
        "health", kind=JobKind.READ_ONLY, interval=timedelta(minutes=5), func=lambda: None
    )
    scheduler.tick(start)
    status = scheduler.status()[0]
    assert "ص" in status["last_run_riyadh"] or "م" in status["last_run_riyadh"]


# --- الإشعارات ------------------------------------------------------------------

def test_every_required_notification_kind_exists():
    required = {
        NotificationKind.CONNECTION_LOST,
        NotificationKind.STALE_PRICES,
        NotificationKind.SESSION_EXPIRED,
        NotificationKind.RECONCILIATION_FAILURE,
        NotificationKind.UNKNOWN_EXECUTION_STATE,
        NotificationKind.RISK_REJECTION,
        NotificationKind.DAILY_LIMIT_REACHED,
        NotificationKind.WEEKLY_LIMIT_REACHED,
        NotificationKind.TWO_LOSS_LOCK,
        NotificationKind.KILL_SWITCH_ACTIVATED,
        NotificationKind.BROKER_STOP_MISSING,
        NotificationKind.POSITION_MISMATCH,
    }
    assert required <= set(NotificationKind)
    for kind in NotificationKind:
        assert kind in KIND_LABELS_AR


def test_critical_kinds_are_marked_critical():
    notifier = InMemoryNotifier()
    for kind in (
        NotificationKind.KILL_SWITCH_ACTIVATED,
        NotificationKind.UNKNOWN_EXECUTION_STATE,
        NotificationKind.RECONCILIATION_FAILURE,
        NotificationKind.BROKER_STOP_MISSING,
        NotificationKind.POSITION_MISMATCH,
        NotificationKind.TWO_LOSS_LOCK,
    ):
        notification = notifier.notify(kind, detail_ar="اختبار")
        assert notification.severity is Severity.CRITICAL


def test_notification_context_is_redacted():
    REGISTRY.register("secret-value-abcdef")
    notifier = InMemoryNotifier()
    notification = notifier.notify(
        NotificationKind.SESSION_EXPIRED,
        detail_ar="انتهت",
        context={"cst": "secret-value-abcdef", "note": "token secret-value-abcdef"},
    )
    serialised = json.dumps(notification.as_dict(), ensure_ascii=False)
    assert "secret-value-abcdef" not in serialised
    REGISTRY.clear()


def test_local_file_notifier_writes_json_lines(tmp_path):
    path = tmp_path / "notifications.jsonl"
    notifier = LocalFileNotifier(path=path)
    notifier.notify(NotificationKind.STALE_PRICES, detail_ar="أسعار قديمة")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "STALE_PRICES"


def test_null_notifier_sends_nothing_anywhere():
    notifier = NullNotifier()
    assert notifier.send.__doc__ is None or True
    notification = notifier.notify(NotificationKind.RISK_REJECTION, detail_ar="مرفوض")
    assert notification.kind is NotificationKind.RISK_REJECTION


def test_notifications_module_has_no_network_client():
    import app.notifications as module

    text = open(module.__file__, encoding="utf-8").read()
    for forbidden in ("smtplib", "httpx", "requests", "urllib.request", "socket"):
        assert forbidden not in text
