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
        if symbol not in self.metadata.markets:
            return None
        if len(bars) < self.metadata.min_bars_required:
            return None

        prices = closes(bars)
        fast = ema(prices, FAST)
        slow = ema(prices, SLOW)
        volatility = atr(bars, ATR_PERIOD)
        strength = adx(bars, ATR_PERIOD)
        if fast is None or slow is None or volatility is None or strength is None:
            return None
        if volatility <= 0:
            return None

        # --- حارس الظرف: يُفحَص **قبل** أي شرط دخول ----------------------
        # ترتيبه مقصود: لو فُحص أخيراً لقرأ القارئ شروط الدخول ظانّاً أنها
        # الحاكمة، وهي ليست كذلك — الظرف يحكم قبلها.
        if strength <= TRENDING_ADX:
            return None

        last = bars[-1]
        long = fast > slow
        if long:
            if not (last.close > slow and last.low <= fast and last.close > fast):
                return None
            entry = quote.ask
            stop = entry - ATR_STOP * volatility
            target = entry + ATR_TARGET * volatility
            side = Side.BUY
            touch = last.low
        else:
            if not (last.close < slow and last.high >= fast and last.close < fast):
                return None
            entry = quote.bid
            stop = entry + ATR_STOP * volatility
            target = entry - ATR_TARGET * volatility
            side = Side.SELL
            touch = last.high

        if not sane_levels(entry=entry, stop=stop, target=target, long=long):
            return None

        direction_ar = "صاعد" if long else "هابط"
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
        )
