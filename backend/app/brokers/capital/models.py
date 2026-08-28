"""
تحويل استجابات Capital.com إلى نماذج داخلية مُتحقَّق منها.

قاعدة: إذا نقص حقل جوهري، نرمي `CapitalMalformedResponse` ولا نخمّن قيمة.
حقل ناقص في نموذج تكلفة = خسارة حقيقية لاحقاً.

أسماء الحقول مأخوذة حرفياً من الوثيقة الرسمية (تُحقق 2026-08-28).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ...money import D
from .errors import CapitalMalformedResponse


def _require(body: dict, key: str, context: str) -> Any:
    if key not in body or body[key] is None:
        raise CapitalMalformedResponse(
            f"استجابة {context} تفتقد الحقل الإلزامي «{key}» — لن نخمّن قيمته."
        )
    return body[key]


def _decimal(value: Any, context: str) -> Decimal:
    try:
        return D(value)
    except (InvalidOperation, TypeError, ValueError):
        raise CapitalMalformedResponse(f"قيمة غير رقمية في {context}: نوع {type(value).__name__}") from None


def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return D(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def mask_account_id(account_id: str) -> str:
    """معرّف الحساب لا يظهر كاملاً أبداً في تقرير أو واجهة أو سجل."""
    text = str(account_id or "")
    if len(text) <= 4:
        return "****"
    return f"****{text[-4:]}"


# ---------------------------------------------------------------------------
# الحساب
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapitalBalance:
    balance: Decimal
    deposit: Decimal
    profit_loss: Decimal
    available: Decimal

    @staticmethod
    def parse(body: dict) -> "CapitalBalance":
        return CapitalBalance(
            balance=_decimal(_require(body, "balance", "balance"), "balance.balance"),
            deposit=_decimal(body.get("deposit", 0), "balance.deposit"),
            profit_loss=_decimal(body.get("profitLoss", 0), "balance.profitLoss"),
            available=_decimal(_require(body, "available", "balance"), "balance.available"),
        )


@dataclass(frozen=True)
class CapitalAccount:
    account_id: str
    account_name: str
    status: str
    account_type: str
    preferred: bool
    currency: str
    balance: CapitalBalance
    symbol: Optional[str] = None

    @property
    def masked_id(self) -> str:
        return mask_account_id(self.account_id)

    @staticmethod
    def parse(body: dict) -> "CapitalAccount":
        return CapitalAccount(
            account_id=str(_require(body, "accountId", "accounts")),
            account_name=str(body.get("accountName", "")),
            status=str(body.get("status", "UNKNOWN")),
            account_type=str(body.get("accountType", "UNKNOWN")),
            preferred=bool(body.get("preferred", False)),
            currency=str(_require(body, "currency", "accounts")),
            balance=CapitalBalance.parse(_require(body, "balance", "accounts")),
            symbol=body.get("symbol"),
        )

    @staticmethod
    def parse_list(body: dict) -> list["CapitalAccount"]:
        accounts = _require(body, "accounts", "accounts")
        if not isinstance(accounts, list):
            raise CapitalMalformedResponse("حقل accounts ليس قائمة.")
        return [CapitalAccount.parse(a) for a in accounts]

    def for_report(self) -> dict:
        return {
            "account_masked": self.masked_id,
            "account_name": self.account_name,
            "status": self.status,
            "account_type": self.account_type,
            "preferred": self.preferred,
            "currency": self.currency,
            "balance": str(self.balance.balance),
            "available": str(self.balance.available),
            "profit_loss": str(self.balance.profit_loss),
        }


@dataclass(frozen=True)
class CapitalPreferences:
    hedging_mode: bool
    leverages: dict[str, dict[str, Any]]

    @staticmethod
    def parse(body: dict) -> "CapitalPreferences":
        return CapitalPreferences(
            hedging_mode=bool(body.get("hedgingMode", False)),
            leverages=dict(body.get("leverages", {}) or {}),
        )

    def leverage_for(self, category: str) -> Optional[Decimal]:
        entry = self.leverages.get(category) or {}
        return _optional_decimal(entry.get("current"))

    def for_report(self) -> dict:
        return {
            "hedging_mode": self.hedging_mode,
            "leverages": {
                k: {"current": str((v or {}).get("current"))} for k, v in self.leverages.items()
            },
        }


# ---------------------------------------------------------------------------
# السوق
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DealingRules:
    min_deal_size: Decimal
    max_deal_size: Optional[Decimal]
    min_size_increment: Optional[Decimal]
    min_stop_or_profit_distance: Optional[Decimal]
    max_stop_or_profit_distance: Optional[Decimal]
    min_guaranteed_stop_distance: Optional[Decimal]
    market_order_preference: Optional[str]
    trailing_stops_preference: Optional[str]

    @staticmethod
    def parse(body: dict) -> "DealingRules":
        def unit_value(raw: Any) -> Optional[Decimal]:
            """Capital.com يعيد أحياناً {"unit": "...", "value": n} وأحياناً رقماً."""
            if raw is None:
                return None
            if isinstance(raw, dict):
                return _optional_decimal(raw.get("value"))
            return _optional_decimal(raw)

        min_size = unit_value(_require(body, "minDealSize", "dealingRules"))
        if min_size is None:
            raise CapitalMalformedResponse("minDealSize غير قابل للقراءة.")
        return DealingRules(
            min_deal_size=min_size,
            max_deal_size=unit_value(body.get("maxDealSize")),
            min_size_increment=unit_value(body.get("minSizeIncrement")),
            min_stop_or_profit_distance=unit_value(body.get("minStopOrProfitDistance")),
            max_stop_or_profit_distance=unit_value(body.get("maxStopOrProfitDistance")),
            min_guaranteed_stop_distance=unit_value(body.get("minGuaranteedStopDistance")),
            market_order_preference=body.get("marketOrderPreference"),
            trailing_stops_preference=body.get("trailingStopsPreference"),
        )


@dataclass(frozen=True)
class MarketSnapshot:
    market_status: str
    bid: Optional[Decimal]
    offer: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    update_time: Optional[str]
    delay_time: Optional[Decimal]

    @property
    def spread(self) -> Optional[Decimal]:
        if self.bid is None or self.offer is None:
            return None
        return self.offer - self.bid

    @property
    def is_tradeable(self) -> bool:
        return self.market_status.upper() == "TRADEABLE"

    @staticmethod
    def parse(body: dict) -> "MarketSnapshot":
        return MarketSnapshot(
            market_status=str(body.get("marketStatus", "UNKNOWN")),
            bid=_optional_decimal(body.get("bid")),
            offer=_optional_decimal(body.get("offer")),
            high=_optional_decimal(body.get("high")),
            low=_optional_decimal(body.get("low")),
            update_time=body.get("updateTime"),
            delay_time=_optional_decimal(body.get("delayTime")),
        )


@dataclass(frozen=True)
class CapitalMarket:
    epic: str
    symbol: str
    name: str
    instrument_type: str
    currencies: tuple[str, ...]
    lot_size: Optional[Decimal]
    guaranteed_stop_allowed: bool
    streaming_prices_available: bool
    margin_factor: Optional[Decimal]
    margin_factor_unit: Optional[str]
    overnight_fee: Optional[Decimal]
    dealing_rules: DealingRules
    snapshot: MarketSnapshot

    @staticmethod
    def parse(body: dict) -> "CapitalMarket":
        instrument = _require(body, "instrument", "markets/{epic}")
        rules = DealingRules.parse(_require(body, "dealingRules", "markets/{epic}"))
        snapshot = MarketSnapshot.parse(_require(body, "snapshot", "markets/{epic}"))

        currencies_raw = instrument.get("currencies") or []
        currencies: list[str] = []
        for c in currencies_raw:
            if isinstance(c, dict):
                code = c.get("code") or c.get("name")
                if code:
                    currencies.append(str(code))
            elif c:
                currencies.append(str(c))

        return CapitalMarket(
            epic=str(_require(instrument, "epic", "instrument")),
            symbol=str(instrument.get("symbol", instrument.get("epic", ""))),
            name=str(instrument.get("name", "")),
            instrument_type=str(instrument.get("type", "UNKNOWN")),
            currencies=tuple(currencies),
            lot_size=_optional_decimal(instrument.get("lotSize")),
            guaranteed_stop_allowed=bool(instrument.get("guaranteedStopAllowed", False)),
            streaming_prices_available=bool(instrument.get("streamingPricesAvailable", False)),
            margin_factor=_optional_decimal(instrument.get("marginFactor")),
            margin_factor_unit=instrument.get("marginFactorUnit"),
            overnight_fee=_optional_decimal(instrument.get("overnightFee")),
            dealing_rules=rules,
            snapshot=snapshot,
        )

    @property
    def quote_currency(self) -> Optional[str]:
        return self.currencies[0] if self.currencies else None

    def for_report(self) -> dict:
        return {
            "epic": self.epic,
            "symbol": self.symbol,
            "name": self.name,
            "type": self.instrument_type,
            "currencies": list(self.currencies),
            "lot_size": str(self.lot_size) if self.lot_size is not None else None,
            "guaranteed_stop_allowed": self.guaranteed_stop_allowed,
            "streaming_prices_available": self.streaming_prices_available,
            "margin_factor": str(self.margin_factor) if self.margin_factor is not None else None,
            "margin_factor_unit": self.margin_factor_unit,
            "overnight_fee": str(self.overnight_fee) if self.overnight_fee is not None else None,
            "market_status": self.snapshot.market_status,
            "bid": str(self.snapshot.bid) if self.snapshot.bid is not None else None,
            "offer": str(self.snapshot.offer) if self.snapshot.offer is not None else None,
            "spread": str(self.snapshot.spread) if self.snapshot.spread is not None else None,
            "min_deal_size": str(self.dealing_rules.min_deal_size),
            "min_size_increment": (
                str(self.dealing_rules.min_size_increment)
                if self.dealing_rules.min_size_increment is not None
                else None
            ),
            "min_stop_or_profit_distance": (
                str(self.dealing_rules.min_stop_or_profit_distance)
                if self.dealing_rules.min_stop_or_profit_distance is not None
                else None
            ),
            "min_guaranteed_stop_distance": (
                str(self.dealing_rules.min_guaranteed_stop_distance)
                if self.dealing_rules.min_guaranteed_stop_distance is not None
                else None
            ),
        }


@dataclass(frozen=True)
class MarketSummary:
    """عنصر مختصر من GET /markets?searchTerm="""

    epic: str
    instrument_name: str
    instrument_type: str
    market_status: str
    bid: Optional[Decimal]
    offer: Optional[Decimal]

    @staticmethod
    def parse_list(body: dict) -> list["MarketSummary"]:
        markets = body.get("markets")
        if markets is None:
            raise CapitalMalformedResponse("استجابة البحث لا تحتوي حقل markets.")
        out: list[MarketSummary] = []
        for m in markets:
            out.append(
                MarketSummary(
                    epic=str(m.get("epic", "")),
                    instrument_name=str(m.get("instrumentName", "")),
                    instrument_type=str(m.get("instrumentType", "")),
                    market_status=str(m.get("marketStatus", "UNKNOWN")),
                    bid=_optional_decimal(m.get("bid")),
                    offer=_optional_decimal(m.get("offer")),
                )
            )
        return out


# ---------------------------------------------------------------------------
# الأسعار التاريخية
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapitalCandle:
    snapshot_time_utc: datetime
    open_bid: Decimal
    open_ask: Decimal
    high_bid: Decimal
    high_ask: Decimal
    low_bid: Decimal
    low_ask: Decimal
    close_bid: Decimal
    close_ask: Decimal
    volume: Optional[Decimal]

    @property
    def mid_close(self) -> Decimal:
        return (self.close_bid + self.close_ask) / D(2)

    @staticmethod
    def _side(raw: Any, side: str, field: str) -> Decimal:
        if not isinstance(raw, dict):
            raise CapitalMalformedResponse(f"حقل {field} ليس كائن bid/ask.")
        if side not in raw:
            raise CapitalMalformedResponse(f"حقل {field} يفتقد {side}.")
        return _decimal(raw[side], f"{field}.{side}")

    @staticmethod
    def parse(body: dict) -> "CapitalCandle":
        raw_time = body.get("snapshotTimeUTC") or body.get("snapshotTime")
        if not raw_time:
            raise CapitalMalformedResponse("شمعة بلا طابع زمني.")
        text = str(raw_time).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise CapitalMalformedResponse("طابع زمني غير صالح في الشموع.") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return CapitalCandle(
            snapshot_time_utc=parsed.astimezone(timezone.utc),
            open_bid=CapitalCandle._side(body.get("openPrice"), "bid", "openPrice"),
            open_ask=CapitalCandle._side(body.get("openPrice"), "ask", "openPrice"),
            high_bid=CapitalCandle._side(body.get("highPrice"), "bid", "highPrice"),
            high_ask=CapitalCandle._side(body.get("highPrice"), "ask", "highPrice"),
            low_bid=CapitalCandle._side(body.get("lowPrice"), "bid", "lowPrice"),
            low_ask=CapitalCandle._side(body.get("lowPrice"), "ask", "lowPrice"),
            close_bid=CapitalCandle._side(body.get("closePrice"), "bid", "closePrice"),
            close_ask=CapitalCandle._side(body.get("closePrice"), "ask", "closePrice"),
            volume=_optional_decimal(body.get("lastTradedVolume")),
        )

    @staticmethod
    def parse_list(body: dict) -> list["CapitalCandle"]:
        prices = body.get("prices")
        if prices is None:
            raise CapitalMalformedResponse("استجابة الأسعار لا تحتوي حقل prices.")
        return [CapitalCandle.parse(p) for p in prices]


# ---------------------------------------------------------------------------
# المراكز والتأكيدات
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapitalPosition:
    deal_id: str
    epic: str
    direction: str
    size: Decimal
    level: Optional[Decimal]
    stop_level: Optional[Decimal]
    profit_level: Optional[Decimal]
    guaranteed_stop: bool
    upl: Optional[Decimal]
    currency: Optional[str]
    created_utc: Optional[str]

    @property
    def has_broker_stop(self) -> bool:
        return self.stop_level is not None

    @staticmethod
    def parse(body: dict) -> "CapitalPosition":
        position = body.get("position", body)
        market = body.get("market", {}) or {}
        return CapitalPosition(
            deal_id=str(_require(position, "dealId", "positions")),
            epic=str(market.get("epic") or position.get("epic") or ""),
            direction=str(_require(position, "direction", "positions")),
            size=_decimal(_require(position, "size", "positions"), "position.size"),
            level=_optional_decimal(position.get("level")),
            stop_level=_optional_decimal(position.get("stopLevel")),
            profit_level=_optional_decimal(position.get("profitLevel")),
            guaranteed_stop=bool(position.get("guaranteedStop", False)),
            upl=_optional_decimal(position.get("upl")),
            currency=position.get("currency"),
            created_utc=position.get("createdDateUTC") or position.get("createdDate"),
        )

    @staticmethod
    def parse_list(body: dict) -> list["CapitalPosition"]:
        positions = body.get("positions")
        if positions is None:
            raise CapitalMalformedResponse("استجابة المراكز لا تحتوي حقل positions.")
        return [CapitalPosition.parse(p) for p in positions]


@dataclass(frozen=True)
class CapitalConfirmation:
    """
    GET /confirms/{dealReference} — **المصدر الوحيد المقبول لإثبات التنفيذ**.

    استجابة 200 على POST لا تعني أن مركزاً فُتح. هذا الكائن يعني ذلك.
    """

    deal_reference: str
    deal_id: Optional[str]
    deal_status: str
    status: Optional[str]
    epic: Optional[str]
    direction: Optional[str]
    size: Optional[Decimal]
    level: Optional[Decimal]
    guaranteed_stop: bool
    reason: Optional[str]
    date: Optional[str]
    affected_deals: tuple[dict, ...]

    @property
    def accepted(self) -> bool:
        return self.deal_status.upper() == "ACCEPTED"

    @property
    def rejected(self) -> bool:
        return self.deal_status.upper() == "REJECTED"

    @staticmethod
    def parse(body: dict) -> "CapitalConfirmation":
        return CapitalConfirmation(
            deal_reference=str(_require(body, "dealReference", "confirms")),
            deal_id=body.get("dealId"),
            deal_status=str(_require(body, "dealStatus", "confirms")),
            status=body.get("status"),
            epic=body.get("epic"),
            direction=body.get("direction"),
            size=_optional_decimal(body.get("size")),
            level=_optional_decimal(body.get("level")),
            guaranteed_stop=bool(body.get("guaranteedStop", False)),
            reason=body.get("reason"),
            date=body.get("date"),
            affected_deals=tuple(body.get("affectedDeals") or ()),
        )
