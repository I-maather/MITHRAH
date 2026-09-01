"""
المحرّك يختبر **الاستراتيجية المسجَّلة**، لا واحدةً تحمل اسمها.

## العطل الذي أنتج هذا الملف (2026-09-01)

كان `Backtester` يفرض على كل إشارة:

    وقفاً ثابتاً    `config.stop_distance_pips`      (٣٠ نقطة)
    هدفاً ثابتاً    `config.take_profit_distance_pips`
    واتجاهاً واحداً: شراءً دائماً، مهما قال `signal.side`

وكل استراتيجياتنا تشتقّ وقفها من `ATR` — أي من تقلّب السوق ساعتَه. فكان
الاختبار يقيس **استراتيجيةً أخرى**: نفس شروط الدخول تماماً، وخروجٌ مختلف
كلياً. ونتيجةٌ من ذلك لا تقول شيئاً عمّا سيقع في السوق، لا سلباً ولا إيجاباً.

⇒ وهذا يُبطل **كل نتيجة سابقة**: «أربعة تشغيلات كلها داخل الضجيج» كانت عن
خروجٍ لم تطلبه أي استراتيجية.

**والأسوأ:** إشارة بيعٍ كانت تُقرأ بمنطق شراء — فيُعكس كل ربحٍ وخسارة فيها.
وبما أن `v1` كانت شراءً فقط، لم يظهر العطل قطّ. ثم صارت `v2` ثنائية الاتجاه،
فكان سيظهر **كأداءٍ عشوائي** لا كخطأ في المحرّك.

نفس العائلة الحاكمة: مسارٌ لم يُسلَك فلم ينكشف.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Sequence

import pytest

from app.contracts import Bar, DataSource, Quote, Side, Signal, StrategyState
from app.money import D
from app.risk.capital_costs import CapitalComCostModel, InstrumentEconomics
from app.strategies.backtest import BacktestConfig, Backtester, ExitReason
from app.strategies.base import Strategy, StrategyMetadata

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def economics() -> InstrumentEconomics:
    from tests.test_backtest_shadow_gates import economics as base

    return base()


def cost_model() -> CapitalComCostModel:
    return CapitalComCostModel(economics())


def flat_bars(n: int = 60, price: str = "1.1000") -> list[Bar]:
    """سوقٌ ساكن — الحركة كلها تأتي من الشمعة التي نزرعها بعد الإشارة."""
    out = []
    for i in range(n):
        p = D(price)
        out.append(Bar(
            symbol="EURUSD", start_utc=T0 + timedelta(hours=i),
            open=p, high=p + D("0.0001"), low=p - D("0.0001"), close=p,
            volume=D("1000"), source=DataSource.HISTORICAL,
        ))
    return out


def meta(name: str) -> StrategyMetadata:
    return StrategyMetadata(
        name=name, version="1.0.0", hypothesis_ar="اختبار", markets=("EURUSD",),
        timeframe="1H", entry_conditions_ar=(), exit_conditions_ar=(),
        invalidations_ar=(), min_bars_required=5, assumed_costs_ar="اختبار",
        no_trade_conditions_ar=(), state=StrategyState.APPROVED,
        changelog_ar=(), backtest_evidence_ar="اختبار", walkforward_evidence_ar="اختبار",
    )


class OnceAt(Strategy):
    """تُشير مرّةً واحدة عند شمعةٍ بعينها، بمستوياتٍ **تُملى عليها**."""

    def __init__(self, *, at: int, side: Side, stop: str, target: str) -> None:
        self.metadata = meta(f"ONCE_{side.value}")
        self.at = at
        self.side = side
        self.stop = D(stop)
        self.target = D(target)

    def evaluate(
        self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime
    ) -> Optional[Signal]:
        if len(bars) != self.at:
            return None
        return Signal(
            strategy_name=self.metadata.name, strategy_version="1.0.0", symbol=symbol,
            side=self.side, entry_price=quote.ask if self.side is Side.BUY else quote.bid,
            stop_price=self.stop, take_profit_price=self.target,
            generated_at_utc=now, rationale_ar="اختبار", invalidation_ar="اختبار",
            inputs_digest="test",
        )


def run(strategy: Strategy, bars: Sequence[Bar], **overrides):
    config = BacktestConfig(
        size=D("100"),
        # قيمٌ **مخالفة عمداً** لمستويات الإشارة: لو استعملها المحرّك لظهر.
        stop_distance_pips=D("500"), take_profit_distance_pips=D("1000"),
        min_trades_for_conclusion=1, max_bars_in_trade=20,
    )
    config = BacktestConfig(**{**config.__dict__, **overrides})
    return Backtester(cost_model=cost_model(), config=config).run(
        strategy, list(bars), symbol="EURUSD"
    )


# ---------------------------------------------------------------------------
# ١ · المستويات تُقرأ من الإشارة
# ---------------------------------------------------------------------------

def test_the_stop_comes_from_the_signal_not_from_the_configuration():
    """
    **العطل بعينه.** الإعداد يقول ٥٠٠ نقطة والإشارة تقول ٢٠، والسوق يهبط ٢٥
    نقطة. فإن قُرئ الإعداد لم تُغلق الصفقة أصلاً؛ وإن قُرئت الإشارة أُغلقت
    على الوقف.
    """
    bars = flat_bars(50)
    # الشمعة التالية للإشارة تهبط إلى 1.0975 — تحت وقف الإشارة (1.0980).
    bars.append(Bar(
        symbol="EURUSD", start_utc=T0 + timedelta(hours=50),
        open=D("1.1000"), high=D("1.1001"), low=D("1.0975"), close=D("1.0980"),
        volume=D("1000"), source=DataSource.HISTORICAL,
    ))
    bars += flat_bars(5, "1.0980")

    result = run(OnceAt(at=50, side=Side.BUY, stop="1.0980", target="1.1200"), bars)
    assert result.trade_count == 1
    trade = result.trades[0]
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == D("1.0980"), "خرج على مستوىً غير الذي طلبته الإشارة"


def test_the_target_comes_from_the_signal_too():
    bars = flat_bars(50)
    bars.append(Bar(
        symbol="EURUSD", start_utc=T0 + timedelta(hours=50),
        open=D("1.1000"), high=D("1.1030"), low=D("1.0999"), close=D("1.1025"),
        volume=D("1000"), source=DataSource.HISTORICAL,
    ))
    bars += flat_bars(5, "1.1025")

    result = run(OnceAt(at=50, side=Side.BUY, stop="1.0900", target="1.1020"), bars)
    assert result.trades[0].exit_reason is ExitReason.TAKE_PROFIT
    assert result.trades[0].exit_price == D("1.1020")


# ---------------------------------------------------------------------------
# ٢ · البيع يُقرأ بيعاً
# ---------------------------------------------------------------------------

def test_a_sell_signal_profits_when_the_market_falls():
    """
    **الأخطر.** إشارة بيع تُقرأ بمنطق شراء تعكس كل ربحٍ وخسارة. ولم يظهر
    العطل قطّ لأن `v1` كانت شراءً فقط — ثم صارت `v2` ثنائية الاتجاه، فكان
    سيظهر **كأداءٍ عشوائي** لا كخطأ في المحرّك.
    """
    bars = flat_bars(50)
    bars.append(Bar(
        symbol="EURUSD", start_utc=T0 + timedelta(hours=50),
        open=D("1.1000"), high=D("1.1001"), low=D("1.0970"), close=D("1.0975"),
        volume=D("1000"), source=DataSource.HISTORICAL,
    ))
    bars += flat_bars(5, "1.0975")

    result = run(OnceAt(at=50, side=Side.SELL, stop="1.1100", target="1.0980"), bars)
    assert result.trade_count == 1
    trade = result.trades[0]
    assert trade.exit_reason is ExitReason.TAKE_PROFIT, "الهدف تحت الدخول في البيع"
    assert trade.gross_pnl > 0, "بيعٌ في سوقٍ هابط خرج بخسارة — الاتجاه معكوس"


def test_a_sell_signal_loses_when_the_market_rises():
    bars = flat_bars(50)
    bars.append(Bar(
        symbol="EURUSD", start_utc=T0 + timedelta(hours=50),
        open=D("1.1000"), high=D("1.1120"), low=D("1.0999"), close=D("1.1100"),
        volume=D("1000"), source=DataSource.HISTORICAL,
    ))
    bars += flat_bars(5, "1.1100")

    result = run(OnceAt(at=50, side=Side.SELL, stop="1.1100", target="1.0800"), bars)
    trade = result.trades[0]
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.gross_pnl < 0


def test_slippage_hurts_both_directions():
    """
    الانزلاق يرفع سعر الشراء ويخفض سعر البيع — يضرّ في الجهتين. وتطبيقه في
    جهةٍ واحدة يجعل **نصف الصفقات تربح منه**، فيُجمَّل الأداء بلا سبب.
    """
    bars = flat_bars(52)
    buy = run(OnceAt(at=50, side=Side.BUY, stop="1.0900", target="1.1200"), bars)
    sell = run(OnceAt(at=50, side=Side.SELL, stop="1.1200", target="1.0900"), bars)
    assert buy.trades and sell.trades
    open_price = bars[51].open
    assert buy.trades[0].entry_price > open_price, "الشراء لم يدفع الانزلاق"
    assert sell.trades[0].entry_price < open_price, "البيع رَبِح من الانزلاق"


# ---------------------------------------------------------------------------
# ٣ · التكلفة تُحسب على المسافة الحقيقية
# ---------------------------------------------------------------------------

def test_costs_are_computed_from_the_actual_distance_not_the_configured_one():
    """
    تكلفة الصفقة تُقدَّر من مسافة وقفها وهدفها. وحسابها على مسافةٍ من
    الإعداد يعطي تكلفةً لا علاقة لها بالصفقة الواقعة.
    """
    bars = flat_bars(50)
    bars.append(Bar(
        symbol="EURUSD", start_utc=T0 + timedelta(hours=50),
        open=D("1.1000"), high=D("1.1001"), low=D("1.0975"), close=D("1.0980"),
        volume=D("1000"), source=DataSource.HISTORICAL,
    ))
    bars += flat_bars(5, "1.0980")

    narrow = run(OnceAt(at=50, side=Side.BUY, stop="1.0980", target="1.1200"), bars)
    assert narrow.trades[0].costs > 0
    # التكلفة سبريد وانزلاق: لا تعتمد على ٥٠٠ نقطة المعطاة في الإعداد.
    assert narrow.trades[0].costs < D("1.00")
