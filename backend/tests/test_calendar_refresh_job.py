"""
حارس تعافي التقويم.

## العطل الذي كاد يمرّ

كُتب أوّل وصلٍ للتقويم هكذا: يُجلب **عند بناء النظام**، وإن أخفق يُستبدل
المزوّد بـFMP أو بـ`None`. وفيه عطلان لا يظهران في أي اختبار وحدة:

1. **إقلاعٌ معلّق بشبكة خارجية.** بناء النظام ينتظر تغذيةً على الإنترنت.
2. **والأخطر:** انقطاعٌ عابر لثوانٍ لحظةَ الإقلاع يُبقي الحارس معطّلاً
   **لعمر العملية كلها** — لأن لا أحد يعيد المحاولة. خدمةٌ تعمل شهراً بلا
   تقويم، وكل شيء يبدو سليماً.

فصار الجلب مهمّةً مجدولة تعمل عند أوّل نبضة وكل ساعة. وهذه الاختبارات تحرس
ذلك: أن المهمّة مسجَّلة، وأنها تقرأ فقط، وأن إخفاقها لا يُسقط النبض ولا
يجعل النظام يظنّ التقويم سليماً.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.runtime.heartbeat import (
    CALENDAR_JOB,
    CALENDAR_REFRESH_SECONDS,
    register_runtime_jobs,
)
from app.scheduling import JobKind, SafeScheduler


class FakeCalendar:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.refreshes = 0
        self._raises = raises
        self.configured = False

    def refresh(self) -> None:
        self.refreshes += 1
        if self._raises is not None:
            raise self._raises
        self.configured = True


class FakeRegistry:
    def __init__(self, calendar) -> None:
        self.calendar = calendar


class FakeBroker:
    def health_check(self) -> bool:
        return False


class FakeState:
    """أقلّ ما تلمسه `register_runtime_jobs`."""

    def __init__(self, calendar) -> None:
        self.scheduler = SafeScheduler()
        self.providers = FakeRegistry(calendar)
        self.broker = FakeBroker()
        self.locally_paused = True
        self.last_result = None


def test_the_calendar_refresh_job_is_registered():
    state = FakeState(FakeCalendar())
    register_runtime_jobs(state)
    assert CALENDAR_JOB in state.scheduler.jobs


def test_the_job_is_read_only_not_analysis_and_never_mutating():
    """
    قراءة تغذية عامة. تصنيفها `MUTATING` كان المجدول ليرفضها، وتصنيفها
    `ANALYSIS` يخلطها بخطّ القرار في `/api/health`.
    """
    state = FakeState(FakeCalendar())
    register_runtime_jobs(state)
    assert state.scheduler.jobs[CALENDAR_JOB].kind is JobKind.READ_ONLY


def test_the_job_runs_on_the_very_first_tick():
    """
    الحارس يجب أن يعمل خلال ثوانٍ من الإقلاع، لا بعد ساعة. ولو سُجّلت
    `start_immediately=False` لبقي النظام ساعةً كاملة بلا تقويم — أي ساعة
    يمتنع فيها عن التداول لسببٍ لا وجود له.
    """
    calendar = FakeCalendar()
    state = FakeState(calendar)
    register_runtime_jobs(state)
    ran = state.scheduler.tick()
    assert CALENDAR_JOB in ran
    assert calendar.refreshes == 1
    assert calendar.configured is True


def test_the_job_repeats_hourly_so_a_boot_time_outage_heals():
    """**هذا هو سبب وجود المهمّة.** أوّل محاولة تُخفق، والتالية تنجح."""
    calendar = FakeCalendar(raises=ConnectionError("down"))
    state = FakeState(calendar)
    register_runtime_jobs(state)

    state.scheduler.tick()
    assert calendar.configured is False       # فشل مغلق — لا تداول

    calendar._raises = None                   # عادت الشبكة
    job = state.scheduler.jobs[CALENDAR_JOB]
    state.scheduler.tick(at=job.next_run_utc)
    assert calendar.configured is True         # تعافى وحده، بلا إعادة تشغيل


def test_a_failing_refresh_does_not_stop_the_decision_loop():
    """
    خطأ في مهمّةٍ لا يُسقط بقيّة المهام. تقويمٌ متعثّر يجب ألّا يوقف النبض.
    """
    state = FakeState(FakeCalendar(raises=RuntimeError("feed exploded")))
    register_runtime_jobs(state)
    ran = state.scheduler.tick()
    assert len(ran) == len(state.scheduler.jobs)
    assert state.scheduler.jobs[CALENDAR_JOB].failures == 1
    assert state.scheduler.jobs[CALENDAR_JOB].last_error == "RuntimeError"


def test_a_registry_without_a_calendar_does_not_break_the_tick():
    """صلابةٌ لا تسامح: غياب المزوّد لا يُفجّر النبض."""
    state = FakeState(None)
    register_runtime_jobs(state)
    state.scheduler.tick()
    assert state.scheduler.jobs[CALENDAR_JOB].failures == 0


def test_the_refresh_interval_stays_well_inside_the_feeds_staleness_limit():
    """
    لو صار التواتر أطول من عمر التغذية المقبول، لبات التقويم بين تحديثين
    فسقطت الأهلية دورياً بلا سبب مفهوم.
    """
    from app.providers.faireconomy_calendar import MAX_FEED_AGE

    assert timedelta(seconds=CALENDAR_REFRESH_SECONDS) < MAX_FEED_AGE / 2
