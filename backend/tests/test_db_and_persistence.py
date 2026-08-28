from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.audit.log import Actor, AuditAction, AuditLog, verify_chain
from app.audit.sqlstore import SqlAuditStore
from app.db.models import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        yield s


def test_all_required_tables_exist(session):
    required = {
        "accounts", "broker_connections", "instruments", "market_bars", "strategies",
        "strategy_versions", "signals", "risk_decisions", "order_intents", "broker_orders",
        "executions", "positions", "trades", "daily_equity", "risk_limits",
        "kill_switch_events", "system_health", "news_blackouts", "audit_events",
        "approvals", "configuration_versions",
    }
    existing = set(Base.metadata.tables)
    assert required <= existing, f"جداول ناقصة: {required - existing}"


def test_audit_persists_and_chain_verifies(session):
    log = AuditLog(SqlAuditStore(session))
    for i in range(4):
        log.record(actor=Actor.PIPELINE, action=AuditAction.NO_TRADE, decision=f"D{i}",
                   reason_ar=f"سبب {i}", source="test")
    assert verify_chain(log.events()).ok


def test_chain_survives_reopening_the_store(session):
    log1 = AuditLog(SqlAuditStore(session))
    log1.record(actor=Actor.SYSTEM, action=AuditAction.SYSTEM_START, decision="OK",
                reason_ar="بدء", source="test")
    log2 = AuditLog(SqlAuditStore(session))  # كأنها عملية جديدة بعد إعادة تشغيل
    log2.record(actor=Actor.SYSTEM, action=AuditAction.HEALTH_CHECK, decision="OK",
                reason_ar="فحص", source="test")
    events = log2.events()
    assert len(events) == 2
    assert events[1].previous_hash == events[0].entry_hash
    assert verify_chain(events).ok


def test_direct_db_tampering_is_detected(session):
    """
    نُثبت بالتجربة ما نقوله في KNOWN_LIMITATIONS: التعديل المباشر ممكن،
    لكنه *يُكتشف*. هذا هو مستوى الحماية الحقيقي، ولا ندّعي أكثر منه.
    """
    log = AuditLog(SqlAuditStore(session))
    for i in range(3):
        log.record(actor=Actor.PIPELINE, action=AuditAction.NO_TRADE, decision=f"D{i}",
                   reason_ar=f"سبب {i}", source="test")
    session.execute(text("UPDATE audit_events SET reason_ar='مزوّر' WHERE sequence=2"))
    session.commit()
    result = verify_chain(AuditLog(SqlAuditStore(session)).events())
    assert not result.ok
    assert result.first_bad_sequence == 2


def test_duplicate_idempotency_key_is_rejected_by_the_database(session):
    from datetime import datetime, timezone

    from app.db.models import OrderIntentRow

    def row(key):
        return OrderIntentRow(
            idempotency_key=key, client_order_id=f"C-{key}", symbol="SPY", side="BUY",
            order_type="LMT", quantity=1, expected_fill_price=640, max_slippage_abs=0.05,
            exit_plan_ar="خطة", instrument_snapshot_json="{}",
            created_at_utc=datetime.now(timezone.utc),
        )

    session.add(row("K1"))
    session.commit()
    session.add(row("K1"))
    with pytest.raises(Exception):
        session.commit()
