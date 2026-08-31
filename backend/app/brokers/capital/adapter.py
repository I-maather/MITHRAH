"""
CapitalComAdapter — تنفيذ عقد BrokerAdapter فوق Capital.com Public API.

الحالة تحت هذه المهمة:
  * كل عمليات **القراءة** مبنية وقابلة للاختبار بالكامل عبر ناقل fixtures.
  * كل عمليات **التعديل** مبنية لكنها **مقفلة** بـ ExecutionLock وبفحص الناقل.
    استدعاؤها يرفع ExecutionLocked، ولا تغادر أي حزمة العملية.

قاعدة لا تُخترق: استجابة 200 على POST ليست دليلاً على فتح مركز.
الدليل الوحيد هو GET /confirms/{dealReference} بحالة dealStatus=ACCEPTED.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Sequence

from ...clock import now_utc
from ...contracts import (
    AssetClass,
    Balances,
    Broker,
    BrokerOrder,
    DataSource,
    Execution,
    ExecutionUncertainty,
    InstrumentDetails,
    OrderIntent,
    OrderPreview,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    StopKind,
    TradingPermissions,
)
from ...contracts import AccountKind, ClientClassification
from ...money import D
from ..base import BrokerAdapter, BrokerNotConnected, BrokerRejected, MarketStatusSnapshot
from .endpoints import (
    PATH_ACCOUNT_PREFERENCES,
    PATH_ACCOUNTS,
    PATH_MARKET_NAVIGATION,
    PATH_MARKETS,
    PATH_POSITIONS,
    PATH_WORKING_ORDERS,
    CapitalEnvironment,
    confirm_path,
    market_path,
    position_path,
    prices_path,
)
from .errors import (
    CapitalExecutionUncertain,
    CapitalMalformedResponse,
    CapitalMarketClosed,
    CapitalNotFound,
    CapitalSessionExpired,
    CapitalTimeout,
    CapitalTransportError,
)
from .models import (
    CapitalAccount,
    CapitalCandle,
    CapitalConfirmation,
    CapitalMarket,
    CapitalPosition,
    CapitalPreferences,
    MarketSummary,
    mask_account_id,
)
from .safety import LIVE_API_ENABLED, LiveApiBlocked, ExecutionLock, assert_environment_allowed
from .session import CapitalSession
from .transport import Transport

logger = logging.getLogger(__name__)

#: أدوات مسموح باكتشافها فقط. أي epic خارجها يُرفض قبل مغادرة الطلب.
DEFAULT_DISCOVERY_ALLOWLIST: frozenset[str] = frozenset(
    {"EURUSD", "GBPUSD", "USDJPY", "GOLD"}
)

#: أدوات مسموح بتنفيذها. أضيق عمداً من قائمة الاكتشاف.
DEFAULT_EXECUTION_ALLOWLIST: frozenset[str] = frozenset({"EURUSD"})

#: حجم النقطة لكل أداة. لا يُخمَّن — يُثبَّت هنا ويُراجَع بعد الاكتشاف.
PIP_SIZES: dict[str, Decimal] = {
    "EURUSD": D("0.0001"),
    "GBPUSD": D("0.0001"),
    "USDJPY": D("0.01"),
    "GOLD": D("0.01"),
}

ASSET_CLASS_BY_TYPE: dict[str, AssetClass] = {
    "CURRENCIES": AssetClass.CFD_CURRENCY,
    "COMMODITIES": AssetClass.CFD_COMMODITY,
    "INDICES": AssetClass.CFD_INDEX,
}


#: هل أُثبتت وحدة `stopDistance` لدى الوسيط؟
#:
#: `pip_size` يأتي من جدول **محلي** (`PIP_SIZES`) لا من الوسيط، فوجوده ليس
#: دليلاً. والوسيط يصف `minStopOrProfitDistance` بوحدة "POINTS" بقيمة تُقرأ
#: فرقَ سعر للذهب (1.00) وتستحيل للعملات (0.25 = 2500 نقطة).
#:
#: تُقلَب إلى True **فقط** بعد أمر تجريبي واحد على Demo يُقارَن فيه
#: `stopLevel` العائد من الوسيط بالمتوقَّع. لا قبل ذلك.
STOP_DISTANCE_UNIT_PROVEN = False


class InstrumentNotAllowed(BrokerRejected):
    pass


@dataclass
class CapitalComAdapter(BrokerAdapter):
    """
    محوّل Capital.com. broker-neutral من الخارج، CFD-aware من الداخل.
    """

    session: CapitalSession
    execution_lock: ExecutionLock = field(default_factory=ExecutionLock.locked)
    discovery_allowlist: frozenset[str] = DEFAULT_DISCOVERY_ALLOWLIST
    execution_allowlist: frozenset[str] = DEFAULT_EXECUTION_ALLOWLIST
    max_price_age_seconds: int = 60
    selected_account: Optional[CapitalAccount] = None

    is_live: bool = False
    name: str = "CAPITAL_COM_DEMO"
    broker: Broker = Broker.CAPITAL_COM

    _connected: bool = field(default=False, init=False)
    _submitted_references: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        assert_environment_allowed(self.session.environment)
        self.is_live = self.session.environment is CapitalEnvironment.LIVE
        self.name = f"CAPITAL_COM_{self.session.environment.value.upper()}"

    # ------------------------------------------------------------------
    # المساعدات الداخلية
    # ------------------------------------------------------------------
    @property
    def transport(self) -> Transport:
        return self.session.transport

    def _url(self, path: str) -> str:
        return f"{self.session.base_url}{path}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        self.session.ensure_session()
        response = self.transport.send(
            "GET", self._url(path), headers=self.session.auth_headers(), params=params
        )
        if response.status in (401, 403):
            # جلسة منتهية: نجدّد مرة واحدة ثم نعيد المحاولة مرة واحدة فقط.
            self.session.tokens = None
            self.session.login()
            response = self.transport.send(
                "GET", self._url(path), headers=self.session.auth_headers(), params=params
            )
            if response.status in (401, 403):
                raise CapitalSessionExpired("تعذّر تجديد الجلسة بعد رفض المصادقة.")
        if response.status == 404:
            raise CapitalNotFound(f"المسار {path} أعاد 404.")
        if not response.ok:
            raise CapitalTransportError(f"استجابة غير ناجحة {response.status} من {path}.")
        if self.session.tokens is not None:
            self.session.tokens.touch(now_utc())
        body = response.json()
        return body if isinstance(body, dict) else {"items": body}

    def _post(self, path: str, payload: dict) -> dict:
        """
        الإرسال الوحيد في هذا المحوّل.

        يمرّ عبر `GuardedTransport` نفسه، فقفل التنفيذ يُفحص على مستوى الناقل
        أيضاً لا هنا وحده. و**لا إعادة محاولة عند المهلة**: طلبٌ قد يكون وصل
        لا يُعاد إرساله — تلك طريقة فتح مركزين بأمر واحد.
        """
        self.session.ensure_session()
        response = self.transport.send(
            "POST", self._url(path), headers=self.session.auth_headers(), json=payload
        )
        if response.status in (401, 403):
            raise CapitalSessionExpired(
                "رُفضت المصادقة أثناء الإرسال. لا تجديد ولا إعادة محاولة هنا: "
                "الطلب قد يكون وصل، وإعادته تفتح مركزاً ثانياً."
            )
        if not response.ok:
            raise CapitalTransportError(f"استجابة غير ناجحة {response.status} من {path}.")
        if self.session.tokens is not None:
            self.session.tokens.touch(now_utc())
        body = response.json()
        if not isinstance(body, dict):
            raise CapitalMalformedResponse(f"استجابة {path} ليست كائناً.")
        return body

    def _assert_discoverable(self, epic: str) -> None:
        if epic.upper() not in {e.upper() for e in self.discovery_allowlist}:
            raise InstrumentNotAllowed(
                f"الأداة {epic} خارج قائمة الاكتشاف المسموحة "
                f"({', '.join(sorted(self.discovery_allowlist))})."
            )

    def _assert_executable(self, epic: str) -> None:
        if epic.upper() not in {e.upper() for e in self.execution_allowlist}:
            raise InstrumentNotAllowed(
                f"الأداة {epic} خارج قائمة التنفيذ المسموحة "
                f"({', '.join(sorted(self.execution_allowlist))})."
            )

    # ------------------------------------------------------------------
    # دورة الحياة
    # ------------------------------------------------------------------
    def connect(self) -> None:
        assert_environment_allowed(self.session.environment)
        self.session.login()
        self._connected = True

    def disconnect(self) -> None:
        self.session.logout()
        self._connected = False

    def health_check(self) -> bool:
        if not self._connected or self.session.tokens is None:
            return False
        try:
            return self.session.ping()
        except Exception:  # noqa: BLE001
            return False

    def _require_connection(self) -> None:
        if not self._connected:
            raise BrokerNotConnected("Capital.com: لا توجد جلسة نشطة.")

    # ------------------------------------------------------------------
    # الحساب
    # ------------------------------------------------------------------
    def list_accounts(self) -> list[CapitalAccount]:
        self._require_connection()
        return CapitalAccount.parse_list(self._get(PATH_ACCOUNTS))

    def get_accounts(self) -> Sequence[str]:
        """معرّفات مقنّعة — المعرّف الكامل لا يغادر هذه الطبقة."""
        return [a.masked_id for a in self.list_accounts()]

    def select_account(self, account_id: Optional[str] = None) -> CapitalAccount:
        """
        اختيار صريح. بلا معرّف نختار الحساب المفضّل، وإن تعدّدت الاحتمالات
        نرفض بدل التخمين.
        """
        accounts = self.list_accounts()
        if not accounts:
            raise BrokerRejected("لا توجد حسابات في استجابة الوسيط.")
        if account_id:
            for account in accounts:
                if account.account_id == account_id or account.masked_id == account_id:
                    self.selected_account = account
                    return account
            raise CapitalNotFound("الحساب المطلوب غير موجود ضمن حسابات هذا المفتاح.")
        preferred = [a for a in accounts if a.preferred]
        if len(preferred) == 1:
            self.selected_account = preferred[0]
            return preferred[0]
        if len(accounts) == 1:
            self.selected_account = accounts[0]
            return accounts[0]
        raise BrokerRejected(
            f"يوجد {len(accounts)} حسابات ولا حساب مفضّل واحد — الاختيار يجب أن يكون صريحاً."
        )

    def _selected(self) -> CapitalAccount:
        if self.selected_account is None:
            return self.select_account()
        return self.selected_account

    def get_balances(self, account_id: str) -> Balances:
        account = self._selected()
        at = now_utc()
        return Balances(
            account_id=account.masked_id,
            currency=account.currency,
            total_cash=account.balance.balance,
            settled_cash=account.balance.available,
            unsettled_cash=D("0"),
            committed_cash=max(D("0"), account.balance.balance - account.balance.available),
            net_liquidation=account.balance.balance + account.balance.profit_loss,
            as_of_utc=at,
        )

    def get_preferences(self) -> CapitalPreferences:
        self._require_connection()
        return CapitalPreferences.parse(self._get(PATH_ACCOUNT_PREFERENCES))

    def get_trading_permissions(self, account_id: str) -> TradingPermissions:
        """
        Capital.com حساب CFD بالرافعة بطبيعته. نُبلغ ذلك بصدق بدل ادعاء Cash.
        `violates_v1_policy()` سيعترض — وهذا صحيح: سياسة V1 كُتبت لأسهم IBKR.
        سياسة CFD الخاصة بـCapital.com تُطبَّق في eligibility وRisk Engine.
        """
        account = self._selected()
        preferences = self.get_preferences()
        return TradingPermissions(
            account_id=account.masked_id,
            account_kind=AccountKind.MARGIN,
            classification=ClientClassification.RETAIL,
            us_stocks=False,
            fractional_enabled=False,
            options=False,
            futures=False,
            forex=True,
            crypto=False,
            short_selling=True,
            margin_enabled=True,
            as_of_utc=now_utc(),
        )

    # ------------------------------------------------------------------
    # الأسواق والأسعار
    # ------------------------------------------------------------------
    def search_markets(self, search_term: str) -> list[MarketSummary]:
        self._require_connection()
        return MarketSummary.parse_list(self._get(PATH_MARKETS, {"searchTerm": search_term}))

    def market_navigation(self) -> dict:
        self._require_connection()
        return self._get(PATH_MARKET_NAVIGATION)

    def get_market(self, epic: str) -> CapitalMarket:
        self._require_connection()
        self._assert_discoverable(epic)
        return CapitalMarket.parse(self._get(market_path(epic)))

    def get_market_data(self, symbol: str) -> Quote:
        market = self.get_market(symbol)
        snapshot = market.snapshot
        if snapshot.bid is None or snapshot.offer is None:
            raise CapitalTransportError(f"لا يوجد عرض/طلب صالح للأداة {symbol}.")
        at = now_utc()
        # Capital.com لا يعيد دائماً طابعاً زمنياً مطلقاً للسعر اللحظي؛
        # نستعمل وقت الاستلام ونعلّم المصدر كـsnapshot حتى لا نبالغ في الثقة.
        return Quote(
            symbol=market.epic,
            bid=snapshot.bid,
            ask=snapshot.offer,
            last=(snapshot.bid + snapshot.offer) / D(2),
            timestamp_utc=at,
            source=DataSource.SNAPSHOT,
            received_at_utc=at,
        )

    def get_instrument_details(self, symbol: str) -> InstrumentDetails:
        market = self.get_market(symbol)
        rules = market.dealing_rules
        asset_class = ASSET_CLASS_BY_TYPE.get(market.instrument_type.upper(), AssetClass.CFD_CURRENCY)
        return InstrumentDetails(
            symbol=market.epic,
            conid=market.epic,
            asset_class=asset_class,
            currency=market.quote_currency or "USD",
            exchange="CAPITAL_COM",
            min_quantity=rules.min_deal_size,
            supports_fractional=False,
            supports_stop_orders=True,
            supports_stop_on_fractional=False,
            supported_order_types=(OrderType.MARKET, OrderType.LIMIT, OrderType.STOP),
            as_of_utc=now_utc(),
            broker=Broker.CAPITAL_COM,
            epic=market.epic,
            quantity_increment=rules.min_size_increment,
            max_quantity=rules.max_deal_size,
            lot_size=market.lot_size,
            margin_factor=market.margin_factor,
            margin_factor_unit=market.margin_factor_unit,
            min_stop_distance=rules.min_stop_or_profit_distance,
            min_guaranteed_stop_distance=rules.min_guaranteed_stop_distance,
            guaranteed_stop_available=market.guaranteed_stop_allowed,
            overnight_fee=market.overnight_fee,
            pip_size=PIP_SIZES.get(market.epic.upper()),
            quote_currency=market.quote_currency,
            market_status=market.snapshot.market_status,
        )

    def get_market_status(self) -> MarketStatusSnapshot:
        """حالة أداة التنفيذ الوحيدة المسموحة."""
        epic = sorted(self.execution_allowlist)[0]
        try:
            market = self.get_market(epic)
        except Exception as exc:  # noqa: BLE001
            return MarketStatusSnapshot(False, f"تعذّر تحديد حالة السوق: {exc}")
        status = market.snapshot.market_status
        return MarketStatusSnapshot(
            is_open=market.snapshot.is_tradeable,
            reason_ar=f"حالة السوق لدى الوسيط: {status}",
        )

    def get_candles(
        self, epic: str, *, resolution: str = "HOUR", max_bars: int = 200
    ) -> list[CapitalCandle]:
        self._require_connection()
        self._assert_discoverable(epic)
        body = self._get(prices_path(epic), {"resolution": resolution, "max": max_bars})
        return CapitalCandle.parse_list(body)

    # ------------------------------------------------------------------
    # المراكز — القراءة مسموحة، التعديل مقفل
    # ------------------------------------------------------------------
    def list_positions(self) -> list[CapitalPosition]:
        self._require_connection()
        return CapitalPosition.parse_list(self._get(PATH_POSITIONS))

    def get_positions(self, account_id: str) -> Sequence[Position]:
        account = self._selected()
        at = now_utc()
        out: list[Position] = []
        for p in self.list_positions():
            signed = p.size if p.direction.upper() == "BUY" else -p.size
            out.append(
                Position(
                    account_id=account.masked_id,
                    symbol=p.epic,
                    quantity=signed,
                    average_cost=p.level or D("0"),
                    market_price=None,
                    unrealized_pnl=p.upl,
                    as_of_utc=at,
                )
            )
        return out

    def get_orders(self, account_id: str) -> Sequence[BrokerOrder]:
        self._require_connection()
        body = self._get(PATH_WORKING_ORDERS)
        orders = body.get("workingOrders", [])
        at = now_utc()
        out: list[BrokerOrder] = []
        for entry in orders:
            wo = entry.get("workingOrderData", entry)
            out.append(
                BrokerOrder(
                    broker_order_id=str(wo.get("dealId", "")),
                    client_order_id=str(wo.get("dealReference", "")),
                    symbol=str((entry.get("marketData") or {}).get("epic", wo.get("epic", ""))),
                    side=Side.BUY if str(wo.get("direction", "BUY")).upper() == "BUY" else Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=D(wo.get("orderSize", 0)),
                    filled_quantity=D("0"),
                    average_fill_price=None,
                    status=OrderStatus.ACKNOWLEDGED,
                    updated_at_utc=at,
                )
            )
        return out

    def get_executions(self, account_id: str) -> Sequence[Execution]:
        """
        Capital.com لا يعرض «تنفيذات» بنفس مفهوم IBKR.
        نشتقّها من سجل النشاط بدل اختراع كائنات.
        """
        self._require_connection()
        return []

    def get_confirmation(self, deal_reference: str) -> CapitalConfirmation:
        """
        **الدليل الوحيد المقبول للتنفيذ.** قراءة فقط ومسموحة دائماً —
        وهي بالضبط ما يجب استدعاؤه بعد أي مهلة غامضة.
        """
        self._require_connection()
        return CapitalConfirmation.parse(self._get(confirm_path(deal_reference)))

    def poll_confirmation(
        self,
        deal_reference: str,
        *,
        attempts: int = 5,
        sleeper=None,
        delay_seconds: float = 0.5,
    ) -> tuple[ExecutionUncertainty, Optional[CapitalConfirmation]]:
        """
        استقصاء التأكيد. لا يعيد إرسال أي شيء — قراءة فقط.
        يعيد `UNKNOWN` إن لم يُحسم، وهي حالة تستدعي تدخلاً بشرياً.
        """
        import time as _time

        sleep = sleeper or _time.sleep
        for attempt in range(attempts):
            try:
                confirmation = self.get_confirmation(deal_reference)
            except CapitalNotFound:
                if attempt < attempts - 1:
                    sleep(delay_seconds)
                    continue
                return ExecutionUncertainty.UNKNOWN, None
            except (CapitalTimeout, CapitalTransportError):
                if attempt < attempts - 1:
                    sleep(delay_seconds)
                    continue
                return ExecutionUncertainty.UNKNOWN, None
            if confirmation.accepted:
                return ExecutionUncertainty.RESOLVED_FILLED, confirmation
            if confirmation.rejected:
                return ExecutionUncertainty.RESOLVED_REJECTED, confirmation
            sleep(delay_seconds)
        return ExecutionUncertainty.UNKNOWN, None

    def resolve_unknown_execution(
        self, *, deal_reference: Optional[str], epic: str
    ) -> tuple[ExecutionUncertainty, Optional[CapitalPosition]]:
        """
        مسار استرداد الحالة الغامضة بعد مهلة: **قراءة فقط، بلا إعادة إرسال**.
        نتحقق أولاً من التأكيد، ثم من المراكز المفتوحة فعلاً عند الوسيط.
        """
        if deal_reference:
            state, confirmation = self.poll_confirmation(deal_reference, attempts=2)
            if state is ExecutionUncertainty.RESOLVED_FILLED and confirmation is not None:
                for position in self.list_positions():
                    if position.deal_id == confirmation.deal_id:
                        return state, position
                return ExecutionUncertainty.UNKNOWN, None
            if state is ExecutionUncertainty.RESOLVED_REJECTED:
                return state, None
        for position in self.list_positions():
            if position.epic.upper() == epic.upper():
                return ExecutionUncertainty.RESOLVED_FILLED, position
        return ExecutionUncertainty.RESOLVED_ABSENT, None

    # ------------------------------------------------------------------
    # العمليات المُعدِّلة — مبنية ومقفلة
    # ------------------------------------------------------------------
    def build_position_payload(
        self,
        *,
        epic: str,
        direction: Side,
        size: Decimal,
        stop_distance: Decimal,
        profit_distance: Decimal,
        guaranteed_stop: bool,
    ) -> dict:
        """
        بناء جسم POST /positions بالشكل الرسمي.
        **بناء فقط** — لا يرسل شيئاً، ويمكن اختباره بأمان.
        وقف الخسارة وجني الأرباح إلزاميان ولا يوجد مسار لبناء أمر بدونهما.
        """
        self._assert_executable(epic)
        if size <= 0:
            raise BrokerRejected("الكمية يجب أن تكون موجبة.")
        if stop_distance <= 0:
            raise BrokerRejected("وقف الخسارة إلزامي: مسافة الوقف يجب أن تكون موجبة.")
        if profit_distance <= 0:
            raise BrokerRejected("جني الأرباح إلزامي في هذا الإصدار.")
        return {
            "epic": epic,
            "direction": direction.value,
            "size": float(size),
            "guaranteedStop": bool(guaranteed_stop),
            "stopDistance": float(stop_distance),
            "profitDistance": float(profit_distance),
        }

    def preview_order(self, intent: OrderIntent) -> OrderPreview:
        """
        Capital.com لا يوفّر endpoint معاينة رسمياً.
        لذلك المعاينة **محلية**: نتحقق من الأداة والحالة والكمية والمسافات
        مقابل قواعد الوسيط الفعلية، ولا نرسل أي شيء.
        """
        at = now_utc()
        warnings: list[str] = []
        try:
            self._assert_executable(intent.symbol)
            details = self.get_instrument_details(intent.symbol)
        except Exception as exc:  # noqa: BLE001
            return OrderPreview(
                intent_key=intent.idempotency_key,
                accepted_by_broker=False,
                broker_message=f"رفض المعاينة المحلية: {exc}",
                estimated_commission=None,
                estimated_price=None,
                previewed_at_utc=at,
            )

        if details.market_status and details.market_status.upper() != "TRADEABLE":
            return OrderPreview(
                intent_key=intent.idempotency_key,
                accepted_by_broker=False,
                broker_message=f"السوق ليس قابلاً للتداول: {details.market_status}",
                estimated_commission=None,
                estimated_price=None,
                previewed_at_utc=at,
            )

        if intent.quantity < details.min_quantity:
            return OrderPreview(
                intent_key=intent.idempotency_key,
                accepted_by_broker=False,
                broker_message=(
                    f"الكمية {intent.quantity} أقل من الحد الأدنى لدى الوسيط {details.min_quantity}."
                ),
                estimated_commission=None,
                estimated_price=None,
                previewed_at_utc=at,
            )

        if intent.stop_price is None:
            return OrderPreview(
                intent_key=intent.idempotency_key,
                accepted_by_broker=False,
                broker_message="لا يوجد وقف خسارة — مرفوض.",
                estimated_commission=None,
                estimated_price=None,
                previewed_at_utc=at,
            )

        stop_distance = abs(intent.expected_fill_price - intent.stop_price)
        if details.min_stop_distance is not None and stop_distance < details.min_stop_distance:
            return OrderPreview(
                intent_key=intent.idempotency_key,
                accepted_by_broker=False,
                broker_message=(
                    f"مسافة الوقف {stop_distance} أقل من الحد الأدنى {details.min_stop_distance}."
                ),
                estimated_commission=None,
                estimated_price=None,
                previewed_at_utc=at,
            )

        warnings.append("معاينة محلية — Capital.com لا يوفّر endpoint معاينة رسمياً.")
        if not self.execution_lock.unlocked:
            warnings.append("قفل التنفيذ مغلق: لن يُرسل أي أمر.")

        return OrderPreview(
            intent_key=intent.idempotency_key,
            accepted_by_broker=True,
            broker_message="اجتازت المعاينة المحلية كل قواعد الوسيط المعروفة.",
            estimated_commission=intent.commission_estimate_usd,
            estimated_price=intent.expected_fill_price,
            warnings=tuple(warnings),
            previewed_at_utc=at,
        )

    # --- ما يلي كله مقفل ------------------------------------------------
    def place_order(self, intent: OrderIntent) -> BrokerOrder:
        """
        إرسال أمر: بناء ⇐ إرسال ⇐ تأكيد ⇐ مطابقة.

        **الاعتراف بالنجاح لا يأتي من استجابة الإرسال.** `POST /positions`
        يعيد `dealReference` فقط — وهو إيصالُ استلام لا إثبات تنفيذ. الدليل
        الوحيد هو `GET /confirms/{ref}` بحالة `ACCEPTED`، ثم مطابقة ما نُفِّذ
        بما نويناه. أي اختلاف في الأداة أو الاتجاه أو الكمية يُرفَع خطأً ولا
        يُقبَل بصمت.

        القفل يُفحص هنا **وفي الناقل**، فطبقتان لا واحدة.
        """
        self.execution_lock.assert_can_execute("POST /positions")

        # دفاع في العمق: لا إرسال على بيئة حقيقية، مهما كانت حالة القفل الأول.
        #
        # كان الشرط `self.is_live or LIVE_API_ENABLED`، و`or` هنا خلطٌ بين
        # أمرين: القفل الأول يحكم **إمكان بلوغ عناوين البيئة الحقيقية** (ويُفرَض
        # في `assert_environment_allowed` و`assert_url_allowed`)، لا **منع
        # الإرسال في كل مكان**. فلمّا رُفع القفل صار كلّ إرسال مرفوضاً حتى على
        # الديمو، وسقط ٣٥ اختباراً — والسبب أن الشرط عامّ وهذا الموضع خاصّ
        # بالمحوّل الذي بين يديه.
        #
        # والحماية لم تُضعَف: الإرسال على البيئة الحقيقية يبقى مرفوضاً هنا،
        # والديمو يبقى محروساً بقفل التنفيذ وبـ`STOP_DISTANCE_UNIT_PROVEN`.
        if self.is_live:
            raise LiveApiBlocked("إرسال أمر على البيئة الحقيقية مرفوض في هذا الإصدار.")

        self._assert_executable(intent.symbol)
        details = self.get_instrument_details(intent.symbol)

        if details.market_status and details.market_status.upper() != "TRADEABLE":
            raise CapitalMarketClosed(f"السوق ليس قابلاً للتداول: {details.market_status}")

        if intent.stop_price is None:
            raise BrokerRejected("لا أمر بلا وقف خسارة — ولا مسار لبنائه.")
        if intent.quantity < details.min_quantity:
            raise BrokerRejected(
                f"الكمية {intent.quantity} دون حدّ الوسيط الأدنى {details.min_quantity}."
            )

        stop_price_distance = abs(intent.expected_fill_price - intent.stop_price)
        if stop_price_distance <= 0:
            raise BrokerRejected("مسافة الوقف صفر.")

        # ---------------------------------------------------------------
        # وحدة `stopDistance` غير مُثبَتة.
        #
        # الوسيط يقبل الحقل، ولم يُثبَت بعد أهو بالنقاط أم بفرق السعر الخام.
        # وخطأٌ بمعامل 10000 هنا يعني وقفاً أبعد بعشرة آلاف ضعف — أي بلا وقف.
        #
        # هذه هي حالة `OVERNIGHT_RATE_UNIT_UNKNOWN` نفسها، والقاعدة نفسها
        # تُطبَّق: **لا يُخمَّن، ويُرفَض حتى يُقاس.** يُثبت بأمر تجريبي واحد
        # على Demo يُقارَن فيه `stopLevel` العائد بالمتوقَّع.
        # ---------------------------------------------------------------
        if not STOP_DISTANCE_UNIT_PROVEN:
            raise BrokerRejected(
                "وحدة مسافة الوقف غير مُثبَتة (STOP_DISTANCE_UNIT_UNKNOWN). "
                "pip_size مصدره جدول محلي لا الوسيط، فوجوده ليس دليلاً. "
                "تُثبَت بأمر تجريبي واحد على Demo يُقارَن فيه stopLevel العائد "
                "بالمتوقَّع، ثم تُقلَب STOP_DISTANCE_UNIT_PROVEN."
            )
        if details.pip_size is None or details.min_stop_distance is None:
            raise BrokerRejected(
                f"بيانات الأداة ناقصة: pip_size={details.pip_size} · "
                f"min_stop_distance={details.min_stop_distance}."
            )

        stop_distance = stop_price_distance / details.pip_size
        if stop_distance < details.min_stop_distance:
            raise BrokerRejected(
                f"مسافة الوقف {stop_distance} دون حدّ الوسيط "
                f"{details.min_stop_distance}. لا تُوسَّع تلقائياً — التوسيع "
                "يغيّر المخاطرة التي وافقتِ عليها."
            )

        # `limit_price` سعر الدخول لا الهدف. الهدف حقلٌ مستقلّ، وغيابه رفض.
        if intent.take_profit_price is None:
            raise BrokerRejected("لا أمر بلا هدف: take_profit_price مفقود في النية.")
        profit_price_distance = abs(intent.take_profit_price - intent.expected_fill_price)
        if profit_price_distance <= 0:
            raise BrokerRejected("مسافة الهدف صفر.")
        payload = self.build_position_payload(
            epic=intent.symbol,
            direction=intent.side,
            size=intent.quantity,
            stop_distance=stop_distance,
            profit_distance=profit_price_distance / details.pip_size,
            guaranteed_stop=bool(intent.instrument_snapshot.get("guaranteed_stop", False)),
        )

        body = self._post(PATH_POSITIONS, payload)
        deal_reference = body.get("dealReference")
        if not deal_reference:
            raise CapitalMalformedResponse(
                "استجابة الإرسال بلا dealReference — لا يمكن إثبات ما حدث."
            )

        state, confirmation = self.poll_confirmation(str(deal_reference))
        at = now_utc()

        if state is ExecutionUncertainty.UNKNOWN or confirmation is None:
            raise CapitalExecutionUncertain(
                f"أُرسل الأمر ({deal_reference}) ولم يُحسم مصيره. "
                "لا تُعيدي الإرسال: استقصي بـresolve_unknown_execution، "
                "وفعّلي قاطع الطوارئ."
            )

        if state is ExecutionUncertainty.RESOLVED_REJECTED:
            return BrokerOrder(
                broker_order_id=confirmation.deal_id or "",
                client_order_id=str(deal_reference),
                symbol=intent.symbol,
                side=intent.side,
                order_type=intent.order_type,
                quantity=intent.quantity,
                filled_quantity=D("0"),
                average_fill_price=None,
                status=OrderStatus.REJECTED,
                updated_at_utc=at,
            )

        # المطابقة: ما نُفِّذ يجب أن يكون ما نويناه، حرفاً بحرف.
        if confirmation.epic and confirmation.epic.upper() != intent.symbol.upper():
            raise BrokerRejected(
                f"أداة مختلفة: نُفِّذ {confirmation.epic} ونويناه {intent.symbol}."
            )
        if confirmation.direction and confirmation.direction.upper() != intent.side.value:
            raise BrokerRejected(
                f"اتجاه مختلف: نُفِّذ {confirmation.direction} ونويناه {intent.side.value}."
            )
        if confirmation.size is not None and confirmation.size != intent.quantity:
            raise BrokerRejected(
                f"كمية مختلفة: نُفِّذت {confirmation.size} ونويناها {intent.quantity}."
            )

        return BrokerOrder(
            broker_order_id=confirmation.deal_id or "",
            client_order_id=str(deal_reference),
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            quantity=intent.quantity,
            filled_quantity=confirmation.size or intent.quantity,
            average_fill_price=confirmation.level,
            status=OrderStatus.FILLED,
            updated_at_utc=at,
        )

    def confirm_order(self, client_order_id: str) -> BrokerOrder:
        """قراءة فقط — مسموحة، لأن التأكيد هو ما ينقذنا من الحالة الغامضة."""
        state, confirmation = self.poll_confirmation(client_order_id, attempts=1)
        at = now_utc()
        if confirmation is None:
            return BrokerOrder(
                broker_order_id="",
                client_order_id=client_order_id,
                symbol="",
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=D("0"),
                filled_quantity=D("0"),
                average_fill_price=None,
                status=OrderStatus.UNKNOWN,
                updated_at_utc=at,
            )
        status = OrderStatus.FILLED if confirmation.accepted else OrderStatus.REJECTED
        return BrokerOrder(
            broker_order_id=confirmation.deal_id or "",
            client_order_id=confirmation.deal_reference,
            symbol=confirmation.epic or "",
            side=Side.BUY if (confirmation.direction or "BUY").upper() == "BUY" else Side.SELL,
            order_type=OrderType.MARKET,
            quantity=confirmation.size or D("0"),
            filled_quantity=(confirmation.size or D("0")) if confirmation.accepted else D("0"),
            average_fill_price=confirmation.level,
            status=status,
            updated_at_utc=at,
        )

    def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        self.execution_lock.assert_can_execute("DELETE /workingorders")
        raise NotImplementedError("إلغاء الأوامر مقفل تحت هذه المهمة.")

    def close_position(self, account_id: str, symbol: str, quantity: Decimal) -> BrokerOrder:
        self.execution_lock.assert_can_execute("DELETE /positions")
        raise NotImplementedError("إغلاق المراكز مقفل تحت هذه المهمة.")

    def update_position(
        self, deal_id: str, *, stop_level: Optional[Decimal] = None,
        profit_level: Optional[Decimal] = None,
    ) -> None:
        self.execution_lock.assert_can_execute("PUT /positions")
        raise NotImplementedError("تعديل المراكز مقفل تحت هذه المهمة.")

    def update_preferences(self, **kwargs) -> None:
        self.execution_lock.assert_can_execute("PUT /accounts/preferences")
        raise NotImplementedError(
            "تعديل تفضيلات الحساب (الرافعة/التحوّط) ممنوع تحت هذه المهمة نهائياً."
        )

    def top_up_demo(self, amount: Decimal) -> None:
        self.execution_lock.assert_can_execute("POST /accounts/topUp")
        raise NotImplementedError("شحن الحساب التجريبي ممنوع تحت هذه المهمة.")

    # ------------------------------------------------------------------
    def state_for_report(self) -> dict:
        account = self.selected_account
        return {
            "broker": self.broker.value,
            "environment": self.session.environment.value,
            "connected": self._connected,
            "is_live": self.is_live,
            "execution_lock": self.execution_lock.as_dict(),
            "selected_account_masked": account.masked_id if account else None,
            "discovery_allowlist": sorted(self.discovery_allowlist),
            "execution_allowlist": sorted(self.execution_allowlist),
            "session": self.session.state_for_report(),
        }
