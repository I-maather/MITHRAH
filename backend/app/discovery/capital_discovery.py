"""
اكتشاف Capital.com — **قراءة فقط، بلا استثناء**.

يجمع كل ما يحتاجه نموذج التكلفة ودستور المخاطر من مصدره الحقيقي (حساب Demo)
بدل الاعتماد على أرقام الموقع العام، ويكتب تقريرين منقّيَين من الأسرار.

ثلاث حمايات مستقلة:
  1. قفل التنفيذ مغلق ⇒ الناقل يرفض أي عملية مُعدِّلة.
  2. `assert_read_only_session()` يفحص كل عملية أُرسلت فعلاً بعد الانتهاء.
  3. قائمة أدوات الاكتشاف محدودة (EURUSD, GBPUSD, USDJPY, GOLD).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from ..brokers.capital.adapter import PIP_SIZES, CapitalComAdapter
from ..brokers.capital.endpoints import PATH_SESSION, CapitalEnvironment, is_read_only
from ..brokers.capital.models import CapitalMarket, mask_account_id
from ..brokers.capital.safety import MutatingEndpointBlocked
from ..brokers.capital.transport import GuardedTransport
from ..clock import format_riyadh, now_utc
from ..money import D
from ..risk.capital_costs import (
    PROVISIONAL_EURUSD,
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
    with_discovered_spread,
)
from ..risk.constitution import CONSTITUTION_VERSION, RiskLimits, RiskMode
from ..contracts import Broker, StopKind
from ..secretstore.redaction import redact

DISCOVERY_EPICS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "GOLD")
EXECUTION_EPICS: tuple[str, ...] = ("EURUSD",)

#: مسارات ممنوعة صراحةً في أمر الاكتشاف. وجود أي منها في السجل = فشل.
FORBIDDEN_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("POST", "/api/v1/positions"),
    ("PUT", "/api/v1/positions"),
    ("DELETE", "/api/v1/positions"),
    ("POST", "/api/v1/workingorders"),
    ("PUT", "/api/v1/workingorders"),
    ("DELETE", "/api/v1/workingorders"),
    ("PUT", "/api/v1/accounts/preferences"),
    ("POST", "/api/v1/accounts/topUp"),
)

STOP_DISTANCES_PIPS: tuple[Decimal, ...] = (D("25"), D("50"), D("75"))


class DiscoveryViolation(RuntimeError):
    """اكتُشفت عملية غير مسموحة — يُفشل التقرير كله."""


def assert_read_only_session(transport: GuardedTransport) -> None:
    """
    يفحص كل عملية أُرسلت فعلاً. POST /session مسموح (مصادقة لا تداول)،
    وكل ما عداه يجب أن يكون قراءة.
    """
    for method, path in transport.sent_operations:
        if (method, path) == ("POST", PATH_SESSION):
            continue
        if (method, path.rstrip("/")) in FORBIDDEN_OPERATIONS:
            raise DiscoveryViolation(f"عملية ممنوعة أُرسلت: {method} {path}")
        if not is_read_only(method, path):
            raise DiscoveryViolation(f"عملية ليست قراءة أُرسلت أثناء الاكتشاف: {method} {path}")


@dataclass
class MarketDiscovery:
    epic: str
    market: Optional[CapitalMarket]
    error_ar: Optional[str] = None
    candles_available: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.market is not None


@dataclass
class DiscoveryReport:
    generated_at_utc: datetime
    environment: str
    base_url: str
    constitution_version: str
    account_masked: Optional[str]
    account_currency: Optional[str]
    account_type: Optional[str]
    balance: Optional[Decimal]
    available: Optional[Decimal]
    profit_loss: Optional[Decimal]
    hedging_mode: Optional[bool]
    leverages: dict[str, Any]
    markets: list[MarketDiscovery]
    worked_examples: list[dict]
    discrepancies: list[str]
    notes: list[str]
    session_state: dict
    adapter_state: dict
    errors: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def generated_at_riyadh(self) -> str:
        return format_riyadh(self.generated_at_utc)

    def to_json(self) -> dict:
        payload = {
            "generated_at_utc": self.generated_at_utc.isoformat(),
            "generated_at_riyadh": self.generated_at_riyadh,
            "environment": self.environment,
            "base_url": self.base_url,
            "constitution_version": self.constitution_version,
            "account": {
                "masked_id": self.account_masked,
                "currency": self.account_currency,
                "type": self.account_type,
                "balance": str(self.balance) if self.balance is not None else None,
                "available": str(self.available) if self.available is not None else None,
                "profit_loss": str(self.profit_loss) if self.profit_loss is not None else None,
                "hedging_mode": self.hedging_mode,
                "leverages": self.leverages,
            },
            "markets": [
                {
                    "epic": m.epic,
                    "ok": m.ok,
                    "error_ar": m.error_ar,
                    "candles_available": m.candles_available,
                    **(m.market.for_report() if m.market else {}),
                    "pip_size": str(PIP_SIZES.get(m.epic.upper()))
                    if PIP_SIZES.get(m.epic.upper())
                    else None,
                }
                for m in self.markets
            ],
            "worked_examples": self.worked_examples,
            "discrepancies_from_public_site": self.discrepancies,
            "notes": self.notes,
            "session": self.session_state,
            "adapter": self.adapter_state,
            "errors": self.errors,
            "read_only": True,
            "secrets_included": False,
        }
        # حماية أخيرة: التقرير كله يمرّ عبر الحجب قبل الكتابة.
        return redact(payload)

    def to_markdown(self) -> str:
        j = self.to_json()
        lines: list[str] = []
        A = lines.append
        A("# Capital.com Demo Discovery — تقرير الاكتشاف")
        A("")
        A(f"> مُولَّد آلياً — قراءة فقط. لا يحتوي أي سرّ ولا معرّف حساب كامل.")
        A("")
        A("| البند | القيمة |")
        A("|---|---|")
        A(f"| التوقيت (UTC) | {j['generated_at_utc']} |")
        A(f"| التوقيت (الرياض) | {j['generated_at_riyadh']} |")
        A(f"| البيئة | {j['environment']} |")
        A(f"| العنوان | `{j['base_url']}` |")
        A(f"| إصدار دستور المخاطر | {j['constitution_version']} |")
        A(f"| الحساب | {j['account']['masked_id']} |")
        A(f"| عملة الحساب | {j['account']['currency']} |")
        A(f"| نوع الحساب | {j['account']['type']} |")
        A(f"| الرصيد | {j['account']['balance']} |")
        A(f"| المتاح | {j['account']['available']} |")
        A(f"| الربح/الخسارة | {j['account']['profit_loss']} |")
        A(f"| وضع التحوّط | {j['account']['hedging_mode']} |")
        A("")

        A("## الأدوات")
        A("")
        A("| Epic | الحالة | العرض | الطلب | السبريد | أدنى كمية | زيادة الكمية | معامل الهامش | أدنى مسافة وقف | أدنى وقف مضمون | وقف مضمون متاح |")
        A("|---|---|---|---|---|---|---|---|---|---|---|")
        for m in j["markets"]:
            if not m["ok"]:
                A(f"| {m['epic']} | ❌ {m['error_ar']} | — | — | — | — | — | — | — | — | — |")
                continue
            A(
                f"| {m['epic']} | {m.get('market_status')} | {m.get('bid')} | {m.get('offer')} | "
                f"{m.get('spread')} | {m.get('min_deal_size')} | {m.get('min_size_increment')} | "
                f"{m.get('margin_factor')} {m.get('margin_factor_unit') or ''} | "
                f"{m.get('min_stop_or_profit_distance')} | {m.get('min_guaranteed_stop_distance')} | "
                f"{m.get('guaranteed_stop_allowed')} |"
            )
        A("")

        if j["worked_examples"]:
            A("## أمثلة محسوبة — EUR/USD")
            A("")
            A("التعرّض والهامش والخسارة **ثلاث قيم مختلفة** ولا يجوز الخلط بينها.")
            A("")
            A("| مسافة الوقف | الكمية | التعرّض | الهامش | قيمة النقطة | خسارة السعر | السبريد | احتياطي الانزلاق | **الخسارة الكلية** | ضمن 0.50 | ضمن 0.75 |")
            A("|---|---|---|---|---|---|---|---|---|---|---|")
            for ex in j["worked_examples"]:
                A(
                    f"| {ex['stop_distance_pips']} نقطة | {ex['size_broker_units']} | "
                    f"{ex['notional_exposure']} | {ex['margin_required']} | {ex['pip_value']} | "
                    f"{ex['price_loss']} | {ex['spread_cost']} | {ex['slippage_reserve']} | "
                    f"**{ex['all_in_risk_at_stop']}** | {ex['within_050']} | {ex['within_075']} |"
                )
            A("")

        if j["discrepancies_from_public_site"]:
            A("## اختلافات عن افتراضات الموقع العام")
            A("")
            for d in j["discrepancies_from_public_site"]:
                A(f"- {d}")
            A("")

        if j["notes"]:
            A("## ملاحظات")
            A("")
            for n in j["notes"]:
                A(f"- {n}")
            A("")

        if j["errors"]:
            A("## أخطاء")
            A("")
            for e in j["errors"]:
                A(f"- {e}")
            A("")

        A("## ضمانات هذا التقرير")
        A("")
        A("- قراءة فقط: لم تُرسل أي عملية إنشاء أو تعديل أو حذف.")
        A("- لا مفاتيح ولا رموز جلسة ولا معرّف حساب كامل.")
        A("- بيئة Demo حصراً؛ عنوان Live مقفل في الكود.")
        return "\n".join(lines) + "\n"


def _worked_examples(model: CapitalComCostModel, entry_price: Decimal) -> list[dict]:
    size = model.economics.min_deal_size
    out: list[dict] = []
    for pips in STOP_DISTANCES_PIPS:
        economics = model.estimate(
            size=size,
            entry_price=entry_price,
            stop_distance_pips=pips,
            take_profit_distance_pips=pips * D("2"),
            stop_kind=StopKind.NORMAL,
        )
        out.append(
            {
                "stop_distance_pips": f"{pips:.0f}",
                "size_broker_units": str(economics.size),
                "notional_exposure": f"{economics.notional_exposure:.2f}",
                "margin_required": f"{economics.margin_required:.2f}",
                "pip_value": f"{economics.pip_value:.4f}",
                "price_loss": f"{economics.price_loss_at_stop:.2f}",
                "spread_cost": f"{economics.spread_cost:.4f}",
                "slippage_reserve": f"{economics.slippage_reserve:.4f}",
                "all_in_risk_at_stop": f"{economics.all_in_risk:.2f}",
                "net_reward": f"{economics.net_reward:.2f}",
                "net_rr": f"{economics.net_reward_risk_ratio:.2f}",
                "within_050": "✅" if economics.all_in_risk <= D("0.50") else "❌",
                "within_075": "✅" if economics.all_in_risk <= D("0.75") else "❌",
                "provisional": economics.provisional,
            }
        )
    return out


def run_discovery(
    adapter: CapitalComAdapter,
    *,
    epics: tuple[str, ...] = DISCOVERY_EPICS,
    fetch_candles: bool = True,
) -> DiscoveryReport:
    """
    ينفّذ الاكتشاف كاملاً. لا يرمي عند فشل أداة واحدة — يسجّل الخطأ ويكمل،
    لأن تقريراً ناقصاً موثّقاً أنفع من انهيار بلا معلومة.
    """
    at = now_utc()
    errors: list[str] = []
    notes: list[str] = []
    discrepancies: list[str] = []

    account = None
    preferences = None
    try:
        account = adapter.select_account()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"تعذّر اختيار الحساب: {exc}")
    try:
        preferences = adapter.get_preferences()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"تعذّر قراءة تفضيلات الحساب: {exc}")

    markets: list[MarketDiscovery] = []
    for epic in epics:
        try:
            market = adapter.get_market(epic)
        except Exception as exc:  # noqa: BLE001
            markets.append(MarketDiscovery(epic=epic, market=None, error_ar=str(exc)))
            continue
        candles_available = None
        if fetch_candles:
            try:
                candles_available = len(adapter.get_candles(epic, resolution="HOUR", max_bars=50))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"تعذّر جلب شموع {epic}: {exc}")
        markets.append(
            MarketDiscovery(epic=epic, market=market, candles_available=candles_available)
        )
        if PIP_SIZES.get(epic.upper()) is None:
            notes.append(f"حجم النقطة غير معرّف للأداة {epic} — يجب تثبيته قبل أي حساب تكلفة.")

    # مقارنة بافتراضات الموقع العام لزوج EUR/USD
    worked: list[dict] = []
    eurusd = next((m for m in markets if m.epic.upper() == "EURUSD" and m.ok), None)
    if eurusd and eurusd.market:
        market = eurusd.market
        rules = market.dealing_rules
        if rules.min_deal_size != PROVISIONAL_EURUSD.min_deal_size:
            discrepancies.append(
                f"أدنى كمية فعلية {rules.min_deal_size} تختلف عن افتراض الموقع العام "
                f"{PROVISIONAL_EURUSD.min_deal_size}."
            )
        if market.margin_factor is not None and market.margin_factor != PROVISIONAL_EURUSD.margin_factor:
            discrepancies.append(
                f"معامل الهامش الفعلي {market.margin_factor} "
                f"{market.margin_factor_unit or ''} يختلف عن افتراض 1%."
            )
        if not market.guaranteed_stop_allowed:
            discrepancies.append(
                "الوقف المضمون غير متاح لهذه الأداة في هذا الحساب — أي خطة تعتمد عليه تسقط."
            )
        if rules.min_guaranteed_stop_distance is None:
            notes.append("أدنى مسافة وقف مضمون غير معلنة في استجابة الوسيط.")

        pip_size = PIP_SIZES.get("EURUSD")
        if pip_size and market.snapshot.bid is not None and market.snapshot.offer is not None:
            economics = InstrumentEconomics(
                epic=market.epic,
                pip_size=pip_size,
                lot_size=market.lot_size or D("1"),
                min_deal_size=rules.min_deal_size,
                size_increment=rules.min_size_increment or D("1"),
                margin_factor=market.margin_factor if market.margin_factor is not None else D("1"),
                margin_factor_unit=market.margin_factor_unit or "PERCENTAGE",
                min_stop_distance=(
                    rules.min_stop_or_profit_distance.value
                    if rules.min_stop_or_profit_distance is not None
                    else None
                ),
                min_stop_distance_unit=(
                    rules.min_stop_or_profit_distance.unit
                    if rules.min_stop_or_profit_distance is not None
                    else None
                ),
                min_guaranteed_stop_distance=(
                    rules.min_guaranteed_stop_distance.value
                    if rules.min_guaranteed_stop_distance is not None
                    else None
                ),
                min_guaranteed_stop_distance_unit=(
                    rules.min_guaranteed_stop_distance.unit
                    if rules.min_guaranteed_stop_distance is not None
                    else None
                ),
                guaranteed_stop_available=market.guaranteed_stop_allowed,
                quote_currency=market.quote_currency or "USD",
                overnight_fee_rate_daily=market.overnight_fee,
                provenance=ValueProvenance.BROKER_DISCOVERY,
            )
            assumptions = with_discovered_spread(
                CfdCostAssumptions.default(), market.snapshot.spread or D("0")
            )
            model = CapitalComCostModel(economics, assumptions)
            worked = _worked_examples(model, market.snapshot.offer)

            if account and account.currency and account.currency.upper() != (
                market.quote_currency or "USD"
            ).upper():
                notes.append(
                    f"عملة الحساب {account.currency} تختلف عن عملة تسعير الأداة "
                    f"{market.quote_currency} — تكلفة التحويل تسري ويجب قياسها."
                )
    else:
        notes.append("لم تُكتشف بيانات EUR/USD — الأمثلة المحسوبة غير متاحة.")

    if not worked:
        notes.append("لا توجد أمثلة محسوبة من قيم مُكتشَفة؛ لا يُبنى قرار تنفيذ على هذا التقرير.")

    return DiscoveryReport(
        generated_at_utc=at,
        environment=adapter.session.environment.value,
        base_url=adapter.session.base_url,
        constitution_version=CONSTITUTION_VERSION,
        account_masked=account.masked_id if account else None,
        account_currency=account.currency if account else None,
        account_type=account.account_type if account else None,
        balance=account.balance.balance if account else None,
        available=account.balance.available if account else None,
        profit_loss=account.balance.profit_loss if account else None,
        hedging_mode=preferences.hedging_mode if preferences else None,
        leverages=preferences.for_report()["leverages"] if preferences else {},
        markets=markets,
        worked_examples=worked,
        discrepancies=discrepancies,
        notes=notes,
        session_state=adapter.session.state_for_report(),
        adapter_state=adapter.state_for_report(),
        errors=errors,
    )


def write_reports(report: DiscoveryReport, *, json_path, markdown_path) -> tuple[str, str]:
    from pathlib import Path

    json_file = Path(json_path)
    md_file = Path(markdown_path)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text(
        json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    md_file.write_text(report.to_markdown(), encoding="utf-8")
    return str(json_file), str(md_file)
