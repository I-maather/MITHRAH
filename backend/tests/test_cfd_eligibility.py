"""
طبقة الأهلية — **هاجرت إلى كابيتال، وسياسة الأسهم لم تُمسّ.**

## العطل

`app/eligibility/allowlist.py` كانت مكتوبةً بالكامل لأسهم IBKR: قائمةٌ
بيضاء فيها `SPY` و`QQQ` و`IVV`، وقائمة رفضٍ صريحة فيها **أدواتنا الأربع
بالاسم**، ونوع أصلٍ مقصور على سهم/ETF، وسياسة صلاحياتٍ تشترط حساباً نقدياً
**بلا هامش ولا فوركس ولا بيع على المكشوف**.

وحساب كابيتال يخالف كل بندٍ منها بالضرورة: الـCFD هامشٌ بطبيعته، والفوركس
هو ما نتداوله، والبيع نصفُ الاستراتيجيات.

⇒ `EXPLICITLY_DENIED` — ونصُّ السبب: «الحد الأدنى لأوامر العملات في
**IBKR** أكبر بكثير من رأس المال». صحيحٌ عند IBKR، وباطلٌ عند كابيتال:
القياس يقول أصغر كمية 100 وحدة بهامش 3.33٪ — نحو 3.7 دولار.

وقد كتب محوّل كابيتال ذلك بصراحة منذ يومه الأول: «سياسة CFD الخاصة
تُطبَّق في eligibility» — **ولم تُكتب قط**. تعليقٌ يصف نيّةً لا كوداً.

## القاعدة

مسارٌ مقابلٌ لا تخفيف: سياسة الأسهم بقيت كما هي حرفاً، والـCFD له قائمته
وسياسته وشروطه — وفيها ما هو **أشدّ**: أدنى مسافة وقفٍ معلومة، وعملة تسعيرٍ
مطابقة لعملة الحساب.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.contracts import (
    AccountKind,
    AssetClass,
    ClientClassification,
    Balances,
    DataSource,
    Quote,
    TradingPermissions,
)
from app.eligibility.allowlist import (
    ACCOUNT_CURRENCY,
    ALLOWLIST,
    CFD_ALLOWLIST,
    IBKR_EXPLICIT_DENYLIST,
    check_eligibility,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def capital_permissions(**over):
    base = dict(
        account_id="****1234",
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
        as_of_utc=NOW,
    )
    base.update(over)
    return TradingPermissions(**base)


def details(symbol="EURUSD", **over):
    base = dict(
        symbol=symbol, conid=symbol, asset_class=AssetClass.CFD_CURRENCY,
        currency="USD", exchange="CAPITAL_COM", min_quantity=D("100"),
        supports_fractional=False, supports_stop_orders=True,
        supports_stop_on_fractional=False, supported_order_types=(),
        as_of_utc=NOW, min_stop_distance=D("0.01"), quote_currency="USD",
    )
    base.update(over)
    return SimpleNamespace(**base)


def quote(symbol="EURUSD"):
    """سعرٌ حقيقيّ النوع — `assess_quote` تسأله عن عمره وفارقه."""
    return Quote(
        symbol=symbol, bid=D("1.10000"), ask=D("1.10007"), last=D("1.10003"),
        timestamp_utc=NOW, source=DataSource.REALTIME, received_at_utc=NOW,
    )


def balances(available="300"):
    return Balances(
        account_id="****1234", total_cash=D(available), settled_cash=D(available),
        unsettled_cash=D("0"), committed_cash=D("0"), net_liquidation=D(available),
        as_of_utc=NOW,
    )


def evaluate(symbol="EURUSD", *, quote_obj=None, det=None, perms=None, open_=True):
    return check_eligibility(
        symbol=symbol,
        quote=quote_obj if quote_obj is not None else quote(symbol),
        details=det if det is not None else details(symbol),
        permissions=perms if perms is not None else capital_permissions(),
        balances=balances(),
        market_is_open=open_,
        minutes_since_open=None,
        minutes_to_close=None,
        now=NOW,
    )


# -- المسار الجديد -----------------------------------------------------------

def test_eurusd_is_eligible_on_capital():
    """**الفحص الذي كان مستحيلاً.** كان يُرفض بالاسم لسببٍ يخصّ IBKR."""
    result = evaluate("EURUSD")
    assert result.eligible, result.reason_ar
    assert result.reason_code is None


def test_gold_is_eligible_as_a_commodity_cfd():
    result = evaluate("GOLD", det=details("GOLD", asset_class=AssetClass.CFD_COMMODITY))
    assert result.eligible, result.reason_ar


def test_a_leveraged_account_is_not_a_violation_here():
    """
    الرافعة والبيع متوقَّعان في CFD. واشتراطُ `Cash` بلا هامش يرفض حساب
    كابيتال في كل بند — وهو ما كان يقع.
    """
    result = evaluate("EURUSD", perms=capital_permissions(margin_enabled=True, short_selling=True))
    assert result.eligible, result.reason_ar


# -- وما يُشدَّد ---------------------------------------------------------------

def test_an_unknown_minimum_stop_is_refused():
    """بلا حدٍّ معلوم يُبنى وقفٌ يُرفض عند الوسيط — عطل ليلة 09-01."""
    result = evaluate("EURUSD", det=details("EURUSD", min_stop_distance=None))
    assert not result.eligible
    assert result.reason_code == "STOP_DISTANCE_UNKNOWN"


def test_an_instrument_priced_in_another_currency_is_refused_until_measured():
    """
    ربحٌ بالين يُحوَّل إلى دولار بكلفةٍ **مفترضة صفراً** في نموذج التكلفة.
    فيُرفض حتى تُقاس — رفضٌ مؤقّت وسببه مكتوب، يرتفع بالقياس لا بالرأي.
    """
    result = evaluate("USDJPY", det=details("USDJPY", quote_currency="JPY"))
    assert not result.eligible
    assert result.reason_code == "CONVERSION_COST_UNMEASURED"
    assert "JPY" in result.reason_ar


def test_a_symbol_outside_the_cfd_list_is_refused():
    result = evaluate("BTCUSD", det=details("BTCUSD"))
    assert not result.eligible
    assert result.reason_code == "NOT_IN_CFD_ALLOWLIST"


def test_options_enabled_breaks_the_cfd_policy():
    result = evaluate("EURUSD", perms=capital_permissions(options=True))
    assert not result.eligible
    assert result.reason_code == "PERMISSIONS_INSUFFICIENT"


def test_a_professional_classification_breaks_it_too():
    result = evaluate(
        "EURUSD", perms=capital_permissions(classification=ClientClassification.PROFESSIONAL)
    )
    assert not result.eligible


def test_forex_permission_off_breaks_it():
    result = evaluate("EURUSD", perms=capital_permissions(forex=False))
    assert not result.eligible


def test_a_closed_market_is_refused():
    assert not evaluate("EURUSD", open_=False).eligible


# -- سياسة الأسهم لم تُمسّ ------------------------------------------------------

def test_the_stock_allowlist_is_unchanged():
    assert set(ALLOWLIST) == {"SPY", "QQQ", "IVV"}


def test_the_ibkr_denylist_still_denies_on_the_stock_path():
    """
    القائمة لم تُحذف — نُقلت إلى مسارها. ولو دخل `EURUSD` مسار الأسهم
    (تفاصيل بصنف سهم) لبقي مرفوضاً بسببه الأصلي.
    """
    assert "EURUSD" in IBKR_EXPLICIT_DENYLIST
    result = evaluate("EURUSD", det=details("EURUSD", asset_class=AssetClass.STOCK))
    assert not result.eligible
    assert result.reason_code == "EXPLICITLY_DENIED"
    assert "IBKR" in result.reason_ar


def test_missing_details_fall_back_to_the_stricter_stock_path():
    """
    بلا تفاصيل لا يُعرَف صنف الأصل. والسقوط يكون إلى **الأشدّ** لا إلى
    الأسهل: أداةٌ مجهولة الصنف تُعامَل معاملة مسار الأسهم.
    """
    result = check_eligibility(
        symbol="EURUSD", quote=quote(), details=None,
        permissions=capital_permissions(), balances=balances(),
        market_is_open=True, minutes_since_open=None, minutes_to_close=None, now=NOW,
    )
    assert not result.eligible
    assert result.reason_code == "EXPLICITLY_DENIED"


# ---------------------------------------------------------------------------
# عملة التسعير: مقروءة أم مفترضة؟
# ---------------------------------------------------------------------------

def test_an_undeclared_quote_currency_is_named_an_assumption_not_a_reading():
    """
    **قياس 2026-09-02:** كابيتال عادت بالذهب بلا عملة تسعير (`currencies`
    فارغة)، فمُلئت من قائمتنا. والقرار صحيح — الحساب بالدولار والذهب مسعَّر
    به — لكن الفحص كان يقول «التسعير بالدولار — لا تحويل» عن شيءٍ **لم يقله
    الوسيط**.

    وهو العيب الحاكم في أصغر صوره: قيمةٌ تُعرَض كأنها مقروءة وهي مفترضة.
    القرار لا يتغيّر، والنصّ يتغيّر — لأن الفرق بين المقروء والمفترض هو ما
    يُبنى عليه لاحقاً.
    """
    result = evaluate("GOLD", det=details("GOLD", asset_class=AssetClass.CFD_COMMODITY,
                                          quote_currency=None))
    assert result.eligible, result.reason_ar
    check = next(c for c in result.checks if c[0] == "QUOTE_CURRENCY")
    assert check[1] is True
    assert "افتراضٌ لا قراءة" in check[2], (
        "فحصٌ يصف افتراضاً بلغة القراءة يُبنى عليه كأنه دليل."
    )


def test_a_declared_quote_currency_is_reported_as_read():
    """وحين يُعلنها الوسيط، تُقال كما هي بلا تحفّظٍ لا محلّ له."""
    result = evaluate("EURUSD", det=details("EURUSD", quote_currency="USD"))
    check = next(c for c in result.checks if c[0] == "QUOTE_CURRENCY")
    assert "افتراض" not in check[2]


def test_a_foreign_quote_currency_is_still_refused_declared_or_not():
    """التشديد لم يُخفَّف: عملةٌ غير الدولار تُرفض سواءٌ أُعلنت أم فُرضت."""
    from app.eligibility.allowlist import CONVERSION_COST_UNMEASURED
    result = evaluate("USDJPY", det=details("USDJPY", quote_currency="JPY"))
    assert not result.eligible
    assert result.reason_code == CONVERSION_COST_UNMEASURED
