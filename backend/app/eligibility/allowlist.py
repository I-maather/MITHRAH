"""
Instrument allowlist + eligibility checks.

القاعدة: أي أصل غير موجود في القائمة البيضاء مرفوض. لا استثناءات.
القائمة صغيرة عمداً: أدوات عالية السيولة، سبريد ضيق، دولار أمريكي فقط.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..contracts import AssetClass, Balances, DataSource, InstrumentDetails, Quote, TradingPermissions
from ..marketdata.service import DataQuality, assess_quote
from ..money import D
from ..risk.constitution import (
    ALLOW_EXTENDED_HOURS,
    CLOSING_BLACKOUT_MINUTES,
    OPENING_BLACKOUT_MINUTES,
)


@dataclass(frozen=True)
class AllowlistEntry:
    symbol: str
    name_ar: str
    asset_class: AssetClass
    currency: str
    exchange: str
    rationale_ar: str
    enabled: bool = True


ALLOWLIST: dict[str, AllowlistEntry] = {
    e.symbol: e
    for e in [
        AllowlistEntry("SPY", "صندوق مؤشر S&P 500", AssetClass.ETF, "USD", "ARCA",
                       "أعلى صناديق المؤشرات سيولة عالمياً، سبريد سنت واحد غالباً."),
        AllowlistEntry("QQQ", "صندوق مؤشر ناسداك 100", AssetClass.ETF, "USD", "NASDAQ",
                       "سيولة عالية جداً وسبريد ضيق."),
        AllowlistEntry("IVV", "صندوق S&P 500 من iShares", AssetClass.ETF, "USD", "ARCA",
                       "بديل لـSPY بسيولة ممتازة."),
    ]
}

# أصول مذكورة صراحةً كمرفوضة في V1، مع السبب — حتى لا تُضاف بالخطأ لاحقاً.
EXPLICIT_DENYLIST: dict[str, str] = {
    "XAUUSD": "سلعة/فوركس — خارج نطاق V1 ولا يدعمها دستور المخاطر الحالي.",
    "EURUSD": "فوركس — الحد الأدنى لأوامر العملات في IBKR أكبر بكثير من رأس المال.",
    "GBPUSD": "فوركس — نفس السبب.",
    "BTCUSD": "كريبتو — معطّل في V1.",
}


class EligibilityCode(str):
    pass


NOT_IN_ALLOWLIST = "NOT_IN_ALLOWLIST"
EXPLICITLY_DENIED = "EXPLICITLY_DENIED"
ALLOWLIST_ENTRY_DISABLED = "ALLOWLIST_ENTRY_DISABLED"
WRONG_CURRENCY = "WRONG_CURRENCY"
WRONG_ASSET_CLASS = "WRONG_ASSET_CLASS"
MARKET_CLOSED = "MARKET_CLOSED"
OPENING_BLACKOUT = "OPENING_BLACKOUT"
CLOSING_BLACKOUT = "CLOSING_BLACKOUT"
PERMISSIONS_INSUFFICIENT = "PERMISSIONS_INSUFFICIENT"
NO_RELIABLE_STOP = "NO_RELIABLE_STOP"
DATA_NOT_TRADABLE = "DATA_NOT_TRADABLE"
INSUFFICIENT_SETTLED_CASH = "INSUFFICIENT_SETTLED_CASH"


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason_code: Optional[str]
    reason_ar: str
    checks: tuple[tuple[str, bool, str], ...]
    data_quality: Optional[DataQuality]
    fractional_allowed: bool = False


def check_eligibility(
    *,
    symbol: str,
    quote: Optional[Quote],
    details: Optional[InstrumentDetails],
    permissions: TradingPermissions,
    balances: Balances,
    market_is_open: bool,
    minutes_since_open: Optional[int],
    minutes_to_close: Optional[int],
    now: datetime,
) -> EligibilityResult:
    checks: list[tuple[str, bool, str]] = []

    def fail(code: str, message: str) -> EligibilityResult:
        checks.append((code, False, message))
        return EligibilityResult(False, code, message, tuple(checks), None)

    if symbol in EXPLICIT_DENYLIST:
        return fail(EXPLICITLY_DENIED, f"{symbol} مرفوض صراحةً: {EXPLICIT_DENYLIST[symbol]}")

    entry = ALLOWLIST.get(symbol)
    if entry is None:
        return fail(NOT_IN_ALLOWLIST, f"{symbol} غير موجود في القائمة البيضاء.")
    if not entry.enabled:
        return fail(ALLOWLIST_ENTRY_DISABLED, f"{symbol} معطّل في القائمة البيضاء.")
    checks.append(("ALLOWLIST", True, f"{symbol} ضمن القائمة البيضاء ({entry.name_ar})."))

    if entry.currency != "USD":
        return fail(WRONG_CURRENCY, "العملة يجب أن تكون USD في V1.")
    if entry.asset_class not in (AssetClass.STOCK, AssetClass.ETF):
        return fail(WRONG_ASSET_CLASS, "نوع الأصل غير مسموح في V1.")
    checks.append(("CURRENCY_ASSET_CLASS", True, "العملة USD ونوع الأصل سهم/ETF."))

    problems = permissions.violates_v1_policy()
    if problems:
        return fail(PERMISSIONS_INSUFFICIENT, "صلاحيات الحساب تخالف سياسة V1: " + "؛ ".join(problems))
    checks.append(("PERMISSIONS", True, "الحساب Cash/Retail وبلا Margin أو مشتقات."))

    if not market_is_open:
        return fail(MARKET_CLOSED, "السوق مغلق — لا تداول خارج الجلسة الأساسية في V1.")
    if not ALLOW_EXTENDED_HOURS and minutes_since_open is not None and minutes_since_open < OPENING_BLACKOUT_MINUTES:
        return fail(
            OPENING_BLACKOUT,
            f"مرّت {minutes_since_open} دقيقة فقط على الافتتاح — نافذة الحظر {OPENING_BLACKOUT_MINUTES} دقيقة.",
        )
    if minutes_to_close is not None and minutes_to_close < CLOSING_BLACKOUT_MINUTES:
        return fail(
            CLOSING_BLACKOUT,
            f"بقي {minutes_to_close} دقيقة على الإغلاق — نافذة الحظر {CLOSING_BLACKOUT_MINUTES} دقيقة.",
        )
    checks.append(("SESSION_WINDOW", True, "داخل الجلسة الأساسية وخارج نوافذ الحظر."))

    quality = assess_quote(quote, now=now)
    if not quality.tradable:
        checks.append((DATA_NOT_TRADABLE, False, quality.reason_ar))
        return EligibilityResult(False, DATA_NOT_TRADABLE, quality.reason_ar, tuple(checks), quality)
    checks.append(("MARKET_DATA", True, quality.reason_ar))

    if details is None:
        return fail(NO_RELIABLE_STOP, "تفاصيل الأداة غير متاحة — لا يمكن التحقق من دعم أوامر الحماية.")
    if not details.supports_stop_orders:
        return fail(NO_RELIABLE_STOP, "الأداة لا تدعم أوامر وقف الخسارة — مرفوضة.")

    # هل نستطيع استعمال الكسور؟ فقط إذا كان الستوب مدعوماً على الكمية الكسرية.
    fractional_allowed = (
        details.supports_fractional
        and permissions.fractional_enabled
        and details.supports_stop_on_fractional
    )
    checks.append((
        "PROTECTIVE_EXIT",
        True,
        "أوامر الوقف مدعومة"
        + (" على الكميات الكسرية." if fractional_allowed else " على الأسهم الكاملة فقط — سنتداول أسهماً كاملة."),
    ))

    if balances.available_for_new_trade <= 0:
        return fail(INSUFFICIENT_SETTLED_CASH, "لا يوجد نقد مسوّى متاح لصفقة جديدة.")
    checks.append((
        "SETTLED_CASH",
        True,
        f"النقد المسوّى المتاح {balances.available_for_new_trade:.2f} دولار.",
    ))

    return EligibilityResult(
        eligible=True,
        reason_code=None,
        reason_ar=f"{symbol} مؤهل للتقييم.",
        checks=tuple(checks),
        data_quality=quality,
        fractional_allowed=fractional_allowed,
    )
