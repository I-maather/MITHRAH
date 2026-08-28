"""Capital.com migration — broker context, CFD economics, execution certainty, system state.

يضيف فقط. لا يحذف عموداً ولا جدولاً، فبيانات 0.1.0 تبقى سليمة.

Revision ID: 0002_capital_com_migration
Revises: 0001_baseline_v0_1_0
Create Date: 2026-08-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_capital_com_migration"
down_revision = "0001_baseline_v0_1_0"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(20, 8)
TS = sa.DateTime(timezone=True)


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    # --- سياق الوسيط واقتصاديات CFD على نيّات الأوامر ---------------------
    for column in (
        sa.Column("broker", sa.String(24), server_default="MOCK"),
        sa.Column("broker_environment", sa.String(8), server_default="demo"),
        sa.Column("account_masked", sa.String(24), server_default=""),
        sa.Column("epic", sa.String(32), server_default=""),
        sa.Column("broker_quantity", MONEY),
        sa.Column("notional_exposure", MONEY),
        sa.Column("margin_estimate", MONEY),
        sa.Column("all_in_risk", MONEY),
        sa.Column("spread_estimate", MONEY),
        sa.Column("stop_kind", sa.String(16), server_default="NORMAL"),
        sa.Column("stop_distance", MONEY),
        sa.Column("gsl_premium", MONEY),
        sa.Column("slippage_reserve", MONEY),
        sa.Column("strategy_name", sa.String(64), server_default=""),
        sa.Column("strategy_version", sa.String(24), server_default=""),
        sa.Column("risk_constitution_version", sa.String(16), server_default=""),
        sa.Column("risk_mode", sa.String(24), server_default="VALIDATION"),
        sa.Column("owner_authorization_reference", sa.String(64), server_default=""),
        sa.Column("market_data_timestamp_utc", TS),
    ):
        _add("order_intents", column)

    # --- يقين التنفيذ على أوامر الوسيط ------------------------------------
    for column in (
        sa.Column("deal_reference", sa.String(64)),
        sa.Column("broker_deal_id", sa.String(64)),
        sa.Column("broker_confirmation_state", sa.String(24), server_default="PENDING"),
        sa.Column("reconciliation_state", sa.String(24), server_default="UNRECONCILED"),
        sa.Column("execution_uncertainty", sa.String(24), server_default="NONE"),
    ):
        _add("broker_orders", column)

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- محاولات التنفيذ: ما يمنع إعادة الإرسال الأعمى بعد انقطاع ---------
    if not inspector.has_table("execution_attempts"):
        op.create_table(
            "execution_attempts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("idempotency_key", sa.String(64), unique=True, index=True),
            sa.Column("broker", sa.String(24), index=True),
            sa.Column("broker_environment", sa.String(8)),
            sa.Column("epic", sa.String(32)),
            sa.Column("deal_reference", sa.String(64), index=True),
            sa.Column("broker_deal_id", sa.String(64)),
            sa.Column("uncertainty", sa.String(24), server_default="PENDING_CONFIRMATION", index=True),
            sa.Column("resolved", sa.Boolean, server_default=sa.false(), index=True),
            sa.Column("resolution_note_ar", sa.Text, server_default=""),
            sa.Column("attempted_at_utc", TS),
            sa.Column("resolved_at_utc", TS),
        )

    # --- الحالة الدائمة: Kill Switch يبقى مفعّلاً عبر إعادة التشغيل --------
    if not inspector.has_table("system_state"):
        op.create_table(
            "system_state",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("trading_locked", sa.Boolean, server_default=sa.true()),
            sa.Column("kill_switch_active", sa.Boolean, server_default=sa.false()),
            sa.Column("kill_switch_trigger", sa.String(48), server_default=""),
            sa.Column("kill_switch_reason_ar", sa.Text, server_default=""),
            sa.Column("risk_mode", sa.String(24), server_default="VALIDATION"),
            sa.Column("risk_constitution_version", sa.String(16), server_default=""),
            sa.Column("broker", sa.String(24), server_default="CAPITAL_COM"),
            sa.Column("broker_environment", sa.String(8), server_default="demo"),
            sa.Column("account_masked", sa.String(24), server_default=""),
            sa.Column("consecutive_losses", sa.Integer, server_default="0"),
            sa.Column("lifetime_entry_orders", sa.Integer, server_default="0"),
            sa.Column("updated_at_utc", TS),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("system_state"):
        op.drop_table("system_state")
    if inspector.has_table("execution_attempts"):
        op.drop_table("execution_attempts")
    # الأعمدة المضافة تبقى: حذفها في SQLite يتطلب إعادة بناء الجدول،
    # وهي غير ضارة لو بقيت.
