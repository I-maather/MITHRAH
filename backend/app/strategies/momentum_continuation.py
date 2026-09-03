"""
MOMENTUM_CONTINUATION — اختراق قناة دونتشيان **داخل اتجاه**، على الساعة.

الحالة: `RESEARCH`. لا اعتماد ولا تشغيل حقيقي قبل دليل.

## موضعها من المكتبة — ولماذا ليست تكراراً

| الفكرة | الظرف | لحظة الدخول |
|---|---|---|
| `TREND_PULLBACK` | اتجاهٌ ممتدّ | **بعد ارتداد** نحو المتوسط |
| `BREAKOUT_RETEST` | ضغطٌ ثم اتّساع | بعد الاختراق و**عودةٍ تختبره** |
| `RANGE_MEAN_REVERSION` | سوقٌ عرضي | عند **طرف** النطاق |
| `MOMENTUM_CONTINUATION` | اتجاهٌ ممتدّ | **على الاختراق نفسه**، بلا انتظار |

الفرق عن `BREAKOUT_RETEST` ليس في العتبة بل في **الحدث**: تلك تنتظر عودةً
تختبر المستوى، وهذه تدخل على الإغلاق الأوّل خارج القناة. والانتظار يرفع
الجودة ويخفض التواتر؛ وتركُه يعكس المقايضة. فوجودهما معاً يقيس المقايضة
نفسها بدل أن يفترضها.

## الفرضية القابلة للتكذيب

> في اتجاهٍ مؤكَّد (ADX فوق 25 وEMA10 في جهة EMA30)، الإغلاقُ خارج أعلى
> (أو أدنى) عشرين شمعة يمتدّ في جهته بنسبة أعلى من الصدفة.

**وما يكذّبها:** معدّل فوزٍ لا يتجاوز حدّ التعادل بدلالةٍ إحصائية بعد
تصحيح المقارنات المتعدّدة، أو صافٍ سالب.

## الأرقام وسببُ اختيارها — **قبل أي قياس**

| المعلمة | القيمة | لماذا |
|---|---|---|
| القناة | ٢٠ شمعة | اصطلاح دونتشيان الشائع (سلاحف السوق) |
| حارس الاتجاه | ADX14 > 25 | العتبة نفسها المستعملة في `TREND_PULLBACK v2` |
| الوقف | 1.5×ATR14 | مطابقٌ لاستراتيجية الاتجاه — فلا يختلط أثر الوقف بأثر الفكرة |
| الهدف | 3.0×ATR14 | نسبةٌ ٢ قبل التكاليف |

**ولم تُعايَر واحدةٌ منها على البيانات.** والوقفُ والهدف مطابقان عمداً
لـ`TREND_PULLBACK v2`: المتغيّر الوحيد بين الفكرتين هو **لحظة الدخول**،
فيُنسَب الفرقُ إليها.

## وما لا تفعله

لا تدخل على شمعةٍ لم تُغلق، ولا تدخل إن كان الاختراق قد وقع قبلها (فذلك
امتدادٌ لا إشارة)، ولا تُبيّت.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from ..contracts import Bar, Quote, Side, Signal, StrategyState
from .assessment import Recorder
from .base import Strategy, StrategyMetadata
from .fx_common import D, FX_MARKETS, TRENDING_ADX, closes, sane_levels
from .indicators import adx, atr, ema, highest_high, lowest_low

CHANNEL = 20
FAST = 10
SLOW = 30
ATR_PERIOD = 14
ATR_STOP = D("1.5")
ATR_TARGET = D("3.0")

MIN_BARS = max(CHANNEL + 2, SLOW, 2 * ATR_PERIOD + 1) + 5


class MomentumContinuation(Strategy):
    metadata = StrategyMetadata(
        name="MOMENTUM_CONTINUATION",
        version="1.0.0",
        hypothesis_ar=(
            "في اتجاهٍ مؤكَّد بـADX فوق 25 وEMA10 في جهة EMA30، الإغلاقُ خارج "
            "أعلى أو أدنى عشرين شمعة يمتدّ في جهته بنسبة أعلى من الصدفة."
        ),
        markets=FX_MARKETS,
        timeframe="1H",
        entry_conditions_ar=(
            "ADX14 فوق 25 — اتجاهٌ ممتدّ لا تذبذبٌ عرضي.",
            "EMA10 فوق EMA30 (شراء) أو تحته (بيع).",
            "إغلاق الشمعة الأخيرة فوق أعلى عشرين شمعة سابقة (شراء) أو تحت أدناها (بيع).",
            "الشمعة السابقة **داخل** القناة — أي أن هذا هو الاختراق لا امتداده.",
            "ATR14 موجب.",
        ),
        exit_conditions_ar=(
            "وقفٌ عند الدخول ∓ 1.5×ATR14.",
            "هدفٌ عند الدخول ± 3.0×ATR14 — نسبة ٢ قبل التكاليف.",
            "لا مبيت.",
        ),
        invalidations_ar=(
            "إغلاقٌ عائدٌ داخل القناة يلغي الاختراق.",
            "هبوط ADX تحت 25 يخرجها من ظرفها.",
            "تقاطع EMA10 مع EMA30 عكسياً يلغي الاتجاه.",
        ),
        min_bars_required=MIN_BARS,
        assumed_costs_ar=(
            "سبريد كابيتال المقيس ذهاباً وإياباً + احتياطي انزلاق نقطة. "
            "ولا عمولة على عقود الفروقات."
        ),
        no_trade_conditions_ar=(
            "ADX دون 25 — الظرف ليس ظرفها.",
            "المتوسطان متعاكسان مع جهة الاختراق.",
            "الإغلاق داخل القناة.",
            "الاختراق وقع في شمعةٍ سابقة — امتدادٌ لا إشارة.",
            "بيانات ناقصة أو ATR صفر.",
        ),
        state=StrategyState.RESEARCH,
        changelog_ar=(
            "1.0.0 — الإصدار الأول. الوقف والهدف مطابقان لـTREND_PULLBACK v2 "
            "عمداً، فالمتغيّر الوحيد لحظةُ الدخول.",
        ),
        backtest_evidence_ar="لا يوجد — تُقاس في مسح التاريخ. لا اعتماد بدونه.",
        walkforward_evidence_ar="لا يوجد.",
    )

    def evaluate(
        self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime
    ) -> Optional[Signal]:
        return self.assess(symbol=symbol, bars=bars, quote=quote, now=now).signal

    def assess(self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime):
        record = Recorder()
        if symbol not in self.metadata.markets:
            return record.fail("الأداة", f"{symbol} خارج أسواق هذه الاستراتيجية.")
        if len(bars) < self.metadata.min_bars_required:
            return record.fail(
                "البيانات",
                f"{len(bars)} شمعة أقلّ من {self.metadata.min_bars_required}.",
            )

        prices = closes(bars)
        fast = ema(prices, FAST)
        slow = ema(prices, SLOW)
        strength = adx(bars, ATR_PERIOD)
        volatility = atr(bars, ATR_PERIOD)
        if fast is None or slow is None or strength is None or volatility is None:
            return record.fail("المؤشرات", "أحد المؤشرات غير محسوب.")
        if volatility <= 0:
            return record.fail("التقلّب", "ATR14 صفر — لا تقلّب قابل للقياس.")

        if strength <= TRENDING_ADX:
            return record.fail(
                "قوة الاتجاه",
                f"ADX14 = {strength:.1f} ليس فوق {TRENDING_ADX} — سوقٌ بلا اتجاه ممتدّ.",
            )
        record.ok("قوة الاتجاه", f"ADX14 = {strength:.1f} فوق {TRENDING_ADX}.")

        # **القناة تُحسَب على ما قبل الشمعة الأخيرة.** إدراجُها في مدى
        # القناة يجعل «الإغلاق فوق الأعلى» شبه مستحيل — ويُقرأ الصمتُ
        # الناتج «لا فرص»، وهو خطأ حساب لا حالة سوق.
        prior = bars[:-1]
        top = highest_high(prior, CHANNEL)
        bottom = lowest_low(prior, CHANNEL)
        if top is None or bottom is None or top <= bottom:
            return record.fail("القناة", "قناة دونتشيان غير محسوبة.")
        record.ok("القناة", f"{bottom:.5f} — {top:.5f} على {CHANNEL} شمعة.")

        last = bars[-1]
        previous = bars[-2]
        up = fast > slow
        if last.close > top and up:
            if previous.close > top:
                return record.fail(
                    "الاختراق",
                    f"الشمعة السابقة أُغلقت أيضاً فوق القناة ({previous.close:.5f}) "
                    "— امتدادٌ لا اختراق.",
                )
            long, side = True, Side.BUY
            entry = quote.ask
            stop = entry - ATR_STOP * volatility
            target = entry + ATR_TARGET * volatility
        elif last.close < bottom and not up:
            if previous.close < bottom:
                return record.fail(
                    "الاختراق",
                    f"الشمعة السابقة أُغلقت أيضاً تحت القناة ({previous.close:.5f}) "
                    "— امتدادٌ لا اختراق.",
                )
            long, side = False, Side.SELL
            entry = quote.bid
            stop = entry + ATR_STOP * volatility
            target = entry - ATR_TARGET * volatility
        else:
            return record.fail(
                "الاختراق",
                f"الإغلاق {last.close:.5f} داخل القناة "
                f"({bottom:.5f} — {top:.5f}) أو في جهةٍ تخالف "
                f"EMA10={fast:.5f} مقابل EMA30={slow:.5f}.",
            )

        record.ok(
            "الاتجاه",
            f"EMA10 = {fast:.5f} {'فوق' if up else 'تحت'} EMA30 = {slow:.5f}.",
        )
        if not sane_levels(entry=entry, stop=stop, target=target, long=long):
            return record.fail(
                "خطة الخروج",
                f"مستويات غير صالحة: دخول {entry:.5f} · وقف {stop:.5f} · هدف {target:.5f}.",
            )

        signal = Signal(
            strategy_name=self.metadata.name,
            strategy_version=self.metadata.version,
            symbol=symbol,
            side=side,
            entry_price=entry,
            stop_price=stop,
            take_profit_price=target,
            generated_at_utc=now,
            rationale_ar=(
                f"اتجاهٌ مؤكَّد: ADX14 = {strength:.1f}، وEMA10 = {fast:.5f} "
                f"{'فوق' if up else 'تحت'} EMA30 = {slow:.5f}. "
                f"إغلاق {last.close:.5f} {'فوق' if long else 'تحت'} قناة "
                f"{CHANNEL} شمعة ({bottom:.5f} — {top:.5f}) والسابقة داخلها. "
                f"ATR14 = {volatility:.5f} ⇒ وقف {stop:.5f} وهدف {target:.5f}."
            ),
            invalidation_ar=(
                "إغلاقٌ عائدٌ داخل القناة يلغي الاختراق، وهبوط ADX تحت "
                f"{TRENDING_ADX} يخرجها من ظرفها."
            ),
            inputs_digest=self.inputs_digest(symbol, bars),
        )
        return record.signal(signal)
