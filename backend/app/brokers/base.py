"""
BrokerAdapter — الواجهة المجردة للوسيط.

النظام كله يتكلم مع هذه الواجهة فقط. IBKR تفصيلة تنفيذية خلفها،
حتى يمكن إضافة وسيط ثانٍ لاحقاً دون لمس Risk Engine أو Pipeline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Sequence

from ..contracts import (
    Balances,
    BrokerOrder,
    Execution,
    InstrumentDetails,
    OrderIntent,
    OrderPreview,
    Position,
    Quote,
    TradingPermissions,
)


class BrokerError(RuntimeError):
    pass


class BrokerNotConnected(BrokerError):
    pass


class BrokerRejected(BrokerError):
    pass


class BrokerTimeout(BrokerError):
    pass


class MarketStatusSnapshot:
    def __init__(self, is_open: bool, reason_ar: str):
        self.is_open = is_open
        self.reason_ar = reason_ar


class BrokerAdapter(ABC):
    """
    عقد ثابت لكل الوسطاء. كل ميثود ترفع BrokerError عند الفشل،
    ولا ترجع أبداً قيمة مخترعة أو افتراضية صامتة.
    """

    #: يجب أن يكون True فقط لمحوّل يرسل أوامر بمال حقيقي.
    is_live: bool = False
    name: str = "abstract"

    # --- lifecycle ---------------------------------------------------------
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    # --- account -----------------------------------------------------------
    @abstractmethod
    def get_accounts(self) -> Sequence[str]: ...

    @abstractmethod
    def get_balances(self, account_id: str) -> Balances: ...

    @abstractmethod
    def get_positions(self, account_id: str) -> Sequence[Position]: ...

    @abstractmethod
    def get_trading_permissions(self, account_id: str) -> TradingPermissions: ...

    # --- market ------------------------------------------------------------
    @abstractmethod
    def get_market_data(self, symbol: str) -> Quote: ...

    @abstractmethod
    def get_instrument_details(self, symbol: str) -> InstrumentDetails: ...

    @abstractmethod
    def get_market_status(self) -> MarketStatusSnapshot: ...

    # --- orders ------------------------------------------------------------
    @abstractmethod
    def preview_order(self, intent: OrderIntent) -> OrderPreview: ...

    @abstractmethod
    def place_order(self, intent: OrderIntent) -> BrokerOrder: ...

    @abstractmethod
    def confirm_order(self, client_order_id: str) -> BrokerOrder: ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> BrokerOrder: ...

    @abstractmethod
    def close_position(self, account_id: str, symbol: str, quantity: Decimal) -> BrokerOrder: ...

    @abstractmethod
    def get_orders(self, account_id: str) -> Sequence[BrokerOrder]: ...

    @abstractmethod
    def get_executions(self, account_id: str) -> Sequence[Execution]: ...
