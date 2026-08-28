"""
TREND_PULLBACK v1 — الاستراتيجية الوحيدة المسجّلة، وحالتها RESEARCH وليست APPROVED.

فرضية قابلة للاختبار:
  في صندوق مؤشر عالي السيولة داخل اتجاه صاعد على الإطار اليومي،
  الارتداد الضحل نحو المتوسط المتحرك القصير يليه استئناف للاتجاه أكثر من الصدفة.

deterministic بالكامل: لا LLM، لا عشوائية، لا بيانات خارجية غير الشموع والسعر.

⚠️ الحالة: RESEARCH — لم تجتز بوابة الاعتماد (لا Backtest ولا Walk-forward بعد).
    الـpipeline لن يشغّلها في وضع الإنتاج. انظر docs/STRATEGY_APPROVAL.md.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from ..contracts import Bar, Quote, Signal, Side, StrategyState
from ..money import D
from .base import Strategy, StrategyMetadata

FAST_PERIOD = 10
SLOW_PERIOD = 30
ATR_PERIOD = 14
ATR_STOP_MULTIPLE = D("1.5")
ATR_TARGET_MULTIPLE = D("3.0")   # يعطي R:R = 2.0 قبل التكاليف
MIN_BARS = SLOW_PERIOD + ATR_PERIOD + 2


def sma(values: Sequence[Decimal], period: int) -> Optional[Decimal]:
    if len(values) < period:
        return None
    return sum(values[-period:], Decimal("0")) / Decimal(period)


def average_true_range(bars: Sequence[Bar], period: int) -> Optional[Decimal]:
    if len(bars) < period + 1:
        return None
    trs: list[Decimal] = []
    for prev, cur in zip(bars[-(period + 1):-1], bars[-period:]):
        tr = max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
        trs.append(tr)
    return sum(trs, Decimal("0")) / Decimal(period)


class TrendPullbackV1(Strategy):
    metadata = StrategyMetadata(
        name="TREND_PULLBACK",
        version="1.0.0",
        hypothesis_ar=(
            "داخل اتجاه صاعد محدد بـSMA10 فوق SMA30، الارتداد الذي يلامس SMA10 "
            "دون كسر SMA30 يُستأنف صعوداً بنسبة أعلى من الصدفة."
        ),
        markets=("SPY", "QQQ", "IVV"),
        timeframe="1D",
        entry_conditions_ar=(
            "SMA10 > SMA30 على آخر شمعة مغلقة (اتجاه صاعد).",
            "إغلاق آخر شمعة أعلى من SMA30 (لم يُكسر الاتجاه).",
            "أدنى سعر في آخر شمعة لامس أو اخترق SMA10 لأسفل (ارتداد فعلي).",
            "إغلاق آخر شمعة أعلى من SMA10 (رفض الارتداد).",
            "ATR14 > 0 (تقلب قابل للقياس).",
        ),
        exit_conditions_ar=(
            "وقف خسارة أولي عند الدخول − 1.5×ATR14.",
            "هدف عند الدخول + 3.0×ATR14.",
            "إغلاق إجباري قبل نهاية الجلسة — لا مراكز عبر الليل في V1.",
        ),
        invalidations_ar=(
            "إغلاق تحت SMA30 يلغي الفرضية.",
            "SMA10 يهبط تحت SMA30 يلغي الاتجاه.",
        ),
        min_bars_required=MIN_BARS,
        assumed_costs_ar="عمولة IBKR Pro ذهاباً وإياباً + سبريد كامل + 5 نقاط أساس انزلاق لكل ساق.",
        no_trade_conditions_ar=(
            "بيانات ناقصة أو أقل من الحد الأدنى للشموع.",
            "ATR = 0 أو غير قابل للحساب.",
            "الستوب المحسوب يقع فوق سعر الدخول أو عند صفر.",
        ),
        state=StrategyState.RESEARCH,
        changelog_ar=("1.0.0 — الإصدار الأول، لم يُعتمد بعد.",),
        backtest_evidence_ar="لا يوجد — لم يُشغَّل Backtest بعد. الاستراتيجية لا يمكن اعتمادها بدونه.",
        walkforward_evidence_ar="لا يوجد.",
    )

    def evaluate(self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime) -> Optional[Signal]:
        if symbol not in self.metadata.markets:
            return None
        if len(bars) < self.metadata.min_bars_required:
            return None

        closes = [b.close for b in bars]
        fast = sma(closes, FAST_PERIOD)
        slow = sma(closes, SLOW_PERIOD)
        atr = average_true_range(bars, ATR_PERIOD)
        if fast is None or slow is None or atr is None or atr <= 0:
            return None

        last = bars[-1]

        if not (fast > slow):
            return None
        if not (last.close > slow):
            return None
        if not (last.low <= fast):
            return None
        if not (last.close > fast):
            return None

        entry = quote.ask
        stop = entry - (ATR_STOP_MULTIPLE * atr)
        target = entry + (ATR_TARGET_MULTIPLE * atr)
        if stop <= 0 or stop >= entry:
            return None

        return Signal(
            strategy_name=self.metadata.name,
            strategy_version=self.metadata.version,
            symbol=symbol,
            side=Side.BUY,
            entry_price=entry,
            stop_price=stop,
            take_profit_price=target,
            generated_at_utc=now,
            rationale_ar=(
                f"اتجاه صاعد (SMA10 {fast:.2f} فوق SMA30 {slow:.2f})، "
                f"ارتداد لامس SMA10 عند {last.low:.2f} ثم أُغلق فوقه عند {last.close:.2f}. "
                f"ATR14 = {atr:.2f}، وقف عند {stop:.2f} وهدف عند {target:.2f}."
            ),
            invalidation_ar="إغلاق تحت SMA30 أو هبوط SMA10 تحت SMA30 يلغي الفرضية.",
            inputs_digest=self.inputs_digest(symbol, bars),
        )
