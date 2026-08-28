"""
سلامة التنفيذ — أهم ملف اختبار في هذه الهجرة.

يثبت أن النظام لا يستطيع إرسال أمر تحت هذه المهمة، وأنه عند الغموض
يقرأ ولا يعيد الإرسال أبداً.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.brokers.capital.endpoints import (
    PATH_ACCOUNT_PREFERENCES,
    PATH_ACCOUNT_TOPUP,
    PATH_POSITIONS,
    PATH_SESSION,
    PATH_WORKING_ORDERS,
    is_mutating,
    is_read_only,
)
from app.brokers.capital.errors import CapitalNotFound, CapitalTimeout
from app.brokers.capital.safety import (
    ExecutionLock,
    ExecutionLocked,
    MutatingEndpointBlocked,
    assert_not_mutating,
)
from app.brokers.capital.transport import ApiResponse
from app.clock import now_utc
from app.contracts import ExecutionUncertainty, OrderIntent, OrderType, Side
from app.money import D
from tests.capital_fixtures import (
    build_adapter,
    build_transport,
    confirm_body,
    eurusd_market_body,
    positions_body,
)


def connected(transport=None, **kwargs):
    adapter, guarded, fixture = build_adapter(transport, **kwargs)
    adapter.connect()
    return adapter, guarded, fixture


def an_intent(**overrides) -> OrderIntent:
    base = dict(
        idempotency_key="key-1",
        client_order_id="ref-abc-123",
        symbol="EURUSD",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=D("100"),
        limit_price=D("1.08546"),
        stop_price=D("1.08046"),
        expected_fill_price=D("1.08546"),
        max_slippage_abs=D("0.0002"),
        strategy_name="TREND_PULLBACK",
        strategy_version="1.0.0",
        risk_amount_usd=D("0.51"),
        commission_estimate_usd=D("0.01"),
        exit_plan_ar="وقف 50 نقطة وهدف 100 نقطة",
        instrument_snapshot={},
        created_at_utc=now_utc(),
    )
    base.update(overrides)
    return OrderIntent(**base)


# --- تصنيف المسارات ---------------------------------------------------------

def test_mutating_endpoints_are_classified_as_mutating():
    for method, path in (
        ("POST", PATH_POSITIONS),
        ("PUT", PATH_POSITIONS + "/deal-1"),
        ("DELETE", PATH_POSITIONS + "/deal-1"),
        ("POST", PATH_WORKING_ORDERS),
        ("PUT", PATH_WORKING_ORDERS + "/deal-1"),
        ("DELETE", PATH_WORKING_ORDERS + "/deal-1"),
        ("PUT", PATH_ACCOUNT_PREFERENCES),
        ("POST", PATH_ACCOUNT_TOPUP),
    ):
        assert is_mutating(method, path) is True, f"{method} {path}"
        with pytest.raises(MutatingEndpointBlocked):
            assert_not_mutating(method, path)


def test_read_endpoints_are_classified_as_read_only():
    for method, path in (
        ("GET", PATH_POSITIONS),
        ("GET", PATH_WORKING_ORDERS),
        ("GET", PATH_ACCOUNT_PREFERENCES),
        ("GET", "/api/v1/markets/EURUSD"),
        ("GET", "/api/v1/confirms/ref-1"),
    ):
        assert is_read_only(method, path) is True
        assert is_mutating(method, path) is False


def test_unknown_path_is_treated_as_mutating_fail_closed():
    assert is_mutating("POST", "/api/v1/something/new") is True
    assert is_mutating("GET", "/api/v1/totally/unknown") is True


def test_session_creation_is_not_classified_as_mutating():
    assert is_mutating("POST", PATH_SESSION) is False


# --- قفل التنفيذ ------------------------------------------------------------

def test_task_execution_lock_is_closed_by_default():
    lock = ExecutionLock.locked()
    assert lock.unlocked is False
    with pytest.raises(ExecutionLocked):
        lock.assert_can_execute("POST /positions")


def test_lock_cannot_be_opened_by_environment_variable(monkeypatch):
    monkeypatch.setenv("CAPITAL_EXECUTION_UNLOCKED", "true")
    assert ExecutionLock.from_environment().unlocked is False


def test_lock_requires_owner_reference_and_reason_to_open():
    lock = ExecutionLock.locked()
    with pytest.raises(ExecutionLocked):
        lock.authorise(owner_authorization_reference="", reason_ar="سبب كافٍ جداً", at=now_utc())
    with pytest.raises(ExecutionLocked):
        lock.authorise(owner_authorization_reference="APPROVAL-1", reason_ar="قصير", at=now_utc())
    opened = lock.authorise(
        owner_authorization_reference="APPROVAL-1",
        reason_ar="موافقة موثقة على صفقة التشغيل التجريبي",
        at=now_utc(),
    )
    assert opened.unlocked is True
    assert lock.unlocked is False, "الأصل يبقى مغلقاً — الفتح ينتج كائناً جديداً"


# --- المحوّل: كل عملية مُعدِّلة مقفلة ---------------------------------------

def test_place_order_is_blocked_and_sends_nothing():
    adapter, _g, fixture = connected()
    before = len(fixture.calls)
    with pytest.raises(ExecutionLocked):
        adapter.place_order(an_intent())
    assert len(fixture.calls) == before


def test_cancel_close_and_update_are_blocked():
    adapter, _g, _f = connected()
    for call in (
        lambda: adapter.cancel_order("deal-1"),
        lambda: adapter.close_position("acct", "EURUSD", D("100")),
        lambda: adapter.update_position("deal-1", stop_level=D("1.08")),
    ):
        with pytest.raises(ExecutionLocked):
            call()


def test_guarded_transport_blocks_a_mutating_request_even_if_called_directly():
    adapter, guarded, fixture = connected()
    before = len(fixture.calls)
    with pytest.raises(ExecutionLocked):
        guarded.send(
            "POST",
            adapter.session.base_url + PATH_POSITIONS,
            headers={},
            json={"epic": "EURUSD", "direction": "BUY", "size": 100},
        )
    assert len(fixture.calls) == before, "لم تغادر أي حزمة العملية"


# --- بناء الأمر بلا إرسال ----------------------------------------------------

def test_position_payload_matches_the_official_shape():
    adapter, _g, fixture = connected()
    before = len(fixture.calls)
    payload = adapter.build_position_payload(
        epic="EURUSD", direction=Side.BUY, size=D("100"),
        stop_distance=D("0.0050"), profit_distance=D("0.0100"), guaranteed_stop=False,
    )
    assert set(payload) == {"epic", "direction", "size", "guaranteedStop", "stopDistance", "profitDistance"}
    assert payload["direction"] == "BUY"
    assert len(fixture.calls) == before, "بناء الجسم لا يرسل شيئاً"


def test_payload_without_stop_is_refused():
    from app.brokers.base import BrokerRejected

    adapter, _g, _f = connected()
    with pytest.raises(BrokerRejected, match="وقف الخسارة إلزامي"):
        adapter.build_position_payload(
            epic="EURUSD", direction=Side.BUY, size=D("100"),
            stop_distance=D("0"), profit_distance=D("0.01"), guaranteed_stop=False,
        )


def test_payload_without_take_profit_is_refused():
    from app.brokers.base import BrokerRejected

    adapter, _g, _f = connected()
    with pytest.raises(BrokerRejected, match="جني الأرباح إلزامي"):
        adapter.build_position_payload(
            epic="EURUSD", direction=Side.BUY, size=D("100"),
            stop_distance=D("0.005"), profit_distance=D("0"), guaranteed_stop=False,
        )


# --- المعاينة المحلية --------------------------------------------------------

def test_preview_accepts_a_valid_intent_without_sending_an_order():
    adapter, _g, fixture = connected()
    preview = adapter.preview_order(an_intent())
    assert preview.accepted_by_broker is True
    assert any("قفل التنفيذ مغلق" in w for w in preview.warnings)
    assert not any(c["method"] == "POST" and "positions" in c["path"] for c in fixture.calls)


def test_preview_rejects_quantity_below_broker_minimum():
    adapter, _g, _f = connected()
    preview = adapter.preview_order(an_intent(quantity=D("50")))
    assert preview.accepted_by_broker is False
    assert "الحد الأدنى" in preview.broker_message


def test_preview_rejects_stop_closer_than_broker_minimum_distance():
    adapter, _g, _f = connected()
    preview = adapter.preview_order(an_intent(stop_price=D("1.08536")))
    assert preview.accepted_by_broker is False
    assert "مسافة الوقف" in preview.broker_message


def test_preview_rejects_when_market_is_closed():
    adapter, _g, _f = connected(build_transport(markets={"EURUSD": eurusd_market_body(status="CLOSED")}))
    preview = adapter.preview_order(an_intent())
    assert preview.accepted_by_broker is False
    assert "قابلاً للتداول" in preview.broker_message


def test_preview_rejects_intent_without_a_stop():
    adapter, _g, _f = connected()
    preview = adapter.preview_order(an_intent(stop_price=None))
    assert preview.accepted_by_broker is False
    assert "وقف خسارة" in preview.broker_message


# --- التأكيد هو الدليل الوحيد ------------------------------------------------

def test_accepted_confirmation_resolves_as_filled():
    transport = build_transport(confirms={"ref-abc-123": confirm_body()})
    adapter, _g, _f = connected(transport)
    state, confirmation = adapter.poll_confirmation("ref-abc-123", sleeper=lambda _s: None)
    assert state is ExecutionUncertainty.RESOLVED_FILLED
    assert confirmation.deal_id == "deal-abc-123"


def test_rejected_confirmation_resolves_as_rejected():
    transport = build_transport(
        confirms={"ref-x": confirm_body(deal_reference="ref-x", deal_status="REJECTED",
                                        deal_id=None, reason="INSUFFICIENT_FUNDS")}
    )
    adapter, _g, _f = connected(transport)
    state, confirmation = adapter.poll_confirmation("ref-x", sleeper=lambda _s: None)
    assert state is ExecutionUncertainty.RESOLVED_REJECTED
    assert confirmation.reason == "INSUFFICIENT_FUNDS"


def test_missing_confirmation_stays_unknown_not_failed():
    adapter, _g, _f = connected()
    state, confirmation = adapter.poll_confirmation("ref-missing", attempts=2, sleeper=lambda _s: None)
    assert state is ExecutionUncertainty.UNKNOWN
    assert confirmation is None


def test_delayed_confirmation_is_resolved_after_retrying_the_read():
    transport = build_transport()
    attempts = {"n": 0}

    def handler(_ctx):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return ApiResponse(404, {}, {"errorCode": "error.confirm.notfound"})
        return ApiResponse(200, {}, confirm_body())

    transport.register("GET", "/api/v1/confirms/ref-abc-123", handler)
    adapter, _g, _f = connected(transport)
    state, _c = adapter.poll_confirmation("ref-abc-123", attempts=5, sleeper=lambda _s: None)
    assert state is ExecutionUncertainty.RESOLVED_FILLED
    assert attempts["n"] == 3


def test_confirmation_polling_only_reads_never_writes():
    transport = build_transport(confirms={"ref-abc-123": confirm_body()})
    adapter, _g, fixture = connected(transport)
    adapter.poll_confirmation("ref-abc-123", sleeper=lambda _s: None)
    methods = {c["method"] for c in fixture.calls if "confirms" in c["path"]}
    assert methods == {"GET"}


# --- الحالة الغامضة بعد المهلة ----------------------------------------------

def test_timeout_after_submission_is_unknown_and_never_retried():
    """
    مهلة بعد الإرسال ليست فشلاً — قد يكون الأمر نُفِّذ.
    المسار الصحيح: قراءة التأكيد ثم المراكز. لا إرسال ثانٍ إطلاقاً.
    """
    transport = build_transport(positions=positions_body(with_position=True))
    adapter, _g, fixture = connected(transport)
    state, position = adapter.resolve_unknown_execution(deal_reference=None, epic="EURUSD")
    assert state is ExecutionUncertainty.RESOLVED_FILLED
    assert position.deal_id == "deal-abc-123"
    assert all(c["method"] == "GET" for c in fixture.calls if "positions" in c["path"])


def test_unknown_execution_with_no_broker_position_resolves_as_absent():
    adapter, _g, _f = connected()
    state, position = adapter.resolve_unknown_execution(deal_reference=None, epic="EURUSD")
    assert state is ExecutionUncertainty.RESOLVED_ABSENT
    assert position is None


def test_confirmation_says_filled_but_position_absent_stays_unknown():
    """
    الحالة الأخبث: الوسيط يقول ACCEPTED لكن المركز غير موجود.
    لا نفترض شيئاً — نبقى على UNKNOWN ونطلب تدخلاً بشرياً.
    """
    transport = build_transport(confirms={"ref-abc-123": confirm_body()})
    adapter, _g, _f = connected(transport)
    state, position = adapter.resolve_unknown_execution(
        deal_reference="ref-abc-123", epic="EURUSD"
    )
    assert state is ExecutionUncertainty.UNKNOWN
    assert position is None


def test_local_position_exists_but_broker_has_none_is_a_mismatch():
    from app.contracts import Position
    from app.execution.orders import reconcile

    local = [Position(account_id="****3456", symbol="EURUSD", quantity=D("100"),
                      average_cost=D("1.08546"), as_of_utc=now_utc())]
    result = reconcile(local_positions=local, broker_positions=[], now=now_utc())
    assert result.matched is False
    assert "غير موجود لدى الوسيط" in result.discrepancies_ar[0]


def test_broker_position_exists_but_local_has_none_is_a_mismatch():
    from app.execution.orders import reconcile

    adapter, _g, _f = connected(build_transport(positions=positions_body(with_position=True)))
    broker_positions = list(adapter.get_positions("x"))
    result = reconcile(local_positions=[], broker_positions=broker_positions, now=now_utc())
    assert result.matched is False
    assert "غير معروف" in result.discrepancies_ar[0]


def test_broker_position_without_stop_is_detectable():
    adapter, _g, _f = connected(
        build_transport(positions=positions_body(with_position=True, stop_level=None))
    )
    positions = adapter.list_positions()
    assert positions[0].has_broker_stop is False


def test_broker_position_with_stop_is_detectable():
    adapter, _g, _f = connected(build_transport(positions=positions_body(with_position=True)))
    assert adapter.list_positions()[0].has_broker_stop is True


# --- منع التكرار -------------------------------------------------------------

def test_duplicate_submission_is_blocked_by_the_existing_guard():
    from app.audit.log import AuditLog, InMemoryAuditStore
    from app.execution.orders import ExecutionService, IdempotencyGuard, SubmissionOutcome
    from app.brokers.mock import MockBehaviour, MockBrokerAdapter, make_quote
    from app.contracts import DataSource

    broker = MockBrokerAdapter(behaviour=MockBehaviour(stop_on_fractional_supported=True))
    broker.connect()
    broker.set_quote(make_quote("EURUSD", "1.0854", "1.08546", source=DataSource.REALTIME))
    service = ExecutionService(
        broker=broker, audit=AuditLog(InMemoryAuditStore()), guard=IdempotencyGuard()
    )
    intent = an_intent()
    assert service.submit(intent).outcome is SubmissionOutcome.FILLED
    second = service.submit(intent)
    assert second.outcome is SubmissionOutcome.DUPLICATE_BLOCKED
    assert second.requires_kill_switch is True
