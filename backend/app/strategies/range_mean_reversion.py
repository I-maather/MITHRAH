"""
RANGE_MEAN_REVERSION — تطرّفٌ يرتدّ إلى المتوسط، **في سوقٍ عرضي وحده**.

الحالة: `RESEARCH`.

## لماذا هذه الاستراتيجية موجودة أصلاً

`TREND_PULLBACK` تربح حين يمتدّ السوق وتخسر حين يتذبذب. وأسواق العملات
تقضي أكثر وقتها **عرضيةً** لا ممتدّة. فنظامٌ لا يملك إلا فكرة اتجاه يصمت
في أغلب الأيام، ثم يخسر في الأيام التي يتكلّم فيها بلا ظرفه.

وهذه فكرةٌ **معاكسة تماماً** لا نسخةٌ أخرى منها: تشتري الضعف وتبيع القوة،
حيث تفعل الأولى العكس. ولذلك تربح حين تصمت الأولى — وهو الغرض من وجود أكثر
من استراتيجية: **تغطيةٌ لا تكرار**.

## الفرضية القابلة للتكذيب

> في سوقٍ عرضي مؤكَّد بـ`ADX < 20`، الإغلاقُ خارج نطاق بولنجر مع `RSI` في
> منطقة تطرّفٍ يرتدّ نحو المتوسط بنسبةٍ أعلى من الصدفة.

## والخطر الذي تحمله في جوهرها

**بيعُ القوة وشراءُ الضعف يقف أمام الاتجاه.** فإن أخفق حارس `ADX` مرّةً
واحدة ودخلت في بداية اتجاهٍ حقيقي، تكون في الجهة الخاطئة منه تماماً. ولذلك
وقفها **أضيق** (1.0×ATR) وهدفها المتوسط نفسه لا امتدادٌ بعيد: فكرةٌ تعيش
على ارتداداتٍ صغيرة لا تحتمل خسارةً كبيرة واحدة.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ..contracts import Bar, Quote, Side, Signal, StrategyState
from .base import Strategy, StrategyMetadata
from .fx_common import D, FX_MARKETS, RANGING_ADX, closes, sane_levels
from .indicators import atr, adx, bollinger, rsi

BAND_PERIOD = 20
BAND_K = D("2")
RSI_PERIOD = 14
RSI_OVERSOLD = D("30")
RSI_OVERBOUGHT = D("70")
ATR_PERIOD = 14
ATR_STOP = D("1.0")

MIN_BARS = max(BAND_PERIOD, 2 * ATR_PERIOD + 1) + 5


class RangeMeanReversion(Strategy):
    metadata = StrategyMetadata(
        name="RANGE_MEAN_REVERSION",
        version="1.0.0",
        hypothesis_ar=(
            "في سوقٍ عرضي مؤكَّد بـADX تحت 20، الإغلاقُ خارج نطاق بولنجر مع "
            "RSI في منطقة تطرّف يرتدّ نحو المتوسط بنسبة أعلى من الصدفة."
        ),
        markets=FX_MARKETS,
        timeframe="1D",
        entry_conditions_ar=(
            "ADX14 تحت 20 — سوقٌ عرضي، لا اتجاهٌ ممتدّ.",
            "إغلاق تحت النطاق السفلي مع RSI تحت 30 (شراء)، أو فوق العلوي مع RSI فوق 70 (بيع).",
            "عرض النطاق موجب — تقلّبٌ قابل للقياس.",
            "الهدف (المتوسط) أبعد من الوقف — وإلا فالصفقة سالبة التوقّع بالبناء.",
        ),
        exit_conditions_ar=(
            "الهدف هو **متوسط النطاق نفسه** لا امتدادٌ بعيد.",
            "وقفٌ عند الدخول ∓ 1.0×ATR14 — أضيق من استراتيجية الاتجاه عمداً.",
            "لا مبيت.",
        ),
        invalidations_ar=(
            "ارتفاع ADX فوق 20 يخرجها من ظرفها.",
            "إغلاقٌ أبعد في الجهة نفسها يعني اتجاهاً لا تطرّفاً.",
        ),
        min_bars_required=MIN_BARS,
        assumed_costs_ar=(
            "سبريد كابيتال ذهاباً وإياباً. **والتكلفة هنا أثقل نسبياً** لأن "
            "الهدف أقرب: نفس السبريد على ربحٍ أصغر يأكل نسبةً أكبر منه."
        ),
        no_trade_conditions_ar=(
            "ADX فوق 20 — الظرف ليس ظرفها.",
            "لا تطرّف: الإغلاق داخل النطاق أو RSI معتدل.",
            "الهدف أقرب من الوقف — نسبة عائد دون الواحد.",
            "بيانات ناقصة أو ATR صفر.",
        ),
        state=StrategyState.RESEARCH,
        changelog_ar=("1.0.0 — الإصدار الأول. لم يُعتمد.",),
        backtest_evidence_ar="لا يوجد — لم يُشغَّل بعد. لا اعتماد بدونه.",
        walkforward_evidence_ar="لا يوجد.",
    )

    def evaluate(
        self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime
    ) -> Optional[Signal]:
        if symbol not in self.metadata.markets:
            return None
        if len(bars) < self.metadata.min_bars_required:
            return None

        prices = closes(bars)
        band = bollinger(prices, BAND_PERIOD, BAND_K)
        momentum = rsi(prices, RSI_PERIOD)
        volatility = atr(bars, ATR_PERIOD)
        strength = adx(bars, ATR_PERIOD)
        if band is None or momentum is None or volatility is None or strength is None:
            return None
        if volatility <= 0 or band.width <= 0:
            return None

        # حارس الظرف أوّلاً: هذه الفكرة تقف أمام الاتجاه، فدخولها في اتجاهٍ
        # حقيقي يضعها في الجهة الخاطئة منه تماماً.
        if strength >= RANGING_ADX:
            return None

        last = bars[-1]
        if last.close < band.lower and momentum < RSI_OVERSOLD:
            long = True
            entry = quote.ask
            stop = entry - ATR_STOP * volatility
            target = band.middle
            side = Side.BUY
        elif last.close > band.upper and momentum > RSI_OVERBOUGHT:
            long = False
            entry = quote.bid
            stop = entry + ATR_STOP * volatility
            target = band.middle
            side = Side.SELL
        else:
            return None

        if not sane_levels(entry=entry, stop=stop, target=target, long=long):
            return None

        # **فحصٌ خاصّ بهذه الفكرة.** الهدف متوسطٌ متحرّك لا مضاعفُ ATR، فقد
        # يقع أقرب من الوقف حين يكون المتوسط قريباً — فتصير الصفقة سالبة
        # التوقّع **بالبناء** لا بسوء الحظ. تُرفض ولا تُعدَّل مستوياتها.
        if abs(target - entry) <= abs(entry - stop):
            return None

        side_ar = "تحت النطاق السفلي" if long else "فوق النطاق العلوي"
        return Signal(
            strategy_name=self.metadata.name,
            strategy_version=self.metadata.version,
            symbol=symbol,
            side=side,
            entry_price=entry,
            stop_price=stop,
            take_profit_price=target,
            generated_at_utc=now,
            rationale_ar=(
                f"سوقٌ عرضي: ADX14 = {strength:.1f} تحت 20. "
                f"إغلاقٌ {side_ar} عند {last.close:.5f} "
                f"(النطاق {band.lower:.5f} — {band.upper:.5f}) "
                f"مع RSI14 = {momentum:.1f}. الهدف متوسط النطاق {band.middle:.5f}، "
                f"والوقف {stop:.5f} على بعد 1.0×ATR = {volatility:.5f}."
            ),
            invalidation_ar=(
                f"ارتفاع ADX فوق 20 يخرجها من ظرفها؛ وإغلاقٌ أبعد في الجهة "
                f"نفسها يعني اتجاهاً لا تطرّفاً."
            ),
            inputs_digest=self.inputs_digest(symbol, bars),
        )
