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

#: أدوات CFD المسموح تقييمها عند كابيتال.
#:
#: **قائمة منفصلة عن قائمة الأسهم، لا امتدادٌ لها.** سياسة الأسهم صحيحة
#: كما هي لأسهم IBKR ولم يُمسّ منها شيء؛ وهذه سياسةٌ مقابلة لوسيطٍ آخر
#: وصنف أصلٍ آخر.
CFD_ALLOWLIST: dict[str, AllowlistEntry] = {
    e.symbol: e
    for e in [
        AllowlistEntry("EURUSD", "يورو/دولار", AssetClass.CFD_CURRENCY, "USD", "CAPITAL_COM",
                       "أعلى أزواج العملات سيولةً؛ سبريد مقيس 0.7 نقطة، وأصغر كمية 100 وحدة."),
        AllowlistEntry("GBPUSD", "جنيه/دولار", AssetClass.CFD_CURRENCY, "USD", "CAPITAL_COM",
                       "سيولة عالية؛ سبريد مقيس 1.3 نقطة."),
        AllowlistEntry("USDJPY", "دولار/ين", AssetClass.CFD_CURRENCY, "JPY", "CAPITAL_COM",
                       "سيولة عالية؛ لكن التسعير بالين — يلزم قياس كلفة التحويل."),
        AllowlistEntry("GOLD", "ذهب", AssetClass.CFD_COMMODITY, "USD", "CAPITAL_COM",
                       "سلعة عالية السيولة؛ سبريد مقيس 50 نقطة وهامش 5٪."),
    ]
}

#: أصناف الأصول المسموحة في مسار CFD.
CFD_ASSET_CLASSES = (AssetClass.CFD_CURRENCY, AssetClass.CFD_COMMODITY)

#: عملة الحساب. ما يُسعَّر بغيرها يحتاج **كلفة تحويل مقيسة** لا مفترضة.
ACCOUNT_CURRENCY = "USD"

# أصول مذكورة صراحةً كمرفوضة **في مسار الأسهم (IBKR)**، مع السبب.
#
# ⚠️ كانت تُطبَّق قبل معرفة الوسيط، فترفض `EURUSD` و`GBPUSD` و`XAUUSD`
# على كابيتال بسببٍ نصُّه «الحد الأدنى لأوامر العملات في **IBKR** أكبر
# بكثير من رأس المال». وهو صحيحٌ عند IBKR، وباطلٌ عند كابيتال: القياس
# يقول أصغر كمية 100 وحدة بهامش 3.33٪ — نحو 3.7 دولار.
#
# فالقائمة الآن مقصورةٌ على مسارها، والسبب يُقرأ في موضعه.
IBKR_EXPLICIT_DENYLIST: dict[str, str] = {
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
NOT_IN_CFD_ALLOWLIST = "NOT_IN_CFD_ALLOWLIST"
CONVERSION_COST_UNMEASURED = "CONVERSION_COST_UNMEASURED"
STOP_DISTANCE_UNKNOWN = "STOP_DISTANCE_UNKNOWN"


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

    # **الوسيط يُعرَف أولاً.** كان الرفض الصريح يُطبَّق قبل ذلك، فيرفض
    # أدوات كابيتال بسببٍ يخصّ IBKR.
    if details is not None and details.asset_class in CFD_ASSET_CLASSES:
        return _check_cfd(
            symbol=symbol, quote=quote, details=details, permissions=permissions,
            balances=balances, market_is_open=market_is_open, now=now,
            checks=checks, fail=fail,
        )

    if symbol in IBKR_EXPLICIT_DENYLIST:
        return fail(EXPLICITLY_DENIED, f"{symbol} مرفوض صراحةً: {IBKR_EXPLICIT_DENYLIST[symbol]}")

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


def _check_cfd(
    *, symbol, quote, details, permissions, balances, market_is_open, now, checks, fail
) -> EligibilityResult:
    """
    مسار CFD عند كابيتال — **سياسةٌ مقابلة لسياسة الأسهم لا تخفيفٌ لها**.

    ## ما يختلف عن مسار الأسهم، ولماذا

    * **الرافعة والبيع على المكشوف متوقَّعان** هنا لا مخالفتان: الـCFD هامشٌ
      بطبيعته، ونصف الاستراتيجيات بيع. واشتراط `Cash` بلا هامش يرفض حساب
      كابيتال في كل بند — وهو ما كان يقع.
    * **نافذتا الافتتاح والإغلاق تسقطان**: الفوركس يعمل 24/5 بلا جرس، ونافذة
      «أول ثلاثين دقيقة» مفهومٌ من سوق الأسهم لا معنى له هنا. وحالة السوق
      نفسها تُحسب بتقويم الفوركس (`forex_market_status`) في الخط.

    ## وما يُشدَّد

    * **أدنى مسافة وقف يجب أن تكون معلومة.** بلا حدٍّ معلوم يُبنى وقفٌ يُرفض
      عند الوسيط — وقد كلّفنا ذلك ليلة 09-01 كاملة.
    * **ما يُسعَّر بغير عملة الحساب يُرفض** حتى تُقاس كلفة التحويل. وهي اليوم
      مفترضةٌ صفراً في نموذج التكلفة (`currency_conversion_pct = 0`)، وربحٌ
      بالين يُحوَّل إلى دولار بكلفةٍ غير معلومة. الرفض هنا **مؤقّت وسببه
      مكتوب**، ويرتفع بالقياس لا بالرأي.
    """
    entry = CFD_ALLOWLIST.get(symbol)
    if entry is None:
        return fail(NOT_IN_CFD_ALLOWLIST, f"{symbol} خارج قائمة CFD المسموحة.")
    if not entry.enabled:
        return fail(ALLOWLIST_ENTRY_DISABLED, f"{symbol} معطّل في قائمة CFD.")
    checks.append(("CFD_ALLOWLIST", True, f"{symbol} ضمن قائمة CFD ({entry.name_ar})."))

    quote_currency = (details.quote_currency or entry.currency or "").upper()
    if quote_currency != ACCOUNT_CURRENCY:
        return fail(
            CONVERSION_COST_UNMEASURED,
            f"{symbol} مسعَّر بـ{quote_currency} لا {ACCOUNT_CURRENCY}، وكلفة التحويل "
            "غير مقيسة — تُفترض صفراً في نموذج التكلفة. يُرفض حتى تُقاس.",
        )
    checks.append(("QUOTE_CURRENCY", True, f"التسعير بـ{ACCOUNT_CURRENCY} — لا تحويل."))

    problems = permissions.violates_cfd_policy()
    if problems:
        return fail(PERMISSIONS_INSUFFICIENT, "صلاحيات الحساب تخالف سياسة CFD: " + "؛ ".join(problems))
    checks.append(("PERMISSIONS", True, "حساب CFD تجزئة، بلا خيارات ولا آجلة ولا كريبتو."))

    if not market_is_open:
        return fail(MARKET_CLOSED, "سوق الفوركس مغلق — لا تقييم خارج الجلسة.")
    checks.append(("SESSION", True, "سوق الفوركس مفتوح."))

    quality = assess_quote(quote, now=now)
    if not quality.tradable:
        checks.append((DATA_NOT_TRADABLE, False, quality.reason_ar))
        return EligibilityResult(False, DATA_NOT_TRADABLE, quality.reason_ar, tuple(checks), quality)
    checks.append(("MARKET_DATA", True, quality.reason_ar))

    if not details.supports_stop_orders:
        return fail(NO_RELIABLE_STOP, "الأداة لا تدعم أوامر وقف الخسارة — مرفوضة.")
    if details.min_stop_distance is None:
        return fail(
            STOP_DISTANCE_UNKNOWN,
            f"{symbol}: أدنى مسافة وقف غير معلومة عند الوسيط — الأمر سيُرفض عند الإرسال.",
        )
    checks.append((
        "PROTECTIVE_EXIT", True,
        f"الوقف مدعوم، وأدنى مسافة معلومة ({details.min_stop_distance}).",
    ))

    if balances.available_for_new_trade <= 0:
        return fail(INSUFFICIENT_SETTLED_CASH, "لا نقد متاح لصفقة جديدة.")
    checks.append((
        "AVAILABLE_CASH", True,
        f"المتاح لصفقة جديدة {balances.available_for_new_trade:.2f} دولار.",
    ))

    return EligibilityResult(
        eligible=True,
        reason_code=None,
        reason_ar=f"{symbol} مؤهل للتقييم (CFD).",
        checks=tuple(checks),
        data_quality=quality,
        # لا كسور في CFD كابيتال: `supports_fractional=False` في المحوّل.
        fractional_allowed=False,
    )
