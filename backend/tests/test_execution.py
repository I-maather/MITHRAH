from __future__ import annotations

from decimal import Decimal

import pytest

from app.brokers.mock import MockBehaviour, MockBrokerAdapter, make_quote
from app.contracts import DataSource, Decision, OrderType, Position, RiskDecision, Side, Signal
from app.execution.orders import (
    ExecutionService,
    IdempotencyGuard,
    SubmissionOutcome,
    build_idempotency_key,
    build_order_intent,
    reconcile,
)
from app.money import D
from tests.conftest import MID_SESSION, make_balances, make_permissions


def a_signal(now=MID_SESSION, digest="digest-1"):
    return Signal(
        strategy_name="TREND_PULLBACK", strategy_version="1.0.0", symbol="SPY", side=Side.BUY,
        entry_price=D("640.00"), stop_price=D("630.40"), take_profit_price=D("659.20"),
        generated_at_utc=now, rationale_ar="اختبار", invalidation_ar="اختبار", inputs_digest=digest,
    )


def a_decision(qty="0.5", now=MID_SESSION):
    return RiskDecision(
        approved=True, decision=Decision.TRADE, reason_code=None, reason_ar="موافق",
        checks=(), quantity=D(qty), notional=D(qty) * D("640"),
        expected_risk_usd=D("5.00"), expected_costs_usd=D("0.80"),
        risk_budget_usd=D("5.00"), constitution_fingerprint="fp", decided_at_utc=now,
    )


def an_intent(now=MID_SESSION, qty="0.5", digest="digest-1"):
    return build_order_intent(
        signal=a_signal(now, digest), decision=a_decision(qty, now), trading_day="2026-09-15",
        instrument_snapshot={"symbol": "SPY"}, max_slippage_abs=D("0.05"), now=now,
    )


def fresh_broker(now=MID_SESSION, **behaviour):
    b = MockBrokerAdapter(behaviour=MockBehaviour(stop_on_fractional_supported=True, **behaviour))
    b.connect()
    b.balances = make_balances("5000.00", at=now)
    b.permissions = make_permissions(at=now)
    b.set_quote(make_quote("SPY", "639.99", "640.00", at=now, source=DataSource.REALTIME))
    return b


# --- idempotency ------------------------------------------------------------

def test_same_inputs_give_same_idempotency_key():
    k1 = build_idempotency_key(signal=a_signal(), decision=a_decision(), trading_day="2026-09-15")
    k2 = build_idempotency_key(signal=a_signal(), decision=a_decision(), trading_day="2026-09-15")
    assert k1 == k2


def test_different_day_gives_different_key():
    k1 = build_idempotency_key(signal=a_signal(), decision=a_decision(), trading_day="2026-09-15")
    k2 = build_idempotency_key(signal=a_signal(), decision=a_decision(), trading_day="2026-09-16")
    assert k1 != k2


def test_different_quantity_gives_different_key():
    k1 = build_idempotency_key(signal=a_signal(), decision=a_decision("0.5"), trading_day="d")
    k2 = build_idempotency_key(signal=a_signal(), decision=a_decision("0.6"), trading_day="d")
    assert k1 != k2


def test_duplicate_submission_is_blocked_and_demands_kill_switch(audit):
    svc = ExecutionService(broker=fresh_broker(), audit=audit, guard=IdempotencyGuard())
    intent = an_intent()
    first = svc.submit(intent)
    assert first.outcome is SubmissionOutcome.FILLED
    second = svc.submit(intent)
    assert second.outcome is SubmissionOutcome.DUPLICATE_BLOCKED
    assert second.requires_kill_switch


def test_cannot_build_intent_from_rejected_decision():
    rejected = RiskDecision(
        approved=False, decision=Decision.NO_TRADE, reason_code="X", reason_ar="مرفوض",
        checks=(), decided_at_utc=MID_SESSION,
    )
    with pytest.raises(ValueError):
        build_order_intent(
            signal=a_signal(), decision=rejected, trading_day="d",
            instrument_snapshot={}, max_slippage_abs=D("0.01"), now=MID_SESSION,
        )


# --- broker failure modes ---------------------------------------------------

def test_preview_rejection_stops_before_submission(audit):
    broker = fresh_broker(reject_orders=True, reject_reason="INSUFFICIENT_FUNDS")
    svc = ExecutionService(broker=broker, audit=audit)
    res = svc.submit(an_intent())
    assert res.outcome is SubmissionOutcome.PREVIEW_REJECTED
    assert not broker.get_orders("DU0000000")


def test_timeout_never_retries_and_demands_human_check(audit):
    broker = fresh_broker(timeout_on_place=True)
    svc = ExecutionService(broker=broker, audit=audit)
    res = svc.submit(an_intent())
    assert res.outcome is SubmissionOutcome.UNCONFIRMED
    assert res.requires_kill_switch
    # المفتاح مسجَّل => أي محاولة ثانية تُمنع
    assert svc.guard.seen(res.intent.idempotency_key)
    again = svc.submit(an_intent())
    assert again.outcome is SubmissionOutcome.DUPLICATE_BLOCKED


def test_partial_fill_is_reported_as_partial(audit):
    broker = fresh_broker(partial_fill_ratio=D("0.5"))
    svc = ExecutionService(broker=broker, audit=audit)
    res = svc.submit(an_intent())
    assert res.outcome is SubmissionOutcome.PARTIALLY_FILLED
    assert res.order.filled_quantity < res.intent.quantity


def test_excess_slippage_is_caught(audit):
    broker = fresh_broker(slippage=D("1.00"))  # الحد 0.05
    svc = ExecutionService(broker=broker, audit=audit)
    res = svc.submit(an_intent())
    assert res.outcome is SubmissionOutcome.SLIPPAGE_EXCEEDED
    assert res.requires_kill_switch


def test_stop_order_on_fractional_is_rejected_when_unsupported(audit):
    broker = fresh_broker()
    broker.behaviour.stop_on_fractional_supported = False
    intent = an_intent().model_copy(update={"order_type": OrderType.STOP, "quantity": D("0.5")})
    svc = ExecutionService(broker=broker, audit=audit)
    res = svc.submit(intent)
    assert res.outcome is SubmissionOutcome.REJECTED
    assert "STOP_NOT_SUPPORTED_ON_FRACTIONAL_QUANTITY" in res.reason_ar


def test_lost_confirmation_after_fill_is_unconfirmed(audit):
    broker = fresh_broker(lose_confirmation=True)
    svc = ExecutionService(broker=broker, audit=audit)
    res = svc.submit(an_intent())
    # الوسيط نفّذ فعلاً؛ استرجعنا الحقيقة بالقراءة بدل إعادة الإرسال
    assert res.outcome in (SubmissionOutcome.FILLED, SubmissionOutcome.UNCONFIRMED)
    assert len(broker.get_orders("DU0000000")) == 1


def test_every_submission_writes_audit_events(audit):
    svc = ExecutionService(broker=fresh_broker(), audit=audit)
    svc.submit(an_intent())
    actions = [e.action for e in audit.events()]
    assert "ORDER_PREVIEWED" in actions
    assert "ORDER_SUBMITTED" in actions
    assert "ORDER_CONFIRMED" in actions


# --- reconciliation ---------------------------------------------------------

def pos(symbol, qty, at=MID_SESSION):
    return Position(account_id="DU0000000", symbol=symbol, quantity=D(qty),
                    average_cost=D("640"), as_of_utc=at)


def test_reconciliation_matches():
    r = reconcile(local_positions=[pos("SPY", "0.5")], broker_positions=[pos("SPY", "0.5")], now=MID_SESSION)
    assert r.matched and not r.discrepancies_ar


def test_reconciliation_detects_unknown_broker_position():
    r = reconcile(local_positions=[], broker_positions=[pos("AAPL", "1")], now=MID_SESSION)
    assert not r.matched
    assert "غير معروف" in r.discrepancies_ar[0]


def test_reconciliation_detects_missing_broker_position():
    r = reconcile(local_positions=[pos("SPY", "0.5")], broker_positions=[], now=MID_SESSION)
    assert not r.matched


def test_reconciliation_detects_quantity_drift():
    r = reconcile(local_positions=[pos("SPY", "0.5")], broker_positions=[pos("SPY", "0.7")], now=MID_SESSION)
    assert not r.matched
    assert "اختلاف كمية" in r.discrepancies_ar[0]


def test_reconciliation_tolerates_sub_granularity_noise():
    r = reconcile(
        local_positions=[pos("SPY", "0.50000")], broker_positions=[pos("SPY", "0.50005")],
        tolerance=D("0.0001"), now=MID_SESSION,
    )
    assert r.matched
