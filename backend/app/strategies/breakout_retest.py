"""
BREAKOUT_RETEST — اختراقٌ بعد ضغط، **ثم إعادة اختبار**.

الحالة: `RESEARCH`.

## لماذا «بعد إعادة الاختبار» لا «على الاختراق»

الدخول على الاختراق نفسه أشهر طريقةٍ لخسارة المال في هذه الفكرة: أغلب
الاختراقات كاذبة، والشمعة التي تخترق هي أسوأ سعرٍ في اليوم غالباً — تدخل
عند القمة ثم يعود السعر.

فهذه تنتظر ما بعده: اختراقٌ وقع، ثم **عاد السعر يلمس مستوى الاختراق ولم
يكسره**. وذلك يحوّل المقاومة المكسورة إلى دعمٍ مُختبَر — والدخول عندها
أقرب إلى الوقف، فالمخاطرة أصغر والنسبة أفضل.

والثمن: **فرصٌ ضائعة**. اختراقٌ ينطلق بلا عودة لا تدخله هذه الاستراتيجية
أبداً. وهذا مقصود: تركُ فرصةٍ أرخص من دخولٍ سيّئ.

## الفرضية القابلة للتكذيب

> بعد ضغطٍ في التقلّب (عرض بولنجر في أدنى ربعٍ من نطاقه)، الاختراقُ الذي
> يُعاد اختباره ولا يُكسَر يمتدّ في اتجاهه بنسبةٍ أعلى من الصدفة.

## وظرفها ليس ADX

الاختراق يقع **عند الانتقال** من عرضيٍّ إلى ذي اتجاه — أي حين لا يكون ADX
قد ارتفع بعد ولا هو منخفضٌ استقراراً. فحارسها **ضغطُ التقلّب** قبله
واتّساعه بعده، لا قراءةُ ADX.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ..contracts import Bar, Quote, Side, Signal, StrategyState
from .base import Strategy, StrategyMetadata
from .fx_common import D, FX_MARKETS, closes, sane_levels
from .indicators import atr, bollinger, highest_high, lowest_low

RANGE_PERIOD = 20
BAND_PERIOD = 20
ATR_PERIOD = 14
ATR_STOP = D("1.2")
ATR_TARGET = D("2.4")

#: **نسبة الضغط.** عرض النطاق الحالي إلى أوسعِ عرضٍ في آخر خمسين شمعة.
#: تحت 0.5 يعني تقلّصاً حقيقياً لا هدوءاً عابراً.
SQUEEZE_RATIO = D("0.5")
SQUEEZE_LOOKBACK = 50

#: كم شمعة نسمح بها بين الاختراق وإعادة الاختبار. أطول من ذلك لا يكون
#: «إعادة اختبار» بل حركةٌ مستقلّة.
RETEST_WINDOW = 5

MIN_BARS = SQUEEZE_LOOKBACK + BAND_PERIOD + 5


class BreakoutRetest(Strategy):
    metadata = StrategyMetadata(
        name="BREAKOUT_RETEST",
        version="1.0.0",
        hypothesis_ar=(
            "بعد ضغطٍ في التقلّب، الاختراقُ الذي يُعاد اختباره ولا يُكسَر "
            "يمتدّ في اتجاهه بنسبة أعلى من الصدفة."
        ),
        markets=FX_MARKETS,
        timeframe="1D",
        entry_conditions_ar=(
            "ضغطٌ سابق: عرض بولنجر قبل الاختراق تحت نصف أوسع عرضٍ في خمسين شمعة.",
            "اختراقٌ وقع خلال آخر خمس شموع فوق أعلى النطاق أو تحت أدناه.",
            "إعادة اختبار: الشمعة الأخيرة لامست مستوى الاختراق ولم تُغلق خلفه.",
            "ATR14 موجب.",
        ),
        exit_conditions_ar=(
            "وقفٌ خلف مستوى الاختراق بـ1.2×ATR14 — خلف الدليل لا خلف الدخول.",
            "هدفٌ عند 2.4×ATR14 في اتجاه الاختراق.",
            "لا مبيت.",
        ),
        invalidations_ar=(
            "إغلاقٌ خلف مستوى الاختراق يلغي الفرضية — الاختراق كان كاذباً.",
            "مرور أكثر من خمس شموع بلا إعادة اختبار: الفرصة انتهت ولا تُلاحَق.",
        ),
        min_bars_required=MIN_BARS,
        assumed_costs_ar="سبريد كابيتال ذهاباً وإياباً، واحتياطي انزلاقٍ أوسع: الاختراقات تقع في لحظات اتساع السبريد.",
        no_trade_conditions_ar=(
            "لا ضغط سابق — اختراقٌ من سوقٍ متقلّب أصلاً ليس اختراقاً.",
            "لا اختراق في النافذة.",
            "لم تقع إعادة اختبار، أو أُغلقت الشمعة خلف المستوى.",
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

        volatility = atr(bars, ATR_PERIOD)
        if volatility is None or volatility <= 0:
            return None

        prices = closes(bars)

        # --- الضغط: يُقاس **قبل** الاختراق لا عنده ------------------------
        # قياسه على الشمعة الأخيرة يقرأ اتّساعاً وقع بالاختراق نفسه، فيقلب
        # الشرط رأساً على عقب: يُرفض كل اختراقٍ حقيقي ويُقبل الهادئ.
        before = prices[:-RETEST_WINDOW]
        squeeze_band = bollinger(before, BAND_PERIOD)
        if squeeze_band is None:
            return None
        widths = []
        for end in range(len(before) - SQUEEZE_LOOKBACK, len(before) + 1):
            window = before[:end]
            band = bollinger(window, BAND_PERIOD)
            if band is not None:
                widths.append(band.width)
        if not widths:
            return None
        widest = max(widths)
        if widest <= 0 or squeeze_band.width > widest * SQUEEZE_RATIO:
            return None

        # --- الاختراق: مستوىً من قبل النافذة، اختُرق داخلها ---------------
        prior = bars[:-RETEST_WINDOW]
        resistance = highest_high(prior, RANGE_PERIOD)
        support = lowest_low(prior, RANGE_PERIOD)
        if resistance is None or support is None:
            return None

        window_bars = bars[-RETEST_WINDOW:]
        last = bars[-1]
        broke_up = any(b.close > resistance for b in window_bars[:-1])
        broke_down = any(b.close < support for b in window_bars[:-1])
        if broke_up == broke_down:            # لا اختراق، أو اختراقان متضادّان
            return None

        if broke_up:
            # إعادة اختبار: لامست المستوى من فوق ولم تُغلق تحته.
            if not (last.low <= resistance and last.close > resistance):
                return None
            long = True
            level = resistance
            entry = quote.ask
            stop = level - ATR_STOP * volatility
            target = entry + ATR_TARGET * volatility
            side = Side.BUY
        else:
            if not (last.high >= support and last.close < support):
                return None
            long = False
            level = support
            entry = quote.bid
            stop = level + ATR_STOP * volatility
            target = entry - ATR_TARGET * volatility
            side = Side.SELL

        if not sane_levels(entry=entry, stop=stop, target=target, long=long):
            return None

        direction_ar = "صعودي" if long else "هبوطي"
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
                f"ضغطٌ سابق: عرض النطاق {squeeze_band.width:.5f} تحت نصف أوسعه "
                f"{widest:.5f}. اختراقٌ {direction_ar} لمستوى {level:.5f}، ثم "
                f"إعادة اختبار: الشمعة لامسته عند "
                f"{(last.low if long else last.high):.5f} وأُغلقت عند "
                f"{last.close:.5f} في جهة الاختراق. الوقف {stop:.5f} خلف "
                f"المستوى بـ1.2×ATR = {volatility:.5f}."
            ),
            invalidation_ar=(
                f"إغلاقٌ خلف {level:.5f} يعني اختراقاً كاذباً ويلغي الفرضية."
            ),
            inputs_digest=self.inputs_digest(symbol, bars),
        )
