"""
شاشة الشموع — تُخدَم **من الذاكرة لا من الشبكة**.

## القيد الذي يحكم هذا الملف

`build_mobile_state` يُستدعى عند **كل طلب قراءة**، ووثيقته تقول: «رخيص
عمداً: لا شبكة ولا وسيط». وجلبُ شموعٍ فيه يحوّل تصفّحاً عادياً إلى عشرات
النداءات على الوسيط، فتُستهلَك حدوده ويُحرَم منها القرار نفسه.

فالشموع تُحفَظ في دورة المسح وتُقرأ هنا. ومعنى ذلك أن المعروض هو **الصورة
التي رآها النظام حين قرّر**، لا صورةً أحدث — وذلك أصدق: شمعةٌ أحدث من القرار
تجعل السبب المكتوب يبدو خاطئاً وهو صحيح على بياناته.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.contracts import Bar, DataSource
from app.money import D
from app.mobile.state import _candles

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def bar(i: int, o="1.1000", h="1.1010", l="1.0990", c="1.1005") -> Bar:
    return Bar(
        symbol="EURUSD", start_utc=NOW + timedelta(hours=i),
        open=D(o), high=D(h), low=D(l), close=D(c),
        volume=D(0), source=DataSource.HISTORICAL,
    )


class Session:
    open_positions = 0


class Sys:
    def __init__(self, bars=None) -> None:
        self.last_bars = bars if bars is not None else {}
        self.session_state = Session()


def test_the_candles_reach_the_phone_with_all_four_prices():
    view = _candles(Sys({"EURUSD": [bar(0), bar(1)]}))
    assert view["symbols"] == ["EURUSD"]
    row = view["instruments"]["EURUSD"][0]
    assert set(row) == {"t", "o", "h", "l", "c"}
    assert row["h"] == "1.1010" and row["l"] == "1.0990"


def test_prices_are_strings_not_floats():
    """
    الأسعار تُنقل نصّاً كبقيّة أرقام هذا العقد: تحويلها إلى عائم في JSON
    يُدخل خطأ تقريبٍ على سعرٍ من خمس خانات — وهو ما بُني كل الحساب العشري
    في هذا المشروع لتجنّبه.
    """
    row = _candles(Sys({"EURUSD": [bar(0)]}))["instruments"]["EURUSD"][0]
    for key in ("o", "h", "l", "c"):
        assert isinstance(row[key], str), f"{key} ليس نصاً"


def test_no_candles_yet_says_so_and_invents_nothing():
    view = _candles(Sys())
    assert view["instruments"] == {} and view["symbols"] == []
    assert "لم تُقرأ شموعٌ بعد" in view["note_ar"]


def test_the_note_admits_the_candles_are_as_old_as_the_decision():
    """
    ادّعاءُ «مباشر» عن صورةٍ عمرها دقيقة هو الحقل الذي يُعرَض ولا يُقاس من
    مصدره — وهو صنف العطل الحاكم لهذا المشروع.
    """
    view = _candles(Sys({"EURUSD": [bar(0)]}))
    assert "آخر دورة مسح" in view["note_ar"]
    assert "مباشر" not in view["note_ar"]


def test_position_levels_are_null_when_there_is_no_position():
    """`None` تعني «لا مركز»، لا صفراً يُرسَم على السعر."""
    levels = _candles(Sys({"EURUSD": [bar(0)]}))["levels"]
    assert levels == {"symbol": None, "entry": None, "stop": None, "target": None}


def test_every_scanned_instrument_appears_even_if_it_was_refused():
    """
    أداةٌ رُفضت لسببٍ ما تبقى شموعها مرئية: الغرض أن تُرى **الصورة التي رآها
    النظام حين قرّر**، لا صور الأدوات التي قَبِلها وحدها.
    """
    view = _candles(Sys({"EURUSD": [bar(0)], "GOLD": [bar(0)], "GBPUSD": [bar(0)]}))
    assert view["symbols"] == ["EURUSD", "GBPUSD", "GOLD"]


def test_building_the_view_touches_no_broker_and_no_network():
    """
    **فحصٌ ساكن.** نداءٌ واحد على الوسيط هنا يضرب حدوده عند كل تصفّح، ولا
    يظهر أثره إلا حين يُرفَض طلبُ القرار نفسه لتجاوز الحدّ.
    """
    source = inspect.getsource(_candles)
    tree = ast.parse(source.lstrip())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("get_candles", "get_market_data", "connect", "get_quote"):
        assert forbidden not in called, f"يُنادى {forbidden} في بناء الحالة"
    assert "broker" not in source


@pytest.mark.parametrize("route", ["market/candles"])
def test_the_route_is_a_read_route_only(route):
    from app.mobile.api import READ_ROUTES, RISK_INCREASING_ROUTES, RISK_REDUCING_ROUTES

    assert route in READ_ROUTES
    assert route not in RISK_REDUCING_ROUTES + RISK_INCREASING_ROUTES


def test_the_heartbeat_stores_the_bars_it_evaluated():
    """
    وتُحفَظ **قبل** التقييم: أداةٌ رُفضت تبقى شموعها محفوظة، وإلا صارت
    الشاشة تعرض ما قَبِله النظام وتُخفي ما رفضه — وهو عكس الغرض.
    """
    import app.runtime.heartbeat as heartbeat

    source = inspect.getsource(heartbeat)
    store = source.index("state.last_bars[symbol]")
    run = source.index("state.pipeline.run(", store - 2000)
    assert store < run, "الشموع تُحفَظ بعد التقييم — فتضيع شموع ما رُفض"


def test_a_price_keeps_every_digit_it_arrived_with():
    """
    **العطل الذي أنتج `_price`.** كان `_money` يُستعمل هنا فيقرّب إلى
    منزلتين: `1.10105` تصير `"1.10"`. فتُرسم الشموع كلها على مستوىً واحد
    ويختفي التحرّك تماماً — رسمٌ صامتٌ لسوقٍ يتحرّك.

    وهو نفس صنف خطأ `stopDistance`: **مقياسٌ صحيح في مكانه، مستعملٌ في غير
    مكانه.**
    """
    from app.mobile.state import _money, _price

    price = D("1.10105")
    assert _price(price) == "1.10105"
    assert _money(price) == "1.10", "تغيّر مقياس المال — يُراجَع الاثنان معاً"
    assert _price(None) is None


def test_five_decimal_candles_survive_the_journey():
    detailed = Bar(
        symbol="EURUSD", start_utc=NOW, open=D("1.15876"), high=D("1.15904"),
        low=D("1.15841"), close=D("1.15869"), volume=D(0), source=DataSource.HISTORICAL,
    )
    row = _candles(Sys({"EURUSD": [detailed]}))["instruments"]["EURUSD"][0]
    assert row == {
        "t": NOW.isoformat(), "o": "1.15876", "h": "1.15904",
        "l": "1.15841", "c": "1.15869",
    }
