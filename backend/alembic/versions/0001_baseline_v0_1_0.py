"""Baseline schema as shipped in v0.1.0 (created previously via create_all).

قواعد بيانات موجودة أُنشئت بـ`create_all` في 0.1.0 تُختم بهذه المراجعة
بدل إعادة إنشائها:

    alembic stamp 0001_baseline_v0_1_0
    alembic upgrade head

قاعدة بيانات جديدة تماماً تُنشأ من الصفر بـ`alembic upgrade head`.

Revision ID: 0001_baseline_v0_1_0
Revises:
Create Date: 2026-08-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_baseline_v0_1_0"
down_revision = None
branch_labels = None
depends_on = None

MONEY = sa.Numeric(20, 8)
TS = sa.DateTime(timezone=True)


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    # idempotent: إن كانت الجداول موجودة (create_all سابق) لا نلمسها.
    if _has_table("audit_events"):
        return

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("broker_account_id", sa.String(64), unique=True),
        sa.Column("account_kind", sa.String(16)),
        sa.Column("classification", sa.String(16)),
        sa.Column("base_currency", sa.String(8)),
        sa.Column("baseline_equity", MONEY),
        sa.Column("baseline_approved_by", sa.String(64)),
        sa.Column("baseline_approved_at_utc", TS),
        sa.Column("created_at_utc", TS, nullable=False),
    )
    op.create_table(
        "broker_connections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("adapter_name", sa.String(32)),
        sa.Column("is_live", sa.Boolean),
        sa.Column("connected", sa.Boolean),
        sa.Column("last_success_utc", TS),
        sa.Column("last_failure_utc", TS),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at_utc", TS, nullable=False),
    )
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(24), unique=True),
        sa.Column("conid", sa.String(32)),
        sa.Column("asset_class", sa.String(8)),
        sa.Column("currency", sa.String(8)),
        sa.Column("exchange", sa.String(24)),
        sa.Column("allowlisted", sa.Boolean),
        sa.Column("supports_fractional", sa.Boolean),
        sa.Column("supports_stop_orders", sa.Boolean),
        sa.Column("supports_stop_on_fractional", sa.Boolean),
        sa.Column("verified_at_utc", TS),
        sa.Column("created_at_utc", TS, nullable=False),
    )
    op.create_table(
        "market_bars",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(24), index=True),
        sa.Column("timeframe", sa.String(8)),
        sa.Column("start_utc", TS),
        sa.Column("open", MONEY),
        sa.Column("high", MONEY),
        sa.Column("low", MONEY),
        sa.Column("close", MONEY),
        sa.Column("volume", MONEY),
        sa.Column("source", sa.String(16)),
        sa.UniqueConstraint("symbol", "start_utc", "timeframe"),
    )
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), unique=True),
        sa.Column("description_ar", sa.Text),
        sa.Column("created_at_utc", TS, nullable=False),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, sa.ForeignKey("strategies.id")),
        sa.Column("version", sa.String(24)),
        sa.Column("state", sa.String(16)),
        sa.Column("hypothesis_ar", sa.Text),
        sa.Column("metadata_json", sa.Text),
        sa.Column("backtest_evidence_ar", sa.Text),
        sa.Column("walkforward_evidence_ar", sa.Text),
        sa.Column("approved_by", sa.String(64)),
        sa.Column("approved_at_utc", TS),
        sa.Column("created_at_utc", TS, nullable=False),
        sa.UniqueConstraint("strategy_id", "version"),
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_name", sa.String(64)),
        sa.Column("strategy_version", sa.String(24)),
        sa.Column("symbol", sa.String(24), index=True),
        sa.Column("side", sa.String(8)),
        sa.Column("entry_price", MONEY),
        sa.Column("stop_price", MONEY),
        sa.Column("take_profit_price", MONEY),
        sa.Column("rationale_ar", sa.Text),
        sa.Column("inputs_digest", sa.String(64)),
        sa.Column("generated_at_utc", TS),
    )
    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("signal_id", sa.Integer, sa.ForeignKey("signals.id")),
        sa.Column("approved", sa.Boolean),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("reason_ar", sa.Text),
        sa.Column("checks_json", sa.Text),
        sa.Column("quantity", MONEY),
        sa.Column("expected_risk_usd", MONEY),
        sa.Column("expected_costs_usd", MONEY),
        sa.Column("risk_budget_usd", MONEY),
        sa.Column("constitution_fingerprint", sa.String(64)),
        sa.Column("decided_at_utc", TS),
    )
    op.create_table(
        "order_intents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("idempotency_key", sa.String(64), unique=True, index=True),
        sa.Column("client_order_id", sa.String(64), unique=True),
        sa.Column("risk_decision_id", sa.Integer, sa.ForeignKey("risk_decisions.id")),
        sa.Column("symbol", sa.String(24)),
        sa.Column("side", sa.String(8)),
        sa.Column("order_type", sa.String(16)),
        sa.Column("quantity", MONEY),
        sa.Column("limit_price", MONEY),
        sa.Column("stop_price", MONEY),
        sa.Column("expected_fill_price", MONEY),
        sa.Column("max_slippage_abs", MONEY),
        sa.Column("exit_plan_ar", sa.Text),
        sa.Column("instrument_snapshot_json", sa.Text),
        sa.Column("created_at_utc", TS),
    )
    op.create_table(
        "broker_orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("broker_order_id", sa.String(64), unique=True),
        sa.Column("client_order_id", sa.String(64), index=True),
        sa.Column("symbol", sa.String(24)),
        sa.Column("side", sa.String(8)),
        sa.Column("order_type", sa.String(16)),
        sa.Column("quantity", MONEY),
        sa.Column("filled_quantity", MONEY),
        sa.Column("average_fill_price", MONEY),
        sa.Column("status", sa.String(24)),
        sa.Column("updated_at_utc", TS),
    )
    op.create_table(
        "executions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("execution_id", sa.String(64), unique=True),
        sa.Column("broker_order_id", sa.String(64), index=True),
        sa.Column("symbol", sa.String(24)),
        sa.Column("side", sa.String(8)),
        sa.Column("quantity", MONEY),
        sa.Column("price", MONEY),
        sa.Column("commission", MONEY),
        sa.Column("executed_at_utc", TS),
    )
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.String(64)),
        sa.Column("symbol", sa.String(24)),
        sa.Column("quantity", MONEY),
        sa.Column("average_cost", MONEY),
        sa.Column("opened_at_utc", TS),
        sa.Column("closed_at_utc", TS),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(24)),
        sa.Column("strategy_name", sa.String(64)),
        sa.Column("strategy_version", sa.String(24)),
        sa.Column("entry_price", MONEY),
        sa.Column("exit_price", MONEY),
        sa.Column("quantity", MONEY),
        sa.Column("gross_pnl", MONEY),
        sa.Column("commissions", MONEY),
        sa.Column("slippage", MONEY),
        sa.Column("net_pnl", MONEY),
        sa.Column("opened_at_utc", TS),
        sa.Column("closed_at_utc", TS),
    )
    op.create_table(
        "daily_equity",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trading_day", sa.String(10), unique=True),
        sa.Column("opening_equity", MONEY),
        sa.Column("closing_equity", MONEY),
        sa.Column("realized_pnl", MONEY),
        sa.Column("unrealized_pnl", MONEY),
        sa.Column("settled_cash", MONEY),
        sa.Column("unsettled_cash", MONEY),
    )
    op.create_table(
        "risk_limits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fingerprint", sa.String(64), unique=True),
        sa.Column("limits_json", sa.Text),
        sa.Column("created_at_utc", TS, nullable=False),
    )
    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trigger", sa.String(48)),
        sa.Column("reason_ar", sa.Text),
        sa.Column("policy", sa.String(32)),
        sa.Column("context_json", sa.Text),
        sa.Column("triggered_at_utc", TS),
        sa.Column("reset_approved_by", sa.String(64)),
        sa.Column("reset_reason_ar", sa.Text),
        sa.Column("reset_at_utc", TS),
    )
    op.create_table(
        "system_health",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("component", sa.String(32), index=True),
        sa.Column("ok", sa.Boolean),
        sa.Column("detail_ar", sa.Text),
        sa.Column("checked_at_utc", TS),
    )
    op.create_table(
        "news_blackouts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(24)),
        sa.Column("title_ar", sa.Text),
        sa.Column("source", sa.String(128)),
        sa.Column("starts_utc", TS),
        sa.Column("ends_utc", TS),
        sa.Column("confirmed_by", sa.String(64)),
        sa.Column("created_at_utc", TS, nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("timestamp_utc", TS, index=True),
        sa.Column("actor", sa.String(32)),
        sa.Column("action", sa.String(48), index=True),
        sa.Column("decision", sa.String(64)),
        sa.Column("reason_ar", sa.Text),
        sa.Column("source", sa.String(64)),
        sa.Column("before_json", sa.Text),
        sa.Column("after_json", sa.Text),
        sa.Column("related_id", sa.String(64), index=True),
        sa.Column("previous_hash", sa.String(64)),
        sa.Column("entry_hash", sa.String(64), unique=True),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(48)),
        sa.Column("approved_by", sa.String(64)),
        sa.Column("phrase_verified", sa.Boolean),
        sa.Column("reason_ar", sa.Text),
        sa.Column("payload_json", sa.Text),
        sa.Column("approved_at_utc", TS),
    )
    op.create_table(
        "configuration_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fingerprint", sa.String(64), unique=True),
        sa.Column("payload_json", sa.Text),
        sa.Column("note_ar", sa.Text),
        sa.Column("created_at_utc", TS, nullable=False),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "لا تراجع عن المخطط الأساسي — استعيدي من نسخة احتياطية بدلاً من ذلك."
    )
