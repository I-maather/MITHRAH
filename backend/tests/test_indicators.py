"""
المؤشرات — تُقاس بقيمٍ مرجعية منشورة، لا بما تُخرجه هي.

## لماذا القيم المرجعية شرط

اختبارٌ يقارن الدالة بنفسها (`assert rsi(x) == rsi(x)`) يمرّ على تنفيذٍ
خاطئ تماماً. والمؤشرات كلّها تُنتج رقماً من أي مدخل، فلا يُميَّز الصحيح من
القريب إلا بمرجعٍ خارجي.

فبيانات ويلدر المنشورة (`44.34 … 45.64`) تُستعمل هنا: قيمة RSI عند الشمعة
العشرين فيها **57.92** في كل مرجعٍ منشور. ولو استُعمل متوسطٌ بسيط مكان
تنعيم ويلدر لخرج رقمٌ قريب — ولا يطابق ما تراه المالكة على شاشة كابيتال.
وتناقضُ شاشتين أسوأ من خطأ صريح.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.contracts import Bar, DataSource
from app.money import D
from app.strategies.indicators import (
    adx,
    atr,
    bollinger,
    ema,
    highest_high,
    lowest_low,
    lowest_low as _ll,
    macd,
    rsi,
    sma,
    stochastic,
    true_range,
)

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)

#: بيانات ويلدر المرجعية — تُستشهَد في كل مرجعٍ منشور لمؤشر RSI.
WILDER = [
    "44.34", "44.09", "44.15", "43.61", "44.33", "44.83", "45.10", "45.42",
    "45.84", "46.08", "45.89", "46.03", "45.61", "46.28", "46.28", "46.00",
    "46.03", "46.41", "46.22", "45.64",
]
CLOSES = [D(v) for v in WILDER]


def bar(index: int, *, high: str, low: str, close: str, open_: str | None = None) -> Bar:
    return Bar(
        symbol="EURUSD",
        start_utc=NOW + timedelta(days=index),
        open=D(open_ or close), high=D(high), low=D(low), close=D(close),
        volume=D(0), source=DataSource.HISTORICAL,
    )


def rising_bars(count: int, *, step: str = "1.0") -> list[Bar]:
    """سوقٌ صاعد بخطوةٍ ثابتة — اتجاهٌ نقيّ يجب أن يعطي ADX عالياً."""
    out = []
    price = D("100")
    for i in range(count):
        out.append(bar(i, high=str(price + D("0.5")), low=str(price - D("0.5")), close=str(price)))
        price += D(step)
    return out


# ---------------------------------------------------------------------------
# القيم المرجعية
# ---------------------------------------------------------------------------

def test_rsi_matches_the_published_wilder_value():
    """**المرجع الخارجي.** 57.92 عند الشمعة العشرين في كل مرجعٍ منشور."""
    value = rsi(CLOSES, 14)
    assert value is not None
    assert abs(value - D("57.92")) < D("0.01"), f"RSI = {value}"


def test_sma_and_ema_are_not_the_same_thing():
    """
    فحصٌ يبدو تافهاً وليس كذلك: خطأٌ شائع أن تُنفَّذ EMA فتعطي SMA — وهو
    خطأٌ **لا يظهر** في أي رسمٍ بصري لأن المنحنيين متقاربان.
    """
    simple = sma(CLOSES, 5)
    exponential = ema(CLOSES, 5)
    assert simple is not None and exponential is not None
    assert simple != exponential
    assert abs(simple - D("46.06")) < D("0.01")


def test_bollinger_uses_population_deviation_and_brackets_the_mean():
    band = bollinger(CLOSES, 20)
    assert band is not None
    assert band.lower < band.middle < band.upper
    assert abs(band.middle - D("45.409")) < D("0.001")
    # انحرافٌ للمجتمع: قسمة n لا n−1. والفرق يُوسّع النطاق لو انعكس.
    assert abs(band.upper - D("47.1153")) < D("0.001")
    assert band.width > 0


def test_true_range_counts_the_gap_not_just_the_candle():
    """
    المدى الحقيقي يشمل الفجوة عن الإغلاق السابق. وإهمالها يجعل الوقف
    المحسوب من ATR **أضيق مما يحتمله السوق** في أيام الأخبار بالذات.
    """
    previous = bar(0, high="100", low="99", close="99.5")
    gapped = bar(1, high="105", low="104", close="104.5")
    assert true_range(previous, gapped) == D("5.5")
    assert gapped.high - gapped.low == D("1")


# ---------------------------------------------------------------------------
# النقص يُعاد None ولا يُقارَب
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda: sma(CLOSES, 50),
    lambda: ema(CLOSES, 50),
    lambda: rsi(CLOSES[:3], 14),
    lambda: bollinger(CLOSES[:5], 20),
    lambda: macd(CLOSES[:10]),
    lambda: atr(rising_bars(5), 14),
    lambda: adx(rising_bars(10), 14),
    lambda: stochastic(rising_bars(3), 14, 3),
    lambda: highest_high(rising_bars(3), 20),
    lambda: _ll(rising_bars(3), 20),
])
def test_insufficient_data_returns_none_and_never_an_approximation(call):
    """
    **أخطر ما في المؤشرات أنها تُنتج رقماً من أي مدخل.** متوسطٌ لعشرين شمعة
    محسوبٌ على خمس ليس متوسطاً — هو رقمٌ يشبه المتوسط، ويُبنى عليه قرار.
    """
    assert call() is None


@pytest.mark.parametrize("period", [0, -1])
def test_a_nonsensical_period_returns_none_not_a_crash(period):
    assert sma(CLOSES, period) is None
    assert ema(CLOSES, period) is None
    assert rsi(CLOSES, period) is None


# ---------------------------------------------------------------------------
# الحالات الحدّية التي تُنتج قسمةً على صفر
# ---------------------------------------------------------------------------

def test_rsi_of_an_unbroken_rise_is_one_hundred_not_a_crash():
    """صعودٌ بلا خسارةٍ واحدة يعني مقاماً صفراً — و١٠٠ معلومةٌ حقيقية."""
    closes = [D(100 + i) for i in range(20)]
    assert rsi(closes, 14) == D(100)


def test_stochastic_of_a_flat_market_is_the_middle_not_a_crash():
    flat = [bar(i, high="100", low="100", close="100") for i in range(20)]
    result = stochastic(flat, 14, 3)
    assert result is not None and result.k == D(50)


def test_bollinger_width_of_a_flat_market_is_zero():
    band = bollinger([D(100)] * 20, 20)
    assert band is not None and band.width == 0
    assert band.upper == band.middle == band.lower


# ---------------------------------------------------------------------------
# المعنى، لا الرقم وحده
# ---------------------------------------------------------------------------

def test_adx_reads_high_in_a_pure_trend():
    """ADX يقيس **قوّة** الاتجاه: سوقٌ صاعد بخطوةٍ ثابتة يجب أن يقرأ عالياً."""
    value = adx(rising_bars(60), 14)
    assert value is not None and value > D(40), f"ADX = {value}"


def test_adx_reads_low_in_a_chopping_market():
    """
    وهذا هو الفحص الذي يهمّ: فكرةٌ تربح في اتجاهٍ ممتدّ تخسر في سوقٍ عرضي،
    و`ADX` هو ما يفصل الحالتين. ولو قرأ عالياً هنا لكان حارساً بلا معنى.
    """
    chop = []
    for i in range(60):
        price = D("100") + (D("1") if i % 2 else D("0"))
        chop.append(bar(i, high=str(price + D("0.5")), low=str(price - D("0.5")), close=str(price)))
    value = adx(chop, 14)
    assert value is not None and value < D(25), f"ADX = {value}"


def test_macd_signal_is_an_average_of_the_line_not_of_the_prices():
    """
    خطّ الإشارة أسّيٌّ **فوق سلسلة الخط** لا فوق الأسعار. وحسابه على الأسعار
    خطأٌ شائع يعطي منحنىً يشبه الصحيح ويتقاطع في مواضع أخرى — أي إشارات دخولٍ
    مختلفة تماماً.
    """
    # صعودٌ **متسارع** لا خطّي: الخطّي يعطي خطّ MACD ثابتاً فتساويه إشارته
    # تماماً (هستوغرام صفر) — وهو سلوكٌ صحيح ولا يفرّق بين تنفيذين.
    closes = [D(100) + D(i) * D(i) * D("0.02") for i in range(60)]
    result = macd(closes)
    assert result is not None
    assert result.histogram == result.line - result.signal
    assert result.line > result.signal, "الخط لا يسبق إشارته في تسارعٍ صاعد"

    flat_ramp = macd([D(100) + D(i) * D("0.7") for i in range(60)])
    assert flat_ramp is not None
    assert flat_ramp.histogram == 0, "صعودٌ خطّي يعطي هستوغرام صفر"


def test_every_indicator_returns_decimal_never_float():
    """
    عائمٌ واحد يكفي لأن يعطي المؤشر نتيجتين على آلتين، فينهار شرط «نفس
    المدخلات ⇒ نفس المخرجات» الذي يقوم عليه سجلّ التدقيق كلّه.
    """
    bars = rising_bars(60)
    values = [
        sma(CLOSES, 5), ema(CLOSES, 5), rsi(CLOSES, 14),
        atr(bars, 14), adx(bars, 14),
        highest_high(bars, 20), lowest_low(bars, 20),
    ]
    band = bollinger(CLOSES, 20)
    stoch = stochastic(bars, 14, 3)
    line = macd([D(100) + D(i) for i in range(60)])
    assert band is not None and stoch is not None and line is not None
    values += [band.upper, band.middle, band.lower, band.width,
               stoch.k, stoch.d, line.line, line.signal, line.histogram]
    for value in values:
        assert isinstance(value, Decimal), f"{value!r} ليس Decimal"
