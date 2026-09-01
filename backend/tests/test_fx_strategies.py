"""
الاستراتيجيات الثلاث — ويُفحَص فيها **الصمت** قبل الإشارة.

## القاعدة التي تحكم هذا الملف

اختبارُ استراتيجيةٍ يُثبت أنها تُشير حين ينطبق شرطها **سهلٌ ومضلّل**:
استراتيجيةٌ تُشير دائماً تمرّه. والفحص الذي يهمّ عكسه: **أتصمت خارج ظرفها؟**

فلكلٍّ هنا اختبارُ ظرفٍ يمنعها، واختبارُ إشارةٍ يُفعّلها، واختبار حدود.

## ولماذا الظرف أصلاً

`TREND_PULLBACK v1` تدخل في أي سوق: لا شيء فيها يسأل «أهذا اتجاهٌ ممتدّ أم
تذبذبٌ عرضي؟». وارتدادٌ نحو المتوسط في سوقٍ عرضي ليس ارتداداً — هو نصف
الذبذبة. فاستراتيجيةٌ بلا حارس ظرف ليست واحدة، هي واحدةٌ صحيحة وأخرى خاطئة
تعملان بالاسم نفسه ويُجمع أداؤهما فيُلغي بعضه بعضاً.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

import pytest

from app.contracts import Bar, DataSource, Quote, Side, StrategyState
from app.money import D
from app.strategies.breakout_retest import BreakoutRetest
from app.strategies.indicators import adx
from app.strategies.range_mean_reversion import RangeMeanReversion
from app.strategies.trend_pullback_v2 import TrendPullbackV2

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
STRATEGIES = [TrendPullbackV2(), RangeMeanReversion(), BreakoutRetest()]


def bar(i: int, o, h, l, c) -> Bar:
    return Bar(
        symbol="EURUSD", start_utc=NOW - timedelta(days=400 - i),
        open=D(str(o)), high=D(str(h)), low=D(str(l)), close=D(str(c)),
        volume=D(0), source=DataSource.HISTORICAL,
    )


def quote(bid="1.10000", ask="1.10010") -> Quote:
    return Quote(
        symbol="EURUSD", bid=D(bid), ask=D(ask), last=D(bid),
        timestamp_utc=NOW, source=DataSource.REALTIME, received_at_utc=NOW,
    )


def trending(n: int = 120, step="0.0020", start="1.0000") -> list[Bar]:
    """اتجاهٌ صاعد نظيف — ADX عالٍ."""
    out, price = [], D(start)
    for i in range(n):
        out.append(bar(i, price, price + D("0.0010"), price - D("0.0010"), price))
        price += D(step)
    return out


def choppy(n: int = 120, start="1.1000", amplitude="0.0030") -> list[Bar]:
    """تذبذبٌ عرضي حول مستوىً ثابت — ADX منخفض."""
    out = []
    for i in range(n):
        offset = D(amplitude) if i % 2 else -D(amplitude)
        price = D(start) + offset
        out.append(bar(i, price, price + D("0.0005"), price - D("0.0005"), price))
    return out


# ---------------------------------------------------------------------------
# ١ · العقد المشترك
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: s.metadata.name)
def test_every_new_strategy_starts_as_research(strategy):
    """
    **لا استراتيجية تصير حيّة لأنها تُنتج إشارة.** الخط يقبل `APPROVED` وحدها،
    والاعتماد يحتاج Backtest واجتياز بوابات. وهذا الفحص يمنع أن يُكتب
    `APPROVED` سهواً في ملفٍ جديد.
    """
    assert strategy.metadata.state is StrategyState.RESEARCH
    assert "لا يوجد" in strategy.metadata.backtest_evidence_ar


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: s.metadata.name)
def test_every_strategy_accepts_the_instrument_we_actually_trade(strategy):
    """**العطل الذي أنتج هذا الملف كلّه:** v1 ترفض EURUSD في أوّل سطر منها."""
    assert "EURUSD" in strategy.metadata.markets
    assert "GOLD" in strategy.metadata.markets
    assert "SPY" not in strategy.metadata.markets


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: s.metadata.name)
def test_costs_are_declared_for_the_broker_we_use(strategy):
    """v1 كانت تفترض عمولة IBKR على الأسهم — ونحن على CFD بلا عمولة."""
    assert "كابيتال" in strategy.metadata.assumed_costs_ar
    assert "IBKR" not in strategy.metadata.assumed_costs_ar


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: s.metadata.name)
def test_a_foreign_symbol_is_refused_before_any_computation(strategy):
    assert strategy.evaluate(symbol="SPY", bars=trending(), quote=quote(), now=NOW) is None


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: s.metadata.name)
def test_too_few_bars_produces_silence_not_a_guess(strategy):
    few = trending(strategy.metadata.min_bars_required - 1)
    assert strategy.evaluate(symbol="EURUSD", bars=few, quote=quote(), now=NOW) is None


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: s.metadata.name)
def test_the_same_inputs_give_the_same_output(strategy):
    """حتمية: بلا هذا لا معنى لسجلّ تدقيقٍ يعيد بناء القرار."""
    bars, q = trending(), quote()
    first = strategy.evaluate(symbol="EURUSD", bars=bars, quote=q, now=NOW)
    second = strategy.evaluate(symbol="EURUSD", bars=bars, quote=q, now=NOW)
    assert first == second


# ---------------------------------------------------------------------------
# ٢ · حارس الظرف — وهو الفحص الذي يهمّ
# ---------------------------------------------------------------------------

def test_the_market_fixtures_actually_differ_in_adx():
    """
    تجهيزةٌ لا تنتج ما تدّعيه تجعل كل ما بعدها بلا معنى — وقد كلّفنا ذلك
    درساً اليوم حين أعطت تجهيزةٌ معرّفين متطابقين وأخفت فرقاً في الواقع.
    """
    trend_adx = adx(trending(), 14)
    chop_adx = adx(choppy(), 14)
    assert trend_adx is not None and chop_adx is not None
    assert trend_adx > D(25), f"تجهيزة الاتجاه تقرأ ADX = {trend_adx}"
    assert chop_adx < D(20), f"تجهيزة التذبذب تقرأ ADX = {chop_adx}"


# ⚠️ **درسٌ من طفرةٍ لم تعضّ.**
#
# كانت هذه الفحوص تُعطى سوقاً عرضياً وتتوقّع الصمت — وكانت تمرّ **حتى بعد
# إسقاط حارس ADX من الكود**. لأن السوق العرضي لا يستوفي شروط الدخول أصلاً،
# فالصمت يأتي منها لا من الحارس.
#
# اختبارٌ يمرّ لسببٍ غير الذي كُتب له **أسوأ من غياب الاختبار**: يعطي ثقةً
# في حارسٍ قد يكون مفقوداً. وهو صنف العطل الحاكم لهذا المشروع بعينه، واقعاً
# هذه المرّة في الاختبارات نفسها.
#
# فالحارس يُعزَل: تجهيزةٌ **تُشير فعلاً**، ثم تُحقَن قراءة ADX وحدها. فلا
# يبقى بين الإشارة والصمت إلا الحارس المفحوص.


def test_trend_pullback_is_silenced_by_its_adx_guard_alone(monkeypatch):
    """**الحارس الذي كان مفقوداً في v1 تماماً.**"""
    import app.strategies.trend_pullback_v2 as module

    bars, q = pullback_bars(), quote(bid="1.2370", ask="1.2371")

    monkeypatch.setattr(module, "adx", lambda *a, **k: D("30"))
    assert module.TrendPullbackV2().evaluate(
        symbol="EURUSD", bars=bars, quote=q, now=NOW
    ) is not None, "التجهيزة لا تُشير أصلاً — الفحص بلا معنى"

    monkeypatch.setattr(module, "adx", lambda *a, **k: D("18"))
    assert module.TrendPullbackV2().evaluate(
        symbol="EURUSD", bars=bars, quote=q, now=NOW
    ) is None, "أشارت في سوقٍ عرضي — الحارس لا يعمل"


def oversold_bars() -> list[Bar]:
    """تذبذبٌ عرضي ثم هبوطٌ حادّ: إغلاقٌ تحت النطاق وRSI متطرّف."""
    bars = choppy(120)
    price = bars[-1].close
    for i in range(9):
        price -= D("0.0090")
        bars.append(bar(120 + i, price + D("0.0090"), price + D("0.0090"), price, price))
    return bars


def test_mean_reversion_is_silenced_by_its_adx_guard_alone(monkeypatch):
    """
    وهذه الأخطر: بيعُ القوة أو شراءُ الضعف في بداية اتجاهٍ حقيقي يضعك في
    الجهة الخاطئة منه — لا خطأً في التوقيت بل خطأً في الاتجاه.
    """
    import app.strategies.range_mean_reversion as module

    bars = oversold_bars()
    q = quote(bid=str(bars[-1].close), ask=str(bars[-1].close + D("0.0001")))

    monkeypatch.setattr(module, "adx", lambda *a, **k: D("12"))
    fired = module.RangeMeanReversion().evaluate(
        symbol="EURUSD", bars=bars, quote=q, now=NOW
    )
    assert fired is not None, "التجهيزة لا تُشير أصلاً — الفحص بلا معنى"
    assert fired.side is Side.BUY

    monkeypatch.setattr(module, "adx", lambda *a, **k: D("35"))
    assert module.RangeMeanReversion().evaluate(
        symbol="EURUSD", bars=bars, quote=q, now=NOW
    ) is None, "أشارت في اتجاهٍ ممتدّ — الحارس لا يعمل"


def squeeze_breakout_bars() -> list[Bar]:
    """هدوءٌ ضيّق طويل، ثم اختراقٌ صاعد، ثم عودةٌ تلمس المستوى ولا تكسره."""
    bars: list[Bar] = []
    price = D("1.1000")
    # مرحلةٌ واسعة أوّلاً: بلا اتّساعٍ سابق لا يكون ما بعده **ضغطاً** بل
    # هدوءاً مستمراً — والنسبة تُقاس إلى أوسعِ ما كان، فتحتاج أوسعَ فعلياً.
    for i in range(60):
        offset = D("0.0060") if i % 2 else -D("0.0060")
        wide = price + offset
        bars.append(bar(i, wide, wide + D("0.0010"), wide - D("0.0010"), wide))
    # ضغطٌ ضيّق — **وليس ساكناً تماماً**. سكونٌ كامل يعطي عرض نطاقٍ صفراً،
    # وصفرٌ يمرّ أيّ نسبةِ ضغطٍ مهما شُدّدت — فتبطل التجهيزةُ الفحصَ نفسه.
    for i in range(60, 100):
        tick = D("0.0002") if i % 2 else -D("0.0002")
        near = price + tick
        bars.append(bar(i, near, near + D("0.0002"), near - D("0.0002"), near))
    level = price + D("0.0004")
    for i in range(3):                         # اختراق
        price += D("0.0040")
        bars.append(bar(100 + i, price - D("0.0040"), price + D("0.0005"), price - D("0.0040"), price))
    back = level - D("0.0001")                 # إعادة اختبار تلمس ولا تكسر
    bars.append(bar(103, price, price, back, level + D("0.0010")))
    return bars


def test_breakout_is_silenced_by_its_squeeze_guard_alone(monkeypatch):
    """
    اختراقٌ من سوقٍ متقلّب أصلاً ليس اختراقاً — هو حركةٌ عادية أخرى. والحارس
    يُعزَل بحقن نسبة ضغطٍ مستحيلة بدل تغيير التجهيزة.
    """
    import app.strategies.breakout_retest as module

    bars = squeeze_breakout_bars()
    q = quote(bid=str(bars[-1].close), ask=str(bars[-1].close + D("0.0001")))
    assert module.BreakoutRetest().evaluate(
        symbol="EURUSD", bars=bars, quote=q, now=NOW
    ) is not None, "التجهيزة لا تُشير أصلاً — الفحص بلا معنى"

    monkeypatch.setattr(module, "SQUEEZE_RATIO", D("0.001"))
    assert module.BreakoutRetest().evaluate(
        symbol="EURUSD", bars=bars, quote=q, now=NOW
    ) is None, "أشارت بلا ضغطٍ سابق — الحارس لا يعمل"


def test_a_breakout_that_never_came_back_is_left_alone():
    """
    **جوهر الفكرة، لا تفصيلٌ فيها.**

    الدخول على الاختراق نفسه أشهر طريقةٍ لخسارة المال هنا: أغلب الاختراقات
    كاذبة، والشمعة التي تخترق هي أسوأ سعرٍ في اليوم غالباً.

    فاختراقٌ انطلق بلا عودة **لا يُدخَل** — وثمنه فرصةٌ ضائعة، وهو ثمنٌ
    مقصود: تركُ فرصةٍ أرخص من دخولٍ سيّئ.
    """
    bars = squeeze_breakout_bars()
    runaway = bars[-1].close + D("0.0200")          # لم تعد الشمعة تلمس المستوى
    bars[-1] = bar(103, runaway - D("0.0010"), runaway + D("0.0005"),
                   runaway - D("0.0015"), runaway)
    q = quote(bid=str(runaway), ask=str(runaway + D("0.0001")))
    assert BreakoutRetest().evaluate(
        symbol="EURUSD", bars=bars, quote=q, now=NOW
    ) is None, "دخلت على اختراقٍ بلا إعادة اختبار"


def test_the_three_do_not_all_speak_in_the_same_market():
    """
    **الغرض من وجود ثلاث استراتيجيات: تغطيةٌ لا تكرار.**

    ثلاث نسخ من فكرةٍ واحدة تصمت كلها في نفس الأسبوع وتتكلّم كلها في نفس
    اليوم — فتضاعف الرهان بدل أن توزّعه. وهذا الفحص يمنع أن ينحدر النظام
    إلى ذلك بصمت.
    """
    for market in (trending(), choppy()):
        speaking = [
            s.metadata.name for s in STRATEGIES
            if s.evaluate(symbol="EURUSD", bars=market, quote=quote(), now=NOW) is not None
        ]
        assert len(speaking) <= 1, f"تكلّمت معاً: {speaking}"


# ---------------------------------------------------------------------------
# ٣ · الإشارة حين ينطبق الشرط
# ---------------------------------------------------------------------------

def pullback_bars() -> list[Bar]:
    """اتجاهٌ صاعد، ثم شمعةٌ تهبط إلى EMA10 وتُغلق فوقه."""
    bars = trending(120)
    last_close = bars[-1].close
    dip = last_close - D("0.0110")
    bars.append(bar(120, last_close, last_close + D("0.0005"), dip, last_close - D("0.0005")))
    return bars


def test_trend_pullback_signals_a_buy_on_a_rejected_dip():
    signal = TrendPullbackV2().evaluate(
        symbol="EURUSD", bars=pullback_bars(),
        quote=quote(bid="1.2370", ask="1.2371"), now=NOW,
    )
    assert signal is not None, "لم تُشِر رغم انطباق الشرط"
    assert signal.side is Side.BUY
    assert signal.stop_price < signal.entry_price < signal.take_profit_price
    assert "ADX14" in signal.rationale_ar
    assert signal.strategy_version == "2.0.0"


def test_trend_pullback_can_also_sell():
    """
    **نصف الفرص كانت مهدرة في v1** بلا سبب: الفوركس متماثل، وهبوط اليورو
    هو صعود الدولار.
    """
    bars = trending(120, step="-0.0020", start="1.3000")
    last_close = bars[-1].close
    spike = last_close + D("0.0110")
    bars.append(bar(120, last_close, spike, last_close - D("0.0005"), last_close + D("0.0005")))
    signal = TrendPullbackV2().evaluate(
        symbol="EURUSD", bars=bars, quote=quote(bid="1.0620", ask="1.0621"), now=NOW
    )
    assert signal is not None and signal.side is Side.SELL
    assert signal.take_profit_price < signal.entry_price < signal.stop_price


# ---------------------------------------------------------------------------
# ٤ · المستويات لا تُقلَب أبداً
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: s.metadata.name)
def test_no_signal_ever_places_the_stop_on_the_target_side(strategy):
    """
    وقفٌ في جهة الهدف يُنتج أمراً **يُنفَّذ فوراً بخسارة**. وهو خطأ لا يظهر
    في أي اختبارٍ ينظر إلى القيم ولا ينظر إلى الاتجاه.
    """
    for bars in (trending(), choppy(), pullback_bars(), trending(200)):
        signal = strategy.evaluate(symbol="EURUSD", bars=bars, quote=quote(), now=NOW)
        if signal is None:
            continue
        if signal.side is Side.BUY:
            assert signal.stop_price < signal.entry_price < signal.take_profit_price
        else:
            assert signal.take_profit_price < signal.entry_price < signal.stop_price


def test_mean_reversion_refuses_a_target_nearer_than_its_stop():
    """
    هدفها متوسطٌ متحرّك لا مضاعفُ ATR، فقد يقع أقرب من الوقف — فتصير الصفقة
    سالبة التوقّع **بالبناء** لا بسوء الحظ. تُرفَض ولا تُعدَّل مستوياتها،
    لأن تعديلها يجعل الاستراتيجية تفاوض نفسها حتى تجد جواباً.
    """
    import app.strategies.range_mean_reversion as module

    source = (module.__file__ or "")
    assert source
    text = open(source, encoding="utf-8").read()
    assert "abs(target - entry) <= abs(entry - stop)" in text
    assert "return None" in text.split("abs(target - entry)")[1][:80]
