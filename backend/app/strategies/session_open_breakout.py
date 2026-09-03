"""
SESSION_OPEN_BREAKOUT — اختراق نطاق افتتاح الجلسة. **داخل اليوم.**

الحالة: `RESEARCH`. لا اعتماد ولا تشغيل حقيقي قبل دليل.

## لماذا وُجدت هذه الفكرة الآن

استراتيجيات المشروع الثلاث كلّها على الشمعة اليومية، وتواترُها المقيس
`0.03–0.07` صفقة في اليوم — أي **صفقةٌ كل أسبوعين إلى شهر**. وهدف المالكة
التشغيلي صفقةٌ مكتملة في كل يوم تداولٍ مؤهَّل. والفجوة ليست في السياسة ولا
في المخاطر: هي في **التغطية**.

وسببُ انحصارها في اليوم كان مكتوباً في `fx_common`: «أدنى مسافة وقف عند
الوسيط ١٠٠ نقطة، فوقفُ الساعة سُبعُها ⇒ التداول داخل اليوم ليس خياراً
هندسياً». وذلك **خطأ وحدة**: الحدّ `PERCENTAGE 0.01` = ١٫١٦ نقطة على
اليورو. فوقفُ ربع الساعة (نحو ست نقاط) فوق الحدّ بخمسة أضعاف.

⇒ الإطار الداخل-يومي مفتوحٌ هندسياً. وهذه فرضيةٌ فيه، تُقاس ولا تُعتمَد
بالرأي.

## الفرضية القابلة للتكذيب

> نطاق الساعة الأولى بعد افتتاح جلسةٍ رئيسية يحدّ توازناً مؤقّتاً؛
> والإغلاقُ خارجه داخل نافذة الجلسة يمتدّ في جهته بنسبة أعلى من الصدفة.

**وما يكذّبها:** معدّل فوزٍ لا يتجاوز حدّ التعادل خارج العيّنة بدلالة
إحصائية بعد تصحيح المقارنات المتعدّدة.

## الأرقام وسببُ اختيارها — **قبل أي قياس**

| المعلمة | القيمة | لماذا هذه بالذات |
|---|---|---|
| الجلسة | لندن 07:00 UTC | أعلى سيولةٍ في اليوم لأزواج اليورو والجنيه |
| طول النطاق | ٤ شمعات ربع ساعة = ساعة | الاصطلاح الشائع في Opening Range Breakout |
| نافذة الدخول | حتى 12:00 UTC | قبل افتتاح نيويورك، فلا تختلط جلستان في فرضيةٍ واحدة |
| الوقف | الطرف المقابل للنطاق | نقطةُ إبطالٍ **بنيوية** لا مضاعف تقلّب |
| الهدف | ٢× ارتفاع النطاق | نسبةٌ ٢ قبل التكاليف |
| حارس الاتّساع | ‎0.3×ATR ≤ النطاق ≤ 3×ATR | نطاقٌ ضيّقٌ جداً يُخترَق بالضجيج، وواسعٌ جداً يجعل الوقف أكبر من الميزانية |

**ولم تُعايَر واحدةٌ منها على البيانات.** هي اصطلاحات معلنة قبل القياس،
وذلك شرط أن تكون النتيجة اختباراً لا بحثاً عن رقمٍ يعجبنا.

## وما لا تفعله

لا تدخل قبل اكتمال النطاق، ولا بعد نافذتها، ولا مرّتين في اليوم نفسه —
والأخيرة تحرسها بوابة «أمر دخولٍ واحد لكل أداة في اليوم» في محرّك المخاطر،
وتحرسها هنا أيضاً بشرط أوّل إغلاقٍ خارج النطاق.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from ..contracts import Bar, Quote, Side, Signal, StrategyState
from .assessment import Recorder
from .base import Strategy, StrategyMetadata
from .fx_common import D, FX_MARKETS, sane_levels
from .indicators import atr

#: افتتاح جلسة لندن بالتوقيت العالمي.
SESSION_OPEN_HOUR = 7
#: طول نطاق الافتتاح بالدقائق.
RANGE_MINUTES = 60
#: آخر ساعةٍ يُسمح فيها بالدخول (UTC).
ENTRY_WINDOW_END_HOUR = 12
ATR_PERIOD = 14
MIN_RANGE_ATR = D("0.3")
MAX_RANGE_ATR = D("3")
TARGET_MULTIPLE = D("2")

MIN_BARS = max(2 * ATR_PERIOD + 1, 40)


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class SessionOpenBreakout(Strategy):
    metadata = StrategyMetadata(
        name="SESSION_OPEN_BREAKOUT",
        version="1.0.0",
        hypothesis_ar=(
            "نطاق الساعة الأولى بعد افتتاح جلسة لندن يحدّ توازناً مؤقّتاً، "
            "والإغلاقُ خارجه قبل افتتاح نيويورك يمتدّ في جهته بنسبة أعلى من الصدفة."
        ),
        markets=FX_MARKETS,
        timeframe="15M",
        entry_conditions_ar=(
            "الشمعة داخل نافذة 08:00–12:00 بالتوقيت العالمي.",
            "نطاق 07:00–08:00 مكتمل وله أعلى وأدنى.",
            "إغلاق الشمعة خارج النطاق — أعلى قمّته (شراء) أو أدنى قاعه (بيع).",
            "لم يقع إغلاقٌ خارج النطاق قبلها في هذه الجلسة — الدخول على الأوّل وحده.",
            "ارتفاع النطاق بين 0.3 و3.0 من ATR14 — لا ضجيجٌ ولا اتّساعٌ شاذّ.",
        ),
        exit_conditions_ar=(
            "الوقف عند الطرف المقابل للنطاق — نقطة الإبطال البنيوية.",
            "الهدف على بعد ٢× ارتفاع النطاق من الدخول.",
            "لا مبيت: الفرضية جلسةٌ واحدة.",
        ),
        invalidations_ar=(
            "إغلاقٌ عائدٌ داخل النطاق يلغي الاختراق.",
            "انتهاء نافذة الجلسة يلغي الفرضية لهذا اليوم.",
        ),
        min_bars_required=MIN_BARS,
        assumed_costs_ar=(
            "سبريد كابيتال المقيس ذهاباً وإياباً + احتياطي انزلاق نقطة. "
            "**والتكلفة هنا أثقل نسبياً**: الهدف أقصر من هدف اليوم، فنفس "
            "السبريد يأكل نسبةً أكبر من العائد."
        ),
        no_trade_conditions_ar=(
            "خارج نافذة الدخول.",
            "نطاق الافتتاح غير مكتمل أو صفري.",
            "النطاق أضيق من 0.3×ATR أو أوسع من 3×ATR.",
            "وقع اختراقٌ سابق في الجلسة نفسها.",
            "بيانات ناقصة أو ATR غير محسوب.",
        ),
        state=StrategyState.RESEARCH,
        changelog_ar=(
            "1.0.0 — الإصدار الأول. معلماتها اصطلاحية ومُعلَنة قبل أي قياس.",
        ),
        backtest_evidence_ar="لا يوجد — تُقاس في مسح التاريخ. لا اعتماد بدونه.",
        walkforward_evidence_ar="لا يوجد.",
    )

    # ------------------------------------------------------------------
    def _session_bars(self, bars: Sequence[Bar]) -> tuple[list[Bar], list[Bar]]:
        """
        يعيد (شمعات النطاق، شمعات ما بعده) **لجلسة الشمعة الأخيرة**.

        ويُقاس اليوم من الشمعة الأخيرة لا من ساعة النظام: تشغيلٌ على تاريخٍ
        يجب أن يعطي النتيجة نفسها في أي لحظةٍ يُشغَّل فيها.
        """
        last_day = _utc(bars[-1].start_utc).date()
        window = [b for b in bars if _utc(b.start_utc).date() == last_day]
        opening = [
            b for b in window
            if _utc(b.start_utc).hour == SESSION_OPEN_HOUR
        ]
        after = [
            b for b in window
            if SESSION_OPEN_HOUR < _utc(b.start_utc).hour < ENTRY_WINDOW_END_HOUR
        ]
        return opening, after

    def evaluate(
        self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime
    ) -> Optional[Signal]:
        return self.assess(symbol=symbol, bars=bars, quote=quote, now=now).signal

    def assess(self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime):
        record = Recorder()
        if symbol not in self.metadata.markets:
            return record.fail("الأداة", f"{symbol} خارج أسواق هذه الاستراتيجية.")
        if len(bars) < self.metadata.min_bars_required:
            return record.fail("البيانات", f"{len(bars)} شمعة أقلّ من {self.metadata.min_bars_required}.")

        volatility = atr(bars, ATR_PERIOD)
        if volatility is None or volatility <= 0:
            return record.fail("التقلّب", "ATR14 غير محسوب أو صفر.")

        opening, after = self._session_bars(bars)
        if not opening:
            return record.fail(
                "نطاق الافتتاح",
                f"لا شمعات في ساعة الافتتاح {SESSION_OPEN_HOUR}:00 من يوم الشمعة الأخيرة.",
            )
        if not after:
            return record.fail(
                "النافذة",
                f"الشمعة الأخيرة خارج نافذة الدخول "
                f"({SESSION_OPEN_HOUR + 1}:00–{ENTRY_WINDOW_END_HOUR}:00 UTC).",
            )

        high = max(b.high for b in opening)
        low = min(b.low for b in opening)
        height = high - low
        if height <= 0:
            return record.fail("النطاق", "ارتفاع نطاق الافتتاح صفر.")
        record.ok("نطاق الافتتاح", f"{low:.5f} — {high:.5f} (ارتفاع {height:.5f}).")

        if height < MIN_RANGE_ATR * volatility:
            return record.fail(
                "اتّساع النطاق",
                f"النطاق {height:.5f} أضيق من {MIN_RANGE_ATR}×ATR "
                f"({MIN_RANGE_ATR * volatility:.5f}) — يُخترَق بالضجيج.",
            )
        if height > MAX_RANGE_ATR * volatility:
            return record.fail(
                "اتّساع النطاق",
                f"النطاق {height:.5f} أوسع من {MAX_RANGE_ATR}×ATR "
                f"({MAX_RANGE_ATR * volatility:.5f}) — وقفُه أبعد من أن يُحتمَل.",
            )
        record.ok("اتّساع النطاق", f"ضمن {MIN_RANGE_ATR}–{MAX_RANGE_ATR}×ATR.")

        # **الاختراق الأوّل وحده.** ما بعده امتدادٌ لا إشارة، والدخول عليه
        # يشتري بعد أن تحرّك السعر — وهو تغييرٌ للفرضية لا تطبيقٌ لها.
        breakout_index = None
        for index, bar in enumerate(after):
            if bar.close > high or bar.close < low:
                breakout_index = index
                break
        if breakout_index is None:
            return record.fail(
                "الاختراق",
                f"لا إغلاق خارج النطاق في هذه الجلسة (آخر إغلاق {bars[-1].close:.5f}).",
            )
        if after[breakout_index] is not after[-1] or after[-1] is not bars[-1]:
            return record.fail(
                "الاختراق الأوّل",
                "الاختراق وقع في شمعةٍ سابقة من هذه الجلسة — الدخول على الأوّل وحده.",
            )

        last = bars[-1]
        long = last.close > high
        if long:
            entry, stop = quote.ask, low
            target = entry + TARGET_MULTIPLE * height
            side = Side.BUY
        else:
            entry, stop = quote.bid, high
            target = entry - TARGET_MULTIPLE * height
            side = Side.SELL

        if not sane_levels(entry=entry, stop=stop, target=target, long=long):
            return record.fail(
                "خطة الخروج",
                f"مستويات غير صالحة: دخول {entry:.5f} · وقف {stop:.5f} · هدف {target:.5f}.",
            )
        record.ok(
            "الاختراق",
            f"إغلاق {last.close:.5f} {'فوق' if long else 'تحت'} "
            f"{'قمّة' if long else 'قاع'} النطاق.",
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
                f"نطاق افتتاح لندن {low:.5f}–{high:.5f} (ارتفاع {height:.5f}، "
                f"ATR14 {volatility:.5f}). أوّل إغلاقٍ خارجه عند {last.close:.5f} "
                f"{'صعوداً' if long else 'هبوطاً'} ⇒ وقفٌ عند الطرف المقابل "
                f"{stop:.5f} وهدفٌ عند {target:.5f} (٢× ارتفاع النطاق)."
            ),
            invalidation_ar=(
                "إغلاقٌ عائدٌ داخل النطاق يلغي الاختراق، وانتهاء نافذة الجلسة "
                f"عند {ENTRY_WINDOW_END_HOUR}:00 UTC يلغي الفرضية لهذا اليوم."
            ),
            inputs_digest=self.inputs_digest(symbol, bars),
        )
        return record.signal(signal)
