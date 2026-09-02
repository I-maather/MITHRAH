"""
النبض — الحلقة التي تجعل النظام يبادر بدل أن ينتظر أن يُسأل.

قبل هذا الملف كان `SafeScheduler` يُبنى عند الإقلاع **فارغاً**، و`tick()` لا
يستدعيها أحد. فالخادم يعمل ٢٤/٧ ولا شيء بداخله يتحرّك: عمليةٌ حيّة تنتظر
طلباً، لا نظام يراقب سوقاً.

## لماذا حلقة لا «جدولة»

الفرق ليس لفظياً. الجدولة تعني «استيقظ الساعة كذا»؛ والحلقة تعني **لا ينام
أصلاً**. هذه تبدأ مع الخادم ولا تتوقف حتى يتوقف، وتُعيد التقييم على تواتر
قصير. `SafeScheduler` هو آلة التوقيت داخلها، لا بديلاً عنها.

## ما لا تفعله هذه الحلقة

**لا ترسل أمراً، ولا تستطيع.** المجدول يرفض تسجيل أي مهمة مصنَّفة `MUTATING`
عند التسجيل نفسه — لا عند التشغيل. فالمنع بنيوي لا سلوكي.

## ثلاثة حرّاس قبل تشغيل خط القرار

كلٌّ منها يُنتج **سبباً مكتوباً** بدل صمت أو خطأ:

1. **إيقاف محلي** — قرار المالكة، يُحترَم فوراً.
2. **الوسيط مفصول** — وهذا الحارس هو الأهم: تشغيل الخط والوسيط مفصول
   **يُفعّل قاطع الطوارئ** (`BROKER_DISCONNECTED`). وحلقةٌ تعمل كل دقيقة
   كانت ستُفعّله في أول دقيقة انقطاع، فيتحوّل عطلُ شبكةٍ عابر إلى توقّف
   يحتاج موافقة مكتوبة لرفعه. الانقطاع يُقال، ولا يُصعَّد.
3. **قاطع الطوارئ مفعّل** — لا معنى لتقييم لا يمكن أن يُنفَّذ.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from ..brokers.capital.errors import CapitalAuthLockout
from ..clock import now_utc
from ..contracts import Bar, DataSource, Decision
from ..money import D
from ..pipeline.runner import MacroAssessment, NewsBlackout, PipelineResult
from ..risk.session_state import load_session_state
from ..scheduling import JobKind

logger = logging.getLogger(__name__)

DECISION_JOB = "decision-loop"
CALENDAR_JOB = "calendar-refresh"
BROKER_JOB = "broker-keepalive"

#: تواتر إعادة التقييم. قصيرٌ كفايةً ليبدو حياً، وطويلٌ كفايةً ألّا يُرهق
#: الوسيط ولا حدود المزوّدين.
DEFAULT_INTERVAL_SECONDS = 60

#: تواتر نبضة الحلقة نفسها. المجدول يقرّر ما يستحقّ التشغيل.
TICK_SECONDS = 1.0

#: تواتر تحديث التقويم الاقتصادي. التغذية أسبوعية، فساعةٌ سخيّة جداً —
#: لكن الغرض ليس الطزاجة وحدها بل **التعافي**: انقطاعٌ عابر يُصلَح في
#: الساعة التالية بدل أن يُعطّل الحارس حتى يُعاد تشغيل الخدمة.
CALENDAR_REFRESH_SECONDS = 3600

#: نافذة الحظر حول حدثٍ عالي الأثر — قبله وبعده.
#:
#: القيمتان **افتراضٌ معلَن** لا قياس: لا يملك المشروع دليلاً على المدّة
#: الصحيحة، والمتحفّظ أسلم. وأي تضييقٍ لهما يحتاج قياساً لا رأياً.
BLACKOUT_BEFORE = timedelta(minutes=30)
BLACKOUT_AFTER = timedelta(minutes=30)

#: كم يوماً تُحفَظ تأكيداته. يومان يكفيان القرار، والباقي نموٌّ بلا فائدة.
CONFIRMED_DAYS_KEPT = 2

#: تواتر إبقاء جلسة الوسيط حيّة وإعادة وصلها.
#:
#: **لماذا هذه المهمّة هي مبرّر الخادم نفسه.** نُقل النظام إلى خادم يعمل
#: ٢٤/٧ كي لا ينقطع شيء. والوسيط كان يُوصَل **مرّة واحدة عند الإقلاع**، ثم
#: لا شيء يُبقي الجلسة ولا يعيد المحاولة:
#:
#:   * جلسة كابيتال تنتهي بعد عشر دقائق خمول.
#:   * وإخفاق الوصل عند الإقلاع كان يُبتلع بـ`except: pass`، فيبقى المحوّل
#:     غير موصول **لعمر العملية**. و`_require_connection` ترفض كل قراءة،
#:     فلا قراءةٌ تُصلح الجلسة، فلا تعافي أبداً — حتى يُعاد تشغيل الخدمة يدوياً.
#:
#: أي أن خادماً يعمل ٢٤/٧ كان يستطيع أن يبقى بلا وسيط أياماً، والتطبيق يقول
#: «غير متصل» بلا سبب. وهذا نقضٌ لغرض النقل إلى الخادم من أصله.
#:
#: أربع دقائق: داخل مهلة العشر بهامش، وداخل هامش التجديد (ثمان دقائق).
BROKER_KEEPALIVE_SECONDS = 240


#: عدد الشموع المطلوبة لأطول استراتيجية (30 + 14 + 2 = 46) بهامش.
BARS_NEEDED = 120

#: كم شمعة تُحفَظ للعرض. ستّون تكفي لقراءة السياق على الشاشة،
#: وحفظُ المئة والعشرين كلها يضخّم حمولة الجوال بلا فائدة بصرية.
CHART_BARS = 60


#: العملات التي يُسأل عنها التقويم — عملات أدوات الاكتشاف.
CALENDAR_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "JPY")

#: مستويات الأثر التي تُنشئ نافذة حظر. المتوسط والمنخفض لا يوقفان التداول.
HIGH_IMPACT: frozenset[str] = frozenset({"HIGH"})

#: أي أداة تتأثر بأي عملة. الذهب مسعَّرٌ بالدولار فيتأثر به.
SYMBOLS_BY_CURRENCY: dict[str, tuple[str, ...]] = {
    "USD": ("EURUSD", "GBPUSD", "USDJPY", "GOLD"),
    "EUR": ("EURUSD",),
    "GBP": ("GBPUSD",),
    "JPY": ("USDJPY",),
}


def _prune_confirmations(confirmed: set, today: date) -> None:
    """يُبقي اليوم وما بعده. تأكيدُ الأمس لا يفيد قراراً ولا يُترك ينمو."""
    for day in [d for d in confirmed if d < today]:
        confirmed.discard(day)


def _no_trade(code: str, reason_ar: str, stage: str) -> PipelineResult:
    return PipelineResult(Decision.NO_TRADE, code, reason_ar, stage, at_utc=now_utc())


def _bars(broker, symbol: str, resolution: str = "DAY") -> list[Bar]:
    """شموع الوسيط ⇐ شموع الخط. الوسط بين العرض والطلب."""
    get = getattr(broker, "get_candles", None)
    if get is None:
        return []
    two = D(2)
    return [
        Bar(
            symbol=symbol,
            start_utc=c.snapshot_time_utc,
            open=(c.open_bid + c.open_ask) / two,
            high=(c.high_bid + c.high_ask) / two,
            low=(c.low_bid + c.low_ask) / two,
            close=(c.close_bid + c.close_ask) / two,
            volume=c.volume if c.volume is not None else D(0),
            source=DataSource.HISTORICAL,
        )
        for c in get(symbol, resolution=resolution, max_bars=BARS_NEEDED)
    ]


def _chosen(scan: list[tuple[str, PipelineResult]]) -> Optional[PipelineResult]:
    """
    أيّ نتيجةٍ من المسح تُعرَض في الشاشة الواحدة؟

    **التنفيذ أوّلاً** — فإن وُجد فهو الحدث. وإلّا فأكثر الرفوض إفادةً:
    رفضٌ من مرحلة الاستراتيجية يقول «رأيتُ السوق ولم أجد فرصة»، ورفضٌ من
    مرحلة البيانات يقول «لم أرَ السوق أصلاً». والثاني عطلٌ يُصلَح، والأول
    عملُ النظام الطبيعي — وعرضُ أحدهما مكان الآخر يرسل المالكة إلى المكان
    الخطأ تماماً.

    ولذلك يُقدَّم **العطل** على العمل الطبيعي: ما يحتاج يداً يُعرَض أوّلاً.
    """
    if not scan:
        return None
    for _, result in scan:
        if result.decision is Decision.TRADE:
            return result
    for _, result in scan:
        if result.reason_code in _NEEDS_A_HAND:
            return result
    return scan[0][1]


#: رفوضٌ سببها عطلٌ عندنا لا حالةُ سوق. تُقدَّم في العرض على «لا فرصة».
_NEEDS_A_HAND = frozenset({
    "INSUFFICIENT_BARS",
    "BROKER_UNREACHABLE",
    "MARKET_DATA_STALE",
    "CALENDAR_UNCONFIRMED",
})


def _macro() -> MacroAssessment:
    """
    الفيتو الكلي.

    **لا يُختلَق منعٌ ولا سماح.** غياب المزوّد الكلي يعني أننا لا نملك مُدخلاً
    كلياً — لا أننا رأينا خطراً. فلا فيتو هنا، ومرحلة التقويم بعده هي الحارس
    الحقيقي: تُوقف الخط صراحةً إن لم يكن تقويم اليوم مؤكَّداً.

    اختلاق منعٍ من فراغ خطأٌ بقدر اختلاق سماح: كلاهما ادّعاء بلا دليل.
    """
    return MacroAssessment(
        blocks_trading=False,
        reason_ar="لا مزوّد كليّ موصول بالخط بعد — لا فيتو كليّ. التقويم يحرس بعده.",
    )


def register_runtime_jobs(state, *, interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    """
    يسجّل مهمة القرار. تُستدعى مرة عند الإقلاع.

    المهمة `ANALYSIS` لا `MUTATING`: تقرّر وتكتب، ولا تلمس الوسيط بتعديل.
    """

    def run_decision() -> None:
        if getattr(state, "locally_paused", False):
            state.last_result = _no_trade(
                "LOCALLY_PAUSED", "التداول موقوف محلياً بقرارك. لا تقييم.", "runtime"
            )
            return

        try:
            connected = state.broker.health_check()
        except Exception:  # noqa: BLE001
            connected = False
        if not connected:
            # لا يُستدعى الخط: استدعاؤه هنا يُفعّل قاطع الطوارئ على انقطاع عابر.
            state.last_result = _no_trade(
                "BROKER_UNREACHABLE",
                "لا اتصال بالوسيط — لا أرى السوق. البيانات المعروضة قديمة.",
                "runtime",
            )
            return

        if state.kill_switch.is_active:
            event = state.kill_switch.state.current_event
            state.last_result = _no_trade(
                "HALTED",
                f"قاطع الطوارئ مفعّل: {event.reason_ar if event else 'سبب غير مسجّل'}.",
                "runtime",
            )
            return

        symbols = sorted(state.limits.allowed_instruments)
        if not symbols:
            state.last_scan = []
            state.last_result = _no_trade(
                "NO_INSTRUMENT", "لا أداة مسموحة في وضع المخاطرة الحالي.", "runtime"
            )
            return

        # حالة المخاطرة تُقرأ من السجل مرّة لكل دورة مسح، لا مرّة لكل أداة:
        # قراءتها بين الأدوات تجعل نتيجة الأداة الثانية تعتمد على أثر الأولى
        # في المنتصف — وهو ما لا يمكن إعادة إنتاجه ولا تفسيره في التدقيق.
        session_state = load_session_state(
            state.db_session, baseline_equity=state.limits.baseline_equity
        )
        state.session_state = session_state

        scan: list[tuple[str, PipelineResult]] = []
        for symbol in symbols:
            # الدقّة من الحالة لا مثبّتة: الحلقة كانت تقرأ شموعاً **يومية**
            # وتكرّر السؤال 1440 مرّة في اليوم على نفس الشمعة.
            bars = _bars(state.broker, symbol, getattr(state, "candle_resolution", "DAY"))
            if len(bars) < BARS_NEEDED // 2:
                scan.append((symbol, _no_trade(
                    "INSUFFICIENT_BARS",
                    f"{symbol}: وصلت {len(bars)} شمعة فقط — لا تكفي لتقييم. "
                    f"لا يُقيَّم على بيانات ناقصة.",
                    "runtime",
                )))
                continue

            # الشموع تُحفَظ **قبل** التقييم: أداةٌ رُفضت لسببٍ ما تبقى
            # شموعها مرئية، فتُرى الصورة التي رآها النظام حين قرّر.
            state.last_bars[symbol] = list(bars[-CHART_BARS:])

            result = state.pipeline.run(
                symbol=symbol, bars=bars, state=session_state, macro=_macro()
            )
            scan.append((symbol, result))

            # **يتوقّف المسح عند أول تنفيذ.** المضيّ بعده يقيّم بقيّة الأدوات
            # على حالة مخاطرة صارت بائدة في السطر السابق — فيُفتح مركزٌ ثانٍ
            # بميزانيةٍ أُنفقت. الحالة تُقرأ من جديد في الدورة التالية.
            if result.decision is Decision.TRADE:
                break

        state.last_scan = scan
        state.last_result = _chosen(scan)

    state.scheduler.register(
        DECISION_JOB,
        kind=JobKind.ANALYSIS,
        interval=timedelta(seconds=interval_seconds),
        func=run_decision,
    )

    def refresh_calendar() -> None:
        """
        يُحدّث التقويم الاقتصادي **ويُغذّي الحارس الذي يقرأه**.

        ## العطل الذي فرض إعادة كتابة هذه الدالّة

        كانت تستدعي `calendar.refresh()` وتقف. والخط يقرأ حارساً آخر:
        `BlackoutCalendar.confirmed_for` — وهو `set()` يُنشأ فارغاً في
        `build_system` **ولا يُكتب فيه سطرٌ واحد في المشروع كلّه**. بحثتُ:
        يُعلَن في `runner.py:78`، ويُقرأ في `runner.py:228`، ويُعرَض في
        `main.py:566`، ولا يُكتب أبداً.

        ⇒ `is_confirmed(today)` **زائفةٌ دائماً**، فيقف كل تقييمٍ عند المرحلة
        الثالثة بـ`NEWS_CALENDAR_UNCONFIRMED` قبل أن يبلغ الاستراتيجية.
        **لم يكن النظام قادراً على فتح صفقة واحدة منذ كُتب.**

        وهو العطل الحاكم في المشروع بأخطر صوره: بوّابةٌ موصولةٌ بمصدرٍ لم
        يوصلها أحد به — تقول «لا أعرف» فيُقرأ ذلك حذراً، وهو عطل.

        ## القاعدة

        اليوم يُؤكَّد **بعد جلبٍ ناجح فعلاً**، لا بمحاولة. وإخفاق الجلب لا
        يؤكّد شيئاً ولا يمحو تأكيداً سابقاً: يومٌ جُلب تقويمُه بنجاح يبقى
        مجلوباً وإن سقطت الشبكة بعده.
        """
        calendar = getattr(state.providers, "calendar", None)
        if calendar is None:
            return
        refresh = getattr(calendar, "refresh", None)
        if callable(refresh):
            refresh()
        if not getattr(calendar, "configured", False):
            # مزوّدٌ غير مُعدّ لا يؤكّد يوماً. يفشل مغلقاً.
            return

        now = now_utc()
        start = now - timedelta(hours=12)
        end = now + timedelta(hours=36)
        try:
            events = calendar.events(
                currencies=CALENDAR_CURRENCIES,
                window_start_utc=start,
                window_end_utc=end,
            )
        except Exception as exc:  # noqa: BLE001
            # **لا تأكيد على إخفاق.** والسبب يُكتب: «غير مؤكد» بلا سببٍ
            # ترسل المالكة تبحث في مكانٍ سليم.
            logging.getLogger(__name__).warning(
                "تعذّر جلب التقويم الاقتصادي: %s", type(exc).__name__
            )
            return

        blackouts = []
        for event in events:
            if getattr(event.impact, "value", str(event.impact)).upper() not in HIGH_IMPACT:
                continue
            at = event.scheduled_utc
            for currency in event.currencies:
                for symbol in SYMBOLS_BY_CURRENCY.get(currency.upper(), ()):
                    blackouts.append(
                        NewsBlackout(
                            symbol=symbol,
                            starts_utc=at - BLACKOUT_BEFORE,
                            ends_utc=at + BLACKOUT_AFTER,
                            title_ar=event.name,
                            source=event.provider,
                        )
                    )

        state.blackouts.entries = blackouts
        state.blackouts.confirmed_for.add(now.date())
        # التأكيد للغد أيضاً حين تشمله النافذة المجلوبة — وإلّا وقف النظام
        # عند منتصف الليل إلى أن تدور المهمة من جديد.
        state.blackouts.confirmed_for.add((now + timedelta(days=1)).date())
        _prune_confirmations(state.blackouts.confirmed_for, now.date())

    state.scheduler.register(
        CALENDAR_JOB,
        kind=JobKind.READ_ONLY,
        interval=timedelta(seconds=CALENDAR_REFRESH_SECONDS),
        func=refresh_calendar,
    )

    def keep_broker_alive() -> None:
        """
        يُبقي جلسة الوسيط حيّة، ويعيد وصلها إن سقطت. `READ_ONLY` — لا يرسل
        أمراً ولا يفتح قفلاً؛ يسجّل دخولاً ويستعلم عن الحال لا غير.

        وقفلُ المصادقة يُحترَم: بعد ثلاث محاولات فاشلة يقفل المحوّل نفسه
        عمداً، ولا تُعاد المحاولة تلقائياً — إلحاحٌ على اعتمادات خاطئة
        يُوقف الحساب عند الوسيط، وذلك أسوأ من الانقطاع.
        """
        broker = state.broker
        try:
            if broker.health_check():
                state.broker_note_ar = ""
                return
        except Exception as exc:  # noqa: BLE001
            state.broker_note_ar = f"فحص الوسيط أخفق ({type(exc).__name__})."

        try:
            broker.connect()
        except CapitalAuthLockout as exc:
            # لا يُعاد المحاولة. يُقال للمالكة بالنصّ بدل «غير متصل» الصامتة.
            state.broker_note_ar = f"المصادقة مقفلة: {exc}"
            state.scheduler.disable(BROKER_JOB)
            logger.warning("قفل مصادقة الوسيط — أُوقفت مهمة إبقاء الجلسة.")
            return
        except Exception as exc:  # noqa: BLE001
            state.broker_note_ar = f"تعذّر وصل الوسيط ({type(exc).__name__})."
            return

        state.broker_note_ar = ""

    state.scheduler.register(
        BROKER_JOB,
        kind=JobKind.READ_ONLY,
        interval=timedelta(seconds=BROKER_KEEPALIVE_SECONDS),
        func=keep_broker_alive,
    )


class Heartbeat:
    """
    الحلقة الدائمة.

    **لا تُسقط الخادم أبداً.** `SafeScheduler.tick` يعزل خطأ كل مهمة، وهذه
    تعزل ما بقي: أي استثناء يُسجَّل وتستمرّ الحلقة. خادمٌ يموت لأن تقييماً
    فشل أسوأ من تقييم فاشل.
    """

    def __init__(self, state, *, tick_seconds: float = TICK_SECONDS) -> None:
        self.state = state
        self.tick_seconds = tick_seconds
        self._task: Optional[asyncio.Task] = None
        self.ticks = 0

    async def _loop(self) -> None:
        logger.info("النبض بدأ — إعادة التقييم كل %ss", DEFAULT_INTERVAL_SECONDS)
        while True:
            try:
                self.state.scheduler.tick()
                self.ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("نبضة فاشلة: %s", type(exc).__name__)
            await asyncio.sleep(self.tick_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._task = None
