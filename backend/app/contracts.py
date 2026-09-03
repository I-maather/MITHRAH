"""
Data contracts — عقود البيانات بين كل مكونات النظام.

كل حدود بين وحدتين تمر عبر نموذج Pydantic هنا. لا dict عشوائية.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Decision(str, Enum):
    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"
    HALTED = "HALTED"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP LMT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PREVIEWED = "PREVIEWED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class DataSource(str, Enum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    SNAPSHOT = "SNAPSHOT"
    HISTORICAL = "HISTORICAL"
    MOCK = "MOCK"


class AssetClass(str, Enum):
    STOCK = "STK"
    ETF = "ETF"
    CFD_CURRENCY = "CFD_CURRENCY"
    CFD_COMMODITY = "CFD_COMMODITY"
    CFD_INDEX = "CFD_INDEX"


class Broker(str, Enum):
    """
    الوسطاء المعروفون للنظام. النظام محايد تجاه الوسيط:
    كل حساب تكلفة ومخاطرة يُوجَّه حسب هذه القيمة.
    """

    MOCK = "MOCK"
    CAPITAL_COM = "CAPITAL_COM"
    IBKR = "IBKR"


class StopKind(str, Enum):
    NONE = "NONE"
    NORMAL = "NORMAL"
    GUARANTEED = "GUARANTEED"


class ExecutionUncertainty(str, Enum):
    """
    حالة اليقين من التنفيذ. `UNKNOWN` ليست فشلاً — هي أخطر من الفشل،
    لأنها تعني أن أمراً قد يكون نُفِّذ دون أن نعلم.
    """

    NONE = "NONE"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    UNKNOWN = "UNKNOWN"
    RESOLVED_FILLED = "RESOLVED_FILLED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    RESOLVED_ABSENT = "RESOLVED_ABSENT"


class StrategyState(str, Enum):
    DRAFT = "DRAFT"
    RESEARCH = "RESEARCH"
    APPROVED = "APPROVED"
    DISABLED = "DISABLED"


class Base(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

class Quote(Base):
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    timestamp_utc: datetime
    source: DataSource
    received_at_utc: datetime

    @field_validator("timestamp_utc", "received_at_utc")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return v

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.ask + self.bid) / Decimal("2")

    def age_seconds(self, now: datetime) -> float:
        return (now - self.timestamp_utc).total_seconds()


class Bar(Base):
    symbol: str
    start_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: DataSource


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

class AccountKind(str, Enum):
    CASH = "CASH"
    MARGIN = "MARGIN"
    UNKNOWN = "UNKNOWN"


class ClientClassification(str, Enum):
    RETAIL = "RETAIL"
    PROFESSIONAL = "PROFESSIONAL"
    UNKNOWN = "UNKNOWN"


class Balances(Base):
    account_id: str
    currency: str = "USD"
    total_cash: Decimal
    settled_cash: Decimal
    unsettled_cash: Decimal
    committed_cash: Decimal
    net_liquidation: Decimal
    as_of_utc: datetime

    @property
    def available_for_new_trade(self) -> Decimal:
        return max(Decimal("0"), self.settled_cash - self.committed_cash)


class TradingPermissions(Base):
    account_id: str
    account_kind: AccountKind
    classification: ClientClassification
    us_stocks: bool = False
    fractional_enabled: bool = False
    options: bool = False
    futures: bool = False
    forex: bool = False
    crypto: bool = False
    short_selling: bool = False
    margin_enabled: bool = False
    as_of_utc: datetime

    def violates_cfd_policy(self) -> list[str]:
        """
        سياسة حساب CFD بالرافعة — **مقابلة لسياسة V1 لا تخفيفٌ لها**.

        ## لماذا سياستان

        `violates_v1_policy` تشترط حساباً نقدياً بلا هامش ولا فوركس ولا بيعٍ
        على المكشوف، وصلاحية أسهم أمريكية. وهي صحيحةٌ تماماً لأسهم IBKR —
        وتَرفض حساب كابيتال في كل بند: فالـCFD هامشٌ بطبيعته، والفوركس هو
        ما نتداوله، والبيع نصفُ الاستراتيجيات.

        وقد كتب محوّل كابيتال ذلك بصراحة منذ يومه الأول: «سياسة CFD الخاصة
        تُطبَّق في eligibility» — **ولم تُكتب قط**. فبقيت الأدوات الأربع
        مرفوضةً بسياسةٍ لوسيطٍ آخر.

        ## وما تشترطه هذه

        الرافعة والفوركس والبيع **متوقَّعة** هنا لا مخالفات. والمشترَط:
        تصنيفٌ تجزئة (فتلزم حمايات التجزئة: حدّ الرافعة وحماية الرصيد
        السالب)، وصلاحية فوركس فعلاً، **وإطفاء ما هو خارج النطاق** —
        الخيارات والعقود الآجلة والكريبتو. إغفالُ هذه الثلاث يجعل السياسة
        تُجيز حساباً يستطيع ما لم يُختبَر عليه شيء.
        """
        problems: list[str] = []
        if self.classification is not ClientClassification.RETAIL:
            problems.append("التصنيف ليس Retail — تسقط حمايات التجزئة")
        if not self.forex:
            problems.append("صلاحية الفوركس/CFD غير مفعّلة")
        if self.options:
            problems.append("Options مفعّلة — خارج النطاق")
        if self.futures:
            problems.append("Futures مفعّلة — خارج النطاق")
        if self.crypto:
            problems.append("Crypto مفعّلة — خارج النطاق")
        return problems

    def violates_v1_policy(self) -> list[str]:
        """قائمة المخالفات لسياسة V1. أي عنصر هنا يمنع الانتقال إلى Live."""
        problems: list[str] = []
        if self.account_kind is not AccountKind.CASH:
            problems.append("الحساب ليس Cash Account")
        if self.classification is not ClientClassification.RETAIL:
            problems.append("التصنيف ليس Retail")
        if self.margin_enabled:
            problems.append("Margin مفعّل")
        if self.options:
            problems.append("Options مفعّلة")
        if self.futures:
            problems.append("Futures مفعّلة")
        if self.forex:
            problems.append("Forex مفعّل")
        if self.crypto:
            problems.append("Crypto مفعّل")
        if self.short_selling:
            problems.append("Short Selling مفعّل")
        if not self.us_stocks:
            problems.append("صلاحية الأسهم الأمريكية غير مفعّلة")
        return problems


class Position(Base):
    account_id: str
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    market_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    as_of_utc: datetime


class InstrumentDetails(Base):
    symbol: str
    conid: Optional[str] = None
    asset_class: AssetClass
    currency: str
    exchange: str
    min_quantity: Decimal
    supports_fractional: bool
    supports_stop_orders: bool
    supports_stop_on_fractional: bool
    supported_order_types: tuple[OrderType, ...]
    as_of_utc: datetime

    # --- حقول CFD (Capital.com). اختيارية حتى تبقى أدوات IBKR صالحة كما هي. ---
    broker: Broker = Broker.MOCK
    epic: Optional[str] = None
    quantity_increment: Optional[Decimal] = None
    max_quantity: Optional[Decimal] = None
    lot_size: Optional[Decimal] = None
    margin_factor: Optional[Decimal] = None
    margin_factor_unit: Optional[str] = None
    #: **القيمة ووحدتها.** Capital.com يعلن هذه المسافات بوحدة
    #: `PERCENTAGE` غالباً، فالرقم وحده لا يعني شيئاً: ٠٫٠١ نسبةً هو ١٫١٦
    #: نقطة على اليورو، وسعراً خاماً هو ١٠٠ نقطة. الوحدة `None` تعني
    #: **غير محلولة** — لا «سعر» ولا «صفر».
    min_stop_distance: Optional[Decimal] = None
    min_stop_distance_unit: Optional[str] = None
    min_guaranteed_stop_distance: Optional[Decimal] = None
    min_guaranteed_stop_distance_unit: Optional[str] = None
    guaranteed_stop_available: bool = False
    overnight_fee: Optional[Decimal] = None
    pip_size: Optional[Decimal] = None
    quote_currency: Optional[str] = None
    market_status: Optional[str] = None

    @staticmethod
    def resolve_distance(
        value: Optional[Decimal], unit: Optional[str], reference_price: Optional[Decimal]
    ) -> Optional[Decimal]:
        """
        يحوّل مسافةً من قواعد الوسيط إلى **وحدة السعر**.

        `None` = غير قابلة للحلّ (وحدة مجهولة، أو نسبة بلا سعر مرجعي).
        والفرق بينها وبين «لا حدّ» جوهري: الأولى تُوقف القرار وتُسمّي سببه،
        والثانية تمرّ.
        """
        if value is None:
            return None
        u = (unit or "").upper()
        if u == "PERCENTAGE":
            if reference_price is None:
                return None
            return Decimal(value) / Decimal("100") * Decimal(reference_price)
        if u in {"POINTS", "PRICE"}:
            return Decimal(value)
        if not u:
            # وحدةٌ غائبة في `InstrumentDetails` تعني «كُتبت عندنا»، وما
            # نكتبه بوحدة السعر. والمحوّل يملؤها دائماً من الوسيط —
            # يحرس ذلك اختبارٌ ساكن، لا نيّة.
            return Decimal(value)
        return None

    def min_stop_price_at(self, reference_price: Optional[Decimal]) -> Optional[Decimal]:
        return self.resolve_distance(
            self.min_stop_distance, self.min_stop_distance_unit, reference_price
        )

    def min_guaranteed_stop_price_at(
        self, reference_price: Optional[Decimal]
    ) -> Optional[Decimal]:
        return self.resolve_distance(
            self.min_guaranteed_stop_distance,
            self.min_guaranteed_stop_distance_unit,
            reference_price,
        )

    @property
    def min_stop_spec_unresolved(self) -> bool:
        """أُعلن حدٌّ ولم تُعرَف وحدته ⇒ المواصفة غير محلولة."""
        unit = (self.min_stop_distance_unit or "").strip().upper()
        return (
            self.min_stop_distance is not None
            and bool(unit)
            and unit not in {"PERCENTAGE", "POINTS", "PRICE"}
        )

    @property
    def is_cfd(self) -> bool:
        return self.asset_class in (
            AssetClass.CFD_CURRENCY,
            AssetClass.CFD_COMMODITY,
            AssetClass.CFD_INDEX,
        )


# ---------------------------------------------------------------------------
# Signals / risk / orders
# ---------------------------------------------------------------------------

class Signal(Base):
    strategy_name: str
    strategy_version: str
    symbol: str
    side: Side
    entry_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    generated_at_utc: datetime
    rationale_ar: str
    invalidation_ar: str
    inputs_digest: str

    @property
    def exit_plan_is_sane(self) -> bool:
        """
        هل الوقف والهدف في جهتيهما الصحيحتين **بحسب اتجاه الصفقة**؟

        في الشراء: الوقف تحت الدخول والهدف فوقه. وفي البيع العكس تماماً.
        وانعكاسُ أحدهما يُنتج أمراً يُنفَّذ فوراً بخسارة.
        """
        if min(self.entry_price, self.stop_price, self.take_profit_price) <= 0:
            return False
        if self.side is Side.BUY:
            return self.stop_price < self.entry_price < self.take_profit_price
        return self.take_profit_price < self.entry_price < self.stop_price

    @property
    def reward_risk_ratio(self) -> Decimal:
        """
        العائد إلى المخاطرة — **بالمسافة لا بالإشارة**.

        كان يُحسب `entry - stop`، وهو موجبٌ في الشراء وسالبٌ في البيع. فكانت
        كل صفقة بيعٍ تُعيد صفراً، ثم تُرفض بـ«نسبة العائد أقل من الحد».
        وثلاثٌ من أربع استراتيجيات تُصدر بيعاً صراحةً — بل تُعلن ذلك في
        فرضيّتها: «صعوداً كان أو هبوطاً».

        والمسافة لا تعرف اتجاهاً؛ والاتجاه يُفحَص في `exit_plan_is_sane`.
        فصلُ السؤالين هو الإصلاح: «هل الجهات صحيحة؟» غيرُ «كم النسبة؟».
        """
        if not self.exit_plan_is_sane:
            return Decimal("0")
        risk = abs(self.entry_price - self.stop_price)
        if risk <= 0:
            return Decimal("0")
        return abs(self.take_profit_price - self.entry_price) / risk


class RiskDecision(Base):
    approved: bool
    decision: Decision
    reason_code: Optional[str]
    reason_ar: str
    checks: tuple[tuple[str, bool, str], ...]  # (اسم الفحص، نجح؟، شرح عربي)
    quantity: Decimal = Decimal("0")
    notional: Decimal = Decimal("0")
    expected_risk_usd: Decimal = Decimal("0")
    expected_costs_usd: Decimal = Decimal("0")
    risk_budget_usd: Decimal = Decimal("0")
    constitution_fingerprint: str = ""
    decided_at_utc: datetime


class OrderIntent(Base):
    """نية أمر — لم يُرسل بعد. تحمل كل ما يلزم للـidempotency والمطابقة."""

    idempotency_key: str
    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    limit_price: Optional[Decimal]
    stop_price: Optional[Decimal]
    #: هدف جني الأرباح. موجود في `Signal` ومطلوب في حمولة الوسيط، وكان
    #: يضيع بينهما فلا يبقى إلا في نصّ `exit_plan_ar` النثري.
    take_profit_price: Optional[Decimal] = None
    expected_fill_price: Decimal
    max_slippage_abs: Decimal
    strategy_name: str
    strategy_version: str
    risk_amount_usd: Decimal
    commission_estimate_usd: Decimal
    exit_plan_ar: str
    instrument_snapshot: dict
    created_at_utc: datetime


class OrderPreview(Base):
    intent_key: str
    accepted_by_broker: bool
    broker_message: str
    estimated_commission: Optional[Decimal]
    estimated_price: Optional[Decimal]
    warnings: tuple[str, ...] = ()
    previewed_at_utc: datetime


class BrokerOrder(Base):
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Optional[Decimal]
    status: OrderStatus
    parent_order_id: Optional[str] = None
    updated_at_utc: datetime


class Execution(Base):
    execution_id: str
    broker_order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    commission: Decimal
    executed_at_utc: datetime


class ReconciliationResult(Base):
    matched: bool
    checked_at_utc: datetime
    local_positions: tuple[Position, ...]
    broker_positions: tuple[Position, ...]
    discrepancies_ar: tuple[str, ...]


class HealthReport(Base):
    broker_connected: bool
    market_data_ok: bool
    database_ok: bool
    scheduler_ok: bool
    clock_ok: bool
    audit_chain_ok: bool
    kill_switch_active: bool
    details_ar: tuple[str, ...]
    checked_at_utc: datetime
