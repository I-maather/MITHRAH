"""
مؤشرات تحليل فنّي حتمية — بحساب عشري، وبلا اختلاق قيمة.

## القواعد الحاكمة لهذا الملف

**١ · `Decimal` لا `float`.** مؤشرٌ يُحسب بعائم يعطي نتيجتين مختلفتين على
آلتين، فينهار شرط «نفس المدخلات ⇒ نفس المخرجات» الذي يقوم عليه التدقيق كلّه.

**٢ · نقص البيانات يُعاد `None` ولا يُقارَب.** متوسطٌ لعشر شمعات يُحسب على
سبع ليس متوسطاً — هو رقمٌ يشبه المتوسط. وأخطر ما في المؤشرات أن كلّها تُنتج
رقماً من أي مدخل، فلا يُميَّز الصحيح من القريب.

**٣ · لا مكتبة خارجية.** كل ما هنا مكتوبٌ ومختبَر، فلا تدخل حزمةٌ إلى مسار
القرار بلا أن تُقرأ.

## تحذيرٌ يخالف الحدس، ويُكتب هنا لأنه أهمّ من أي دالة أدناه

**زيادة المؤشرات لا تصنع حافّة — بل تصنع إفراط التوفيق.**

عشرة مؤشرات على ١٧٠٠ شمعة تجد نمطاً **دائماً**، ولو كانت الشموع عشوائية
تماماً. والفرق بين نمطٍ حقيقي ونمطٍ اختُرع بكثرة المحاولات لا يظهر داخل
العيّنة أبداً.

فهذه أدوات قياس، لا أدوات كسب. والانضباط في أن تكون كل استراتيجية **فرضيةً
قابلة للتكذيب** تُختبَر خارج عيّنتها وتمرّ بوابات الاعتماد — لا في عدد
المؤشرات المتاحة.

## عن ويلدر

`RSI` و`ATR` و`ADX` تستعمل تنعيم ويلدر (Wilder) لا المتوسط البسيط:

    الأوّل   = مجموع أوّل n ÷ n
    ما بعده  = السابق − (السابق ÷ n) + الحالي ÷ n

وهو ما تحسبه المنصّات، ومنها كابيتال. واستعمال متوسطٍ بسيط مكانه يعطي أرقاماً
تشبه الصحيحة ولا تطابق ما تراه المالكة على شاشة الوسيط — وذلك تناقضُ شاشتين.
"""
from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional, Sequence

from ..contracts import Bar
from ..money import D

ZERO = D("0")
HUNDRED = D("100")


# ---------------------------------------------------------------------------
# المتوسطات
# ---------------------------------------------------------------------------

def sma(values: Sequence[Decimal], period: int) -> Optional[Decimal]:
    """المتوسط المتحرك البسيط لآخر `period` قيمة."""
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:], ZERO) / D(period)


def ema(values: Sequence[Decimal], period: int) -> Optional[Decimal]:
    """
    المتوسط المتحرك الأسّي.

    البذرة متوسطٌ بسيط لأوّل `period` قيمة — لا القيمة الأولى وحدها: البدء
    بقيمةٍ واحدة يجعل أوّل عشرات النتائج مشوّهة بذيلٍ لا معنى له.
    """
    if period <= 0 or len(values) < period:
        return None
    multiplier = D(2) / D(period + 1)
    running = sum(values[:period], ZERO) / D(period)
    for value in values[period:]:
        running = (value - running) * multiplier + running
    return running


def ema_series(values: Sequence[Decimal], period: int) -> list[Decimal]:
    """سلسلة EMA كاملة — يحتاجها MACD الذي يبني أسّياً فوق أسّي."""
    if period <= 0 or len(values) < period:
        return []
    multiplier = D(2) / D(period + 1)
    running = sum(values[:period], ZERO) / D(period)
    out = [running]
    for value in values[period:]:
        running = (value - running) * multiplier + running
        out.append(running)
    return out


# ---------------------------------------------------------------------------
# المدى والتقلّب
# ---------------------------------------------------------------------------

def true_range(previous: Bar, current: Bar) -> Decimal:
    """المدى الحقيقي: يشمل الفجوة بين الإغلاق السابق وشمعة اليوم."""
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def _wilder(values: Sequence[Decimal], period: int) -> Optional[Decimal]:
    if period <= 0 or len(values) < period:
        return None
    running = sum(values[:period], ZERO) / D(period)
    for value in values[period:]:
        running = running - (running / D(period)) + (value / D(period))
    return running


def atr(bars: Sequence[Bar], period: int = 14) -> Optional[Decimal]:
    """متوسط المدى الحقيقي بتنعيم ويلدر."""
    if len(bars) < period + 1:
        return None
    ranges = [true_range(bars[i - 1], bars[i]) for i in range(1, len(bars))]
    return _wilder(ranges, period)


def atr_simple(bars: Sequence[Bar], period: int = 14) -> Optional[Decimal]:
    """
    متوسطٌ بسيط للمدى — **موجودٌ للتوافق مع `TREND_PULLBACK v1` وحدها**.

    لا يُستعمل في استراتيجية جديدة: مؤشران بالاسم نفسه وحسابين مختلفين في
    مشروعٍ واحد بابُ التباسٍ مفتوح.
    """
    if len(bars) < period + 1:
        return None
    ranges = [true_range(bars[i - 1], bars[i]) for i in range(len(bars) - period, len(bars))]
    return sum(ranges, ZERO) / D(period)


# ---------------------------------------------------------------------------
# الزخم
# ---------------------------------------------------------------------------

def rsi(values: Sequence[Decimal], period: int = 14) -> Optional[Decimal]:
    """
    مؤشر القوة النسبية بتنعيم ويلدر. المدى ٠–١٠٠.

    وحين لا تقع خسارةٌ واحدة في النافذة يكون المقام صفراً — وتُعاد ١٠٠
    صراحةً لا `ZeroDivisionError` ولا `None`: السوق صعد في كل شمعة، وهذه
    معلومةٌ حقيقية لا نقصٌ في البيانات.
    """
    if period <= 0 or len(values) < period + 1:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(change if change > 0 else ZERO)
        losses.append(-change if change < 0 else ZERO)
    avg_gain = _wilder(gains, period)
    avg_loss = _wilder(losses, period)
    if avg_gain is None or avg_loss is None:
        return None
    if avg_loss == 0:
        return HUNDRED if avg_gain > 0 else D(50)
    rs = avg_gain / avg_loss
    return HUNDRED - (HUNDRED / (D(1) + rs))


class Macd(NamedTuple):
    line: Decimal
    signal: Decimal
    histogram: Decimal


def macd(
    values: Sequence[Decimal], fast: int = 12, slow: int = 26, signal: int = 9
) -> Optional[Macd]:
    """
    تقارب وتباعد المتوسطات.

    خطّ الإشارة أسّيٌّ **فوق سلسلة الخط** لا فوق الأسعار — ولذلك يحتاج
    `slow + signal` شمعة لا `slow` وحده. وحسابُه على الأسعار خطأٌ شائع يعطي
    منحنىً يشبه الصحيح ويتقاطع في مواضع أخرى.
    """
    if fast >= slow or len(values) < slow + signal:
        return None
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    if not fast_series or not slow_series:
        return None
    # المحاذاة من اليمين: السلسلتان تنتهيان عند الشمعة نفسها.
    overlap = min(len(fast_series), len(slow_series))
    line_series = [
        fast_series[-overlap + i] - slow_series[-overlap + i] for i in range(overlap)
    ]
    signal_series = ema_series(line_series, signal)
    if not signal_series:
        return None
    line = line_series[-1]
    signal_value = signal_series[-1]
    return Macd(line=line, signal=signal_value, histogram=line - signal_value)


class Stochastic(NamedTuple):
    k: Decimal
    d: Decimal


def stochastic(
    bars: Sequence[Bar], k_period: int = 14, d_period: int = 3
) -> Optional[Stochastic]:
    """
    مذبذب ستوكاستيك: أين يقع الإغلاق داخل مدى النافذة.

    ونافذةٌ بلا مدى (أعلى = أدنى) تعني سوقاً لا يتحرّك — تُعاد ٥٠ صراحةً،
    وهي «في المنتصف»، لا قسمةٌ على صفر.
    """
    if k_period <= 0 or d_period <= 0 or len(bars) < k_period + d_period - 1:
        return None
    ks: list[Decimal] = []
    for end in range(k_period, len(bars) + 1):
        window = bars[end - k_period:end]
        highest = max(b.high for b in window)
        lowest = min(b.low for b in window)
        span = highest - lowest
        close = window[-1].close
        ks.append(D(50) if span == 0 else (close - lowest) / span * HUNDRED)
    if len(ks) < d_period:
        return None
    return Stochastic(k=ks[-1], d=sum(ks[-d_period:], ZERO) / D(d_period))


# ---------------------------------------------------------------------------
# التقلّب حول المتوسط
# ---------------------------------------------------------------------------

class Bollinger(NamedTuple):
    upper: Decimal
    middle: Decimal
    lower: Decimal
    width: Decimal


def bollinger(
    values: Sequence[Decimal], period: int = 20, k: Decimal = D("2")
) -> Optional[Bollinger]:
    """
    نطاقات بولنجر بانحرافٍ معياري **للمجتمع** لا للعيّنة.

    والفرق مقصود: النافذة هنا هي كل ما نقيسه، لا عيّنة منه. واستعمال قسمة
    `n−1` يوسّع النطاق قليلاً بلا مبرّر إحصائي في هذا السياق.

    و`width` النطاق منسوباً إلى المتوسط — وهو ما يُقاس به الضغط قبل الاختراق.
    """
    if period <= 1 or len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window, ZERO) / D(period)
    variance = sum(((v - mean) ** 2 for v in window), ZERO) / D(period)
    deviation = variance.sqrt()
    upper = mean + k * deviation
    lower = mean - k * deviation
    width = (upper - lower) / mean if mean != 0 else ZERO
    return Bollinger(upper=upper, middle=mean, lower=lower, width=width)


# ---------------------------------------------------------------------------
# قوة الاتجاه
# ---------------------------------------------------------------------------

def adx(bars: Sequence[Bar], period: int = 14) -> Optional[Decimal]:
    """
    مؤشر الاتجاه المتوسط — **يقيس قوّة الاتجاه لا اتجاهه**.

    وهو الحارس الذي ينقص استراتيجيات التتبّع: فكرةٌ تربح في اتجاهٍ ممتدّ
    تخسر في سوقٍ عرضي، و`ADX` يفصل الحالتين. القراءة الشائعة: فوق ٢٥ اتجاه،
    وتحت ٢٠ عرضيّ.

    يحتاج `2×period + 1` شمعة: تنعيمٌ فوق تنعيم.
    """
    if period <= 0 or len(bars) < 2 * period + 1:
        return None

    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    ranges: list[Decimal] = []
    for i in range(1, len(bars)):
        up = bars[i].high - bars[i - 1].high
        down = bars[i - 1].low - bars[i].low
        plus_dm.append(up if (up > down and up > 0) else ZERO)
        minus_dm.append(down if (down > up and down > 0) else ZERO)
        ranges.append(true_range(bars[i - 1], bars[i]))

    def smoothed_series(values: Sequence[Decimal]) -> list[Decimal]:
        running = sum(values[:period], ZERO)
        out = [running]
        for value in values[period:]:
            running = running - (running / D(period)) + value
            out.append(running)
        return out

    tr_s = smoothed_series(ranges)
    plus_s = smoothed_series(plus_dm)
    minus_s = smoothed_series(minus_dm)

    dx: list[Decimal] = []
    for tr_v, plus_v, minus_v in zip(tr_s, plus_s, minus_s):
        if tr_v == 0:
            continue
        plus_di = HUNDRED * plus_v / tr_v
        minus_di = HUNDRED * minus_v / tr_v
        total = plus_di + minus_di
        if total == 0:
            continue
        dx.append(HUNDRED * abs(plus_di - minus_di) / total)

    return _wilder(dx, period)


# ---------------------------------------------------------------------------
# المستويات
# ---------------------------------------------------------------------------

def highest_high(bars: Sequence[Bar], period: int) -> Optional[Decimal]:
    if period <= 0 or len(bars) < period:
        return None
    return max(b.high for b in bars[-period:])


def lowest_low(bars: Sequence[Bar], period: int) -> Optional[Decimal]:
    if period <= 0 or len(bars) < period:
        return None
    return min(b.low for b in bars[-period:])


__all__ = [
    "Bollinger", "Macd", "Stochastic",
    "adx", "atr", "atr_simple", "bollinger", "ema", "ema_series",
    "highest_high", "lowest_low", "macd", "rsi", "sma", "stochastic",
    "true_range",
]
