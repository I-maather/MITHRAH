"""
MockBrokerAdapter — وسيط محاكاة قابل للبرمجة، يستخدم في الاختبارات
وفي التشغيل المحلي دون أي اتصال بـIBKR.

مصمم ليكون *عدائياً*: يستطيع محاكاة الرفض، التعبئة الجزئية، انقطاع الاتصال،
ضياع التأكيد، والأوامر المكررة — لأن هذه هي الحالات التي تكسر أنظمة التداول.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from ..clock import now_utc, us_market_status
from ..contracts import (
    AccountKind,
    AssetClass,
    Balances,
    BrokerOrder,
    ClientClassification,
    DataSource,
    Execution,
    InstrumentDetails,
    OrderIntent,
    OrderPreview,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    TradingPermissions,
)
from ..money import D, money
from .base import BrokerAdapter, BrokerNotConnected, BrokerRejected, BrokerTimeout, MarketStatusSnapshot

DEFAULT_ACCOUNT = "DU0000000"


@dataclass
class MockBehaviour:
    """مفاتيح لمحاكاة الأعطال."""

    connected: bool = True
    reject_orders: bool = False
    reject_reason: str = "MOCK_REJECT"
    timeout_on_place: bool = False
    lose_confirmation: bool = False
    partial_fill_ratio: Decimal | None = None
    slippage: Decimal = Decimal("0")
    reject_stop_orders: bool = False
    fractional_supported: bool = True
    stop_on_fractional_supported: bool = False  # المسلك المتحفظ افتراضياً


@dataclass
class MockBrokerAdapter(BrokerAdapter):
    quotes: dict[str, Quote] = field(default_factory=dict)
    balances: Balances | None = None
    permissions: TradingPermissions | None = None
    behaviour: MockBehaviour = field(default_factory=MockBehaviour)

    _orders: dict[str, BrokerOrder] = field(default_factory=dict)
    _by_client_id: dict[str, str] = field(default_factory=dict)
    _seen_idempotency_keys: set[str] = field(default_factory=set)
    _executions: list[Execution] = field(default_factory=list)
    _positions: dict[str, Position] = field(default_factory=dict)
    _connected: bool = False

    is_live = False
    name = "MOCK"

    # --- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        if not self.behaviour.connected:
            raise BrokerNotConnected("MockBroker: الاتصال معطّل في سيناريو الاختبار")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def health_check(self) -> bool:
        return self._connected and self.behaviour.connected

    def _require_connection(self) -> None:
        if not self.health_check():
            raise BrokerNotConnected("MockBroker: غير متصل")

    # --- account -----------------------------------------------------------
    def get_accounts(self) -> Sequence[str]:
        self._require_connection()
        return [DEFAULT_ACCOUNT]

    def get_balances(self, account_id: str) -> Balances:
        self._require_connection()
        if self.balances is not None:
            return self.balances
        return Balances(
            account_id=account_id,
            total_cash=D("100.00"),
            settled_cash=D("100.00"),
            unsettled_cash=D("0"),
            committed_cash=D("0"),
            net_liquidation=D("100.00"),
            as_of_utc=now_utc(),
        )

    def get_positions(self, account_id: str) -> Sequence[Position]:
        self._require_connection()
        return list(self._positions.values())

    def get_trading_permissions(self, account_id: str) -> TradingPermissions:
        self._require_connection()
        if self.permissions is not None:
            return self.permissions
        return TradingPermissions(
            account_id=account_id,
            account_kind=AccountKind.CASH,
            classification=ClientClassification.RETAIL,
            us_stocks=True,
            fractional_enabled=self.behaviour.fractional_supported,
            as_of_utc=now_utc(),
        )

    # --- market ------------------------------------------------------------
    def set_quote(self, quote: Quote) -> None:
        self.quotes[quote.symbol] = quote

    def get_market_data(self, symbol: str) -> Quote:
        self._require_connection()
        if symbol not in self.quotes:
            raise BrokerRejected(f"MockBroker: لا توجد بيانات سوق للرمز {symbol}")
        return self.quotes[symbol]

    def get_instrument_details(self, symbol: str) -> InstrumentDetails:
        self._require_connection()
        types = [OrderType.MARKET, OrderType.LIMIT]
        if not self.behaviour.reject_stop_orders:
            types += [OrderType.STOP, OrderType.STOP_LIMIT]
        return InstrumentDetails(
            symbol=symbol,
            conid=f"MOCK-{symbol}",
            asset_class=AssetClass.ETF,
            currency="USD",
            exchange="SMART",
            min_quantity=D("0.0001") if self.behaviour.fractional_supported else D("1"),
            supports_fractional=self.behaviour.fractional_supported,
            supports_stop_orders=not self.behaviour.reject_stop_orders,
            supports_stop_on_fractional=self.behaviour.stop_on_fractional_supported,
            supported_order_types=tuple(types),
            as_of_utc=now_utc(),
        )

    def get_market_status(self) -> MarketStatusSnapshot:
        s = us_market_status()
        return MarketStatusSnapshot(is_open=s.is_open, reason_ar=s.reason_ar)

    # --- orders ------------------------------------------------------------
    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        self._require_connection()
        if self.behaviour.reject_orders:
            return OrderPreview(
                intent_key=intent.idempotency_key,
                accepted_by_broker=False,
                broker_message=self.behaviour.reject_reason,
                estimated_commission=None,
                estimated_price=None,
                previewed_at_utc=now_utc(),
            )
        return OrderPreview(
            intent_key=intent.idempotency_key,
            accepted_by_broker=True,
            broker_message="OK",
            estimated_commission=intent.commission_estimate_usd,
            estimated_price=intent.expected_fill_price,
            previewed_at_utc=now_utc(),
        )

    def place_order(self, intent: OrderIntent) -> BrokerOrder:
        self._require_connection()

        # الحماية من الأوامر المكررة على مستوى الوسيط المحاكى أيضاً
        if intent.idempotency_key in self._seen_idempotency_keys:
            existing_id = self._by_client_id.get(intent.client_order_id)
            if existing_id:
                return self._orders[existing_id]
            raise BrokerRejected("DUPLICATE_IDEMPOTENCY_KEY")

        if self.behaviour.timeout_on_place:
            # سُجّل المفتاح قبل الرمي: هذا بالضبط ما يحدث في الواقع —
            # الوسيط قد يكون استلم الأمر رغم أننا لم نستلم الرد.
            self._seen_idempotency_keys.add(intent.idempotency_key)
            raise BrokerTimeout("MockBroker: انتهت المهلة قبل استلام التأكيد")

        if self.behaviour.reject_orders:
            self._seen_idempotency_keys.add(intent.idempotency_key)
            raise BrokerRejected(self.behaviour.reject_reason)

        if intent.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            if self.behaviour.reject_stop_orders:
                raise BrokerRejected("STOP_ORDERS_NOT_SUPPORTED")
            is_fractional = intent.quantity != intent.quantity.to_integral_value()
            if is_fractional and not self.behaviour.stop_on_fractional_supported:
                raise BrokerRejected("STOP_NOT_SUPPORTED_ON_FRACTIONAL_QUANTITY")

        self._seen_idempotency_keys.add(intent.idempotency_key)
        broker_order_id = f"MO-{uuid.uuid4().hex[:12]}"

        ratio = self.behaviour.partial_fill_ratio
        filled = intent.quantity if ratio is None else (intent.quantity * ratio)
        fill_price = intent.expected_fill_price + self.behaviour.slippage

        status = OrderStatus.FILLED if filled >= intent.quantity else OrderStatus.PARTIALLY_FILLED
        order = BrokerOrder(
            broker_order_id=broker_order_id,
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            quantity=intent.quantity,
            filled_quantity=filled,
            average_fill_price=fill_price if filled > 0 else None,
            status=status,
            updated_at_utc=now_utc(),
        )
        self._orders[broker_order_id] = order
        self._by_client_id[intent.client_order_id] = broker_order_id

        if filled > 0:
            self._executions.append(
                Execution(
                    execution_id=f"EX-{uuid.uuid4().hex[:12]}",
                    broker_order_id=broker_order_id,
                    symbol=intent.symbol,
                    side=intent.side,
                    quantity=filled,
                    price=fill_price,
                    commission=intent.commission_estimate_usd,
                    executed_at_utc=now_utc(),
                )
            )
            self._apply_fill(intent.symbol, intent.side, filled, fill_price)

        if self.behaviour.lose_confirmation:
            raise BrokerTimeout("MockBroker: ضاع تأكيد التنفيذ بعد الإرسال")
        return order

    def _apply_fill(self, symbol: str, side: Side, qty: Decimal, price: Decimal) -> None:
        existing = self._positions.get(symbol)
        delta = qty if side is Side.BUY else -qty
        if existing is None:
            new_qty = delta
            avg = price
        else:
            new_qty = existing.quantity + delta
            avg = existing.average_cost if new_qty != 0 else Decimal("0")
        if new_qty == 0:
            self._positions.pop(symbol, None)
            return
        self._positions[symbol] = Position(
            account_id=DEFAULT_ACCOUNT,
            symbol=symbol,
            quantity=new_qty,
            average_cost=avg,
            market_price=price,
            unrealized_pnl=money((price - avg) * new_qty),
            as_of_utc=now_utc(),
        )

    def confirm_order(self, client_order_id: str) -> BrokerOrder:
        self._require_connection()
        oid = self._by_client_id.get(client_order_id)
        if oid is None:
            return BrokerOrder(
                broker_order_id="",
                client_order_id=client_order_id,
                symbol="",
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0"),
                filled_quantity=Decimal("0"),
                average_fill_price=None,
                status=OrderStatus.UNKNOWN,
                updated_at_utc=now_utc(),
            )
        return self._orders[oid]

    def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        self._require_connection()
        order = self._orders[broker_order_id]
        cancelled = order.model_copy(update={"status": OrderStatus.CANCELLED, "updated_at_utc": now_utc()})
        self._orders[broker_order_id] = cancelled
        return cancelled

    def close_position(self, account_id: str, symbol: str, quantity: Decimal) -> BrokerOrder:
        self._require_connection()
        quote = self.get_market_data(symbol)
        intent = OrderIntent(
            idempotency_key=f"close-{symbol}-{uuid.uuid4().hex[:8]}",
            client_order_id=f"CLS-{uuid.uuid4().hex[:10]}",
            symbol=symbol,
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=quantity,
            limit_price=None,
            stop_price=None,
            expected_fill_price=quote.bid,
            max_slippage_abs=Decimal("0"),
            strategy_name="EMERGENCY",
            strategy_version="0",
            risk_amount_usd=Decimal("0"),
            commission_estimate_usd=Decimal("0"),
            exit_plan_ar="إغلاق طارئ",
            instrument_snapshot={},
            created_at_utc=now_utc(),
        )
        return self.place_order(intent)

    def get_orders(self, account_id: str) -> Sequence[BrokerOrder]:
        self._require_connection()
        return list(self._orders.values())

    def get_executions(self, account_id: str) -> Sequence[Execution]:
        self._require_connection()
        return list(self._executions)


def make_quote(
    symbol: str,
    bid: str | Decimal,
    ask: str | Decimal,
    *,
    at: datetime | None = None,
    source: DataSource = DataSource.MOCK,
) -> Quote:
    at = at or now_utc()
    bid_d, ask_d = D(bid), D(ask)
    return Quote(
        symbol=symbol,
        bid=bid_d,
        ask=ask_d,
        last=(bid_d + ask_d) / Decimal("2"),
        timestamp_utc=at,
        source=source,
        received_at_utc=at,
    )
