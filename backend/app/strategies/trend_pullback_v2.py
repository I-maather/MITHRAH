"""
TREND_PULLBACK v2 — ارتدادٌ داخل اتجاه، **على الفوركس وفي الاتجاهين**.

الحالة: `RESEARCH`. لا Backtest بعد، فلا يشغّلها الخط (`runner.py` يقبل
`APPROVED` وحدها).

## ما تغيّر عن v1، ولماذا

| | v1 | v2 |
|---|---|---|
| الأسواق | `SPY · QQQ · IVV` | الأربع المكتشفة — **v1 ترفض EURUSD في أول سطر** |
| الاتجاه | شراء فقط | شراء وبيع — الفوركس متماثل، وترك نصف الفرص بلا سبب |
| حارس الظرف | **لا شيء** | `ADX > 25` |
| المتوسط | `SMA` | `EMA` — يستجيب لانعطاف الاتجاه أسرع |
| التكلفة المفترضة | عمولة IBKR على الأسهم | سبريد كابيتال على CFD |

**وأهمّها الثالث.** v1 تدخل في أي سوق: لا شيء فيها يسأل «أهذا اتجاهٌ ممتدّ
أم تذبذبٌ عرضي؟». وارتدادٌ نحو المتوسط في سوقٍ عرضي ليس ارتداداً — هو نصف
الذبذبة، وشراؤه شراءٌ عند القمة الصغرى في نصف الحالات.

## الفرضية القابلة للتكذيب

> داخل اتجاهٍ مؤكَّد بـ`ADX > 25` و`EMA10` فوق `EMA30`، الارتدادُ الذي يلامس
> `EMA10` دون كسر `EMA30` يُستأنف في اتجاه الاتجاه بنسبةٍ أعلى من الصدفة.

**وما يكذّبها:** معدّل فوزٍ لا يتجاوز معدّل التعادل خارج العيّنة بدلالة
إحصائية. لا «شعورٌ بأنها تعمل».
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ..contracts import Bar, Quote, Side, Signal, StrategyState
from .base import Strategy, StrategyMetadata
from .assessment import Assessment, Recorder
from .fx_common import D, FX_MARKETS, TRENDING_ADX, closes, sane_levels
from .indicators import adx, atr, ema

FAST = 10
SLOW = 30
ATR_PERIOD = 14
ATR_STOP = D("1.5")
ATR_TARGET = D("3.0")

#: تنعيمٌ فوق تنعيم في ADX يحتاج ضعف المدة، والبطيء يحتاج مدّته. والأكبر يحكم.
MIN_BARS = max(SLOW, 2 * ATR_PERIOD + 1) + 5


class TrendPullbackV2(Strategy):
    metadata = StrategyMetadata(
        name="TREND_PULLBACK",
        version="2.0.0",
        hypothesis_ar=(
            "داخل اتجاهٍ مؤكَّد بـADX فوق 25 وEMA10 في جهة EMA30، الارتدادُ "
            "الذي يلامس EMA10 دون كسر EMA30 يُستأنف في اتجاه الاتجاه بنسبة "
            "أعلى من الصدفة — صعوداً كان أو هبوطاً."
        ),
        markets=FX_MARKETS,
        timeframe="1D",
        entry_conditions_ar=(
            "ADX14 فوق 25 — سوقٌ ذو اتجاه، لا تذبذبٌ عرضي.",
            "EMA10 فوق EMA30 (شراء) أو تحته (بيع).",
            "إغلاق آخر شمعة في جهة EMA30 — الاتجاه لم يُكسر.",
            "الشمعة لامست EMA10 من الجهة المقابلة — ارتدادٌ فعلي وقع.",
            "إغلاق الشمعة عاد إلى جهة EMA10 — الارتداد رُفض.",
            "ATR14 موجب — تقلّبٌ قابل للقياس.",
        ),
        exit_conditions_ar=(
            "وقفٌ عند الدخول ∓ 1.5×ATR14.",
            "هدفٌ عند الدخول ± 3.0×ATR14 — نسبة 2.0 قبل التكاليف.",
            "لا مبيت: تُغلق قبل نهاية الجلسة.",
        ),
        invalidations_ar=(
            "إغلاق في الجهة المقابلة لـEMA30 يلغي الفرضية.",
            "تقاطع EMA10 مع EMA30 عكسياً يلغي الاتجاه.",
            "هبوط ADX تحت 25 يخرجها من ظرفها فلا تُشير.",
        ),
        min_bars_required=MIN_BARS,
        assumed_costs_ar=(
            "سبريد كابيتال ذهاباً وإياباً على CFD بلا عمولة، زائد احتياطي "
            "انزلاق. **لا عمولة لكل أمر** — وهو ما كانت v1 تفترضه خطأً."
        ),
        no_trade_conditions_ar=(
            "ADX تحت 25 — الظرف ليس ظرفها.",
            "بيانات ناقصة أو أقل من الحد الأدنى للشموع.",
            "ATR صفر أو غير محسوب.",
            "مستويات غير منطقية (وقفٌ في جهة الهدف).",
        ),
        state=StrategyState.RESEARCH,
        changelog_ar=(
            "2.0.0 — الفوركس، اتجاهان، حارس ADX، EMA بدل SMA، تكلفة CFD.",
        ),
        backtest_evidence_ar="لا يوجد — لم يُشغَّل بعد. لا اعتماد بدونه.",
        walkforward_evidence_ar="لا يوجد.",
    )

    def evaluate(
        self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime
    ) -> Optional[Signal]:
        """القرار وحده — **لم يتغيّر حرفاً**. التشخيص في `assess`."""
        return self.assess(symbol=symbol, bars=bars, quote=quote, now=now).signal

    def assess(
        self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime
    ) -> Assessment:
        """
        نفس القرار، **ومعه سببه بالأرقام**.

        كان كل رفضٍ هنا `return None` مجرّداً، فيصل إلى المالكة «لا توجد
        فرصة» سواء كان ADX عند 24.9 أو عند 8. والفرق بينهما هو الفرق بين
        «انتظري» و«هذه الاستراتيجية لا تناسب هذا السوق».
        """
        r = Recorder()
        if symbol not in self.metadata.markets:
            return r.fail("الأداة", f"{symbol} ليس من أسواق هذه الاستراتيجية.")
        if len(bars) < self.metadata.min_bars_required:
            return r.fail(
                "عدد الشموع",
                f"{len(bars)} شمعة، والمطلوب {self.metadata.min_bars_required}.",
            )

        prices = closes(bars)
        fast = ema(prices, FAST)
        slow = ema(prices, SLOW)
        volatility = atr(bars, ATR_PERIOD)
        strength = adx(bars, ATR_PERIOD)
        if fast is None or slow is None or volatility is None or strength is None:
            return r.fail("المؤشرات", "تعذّر حساب EMA أو ATR أو ADX من هذه الشموع.")
        if volatility <= 0:
            return r.fail("التقلّب", f"ATR14 = {volatility} — لا تقلّب يُقاس عليه وقف.")
        r.ok("المؤشرات", f"EMA10 = {fast:.5f} · EMA30 = {slow:.5f} · ATR14 = {volatility:.5f}")

        # --- حارس الظرف: يُفحَص **قبل** أي شرط دخول ----------------------
        # ترتيبه مقصود: لو فُحص أخيراً لقرأ القارئ شروط الدخول ظانّاً أنها
        # الحاكمة، وهي ليست كذلك — الظرف يحكم قبلها.
        if strength <= TRENDING_ADX:
            return r.fail(
                "الظرف",
                f"ADX14 = {strength:.1f} دون {TRENDING_ADX} — سوقٌ متذبذب لا متّجه.",
            )
        r.ok("الظرف", f"ADX14 = {strength:.1f} فوق {TRENDING_ADX} — اتجاهٌ مؤكَّد.")

        last = bars[-1]
        long = fast > slow
        direction_ar = "صاعد" if long else "هابط"
        r.ok("الاتجاه", f"{direction_ar} — EMA10 {'فوق' if long else 'تحت'} EMA30.")
        if long:
            if not last.close > slow:
                return r.fail("سلامة الاتجاه", f"الإغلاق {last.close:.5f} تحت EMA30 — الاتجاه مكسور.")
            if not last.low <= fast:
                return r.fail(
                    "الارتداد",
                    f"أدنى الشمعة {last.low:.5f} لم يبلغ EMA10 {fast:.5f} — لا ارتداد وقع.",
                )
            if not last.close > fast:
                return r.fail(
                    "رفض الارتداد",
                    f"الإغلاق {last.close:.5f} تحت EMA10 {fast:.5f} — الارتداد لم يُرفَض.",
                )
            entry = quote.ask
            stop = entry - ATR_STOP * volatility
            target = entry + ATR_TARGET * volatility
            side = Side.BUY
            touch = last.low
        else:
            if not last.close < slow:
                return r.fail("سلامة الاتجاه", f"الإغلاق {last.close:.5f} فوق EMA30 — الاتجاه مكسور.")
            if not last.high >= fast:
                return r.fail(
                    "الارتداد",
                    f"أعلى الشمعة {last.high:.5f} لم يبلغ EMA10 {fast:.5f} — لا ارتداد وقع.",
                )
            if not last.close < fast:
                return r.fail(
                    "رفض الارتداد",
                    f"الإغلاق {last.close:.5f} فوق EMA10 {fast:.5f} — الارتداد لم يُرفَض.",
                )
            entry = quote.bid
            stop = entry + ATR_STOP * volatility
            target = entry - ATR_TARGET * volatility
            side = Side.SELL
            touch = last.high
        r.ok("الارتداد", f"لمست الشمعة EMA10 ثم أُغلقت في جهته — ارتدادٌ مرفوض.")

        if not sane_levels(entry=entry, stop=stop, target=target, long=long):
            return r.fail(
                "المستويات",
                f"دخول {entry:.5f} · وقف {stop:.5f} · هدف {target:.5f} — ترتيبٌ غير منطقي.",
            )
        r.ok("المستويات", f"دخول {entry:.5f} · وقف {stop:.5f} · هدف {target:.5f}")

        return r.signal(Signal(
            strategy_name=self.metadata.name,
            strategy_version=self.metadata.version,
            symbol=symbol,
            side=side,
            entry_price=entry,
            stop_price=stop,
            take_profit_price=target,
            generated_at_utc=now,
            rationale_ar=(
                f"اتجاه {direction_ar} مؤكَّد: ADX14 = {strength:.1f} فوق 25، "
                f"وEMA10 = {fast:.5f} مقابل EMA30 = {slow:.5f}. "
                f"ارتدادٌ لامس EMA10 عند {touch:.5f} ثم أُغلق عند {last.close:.5f} "
                f"في جهة الاتجاه. ATR14 = {volatility:.5f} ⇒ وقف {stop:.5f} "
                f"وهدف {target:.5f}."
            ),
            invalidation_ar=(
                f"إغلاقٌ في الجهة المقابلة لـEMA30 ({slow:.5f})، أو تقاطع "
                f"EMA10 عكسياً، أو هبوط ADX تحت 25 — أيٌّ منها يلغي الفرضية."
            ),
            inputs_digest=self.inputs_digest(symbol, bars),
        ))
