"""
LIVE DISCOVERY — قراءة الحساب الحقيقي والأدوات، ثم بناء تقرير مُنقّى.

**لا شيء هنا يُنفّذ صفقة.** هذه الحزمة لا تستورد خدمة تنفيذ ولا موجّه أوامر
ولا أي ميثود تعديل مركز — مُختبَر بتحليل AST.

نتيجة الاكتشاف **لا تأذن بالتنفيذ**: قائمة التنفيذ تبقى EUR/USD وحدها،
والاستراتيجيات تبقى `RESEARCH`، وقفل Live العام يبقى مغلقاً.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ..clock import format_riyadh, now_utc
from ..money import D
from .overnight import (
    OVERNIGHT_RATE_UNIT_UNKNOWN,
    OvernightRateUnit,
    resolve_unit,
)
from .session import LiveSession

#: أدوات الاكتشاف. قائمة **الاكتشاف** أوسع من قائمة **التنفيذ** عمداً:
#: معرفة شروط أداة لا تعني الإذن بتداولها.
DISCOVERY_EPICS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "GOLD")

#: قائمة التنفيذ — لا تتغيّر بنتيجة أي اكتشاف.
EXECUTION_EPICS: tuple[str, ...] = ("EURUSD",)


def _dec(value: Any) -> Optional[Decimal]:
    """
    `Decimal("NaN")` و`Decimal("Infinity")` **لا يرفعان استثناءً** — وهذه هي
    الخدعة: قيمة `NaN` تمرّ كل مقارنة (`NaN <= 0` تساوي False) فتتسلّل إلى
    الحساب بلا أن يوقفها فحص «موجب». تُرفض هنا صراحةً.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        result = D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def mask_account_id(account_id: Any) -> str:
    """
    لا يُعرض المعرّف الكامل أبداً — آخر أربعة محارف فقط.
    المعرّف القصير يُقنَّع كلياً بدل أن يُكشف جزئياً.
    """
    if not account_id:
        return "****"
    text = str(account_id)
    if len(text) <= 4:
        return "*" * len(text)
    return "****" + text[-4:]


@dataclass(frozen=True)
class LiveAccountInfo:
    masked_id: str
    currency: Optional[str]
    account_type: Optional[str]
    balance: Optional[Decimal]
    available: Optional[Decimal]
    profit_loss: Optional[Decimal]
    status: Optional[str]
    hedging_mode: Optional[bool]
    leverage_preferences: dict[str, Any]
    dealing_enabled: Optional[bool]

    def as_dict(self) -> dict:
        return {
            "masked_id": self.masked_id,
            "currency": self.currency,
            "account_type": self.account_type,
            "balance": str(self.balance) if self.balance is not None else None,
            "available": str(self.available) if self.available is not None else None,
            "profit_loss": str(self.profit_loss) if self.profit_loss is not None else None,
            "status": self.status,
            "hedging_mode": self.hedging_mode,
            "leverage_preferences": self.leverage_preferences,
            "dealing_enabled": self.dealing_enabled,
        }


@dataclass(frozen=True)
class LiveInstrumentInfo:
    epic: str
    found: bool
    market_status: Optional[str] = None
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    spread: Optional[Decimal] = None
    min_deal_size: Optional[Decimal] = None
    min_deal_size_unit: Optional[str] = None
    size_increment: Optional[Decimal] = None
    size_increment_unit: Optional[str] = None
    margin_factor: Optional[Decimal] = None
    margin_factor_unit: Optional[str] = None
    min_stop_distance: Optional[Decimal] = None
    min_stop_distance_unit: Optional[str] = None
    min_step_distance: Optional[Decimal] = None
    min_step_distance_unit: Optional[str] = None
    min_guaranteed_stop_distance: Optional[Decimal] = None
    min_guaranteed_stop_distance_unit: Optional[str] = None
    guaranteed_stop_available: Optional[bool] = None
    guaranteed_stop_premium: Optional[Decimal] = None
    pip_definition: Optional[str] = None
    pip_position: Optional[str] = None
    tick_size: Optional[Decimal] = None
    lot_size: Optional[Decimal] = None
    decimal_places_factor: Optional[Decimal] = None
    scaling_factor: Optional[Decimal] = None
    contract_size: Optional[Decimal] = None
    quantity_interpretation: Optional[str] = None
    overnight_fee_long: Optional[Decimal] = None
    overnight_fee_short: Optional[Decimal] = None
    overnight_fee_time: Optional[str] = None
    #: الوحدة **المُثبتة** لمعدّل التبييت — لا المستنتَجة. انظر `overnight.py`.
    overnight_rate_unit: str = "UNKNOWN"
    overnight_rate_unit_source_ar: Optional[str] = None
    trading_hours: Optional[str] = None
    candles_available: Optional[bool] = None
    candles_count: Optional[int] = None
    data_age_seconds: Optional[float] = None
    snapshot_time: Optional[str] = None
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        def s(v):
            return str(v) if v is not None else None

        return {
            "epic": self.epic,
            "found": self.found,
            "market_status": self.market_status,
            "bid": s(self.bid),
            "ask": s(self.ask),
            "spread": s(self.spread),
            "min_deal_size": s(self.min_deal_size),
            "min_deal_size_unit": self.min_deal_size_unit,
            "size_increment": s(self.size_increment),
            "size_increment_unit": self.size_increment_unit,
            "margin_factor": s(self.margin_factor),
            "margin_factor_unit": self.margin_factor_unit,
            "min_stop_distance": s(self.min_stop_distance),
            "min_stop_distance_unit": self.min_stop_distance_unit,
            "min_step_distance": s(self.min_step_distance),
            "min_step_distance_unit": self.min_step_distance_unit,
            "min_guaranteed_stop_distance": s(self.min_guaranteed_stop_distance),
            "min_guaranteed_stop_distance_unit": self.min_guaranteed_stop_distance_unit,
            "guaranteed_stop_available": self.guaranteed_stop_available,
            "guaranteed_stop_premium": s(self.guaranteed_stop_premium),
            "pip_definition": self.pip_definition,
            "pip_position": self.pip_position,
            "tick_size": s(self.tick_size),
            "lot_size": s(self.lot_size),
            "decimal_places_factor": s(self.decimal_places_factor),
            "scaling_factor": s(self.scaling_factor),
            "contract_size": s(self.contract_size),
            "quantity_interpretation": self.quantity_interpretation,
            "overnight_fee_long": s(self.overnight_fee_long),
            "overnight_fee_short": s(self.overnight_fee_short),
            "overnight_fee_time": self.overnight_fee_time,
            "overnight_rate_unit": self.overnight_rate_unit,
            "overnight_rate_unit_source_ar": self.overnight_rate_unit_source_ar,
            "trading_hours": self.trading_hours,
            "candles_available": self.candles_available,
            "candles_count": self.candles_count,
            "data_age_seconds": self.data_age_seconds,
            "snapshot_time": self.snapshot_time,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class LiveDiscoveryReport:
    generated_at_utc: datetime
    generated_at_riyadh: str
    host: str
    account: Optional[LiveAccountInfo]
    instruments: tuple[LiveInstrumentInfo, ...]
    operations_sent: tuple[tuple[str, str], ...]
    errors: tuple[str, ...]
    notes: tuple[str, ...]
    tokens_retained: bool
    execution_epics: tuple[str, ...] = EXECUTION_EPICS

    def instrument(self, epic: str) -> Optional[LiveInstrumentInfo]:
        for i in self.instruments:
            if i.epic == epic:
                return i
        return None

    def as_dict(self) -> dict:
        return {
            "generated_at_utc": self.generated_at_utc.isoformat(),
            "generated_at_riyadh": self.generated_at_riyadh,
            "host": self.host,
            "read_only": True,
            "account": self.account.as_dict() if self.account else None,
            "instruments": [i.as_dict() for i in self.instruments],
            "operations_sent": [list(op) for op in self.operations_sent],
            "errors": list(self.errors),
            "notes": list(self.notes),
            "tokens_retained": self.tokens_retained,
            "execution_epics": list(self.execution_epics),
            "authorises_execution": False,
        }


# ---------------------------------------------------------------------------
# الاستخراج
# ---------------------------------------------------------------------------

def _extract_account(accounts_body: Any, prefs_body: Any) -> Optional[LiveAccountInfo]:
    if not isinstance(accounts_body, dict):
        return None
    accounts = accounts_body.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        return None

    preferred = next(
        (a for a in accounts if isinstance(a, dict) and a.get("preferred")), accounts[0]
    )
    if not isinstance(preferred, dict):
        return None

    balance_block = preferred.get("balance") or {}
    if not isinstance(balance_block, dict):
        balance_block = {}

    prefs = prefs_body if isinstance(prefs_body, dict) else {}
    leverages = prefs.get("leverages")
    leverage_preferences: dict[str, Any] = {}
    if isinstance(leverages, dict):
        for key, value in leverages.items():
            if isinstance(value, dict):
                leverage_preferences[str(key)] = {
                    "current": value.get("current"),
                    "max": value.get("max"),
                }
            else:
                leverage_preferences[str(key)] = value

    return LiveAccountInfo(
        masked_id=mask_account_id(preferred.get("accountId")),
        currency=preferred.get("currency"),
        account_type=preferred.get("accountType"),
        balance=_dec(balance_block.get("balance")),
        available=_dec(balance_block.get("available")),
        profit_loss=_dec(balance_block.get("profitLoss")),
        status=preferred.get("status"),
        hedging_mode=prefs.get("hedgingMode"),
        leverage_preferences=leverage_preferences,
        dealing_enabled=(
            preferred.get("status") == "ENABLED"
            if preferred.get("status") is not None
            else None
        ),
    )


def _extract_instrument(epic: str, body: Any, now: datetime) -> LiveInstrumentInfo:
    if not isinstance(body, dict):
        return LiveInstrumentInfo(epic=epic, found=False, notes=("استجابة غير متوقعة.",))

    instrument = body.get("instrument") or {}
    snapshot = body.get("snapshot") or {}
    rules = body.get("dealingRules") or {}
    if not isinstance(instrument, dict):
        instrument = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    if not isinstance(rules, dict):
        rules = {}

    def rule(name: str) -> tuple[Optional[Decimal], Optional[str]]:
        block = rules.get(name)
        if isinstance(block, dict):
            return _dec(block.get("value")), block.get("unit")
        return _dec(block), None

    bid = _dec(snapshot.get("bid"))
    ask = _dec(snapshot.get("offer"))
    spread = (ask - bid) if (bid is not None and ask is not None) else None

    min_size, min_size_unit = rule("minDealSize")
    step, step_unit = rule("minSizeIncrement")
    min_stop, min_stop_unit = rule("minNormalStopOrLimitDistance")
    min_step, min_step_unit = rule("minStepDistance")
    min_gsl, min_gsl_unit = rule("minGuaranteedStopDistance")
    if min_gsl is None:
        # الاسم يختلف بين إصدارات الواجهة — يُجرَّب البديل الموثَّق.
        min_gsl, min_gsl_unit = rule("minControlledRiskStopDistance")

    overnight = instrument.get("overnightFee") or {}
    if not isinstance(overnight, dict):
        overnight = {}
    overnight_unit, overnight_unit_source = resolve_unit(overnight)
    if overnight_unit is OvernightRateUnit.UNKNOWN and (
        overnight.get("longRate") is not None
    ):
        notes_unit = (
            "وحدة معدّل التبييت غير مُثبتة ⇒ لا تُحسب تكلفة تبييت "
            f"({OVERNIGHT_RATE_UNIT_UNKNOWN})."
        )
    else:
        notes_unit = None

    notes: list[str] = []
    if notes_unit:
        notes.append(notes_unit)
    margin_factor = _dec(instrument.get("marginFactor"))
    if margin_factor is None:
        notes.append("معامل الهامش غير معلن في الاستجابة.")

    gsl_available = instrument.get("guaranteedStopAllowed")
    if gsl_available is None:
        gsl_available = instrument.get("controlledRiskAllowed")

    age: Optional[float] = None
    updated = snapshot.get("updateTime") or snapshot.get("updateTimeUTC")
    if isinstance(updated, str):
        try:
            parsed = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                age = (now - parsed).total_seconds()
        except ValueError:
            notes.append("تعذّر تفسير طابع تحديث السعر.")

    return LiveInstrumentInfo(
        epic=str(instrument.get("epic") or epic),
        found=True,
        market_status=snapshot.get("marketStatus") or instrument.get("marketStatus"),
        bid=bid,
        ask=ask,
        spread=spread,
        min_deal_size=min_size,
        min_deal_size_unit=min_size_unit,
        size_increment=step,
        size_increment_unit=step_unit,
        margin_factor=margin_factor,
        margin_factor_unit=instrument.get("marginFactorUnit"),
        min_stop_distance=min_stop,
        min_stop_distance_unit=min_stop_unit,
        min_step_distance=min_step,
        min_step_distance_unit=min_step_unit,
        min_guaranteed_stop_distance=min_gsl,
        min_guaranteed_stop_distance_unit=min_gsl_unit,
        guaranteed_stop_available=(
            bool(gsl_available) if gsl_available is not None else None
        ),
        guaranteed_stop_premium=_dec(instrument.get("guaranteedStopPremium")),
        pip_definition=instrument.get("onePipMeans"),
        pip_position=(
            str(instrument.get("pipPosition"))
            if instrument.get("pipPosition") is not None else None
        ),
        tick_size=_dec(instrument.get("tickSize") or snapshot.get("tickSize")),
        lot_size=_dec(instrument.get("lotSize")),
        decimal_places_factor=_dec(snapshot.get("decimalPlacesFactor")),
        scaling_factor=_dec(snapshot.get("scalingFactor")),
        contract_size=_dec(instrument.get("contractSize")),
        quantity_interpretation=instrument.get("unit") or instrument.get("type"),
        overnight_fee_long=_dec(overnight.get("longRate")),
        overnight_fee_short=_dec(overnight.get("shortRate")),
        overnight_fee_time=overnight.get("swapChargeTimestamp"),
        overnight_rate_unit=overnight_unit.value,
        overnight_rate_unit_source_ar=overnight_unit_source,
        trading_hours=_summarise_hours(instrument.get("openingHours")),
        snapshot_time=updated if isinstance(updated, str) else None,
        data_age_seconds=age,
        notes=tuple(notes),
    )


def _summarise_hours(hours: Any) -> Optional[str]:
    """ملخص نصي قصير لساعات التداول — لا يُنسخ الكائن كاملاً."""
    if isinstance(hours, dict):
        days = [k for k in hours.keys() if isinstance(k, str)]
        if days:
            return "أيام معلنة: " + "، ".join(sorted(days)[:7])
    if isinstance(hours, list) and hours:
        return f"{len(hours)} فترة معلنة"
    return None


# ---------------------------------------------------------------------------
# التشغيل
# ---------------------------------------------------------------------------

def run_live_discovery(
    session: LiveSession,
    *,
    epics: tuple[str, ...] = DISCOVERY_EPICS,
    fetch_candles: bool = True,
) -> LiveDiscoveryReport:
    """
    يقرأ الحساب والأدوات. **لا يرمي عند فشل أداة واحدة** — يسجّل الخطأ ويكمل،
    لأن تقريراً ناقصاً موثّقاً أنفع من انهيار بلا معلومة.
    """
    at = now_utc()
    errors: list[str] = []
    notes: list[str] = []

    accounts_body: Any = None
    prefs_body: Any = None

    try:
        response = session.get("/api/v1/accounts")
        if response.ok:
            accounts_body = response.body
        else:
            errors.append(f"قراءة الحسابات فشلت (HTTP {response.status}).")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"تعذّرت قراءة الحسابات ({type(exc).__name__}).")

    try:
        response = session.get("/api/v1/accounts/preferences")
        if response.ok:
            prefs_body = response.body
        else:
            errors.append(f"قراءة التفضيلات فشلت (HTTP {response.status}).")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"تعذّرت قراءة التفضيلات ({type(exc).__name__}).")

    account = _extract_account(accounts_body, prefs_body)
    if account is None:
        errors.append("تعذّر استخراج معلومات الحساب من الاستجابة.")

    instruments: list[LiveInstrumentInfo] = []
    for epic in epics:
        try:
            response = session.get(f"/api/v1/markets/{epic}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{epic}: تعذّرت القراءة ({type(exc).__name__}).")
            instruments.append(LiveInstrumentInfo(epic=epic, found=False))
            continue

        if not response.ok:
            errors.append(f"{epic}: HTTP {response.status}.")
            instruments.append(LiveInstrumentInfo(epic=epic, found=False))
            continue

        info = _extract_instrument(epic, response.body, at)

        if fetch_candles:
            try:
                candles = session.get(
                    f"/api/v1/prices/{epic}", params={"resolution": "DAY", "max": 10}
                )
                if candles.ok and isinstance(candles.body, dict):
                    prices = candles.body.get("prices")
                    count = len(prices) if isinstance(prices, list) else 0
                    info = _replace_candles(info, available=count > 0, count=count)
                else:
                    info = _replace_candles(info, available=False, count=0)
                    notes.append(f"{epic}: لا شموع تاريخية متاحة عبر هذا المسار.")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{epic}: تعذّرت قراءة الشموع ({type(exc).__name__}).")

        instruments.append(info)

    notes.append(
        "نتيجة الاكتشاف لا تأذن بالتنفيذ. قائمة التنفيذ تبقى EUR/USD وحدها، "
        "والاستراتيجيات تبقى RESEARCH، وقفل Live العام يبقى مغلقاً."
    )

    return LiveDiscoveryReport(
        generated_at_utc=at,
        generated_at_riyadh=format_riyadh(at),
        host=session.transport.name,
        account=account,
        instruments=tuple(instruments),
        operations_sent=tuple(session.transport.sent),
        errors=tuple(errors),
        notes=tuple(notes),
        tokens_retained=session.tokens_retained,
    )


def _replace_candles(
    info: LiveInstrumentInfo, *, available: bool, count: int
) -> LiveInstrumentInfo:
    from dataclasses import replace

    return replace(info, candles_available=available, candles_count=count)


__all__ = [
    "DISCOVERY_EPICS",
    "EXECUTION_EPICS",
    "LiveAccountInfo",
    "LiveInstrumentInfo",
    "LiveDiscoveryReport",
    "run_live_discovery",
    "mask_account_id",
]
