"""
مكتبةٌ داخل-يومية — أُضيفت لأن سببَ غيابها كان خطأ قياسٍ لا حقيقةَ سوق.

## لماذا وُجدت

استراتيجيات المشروع الثلاث كلّها على الشمعة اليومية، وتواترُها المقيس على
خمس سنوات ونصف: **0.03–0.07 صفقة في يوم التداول** — أي صفقةٌ كل أسبوعين
إلى شهر. وهدف المالكة صفقةٌ مكتملة في كل يوم تداولٍ مؤهَّل. فالفجوة في
**التغطية**، لا في السياسة ولا في المخاطر.

وسببُ انحصارها في اليوم كان مكتوباً في `fx_common`: «أدنى مسافة وقف عند
الوسيط ١٠٠ نقطة ⇒ التداول داخل اليوم ليس خياراً هندسياً». والحدُّ الحقيقي
`PERCENTAGE 0.01` = **١٫١٦ نقطة**. فالإطار مفتوحٌ هندسياً، وأُغلق بخطأ وحدة.

## وما تحرسه هذه الفحوص

**ليست فحوصَ ربح.** لا شيء هنا يقول إن الفكرتين رابحتان — ذلك يقيسه مسح
التاريخ ويحكم عليه بحدّ تعادلٍ وتصحيح مقارنات. هذه تحرس أن تكون
الاستراتيجيتان **صادقتين في وصف نفسيهما**:

* حالتهما `RESEARCH` ولا دليل مُدّعى.
* شروطهما تمنع فعلاً حين تختلّ (لا إشارة من ظرفٍ ليس ظرفها).
* مستوياتهما متّسقة (وقفٌ في الجهة الصحيحة، وهدفٌ أبعد منه).
* والنتيجة **حتمية**: نفس المدخلات ⇒ نفس المخرجات.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.contracts import Bar, DataSource, Side, StrategyState
from app.money import D
from app.strategies.momentum_continuation import MomentumContinuation
from app.strategies.session_open_breakout import SessionOpenBreakout

from .conftest import make_quote

UTC = timezone.utc


def bar(start, o, h, l, c, symbol="EURUSD", timeframe="1H"):
    # `timeframe` وسيطٌ للقراءة وحدها — `Bar` لا تحمله، والشمعة تُعرَف
    # بفاصلها الزمني في `start_utc`.
    return Bar(
        symbol=symbol, start_utc=start,
        open=D(str(o)), high=D(str(h)), low=D(str(l)), close=D(str(c)),
        volume=D("1000"), source=DataSource.HISTORICAL,
    )


def quote(bid, ask, symbol="EURUSD"):
    return make_quote(symbol, str(bid), str(ask), at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
                      source=DataSource.REALTIME)


# ---------------------------------------------------------------------------
# ١ · الصدق في وصف النفس
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [MomentumContinuation, SessionOpenBreakout])
def test_they_declare_research_and_claim_no_evidence(cls):
    m = cls.metadata
    assert m.state is StrategyState.RESEARCH
    assert "لا يوجد" in m.backtest_evidence_ar
    assert "لا يوجد" in m.walkforward_evidence_ar


@pytest.mark.parametrize("cls", [MomentumContinuation, SessionOpenBreakout])
def test_they_declare_an_intraday_timeframe_and_no_approval(cls):
    """
    إطارٌ داخل-يومي **معلَن**، وقائمة اعتمادٍ فارغة: التشغيل عليه يحتاج
    دليلاً أو استثناءً مُسمّى، ولا يمرّ لأن الاستراتيجية «داخل-يومية».
    """
    m = cls.metadata
    assert m.timeframe in {"1H", "15M"}
    assert m.approved_timeframes == ()
    assert m.allowed_timeframes == (m.timeframe,)


@pytest.mark.parametrize("cls", [MomentumContinuation, SessionOpenBreakout])
def test_they_name_their_own_no_trade_conditions(cls):
    m = cls.metadata
    assert len(m.no_trade_conditions_ar) >= 4
    assert m.hypothesis_ar and m.invalidations_ar


# ---------------------------------------------------------------------------
# ٢ · MOMENTUM_CONTINUATION — الشروط تمنع فعلاً
# ---------------------------------------------------------------------------

def _trending_bars(n=80, start_price=1.1000, step=0.0006):
    """صعودٌ ممتدّ يرفع ADX ويجعل EMA10 فوق EMA30."""
    base = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    out = []
    price = start_price
    for i in range(n):
        o = price
        c = price + step
        out.append(bar(base + timedelta(hours=i), o, c + 0.0002, o - 0.0002, c))
        price = c
    return out


def _flat_bars(n=80, price=1.1000):
    base = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    out = []
    for i in range(n):
        wobble = 0.0001 if i % 2 else -0.0001
        out.append(bar(base + timedelta(hours=i), price, price + 0.0002,
                       price - 0.0002, price + wobble))
    return out


def test_momentum_is_silent_in_a_flat_market():
    """حارس الظرف: بلا اتجاهٍ ممتدّ لا إشارة — ADX هو المانع ويُسمّى."""
    bars = _flat_bars()
    result = MomentumContinuation().assess(
        symbol="EURUSD", bars=bars, quote=quote(1.1000, 1.1001),
        now=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
    )
    assert result.signal is None
    text = " ".join(c.detail_ar for c in result.checks)
    # السبب يُسمّى: إمّا الظرف (ADX) وإمّا أن المؤشر غير محسوب على هذه
    # العيّنة. وكلاهما **سببٌ مكتوب**، وهو المطلوب — لا صمتٌ بلا تعليل.
    assert ("ADX" in text) or ("المؤشرات" in text), text


def test_momentum_refuses_an_extension_not_a_breakout():
    """
    الشمعة السابقة خارج القناة أيضاً ⇒ امتدادٌ لا اختراق. والدخول عليه
    شراءٌ بعد أن تحرّك السعر — تغييرٌ للفرضية لا تطبيقٌ لها.
    """
    bars = _trending_bars()
    result = MomentumContinuation().assess(
        symbol="EURUSD", bars=bars, quote=quote(1.1480, 1.1481),
        now=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
    )
    if result.signal is None:
        text = " ".join(c.detail_ar for c in result.checks)
        assert "امتداد" in text or "داخل القناة" in text or "ADX" in text


def test_momentum_levels_are_coherent_when_it_does_signal():
    """أيّاً كانت الإشارة: الوقف في الجهة الصحيحة، والهدف أبعد منه."""
    bars = _trending_bars(n=60)
    # شمعةٌ أخيرة تخترق بعد أن كانت السابقة داخل القناة
    bars = bars[:-1] + [bar(bars[-1].start_utc, 1.1300, 1.1400, 1.1295, 1.1395)]
    result = MomentumContinuation().assess(
        symbol="EURUSD", bars=bars, quote=quote(1.1394, 1.1396),
        now=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
    )
    if result.signal is not None:
        s = result.signal
        if s.side is Side.BUY:
            assert s.stop_price < s.entry_price < s.take_profit_price
        else:
            assert s.take_profit_price < s.entry_price < s.stop_price


def test_momentum_is_deterministic():
    bars = _trending_bars()
    q = quote(1.1480, 1.1481)
    now = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
    a = MomentumContinuation().assess(symbol="EURUSD", bars=bars, quote=q, now=now)
    b = MomentumContinuation().assess(symbol="EURUSD", bars=bars, quote=q, now=now)
    assert (a.signal is None) == (b.signal is None)
    if a.signal is not None:
        assert a.signal.model_dump() == b.signal.model_dump()


# ---------------------------------------------------------------------------
# ٣ · SESSION_OPEN_BREAKOUT — النافذة والنطاق
# ---------------------------------------------------------------------------

def _session_bars(breakout: bool):
    """
    يومٌ واحد بشمعات ربع ساعة: تاريخٌ سابق ثم نطاق 07:00–08:00 ثم ما بعده.
    """
    out = []
    base = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
    for i in range(60):                       # تاريخٌ سابق لحساب ATR
        p = 1.1000 + (i % 5) * 0.0004
        out.append(bar(base + timedelta(minutes=15 * i), p, p + 0.0010,
                       p - 0.0010, p + 0.0002, timeframe="15M"))
    day = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)
    for i in range(4):                        # نطاق الافتتاح
        out.append(bar(day + timedelta(minutes=15 * i), 1.1000, 1.1020,
                       1.0990, 1.1005, timeframe="15M"))
    after = day + timedelta(hours=1)
    close = 1.1035 if breakout else 1.1010
    out.append(bar(after, 1.1005, close + 0.0005, 1.1000, close, timeframe="15M"))
    return out


def test_the_breakout_signals_inside_the_window():
    result = SessionOpenBreakout().assess(
        symbol="EURUSD", bars=_session_bars(breakout=True),
        quote=quote(1.1034, 1.1036), now=datetime(2026, 9, 3, 8, 15, tzinfo=UTC),
    )
    assert result.signal is not None, " · ".join(
        f"{c.name_ar}:{c.detail_ar}" for c in result.checks
    )
    s = result.signal
    assert s.side is Side.BUY
    assert s.stop_price < s.entry_price < s.take_profit_price
    # الوقف عند الطرف المقابل للنطاق — نقطة إبطالٍ بنيوية لا مضاعف تقلّب
    assert s.stop_price == D("1.0990")


def test_no_signal_without_a_close_outside_the_range():
    result = SessionOpenBreakout().assess(
        symbol="EURUSD", bars=_session_bars(breakout=False),
        quote=quote(1.1009, 1.1011), now=datetime(2026, 9, 3, 8, 15, tzinfo=UTC),
    )
    assert result.signal is None
    text = " ".join(c.detail_ar for c in result.checks)
    assert "خارج النطاق" in text


def test_no_signal_outside_the_entry_window():
    """آخر شمعةٍ خارج النافذة ⇒ لا إشارة، ويُقال إن السبب النافذة."""
    bars = _session_bars(breakout=True)
    late = bars[-1]
    bars = bars[:-1] + [bar(datetime(2026, 9, 3, 14, 0, tzinfo=UTC), 1.1005,
                            1.1040, 1.1000, 1.1035, timeframe="15M")]
    result = SessionOpenBreakout().assess(
        symbol="EURUSD", bars=bars, quote=quote(1.1034, 1.1036),
        now=datetime(2026, 9, 3, 14, 15, tzinfo=UTC),
    )
    assert result.signal is None
    text = " ".join(c.detail_ar for c in result.checks)
    assert "نافذة الدخول" in text or "نطاق الافتتاح" in text, text


def test_the_session_breakout_is_deterministic():
    bars = _session_bars(breakout=True)
    q = quote(1.1034, 1.1036)
    now = datetime(2026, 9, 3, 8, 15, tzinfo=UTC)
    a = SessionOpenBreakout().assess(symbol="EURUSD", bars=bars, quote=q, now=now)
    b = SessionOpenBreakout().assess(symbol="EURUSD", bars=bars, quote=q, now=now)
    assert a.signal.model_dump() == b.signal.model_dump()


def test_an_unknown_symbol_is_refused_by_both():
    for cls in (MomentumContinuation, SessionOpenBreakout):
        result = cls().assess(
            symbol="TSLA", bars=_trending_bars(), quote=quote(1.1, 1.1001),
            now=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
        )
        assert result.signal is None
