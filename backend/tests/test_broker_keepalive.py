"""
جلسة الوسيط تبقى حيّة، وتعود إن سقطت.

## لماذا هذا الملف هو مبرّر الخادم نفسه

نُقل النظام إلى خادم يعمل ٢٤/٧ كي لا ينقطع شيء. والوسيط كان يُوصَل **مرّة
واحدة عند الإقلاع**، ثم لا شيء يُبقي الجلسة ولا يعيد المحاولة:

* جلسة كابيتال تنتهي بعد عشر دقائق خمول.
* وإخفاق الوصل عند الإقلاع كان يُبتلع بـ`except: pass`، فيبقى المحوّل غير
  موصول **لعمر العملية**. و`_require_connection` ترفض كل قراءة، فلا قراءةٌ
  تُصلح الجلسة، فلا تعافي أبداً — حتى يُعاد تشغيل الخدمة يدوياً.

أي أن خادماً يعمل ٢٤/٧ كان يستطيع أن يبقى بلا وسيط أياماً، والتطبيق يقول
«غير متصل» بلا سبب. وهذا نقضٌ لغرض النقل إلى الخادم من أصله.

ولا شبكة هنا: المحوّل مُقلَّد بالكامل.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.brokers.capital.errors import CapitalAuthLockout
from app.runtime.heartbeat import (
    BROKER_JOB,
    BROKER_KEEPALIVE_SECONDS,
    register_runtime_jobs,
)
from app.scheduling import JobKind, SafeScheduler


class FakeBroker:
    """يُحاكي ما تلمسه المهمّة وحده: الفحص والوصل."""

    def __init__(self, *, healthy: bool = True, connect_raises: Exception | None = None,
                 health_raises: Exception | None = None) -> None:
        self.healthy = healthy
        self.connect_raises = connect_raises
        self.health_raises = health_raises
        self.connects = 0
        self.checks = 0

    def health_check(self) -> bool:
        self.checks += 1
        if self.health_raises is not None:
            raise self.health_raises
        return self.healthy

    def connect(self) -> None:
        self.connects += 1
        if self.connect_raises is not None:
            raise self.connect_raises
        self.healthy = True


class FakeState:
    def __init__(self, broker) -> None:
        self.scheduler = SafeScheduler()
        self.broker = broker
        self.providers = type("R", (), {"calendar": None})()
        self.locally_paused = True
        self.last_result = None
        self.broker_note_ar = ""


def wired(broker) -> FakeState:
    state = FakeState(broker)
    register_runtime_jobs(state)
    return state


def run_keepalive(state: FakeState, times: int = 1) -> None:
    job = state.scheduler.jobs[BROKER_JOB]
    for _ in range(times):
        state.scheduler.tick(at=job.next_run_utc)


# ---------------------------------------------------------------------------
def test_the_keepalive_job_is_registered_and_read_only():
    state = wired(FakeBroker())
    assert BROKER_JOB in state.scheduler.jobs
    assert state.scheduler.jobs[BROKER_JOB].kind is JobKind.READ_ONLY


def test_a_healthy_session_is_touched_not_reconnected():
    """
    الفحص نفسه يُبقي الجلسة حيّة. وتسجيل دخولٍ جديد كل أربع دقائق على جلسة
    سليمة إسرافٌ على الوسيط وقد يصطدم بحدوده.
    """
    broker = FakeBroker(healthy=True)
    state = wired(broker)
    run_keepalive(state, times=3)
    assert broker.checks >= 3
    assert broker.connects == 0


def test_a_dropped_session_is_reconnected():
    """**العطل الذي كان يترك الخادم بلا وسيط أياماً.**"""
    broker = FakeBroker(healthy=False)
    state = wired(broker)
    run_keepalive(state)
    assert broker.connects == 1
    assert broker.healthy is True
    assert state.broker_note_ar == ""


def test_a_boot_failure_heals_on_a_later_tick():
    """
    إخفاق الوصل عند الإقلاع لا يعني انقطاعاً دائماً: المحاولة تتكرّر.
    """
    broker = FakeBroker(healthy=False, connect_raises=ConnectionError("down"))
    state = wired(broker)

    run_keepalive(state)
    assert broker.healthy is False
    assert "تعذّر" in state.broker_note_ar        # السبب يُكتب ليُقرأ

    broker.connect_raises = None                   # عادت الشبكة
    run_keepalive(state)
    assert broker.healthy is True
    assert state.broker_note_ar == ""


def test_a_raising_health_check_does_not_stop_the_recovery():
    """فحصٌ ينفجر ليس جواباً بأن الجلسة سليمة — يُحاوَل الوصل."""
    broker = FakeBroker(health_raises=RuntimeError("boom"))
    state = wired(broker)
    run_keepalive(state)
    assert broker.connects == 1


def test_an_auth_lockout_stops_the_job_and_says_why():
    """
    قفلُ المصادقة يُحترَم: المحوّل يقفل نفسه بعد ثلاث محاولات فاشلة عمداً.
    والإلحاح على اعتمادات خاطئة يُوقف الحساب عند الوسيط — وذلك أسوأ من
    الانقطاع. فتتوقّف المهمّة، **ويُقال السبب بالنصّ** بدل «غير متصل» صامتة.
    """
    broker = FakeBroker(healthy=False, connect_raises=CapitalAuthLockout("أُقفلت المصادقة"))
    state = wired(broker)
    run_keepalive(state)

    assert state.scheduler.jobs[BROKER_JOB].enabled is False
    assert "المصادقة مقفلة" in state.broker_note_ar

    before = broker.connects
    run_keepalive(state)
    assert broker.connects == before, "أُعيدت المحاولة رغم القفل"


def test_the_interval_stays_inside_the_session_lifetime():
    """
    لو تجاوز التواتر عمرَ الجلسة لانتهت بين نبضتين، فصار «إبقاء الجلسة»
    اسماً لمهمّةٍ تُعيد تسجيل الدخول كل مرّة.
    """
    from app.brokers.capital.session import SESSION_RENEW_MARGIN, SESSION_TTL

    assert timedelta(seconds=BROKER_KEEPALIVE_SECONDS) < SESSION_TTL - SESSION_RENEW_MARGIN


def test_the_decision_job_still_runs_alongside():
    """مهمّة الوسيط لا تزاحم خطّ القرار — كلتاهما تعملان."""
    state = wired(FakeBroker())
    ran = state.scheduler.tick()
    assert BROKER_JOB in ran
    assert len(ran) == len(state.scheduler.jobs)
