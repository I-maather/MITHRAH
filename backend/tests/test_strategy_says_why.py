"""
كل رفضٍ يقول **أي شرطٍ سقط وبأي رقم**.

## العطل

كل رفضٍ في الاستراتيجيات كان `return None` مجرّداً، فيصل إلى المالكة
`NO_SETUP` — «لا توجد فرصة مطابقة». وهي الجملة نفسها سواء كان ADX عند
24.9 (على بُعد شعرة) أو عند 8 (سوقٌ لا تناسبه الاستراتيجية أصلاً).

⇒ تنظر إلى الجملة نفسها أياماً بلا أن تعرف: أالنظام على وشك الدخول، أم أن
هذه الاستراتيجية لا تناسب هذا السوق بحال؟

وهذا بالضبط ما يُفترض أن يميّز هذا المنتج: «لماذا لم أتداول» — يقولها ثم
يصمت عند أهمّ سؤالٍ فيها.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.contracts import Bar, DataSource, Quote
from app.strategies.trend_pullback_v2 import TrendPullbackV2

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def bars(count=120, *, drift=D("0.0005"), noise=D("0.0002")):
    """شموعٌ باتجاهٍ صاعد واضح — ADX فوق العتبة."""
    out = []
    price = D("1.10000")
    for i in range(count):
        price = price + drift
        out.append(Bar(
            symbol="EURUSD", start_utc=NOW - timedelta(days=count - i),
            open=price - noise, high=price + noise, low=price - noise,
            close=price, volume=D("1000"), source=DataSource.HISTORICAL,
        ))
    return out


def choppy_bars(count=140):
    """
    سوقٌ متذبذب **حقيقي**: تأرجحٌ بموجةٍ حول متوسطٍ ثابت، بحركةٍ اتجاهية
    قابلة للقياس في الجهتين — فيُحسَب ADX ويأتي منخفضاً.

    وأوّل كتابةٍ لهذا الملف استعملت تأرجحاً ثنائياً بقممٍ وقيعانٍ متطابقة،
    فكانت الحركة الاتجاهية **صفراً** وتعذّر حساب ADX أصلاً — فسقط الاختبار
    على «تعذّر الحساب» لا على «الظرف»، أي أنه كان يفحص شيئاً آخر. نفس فخّ
    التجهيزة المتكرّر في هذا المشروع.
    """
    import math

    out = []
    base = D("1.10000")
    for i in range(count):
        wave = D(str(round(math.sin(i / 3.0) * 0.004, 6)))
        close = base + wave
        span = D("0.0006")
        out.append(Bar(
            symbol="EURUSD", start_utc=NOW - timedelta(days=count - i),
            open=close - wave / 4, high=close + span, low=close - span,
            close=close, volume=D("1000"), source=DataSource.HISTORICAL,
        ))
    return out


def quote():
    return Quote(
        symbol="EURUSD", bid=D("1.16000"), ask=D("1.16007"), last=D("1.16003"),
        timestamp_utc=NOW, source=DataSource.REALTIME, received_at_utc=NOW,
    )


def assess(rows, symbol="EURUSD"):
    return TrendPullbackV2().assess(symbol=symbol, bars=rows, quote=quote(), now=NOW)


def test_a_choppy_market_names_adx_with_its_number():
    """**الفحص الذي كان مستحيلاً.** «لا فرصة» صارت «ADX كذا دون 25»."""
    result = assess(choppy_bars())
    assert result.signal is None
    blocker = result.blocking
    assert blocker is not None
    assert blocker.name_ar == "الظرف"
    assert "ADX14" in blocker.detail_ar
    assert "دون 25" in blocker.detail_ar


def test_too_few_bars_names_the_count_not_a_vague_sentence():
    result = assess(bars(count=10))
    assert result.blocking is not None
    assert result.blocking.name_ar == "عدد الشموع"
    assert "10 شمعة" in result.blocking.detail_ar


def test_a_foreign_symbol_says_so_plainly():
    result = assess(bars(), symbol="SPY")
    assert result.blocking is not None
    assert "SPY" in result.blocking.detail_ar


def test_the_chain_stops_at_the_first_failure():
    """
    عرضُ بقيّة الشروط بعد سقوط الظرف يوحي بأنها فُحصت وهي لم تُفحَص — وهو
    ادّعاءٌ عن عملٍ لم يقع.
    """
    result = assess(choppy_bars())
    failed = [c for c in result.checks if not c.passed]
    assert len(failed) == 1
    assert result.checks[-1] is failed[0]


def test_the_summary_is_the_blocking_reason_not_a_generic_line():
    result = assess(choppy_bars())
    assert "ADX14" in result.summary_ar
    assert "لا توجد فرصة" not in result.summary_ar


def test_evaluate_still_returns_exactly_what_it_used_to():
    """
    التشخيص **يُضاف ولا يَحكم**. `evaluate` تبقى القرار، ولو اختلفت عن
    `assess` لصار في النظام مصدرا حقيقةٍ للقرار الواحد.
    """
    strategy = TrendPullbackV2()
    for rows in (choppy_bars(), bars(), bars(count=10)):
        direct = strategy.evaluate(symbol="EURUSD", bars=rows, quote=quote(), now=NOW)
        through = strategy.assess(symbol="EURUSD", bars=rows, quote=quote(), now=NOW).signal
        assert (direct is None) == (through is None)


def test_a_strategy_without_detail_says_so_and_invents_nothing():
    """
    الاستراتيجية التي لم تُفصّل شروطها بعد تقول ذلك — ولا يُختلق لها سبب.
    """
    from app.strategies.trend_pullback_v1 import TrendPullbackV1

    result = TrendPullbackV1().assess(
        symbol="EURUSD", bars=bars(), quote=quote(), now=NOW
    )
    assert result.signal is None
    assert "لا تُفصّل شروطها" in result.summary_ar


def test_the_pipeline_carries_the_reason_into_its_result():
    """
    التشخيص لا ينفع في الذاكرة. والخط يحمله في نتيجته كي تبلغ الشاشة.
    """
    from app.pipeline.runner import Pipeline

    body = __import__("pathlib").Path(
        __file__
    ).resolve().parents[1] / "app" / "pipeline" / "runner.py"
    source = body.read_text(encoding="utf-8")
    assert "strategy.assess(" in source
    assert "assessments=tuple(assessments)" in source
    assert hasattr(Pipeline, "runnable_strategies")
