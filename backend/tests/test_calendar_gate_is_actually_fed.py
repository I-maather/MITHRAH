"""
بوّابة التقويم — **كانت موصولةً بمصدرٍ لم يوصلها أحد به.**

## العطل

`BlackoutCalendar.confirmed_for` مجموعةٌ تُنشأ فارغة في `build_system`،
تُقرأ في `pipeline/runner.py:228`، وتُعرَض في `main.py:566` — **ولا يُكتب
فيها سطرٌ واحد في المشروع كلّه**.

⇒ `is_confirmed(today)` زائفةٌ دائماً، فيقف كل تقييمٍ عند المرحلة الثالثة
بـ`NEWS_CALENDAR_UNCONFIRMED` قبل أن يبلغ الاستراتيجية.

**لم يكن النظام قادراً على فتح صفقة واحدة منذ كُتب.** ولم يظهر ذلك لأن
الخط لم يُشغَّل قطّ باستراتيجيةٍ يمكن أن تُشير: كل شيء قبله كان يوقف
لأسبابٍ أخرى، فبقي هذا الحائط خلف حائط.

وهو العطل الحاكم بأخطر صوره: بوّابةٌ تقول «لا أعرف» فيُقرأ ذلك حذراً
مقصوداً، وهو عطل.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.pipeline.runner import BlackoutCalendar
from app.runtime import heartbeat


class FakeEvent:
    def __init__(self, name, currencies, impact, at):
        self.name = name
        self.currencies = currencies
        self.impact = SimpleNamespace(value=impact)
        self.scheduled_utc = at
        self.provider = "fake-calendar"


class FakeCalendar:
    def __init__(self, *, configured=True, events=(), raises=False):
        self.configured = configured
        self._events = list(events)
        self._raises = raises
        self.refreshed = 0

    def refresh(self, **_):
        self.refreshed += 1

    def events(self, *, currencies, window_start_utc, window_end_utc):
        if self._raises:
            raise RuntimeError("الشبكة")
        return tuple(self._events)


class _Scheduler:
    def __init__(self):
        self.jobs = {}

    def register(self, name, *, kind, interval, func):
        self.jobs[name] = func


def make_state(calendar):
    return SimpleNamespace(
        providers=SimpleNamespace(calendar=calendar),
        blackouts=BlackoutCalendar(),
        scheduler=_Scheduler(),
        settings=SimpleNamespace(decision_interval_seconds=60),
        broker=SimpleNamespace(is_live=False),
    )


def calendar_job(state):
    """**المهمّة الحقيقية** كما تُسجَّل في التشغيل — لا نسخةٌ منها."""
    heartbeat.register_runtime_jobs(state)
    return state.scheduler.jobs[heartbeat.CALENDAR_JOB]


def test_a_successful_fetch_confirms_today():
    """**الفحص الذي كان غائباً.** بلا هذا لا يفتح النظام صفقة أبداً."""
    calendar = FakeCalendar(events=[])
    state = make_state(calendar)
    calendar_job(state)()
    assert state.blackouts.is_confirmed(datetime.now(timezone.utc).date())
    assert calendar.refreshed == 1


def test_an_unconfigured_provider_confirms_nothing():
    state = make_state(FakeCalendar(configured=False))
    calendar_job(state)()
    assert state.blackouts.confirmed_for == set()


def test_a_failed_fetch_confirms_nothing():
    """محاولةٌ ليست جلباً. والتأكيد على محاولةٍ يفتح الباب على بياناتٍ لم تصل."""
    state = make_state(FakeCalendar(raises=True))
    calendar_job(state)()
    assert state.blackouts.confirmed_for == set()


def test_a_high_impact_event_creates_a_blackout_on_the_right_symbols():
    at = datetime.now(timezone.utc) + timedelta(hours=2)
    state = make_state(FakeCalendar(events=[FakeEvent("NFP", ("USD",), "HIGH", at)]))
    calendar_job(state)()
    covered = {b.symbol for b in state.blackouts.entries}
    assert covered == {"EURUSD", "GBPUSD", "USDJPY", "GOLD"}
    # النافذة تحيط بالحدث من الجهتين.
    assert state.blackouts.active(at, "EURUSD") is not None
    assert state.blackouts.active(at + timedelta(hours=3), "EURUSD") is None


def test_a_euro_event_does_not_stop_the_yen():
    at = datetime.now(timezone.utc) + timedelta(hours=1)
    state = make_state(FakeCalendar(events=[FakeEvent("ECB", ("EUR",), "HIGH", at)]))
    calendar_job(state)()
    assert state.blackouts.active(at, "EURUSD") is not None
    assert state.blackouts.active(at, "USDJPY") is None


def test_a_low_impact_event_does_not_stop_anything():
    """
    كل حدثٍ حاجزاً يعني توقّفاً شبه دائم — والحارس الذي يمنع دائماً يُطفأ.
    """
    at = datetime.now(timezone.utc) + timedelta(hours=1)
    state = make_state(FakeCalendar(events=[FakeEvent("مؤشر ثانوي", ("USD",), "LOW", at)]))
    calendar_job(state)()
    assert state.blackouts.entries == []
    assert state.blackouts.is_confirmed(datetime.now(timezone.utc).date())


def test_yesterdays_confirmation_is_pruned():
    state = make_state(FakeCalendar(events=[]))
    stale = datetime.now(timezone.utc).date() - timedelta(days=5)
    state.blackouts.confirmed_for.add(stale)
    calendar_job(state)()
    assert stale not in state.blackouts.confirmed_for


def test_nothing_else_in_the_project_writes_the_confirmation_set():
    """
    الحارس يبقى صحيحاً ما دام موضع الكتابة واحداً. وكاتبٌ ثانٍ في مكانٍ آخر
    يعيد العطل بصورةٍ أخرى: تأكيدٌ من طريقٍ لا يمرّ بجلبٍ ناجح.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    writers = []
    for path in root.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "confirmed_for.add" in line or "confirmed_for =" in line:
                writers.append(f"{path.name}: {line.strip()}")
    # كتابتان اثنتان، كلتاهما في `heartbeat.py` بعد جلبٍ ناجح: اليوم وغده.
    assert len(writers) == 2, writers
    assert all(w.startswith("heartbeat.py:") for w in writers), writers
