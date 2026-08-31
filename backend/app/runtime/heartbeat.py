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
from datetime import timedelta
from typing import Optional

from ..clock import now_utc
from ..contracts import Bar, DataSource, Decision
from ..money import D
from ..pipeline.runner import MacroAssessment, PipelineResult
from ..risk.session_state import load_session_state
from ..scheduling import JobKind

logger = logging.getLogger(__name__)

DECISION_JOB = "decision-loop"
CALENDAR_JOB = "calendar-refresh"

#: تواتر إعادة التقييم. قصيرٌ كفايةً ليبدو حياً، وطويلٌ كفايةً ألّا يُرهق
#: الوسيط ولا حدود المزوّدين.
DEFAULT_INTERVAL_SECONDS = 60

#: تواتر نبضة الحلقة نفسها. المجدول يقرّر ما يستحقّ التشغيل.
TICK_SECONDS = 1.0

#: تواتر تحديث التقويم الاقتصادي. التغذية أسبوعية، فساعةٌ سخيّة جداً —
#: لكن الغرض ليس الطزاجة وحدها بل **التعافي**: انقطاعٌ عابر يُصلَح في
#: الساعة التالية بدل أن يُعطّل الحارس حتى يُعاد تشغيل الخدمة.
CALENDAR_REFRESH_SECONDS = 3600


#: عدد الشموع المطلوبة لأطول استراتيجية (30 + 14 + 2 = 46) بهامش.
BARS_NEEDED = 120


def _no_trade(code: str, reason_ar: str, stage: str) -> PipelineResult:
    return PipelineResult(Decision.NO_TRADE, code, reason_ar, stage, at_utc=now_utc())


def _bars(broker, symbol: str) -> list[Bar]:
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
        for c in get(symbol, resolution="DAY", max_bars=BARS_NEEDED)
    ]


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

        symbol = next(iter(sorted(state.limits.allowed_instruments)), None)
        if symbol is None:
            state.last_result = _no_trade(
                "NO_INSTRUMENT", "لا أداة مسموحة في وضع المخاطرة الحالي.", "runtime"
            )
            return

        bars = _bars(state.broker, symbol)
        if len(bars) < BARS_NEEDED // 2:
            state.last_result = _no_trade(
                "INSUFFICIENT_BARS",
                f"وصلت {len(bars)} شمعة فقط — لا تكفي لتقييم. لا يُقيَّم على بيانات ناقصة.",
                "runtime",
            )
            return

        # حالة المخاطرة تُقرأ من السجل في كل دورة: الخسائر تتراكم بين الدورات.
        session_state = load_session_state(
            state.db_session, baseline_equity=state.limits.baseline_equity
        )
        state.session_state = session_state

        state.last_result = state.pipeline.run(
            symbol=symbol, bars=bars, state=session_state, macro=_macro()
        )

    state.scheduler.register(
        DECISION_JOB,
        kind=JobKind.ANALYSIS,
        interval=timedelta(seconds=interval_seconds),
        func=run_decision,
    )

    def refresh_calendar() -> None:
        """
        يُحدّث التقويم الاقتصادي. `READ_ONLY`: يقرأ تغذيةً عامة ولا يلمس شيئاً.

        وهذه المهمة هي ما يجعل الحارس **يتعافى**. لو جُلب التقويم عند الإقلاع
        وحده، لكان انقطاع شبكةٍ لثوانٍ لحظةَ الإقلاع يُبقي `configured=False`
        حتى يُعاد تشغيل الخدمة — أي حارسٌ ميّتٌ بلا أن يقول أحدٌ شيئاً.

        وإخفاق الجلب لا يُرفَع: `SafeScheduler.tick` يعزل الخطأ ويسجّله،
        والمزوّد يبقى غير مُعدّ — فتسقط أهلية التداول. يفشل مغلقاً.
        """
        calendar = getattr(state.providers, "calendar", None)
        refresh = getattr(calendar, "refresh", None)
        if callable(refresh):
            refresh()

    state.scheduler.register(
        CALENDAR_JOB,
        kind=JobKind.READ_ONLY,
        interval=timedelta(seconds=CALENDAR_REFRESH_SECONDS),
        func=refresh_calendar,
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
