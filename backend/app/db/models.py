"""
SQLAlchemy models.

الهدف من PostgreSQL في الإنتاج: القيود والـconstraints والنسخ الاحتياطي.
SQLite مستعمل في الاختبارات والتشغيل المحلي الأول (انظر ADR-002).

جدول audit_events لا يوجد له في التطبيق أي مسار UPDATE أو DELETE —
هذا مفروض بالكود (AuditLog) وبـtrigger في migration الإنتاج.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MONEY = Numeric(20, 8)


class Base(DeclarativeBase):
    pass


class TimestampedMixin:
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Account(Base, TimestampedMixin):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    broker_account_id: Mapped[str] = mapped_column(String(64), unique=True)
    account_kind: Mapped[str] = mapped_column(String(16))
    classification: Mapped[str] = mapped_column(String(16))
    base_currency: Mapped[str] = mapped_column(String(8), default="USD")
    baseline_equity: Mapped[Decimal] = mapped_column(MONEY)
    baseline_approved_by: Mapped[str] = mapped_column(String(64), default="")
    baseline_approved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrokerConnection(Base, TimestampedMixin):
    __tablename__ = "broker_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    adapter_name: Mapped[str] = mapped_column(String(32))
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")


class Instrument(Base, TimestampedMixin):
    __tablename__ = "instruments"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), unique=True)
    conid: Mapped[str] = mapped_column(String(32), default="")
    asset_class: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(8))
    exchange: Mapped[str] = mapped_column(String(24))
    allowlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_fractional: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_stop_orders: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_stop_on_fractional: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (UniqueConstraint("symbol", "start_utc", "timeframe"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[Decimal] = mapped_column(MONEY)
    high: Mapped[Decimal] = mapped_column(MONEY)
    low: Mapped[Decimal] = mapped_column(MONEY)
    close: Mapped[Decimal] = mapped_column(MONEY)
    volume: Mapped[Decimal] = mapped_column(MONEY)
    source: Mapped[str] = mapped_column(String(16))


class Strategy(Base, TimestampedMixin):
    __tablename__ = "strategies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description_ar: Mapped[str] = mapped_column(Text, default="")


class StrategyVersion(Base, TimestampedMixin):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    version: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(16), default="DRAFT")
    hypothesis_ar: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text)
    backtest_evidence_ar: Mapped[str] = mapped_column(Text, default="")
    walkforward_evidence_ar: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str] = mapped_column(String(64), default="")
    approved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(24))
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    side: Mapped[str] = mapped_column(String(8))
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    stop_price: Mapped[Decimal] = mapped_column(MONEY)
    take_profit_price: Mapped[Decimal] = mapped_column(MONEY)
    rationale_ar: Mapped[str] = mapped_column(Text)
    inputs_digest: Mapped[str] = mapped_column(String(64))
    generated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskDecisionRow(Base):
    __tablename__ = "risk_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    approved: Mapped[bool] = mapped_column(Boolean)
    reason_code: Mapped[str] = mapped_column(String(64), default="")
    reason_ar: Mapped[str] = mapped_column(Text)
    checks_json: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(MONEY, default=0)
    expected_risk_usd: Mapped[Decimal] = mapped_column(MONEY, default=0)
    expected_costs_usd: Mapped[Decimal] = mapped_column(MONEY, default=0)
    risk_budget_usd: Mapped[Decimal] = mapped_column(MONEY, default=0)
    constitution_fingerprint: Mapped[str] = mapped_column(String(64))
    decided_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderIntentRow(Base):
    __tablename__ = "order_intents"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    # --- سياق الوسيط (0.2.0) -------------------------------------------
    broker: Mapped[str] = mapped_column(String(24), default="MOCK", index=True)
    broker_environment: Mapped[str] = mapped_column(String(8), default="demo")
    account_masked: Mapped[str] = mapped_column(String(24), default="")
    epic: Mapped[str] = mapped_column(String(32), default="")
    # --- اقتصاديات CFD: ثلاث قيم منفصلة لا يجوز الخلط بينها -------------
    broker_quantity: Mapped[Decimal | None] = mapped_column(MONEY)
    notional_exposure: Mapped[Decimal | None] = mapped_column(MONEY)
    margin_estimate: Mapped[Decimal | None] = mapped_column(MONEY)
    all_in_risk: Mapped[Decimal | None] = mapped_column(MONEY)
    spread_estimate: Mapped[Decimal | None] = mapped_column(MONEY)
    stop_kind: Mapped[str] = mapped_column(String(16), default="NORMAL")
    stop_distance: Mapped[Decimal | None] = mapped_column(MONEY)
    gsl_premium: Mapped[Decimal | None] = mapped_column(MONEY)
    slippage_reserve: Mapped[Decimal | None] = mapped_column(MONEY)
    # --- الحوكمة --------------------------------------------------------
    strategy_name: Mapped[str] = mapped_column(String(64), default="")
    strategy_version: Mapped[str] = mapped_column(String(24), default="")
    risk_constitution_version: Mapped[str] = mapped_column(String(16), default="")
    risk_mode: Mapped[str] = mapped_column(String(24), default="VALIDATION")
    owner_authorization_reference: Mapped[str] = mapped_column(String(64), default="")
    market_data_timestamp_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    risk_decision_id: Mapped[int | None] = mapped_column(ForeignKey("risk_decisions.id"))
    symbol: Mapped[str] = mapped_column(String(24))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(MONEY)
    limit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    stop_price: Mapped[Decimal | None] = mapped_column(MONEY)
    expected_fill_price: Mapped[Decimal] = mapped_column(MONEY)
    max_slippage_abs: Mapped[Decimal] = mapped_column(MONEY)
    exit_plan_ar: Mapped[str] = mapped_column(Text)
    instrument_snapshot_json: Mapped[str] = mapped_column(Text)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BrokerOrderRow(Base):
    __tablename__ = "broker_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    broker_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    deal_reference: Mapped[str | None] = mapped_column(String(64), index=True)
    broker_deal_id: Mapped[str | None] = mapped_column(String(64), index=True)
    broker_confirmation_state: Mapped[str] = mapped_column(String(24), default="PENDING")
    reconciliation_state: Mapped[str] = mapped_column(String(24), default="UNRECONCILED")
    execution_uncertainty: Mapped[str] = mapped_column(String(24), default="NONE")
    client_order_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(24))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(MONEY)
    filled_quantity: Mapped[Decimal] = mapped_column(MONEY, default=0)
    average_fill_price: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(24))
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutionRow(Base):
    __tablename__ = "executions"
    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), unique=True)
    broker_order_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(24))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(MONEY)
    price: Mapped[Decimal] = mapped_column(MONEY)
    commission: Mapped[Decimal] = mapped_column(MONEY)
    executed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PositionRow(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(24))
    quantity: Mapped[Decimal] = mapped_column(MONEY)
    average_cost: Mapped[Decimal] = mapped_column(MONEY)
    opened_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PositionBookRow(Base):
    """
    **دفترُ المراكز الدائم** — هويّةُ الوسيط أوّلاً، لا الرمز.

    ## لماذا جدولٌ جديد بجانب `positions`

    `positions` جدولٌ محاسبيّ مفتاحه الرمز والحساب، ولم يُكتَب فيه شيء قط:
    يوم 2026-09-04 كان الحساب يحمل خمسة مراكز والجدول فارغاً، فقرأ سقفُ
    العدد صفراً. وإصلاح ذلك كان قراءةَ الوسيط كلَّ دورة (C2). لكن القراءة
    وحدها لا تنجو من إعادة تشغيل: ما لم يُكتَب لا يُقارَن بعد الإقلاع، ولا
    يُعرَف مركزٌ **ظهر بيننا** من مركزٍ كان موجوداً.

    ## ولماذا `broker_deal_id` هو المفتاح

    كابيتال يسمح بعدّة مراكز على الأداة الواحدة — وكان على GBPUSD ثلاثة في
    اليوم نفسه. فمفتاحٌ بالرمز يُسقط أحدَها على الآخر ويقول «مطابَق» وفي
    الحساب ثلاثة أضعاف. هويّةُ المركز عند الوسيط هي المفتاح الوحيد الذي لا
    يلتبس.

    ## والنسب

    `client_order_id` → `deal_reference` → `broker_deal_id` سلسلةٌ تُقرأ من
    `broker_orders`، ومنها يُعرَف أيُّ قرارٍ وأيُّ استراتيجيةٍ بأيّ إصدار
    فتحت المركز. ما لا يُنسَب يُسمّى `UNATTRIBUTED` صراحةً — ولا يُخمَّن.
    """

    __tablename__ = "position_book"
    id: Mapped[int] = mapped_column(primary_key=True)
    #: هويّة المركز لدى الوسيط — المفتاح الحقيقي.
    broker_deal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    #: موقّعة: السالب بيع.
    quantity: Mapped[Decimal] = mapped_column(MONEY)
    entry_price: Mapped[Decimal | None] = mapped_column(MONEY)
    stop_price: Mapped[Decimal | None] = mapped_column(MONEY)
    take_profit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(8), default="")
    #: OPEN · CLOSED · ORPHANED
    state: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    #: STRATEGY · COMMISSIONING · UNATTRIBUTED
    kind: Mapped[str] = mapped_column(String(24), default="UNATTRIBUTED")
    #: LINKED إن وُجد أمرٌ يربطه بقرار، وإلا UNLINKED. لا تخمين بينهما.
    attribution: Mapped[str] = mapped_column(String(16), default="UNLINKED")
    deal_reference: Mapped[str | None] = mapped_column(String(64), index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    risk_decision_id: Mapped[int | None] = mapped_column(ForeignKey("risk_decisions.id"))
    strategy_name: Mapped[str] = mapped_column(String(64), default="")
    strategy_version: Mapped[str] = mapped_column(String(24), default="")
    opened_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: أوّل دورةٍ رأيناه فيها — يفرّق ما فُتح بيننا عمّا وجدناه.
    first_seen_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realised_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    #: آخر إقلاعٍ رآه مفتوحاً — يجيب «هل نجا المركز إعادة التشغيل؟».
    seen_after_restart: Mapped[bool] = mapped_column(default=False)


class TradeRow(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24))
    strategy_name: Mapped[str] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(24))
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    exit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    quantity: Mapped[Decimal] = mapped_column(MONEY)
    gross_pnl: Mapped[Decimal] = mapped_column(MONEY, default=0)
    commissions: Mapped[Decimal] = mapped_column(MONEY, default=0)
    slippage: Mapped[Decimal] = mapped_column(MONEY, default=0)
    net_pnl: Mapped[Decimal] = mapped_column(MONEY, default=0)
    opened_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyEquity(Base):
    __tablename__ = "daily_equity"
    id: Mapped[int] = mapped_column(primary_key=True)
    trading_day: Mapped[str] = mapped_column(String(10), unique=True)
    opening_equity: Mapped[Decimal] = mapped_column(MONEY)
    closing_equity: Mapped[Decimal] = mapped_column(MONEY)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=0)
    settled_cash: Mapped[Decimal] = mapped_column(MONEY, default=0)
    unsettled_cash: Mapped[Decimal] = mapped_column(MONEY, default=0)


class RiskLimitRow(Base, TimestampedMixin):
    """لقطة تاريخية من الحدود السارية. للتوثيق فقط — المصدر هو constitution.py."""

    __tablename__ = "risk_limits"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    limits_json: Mapped[str] = mapped_column(Text)


class KillSwitchEventRow(Base):
    __tablename__ = "kill_switch_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(48))
    reason_ar: Mapped[str] = mapped_column(Text)
    policy: Mapped[str] = mapped_column(String(32))
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    triggered_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reset_approved_by: Mapped[str] = mapped_column(String(64), default="")
    reset_reason_ar: Mapped[str] = mapped_column(Text, default="")
    reset_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemHealthRow(Base):
    __tablename__ = "system_health"
    id: Mapped[int] = mapped_column(primary_key=True)
    component: Mapped[str] = mapped_column(String(32), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    detail_ar: Mapped[str] = mapped_column(Text, default="")
    checked_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NewsBlackoutRow(Base, TimestampedMixin):
    __tablename__ = "news_blackouts"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(24))
    title_ar: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(128))
    starts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str] = mapped_column(String(64), default="")


class AuditEventRow(Base):
    """APPEND ONLY. لا UPDATE ولا DELETE من التطبيق."""

    __tablename__ = "audit_events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(48), index=True)
    decision: Mapped[str] = mapped_column(String(64))
    reason_ar: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64))
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    related_id: Mapped[str | None] = mapped_column(String(64), index=True)
    previous_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))  # LIVE_ENABLE / FIRST_ORDER / KILL_RESET / STRATEGY
    approved_by: Mapped[str] = mapped_column(String(64))
    phrase_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_ar: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    approved_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConfigurationVersion(Base, TimestampedMixin):
    __tablename__ = "configuration_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    payload_json: Mapped[str] = mapped_column(Text)
    note_ar: Mapped[str] = mapped_column(Text, default="")


class ExecutionAttempt(Base):
    """
    كل محاولة إرسال — حتى الغامضة. هذا الجدول هو ما يمنع إعادة الإرسال
    الأعمى بعد انقطاع: عند الإقلاع نبحث عن محاولة بلا حسم ونمنع أي دخول
    جديد حتى تُحسم بالمطابقة مع الوسيط.
    """

    __tablename__ = "execution_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    broker: Mapped[str] = mapped_column(String(24), index=True)
    broker_environment: Mapped[str] = mapped_column(String(8))
    epic: Mapped[str] = mapped_column(String(32))
    deal_reference: Mapped[str | None] = mapped_column(String(64), index=True)
    broker_deal_id: Mapped[str | None] = mapped_column(String(64))
    uncertainty: Mapped[str] = mapped_column(String(24), default="PENDING_CONFIRMATION", index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolution_note_ar: Mapped[str] = mapped_column(Text, default="")
    attempted_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemStateRow(Base):
    """
    حالة النظام الدائمة عبر إعادات التشغيل.

    القيم الافتراضية هي الحالة الآمنة: التداول مقفل، والوضع VALIDATION.
    إعادة التشغيل لا تفتح شيئاً أبداً.
    """

    __tablename__ = "system_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    trading_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean, default=False)
    kill_switch_trigger: Mapped[str] = mapped_column(String(48), default="")
    kill_switch_reason_ar: Mapped[str] = mapped_column(Text, default="")
    risk_mode: Mapped[str] = mapped_column(String(24), default="VALIDATION")
    risk_constitution_version: Mapped[str] = mapped_column(String(16), default="")
    broker: Mapped[str] = mapped_column(String(24), default="CAPITAL_COM")
    broker_environment: Mapped[str] = mapped_column(String(8), default="demo")
    account_masked: Mapped[str] = mapped_column(String(24), default="")
    consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    lifetime_entry_orders: Mapped[int] = mapped_column(Integer, default=0)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
