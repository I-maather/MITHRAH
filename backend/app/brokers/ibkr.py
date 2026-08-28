"""
IBKR adapters — Paper و Live.

⚠️ الحالة الحقيقية: هذه هياكل غير مكتملة عمداً.
كل ميثود ترفع NotImplementedError برسالة واضحة بدل أن تعيد بيانات مخترعة.
السبب: لم نتحقق بعد من قدرات الحساب الفعلية (انظر docs/KNOWN_LIMITATIONS.md،
البنود OPEN-IBKR-01..05)، والادعاء بأن الربط جاهز أخطر من عدم وجوده.

القرار المعماري وأسبابه: docs/adr/001-ibkr-api-selection.md

لماذا لا يوجد اتصال فعلي بعد:
  1. اختيار الواجهة يعتمد على نوع الحساب والكيان الذي سيُفتح — والحساب لم يُفتح.
  2. TWS API / IB Gateway يتطلبان تشغيل تطبيق على جهاز المالكة وتسجيل دخول
     بمصادقة ثنائية — لا يجوز لي فعل ذلك نيابة عنها.
  3. Web API يتطلب إنشاء API credentials — ممنوع عليّ إنشاؤها نيابة عنها.

ما هو مبنيّ فعلاً: العقد (BrokerAdapter) و MockBrokerAdapter، وكل المنطق فوقهما
مُختبَر. إضافة IBKR لاحقاً = ملء هذه الميثودات فقط دون لمس بقية النظام.
"""
from __future__ import annotations

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
from .base import BrokerAdapter, MarketStatusSnapshot

_NOT_READY = (
    "محوّل IBKR غير مكتمل. الخطوة المطلوبة أولاً: فتح حساب IBKR وتشغيل "
    "docs/IBKR_SETUP.md وتثبيت قدرات الحساب في docs/KNOWN_LIMITATIONS.md. "
    "لن يعيد النظام بيانات مخترعة."
)


class _IBKRBase(BrokerAdapter):
    def __init__(self, *, host: str, port: int, client_id: int, account_id: str = "") -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_id = account_id

    def _fail(self, what: str):
        raise NotImplementedError(f"{what}: {_NOT_READY}")

    def connect(self) -> None: self._fail("connect")
    def disconnect(self) -> None: return None
    def health_check(self) -> bool: return False
    def get_accounts(self) -> Sequence[str]: self._fail("get_accounts")
    def get_balances(self, account_id: str) -> Balances: self._fail("get_balances")
    def get_positions(self, account_id: str) -> Sequence[Position]: self._fail("get_positions")
    def get_trading_permissions(self, account_id: str) -> TradingPermissions: self._fail("get_trading_permissions")
    def get_market_data(self, symbol: str) -> Quote: self._fail("get_market_data")
    def get_instrument_details(self, symbol: str) -> InstrumentDetails: self._fail("get_instrument_details")
    def get_market_status(self) -> MarketStatusSnapshot: self._fail("get_market_status")
    def preview_order(self, intent: OrderIntent) -> OrderPreview: self._fail("preview_order")
    def place_order(self, intent: OrderIntent) -> BrokerOrder: self._fail("place_order")
    def confirm_order(self, client_order_id: str) -> BrokerOrder: self._fail("confirm_order")
    def cancel_order(self, broker_order_id: str) -> BrokerOrder: self._fail("cancel_order")
    def close_position(self, account_id: str, symbol: str, quantity: Decimal) -> BrokerOrder:
        self._fail("close_position")
    def get_orders(self, account_id: str) -> Sequence[BrokerOrder]: self._fail("get_orders")
    def get_executions(self, account_id: str) -> Sequence[Execution]: self._fail("get_executions")


class IBKRPaperAdapter(_IBKRBase):
    is_live = False
    name = "IBKR_PAPER"


class IBKRLiveAdapter(_IBKRBase):
    """
    مال حقيقي. `is_live = True` يجعل الـpipeline يرفض الإرسال
    ما لم يكن `allow_live_submission=True` مُمرَّراً صراحةً.
    """

    is_live = True
    name = "IBKR_LIVE"
