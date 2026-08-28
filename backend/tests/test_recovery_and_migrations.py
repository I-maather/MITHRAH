"""
الاسترداد عند الإقلاع والهجرات.

المبدأ المُختبَر: **إعادة التشغيل لا تفتح شيئاً أبداً.**
"""
from __future__ import annotations

import subprocess
import sys
from datetime import timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.clock import now_utc
from app.contracts import ExecutionUncertainty, Position
from app.db.models import Base, SystemStateRow
from app.db.recovery import (
    StartupVerdict,
    load_or_create_state,
    record_attempt,
    resolve_attempt,
    run_startup_recovery,
    unresolved_attempts,
)
from app.money import D
from app.risk.constitution import CONSTITUTION_VERSION

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        yield s


def a_position(symbol: str = "EURUSD", quantity: str = "100") -> Position:
    return Position(
        account_id="****3456", symbol=symbol, quantity=D(quantity),
        average_cost=D("1.08546"), as_of_utc=now_utc(),
    )


# --- الحالة الدائمة ----------------------------------------------------------

def test_default_state_is_locked_and_validation(session):
    state = load_or_create_state(session)
    assert state.trading_locked is True
    assert state.kill_switch_active is False
    assert state.risk_mode == "VALIDATION"
    assert state.risk_constitution_version == CONSTITUTION_VERSION


def test_startup_never_unlocks_trading(session):
    report = run_startup_recovery(session)
    assert report.trading_locked is True
    assert report.allows_new_entries is False
    assert report.verdict is StartupVerdict.READY_TRADING_STILL_LOCKED
    assert any("قرار بشري" in n for n in report.notes_ar)


def test_kill_switch_survives_restart(session):
    state = load_or_create_state(session)
    state.kill_switch_active = True
    state.kill_switch_trigger = "RECONCILIATION_MISMATCH"
    state.kill_switch_reason_ar = "اختلاف مركز"
    session.commit()

    report = run_startup_recovery(session)
    assert report.verdict is StartupVerdict.LOCKED_KILL_SWITCH
    assert report.kill_switch_active is True
    assert any("لا تُلغي Kill Switch" in n for n in report.notes_ar)


def test_constitution_version_change_is_flagged(session):
    state = load_or_create_state(session)
    state.risk_constitution_version = "0.1.0"
    session.commit()
    report = run_startup_recovery(session)
    assert any("دستور المخاطر تغيّر" in n for n in report.notes_ar)


# --- محاولات التنفيذ غير المحسومة --------------------------------------------

def test_unresolved_attempt_blocks_startup(session):
    record_attempt(
        session, idempotency_key="k-1", broker="CAPITAL_COM",
        broker_environment="demo", epic="EURUSD", deal_reference="ref-1",
    )
    report = run_startup_recovery(session)
    assert report.verdict is StartupVerdict.LOCKED_UNKNOWN_EXECUTION
    assert "k-1" in report.unresolved_attempts
    assert any("لا بإعادة الإرسال" in n for n in report.notes_ar)


def test_resolved_attempt_no_longer_blocks(session):
    attempt = record_attempt(
        session, idempotency_key="k-2", broker="CAPITAL_COM",
        broker_environment="demo", epic="EURUSD",
    )
    resolve_attempt(
        session, attempt, uncertainty=ExecutionUncertainty.RESOLVED_ABSENT,
        note_ar="لا مركز لدى الوسيط",
    )
    assert unresolved_attempts(session) == []
    assert run_startup_recovery(session).verdict is StartupVerdict.READY_TRADING_STILL_LOCKED


def test_attempt_is_recorded_before_submission_by_design(session):
    """
    التسجيل قبل الإرسال هو ما يجعل إعادة الإرسال الأعمى مستحيلة:
    حتى لو مات المسار بعد الإرسال مباشرة، المحاولة موجودة.
    """
    attempt = record_attempt(
        session, idempotency_key="k-3", broker="CAPITAL_COM",
        broker_environment="demo", epic="EURUSD",
    )
    assert attempt.uncertainty == ExecutionUncertainty.PENDING_CONFIRMATION.value
    assert attempt.resolved is False


def test_duplicate_attempt_key_is_rejected_by_the_database(session):
    record_attempt(
        session, idempotency_key="k-4", broker="CAPITAL_COM",
        broker_environment="demo", epic="EURUSD",
    )
    with pytest.raises(Exception):
        record_attempt(
            session, idempotency_key="k-4", broker="CAPITAL_COM",
            broker_environment="demo", epic="EURUSD",
        )


# --- المطابقة عند الإقلاع -----------------------------------------------------

def test_startup_reconciles_and_blocks_on_mismatch(session):
    report = run_startup_recovery(
        session,
        fetch_broker_positions=lambda: [a_position()],
        local_positions=[],
    )
    assert report.verdict is StartupVerdict.LOCKED_PENDING_RECONCILIATION
    assert report.reconciliation_problems


def test_startup_passes_reconciliation_when_states_agree(session):
    report = run_startup_recovery(
        session,
        fetch_broker_positions=lambda: [a_position()],
        local_positions=[a_position()],
    )
    assert report.verdict is StartupVerdict.READY_TRADING_STILL_LOCKED
    assert not report.reconciliation_problems


def test_broker_unreachable_at_startup_keeps_everything_locked(session):
    def boom():
        raise RuntimeError("broker down")

    report = run_startup_recovery(session, fetch_broker_positions=boom)
    assert report.verdict is StartupVerdict.LOCKED_PENDING_RECONCILIATION
    assert report.trading_locked is True


def test_startup_report_is_serialisable(session):
    report = run_startup_recovery(session)
    payload = report.as_dict()
    assert payload["allows_new_entries"] is False
    assert payload["trading_locked"] is True


# --- الهجرات ------------------------------------------------------------------

def test_alembic_upgrade_creates_every_table(tmp_path):
    db = tmp_path / "migrate.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "DATABASE_URL": f"sqlite:///{db}",
             "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{db}", future=True)
    tables = set(inspect(engine).get_table_names())
    assert {"execution_attempts", "system_state", "order_intents", "audit_events"} <= tables


def test_new_columns_exist_after_migration(tmp_path):
    db = tmp_path / "migrate2.db"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "DATABASE_URL": f"sqlite:///{db}",
             "HOME": str(tmp_path)},
        capture_output=True, text=True, check=True,
    )
    engine = create_engine(f"sqlite:///{db}", future=True)
    inspector = inspect(engine)
    intents = {c["name"] for c in inspector.get_columns("order_intents")}
    orders = {c["name"] for c in inspector.get_columns("broker_orders")}
    assert {
        "broker", "broker_environment", "account_masked", "epic", "broker_quantity",
        "notional_exposure", "margin_estimate", "all_in_risk", "spread_estimate",
        "stop_kind", "stop_distance", "gsl_premium", "slippage_reserve",
        "strategy_version", "risk_constitution_version", "owner_authorization_reference",
        "market_data_timestamp_utc",
    } <= intents
    assert {
        "deal_reference", "broker_deal_id", "broker_confirmation_state",
        "reconciliation_state", "execution_uncertainty",
    } <= orders


def test_migration_preserves_existing_rows(tmp_path):
    """هجرة إضافية لا تفقد بيانات 0.1.0."""
    db = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        s.add(SystemStateRow(updated_at_utc=now_utc()))
        s.commit()
        count_before = s.query(SystemStateRow).count()
    assert count_before == 1

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "0001_baseline_v0_1_0"],
        cwd=BACKEND_ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "DATABASE_URL": f"sqlite:///{db}",
             "HOME": str(tmp_path)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "DATABASE_URL": f"sqlite:///{db}",
             "HOME": str(tmp_path)},
        capture_output=True, text=True, check=True,
    )
    with Session(engine, future=True) as s:
        assert s.query(SystemStateRow).count() == 1
