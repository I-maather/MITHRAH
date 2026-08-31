"""
النبض — الحلقة التي تعمل ٢٤/٧ بلا أن يراها أحد.

أهمّ ما يُختبَر هنا ليس أنها تشتغل، بل **متى تمتنع**: كل حارس يجب أن يمنع
استدعاء خط القرار، لا أن يعتمد على الخط ليمنع نفسه.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.clock import now_utc
from app.contracts import Decision
from app.money import D
from app.runtime import heartbeat as hb
from app.scheduling import JobKind, SafeScheduler, UnsafeScheduledJob


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return hb.PipelineResult(Decision.NO_TRADE, "NO_SETUP", "لا فرصة.", "strategy", at_utc=now_utc())


class FakeCandle:
    def __init__(self) -> None:
        self.snapshot_time_utc = now_utc()
        self.open_bid = self.high_bid = self.low_bid = self.close_bid = D("1.0")
        self.open_ask = self.high_ask = self.low_ask = self.close_ask = D("1.0")
        self.volume = D("1")


class FakeBroker:
    def __init__(self, *, healthy=True, bars=200) -> None:
        self._healthy = healthy
        self._bars = bars

    def health_check(self) -> bool:
        if isinstance(self._healthy, Exception):
            raise self._healthy
        return self._healthy

    def get_candles(self, symbol, *, resolution="DAY", max_bars=200):
        return [FakeCandle() for _ in range(self._bars)]


def build_state(monkeypatch, **over):
    monkeypatch.setattr(hb, "load_session_state", lambda *a, **k: "STATE")
    ks = SimpleNamespace(is_active=False, state=SimpleNamespace(current_event=None))
    state = SimpleNamespace(
        locally_paused=over.pop("locally_paused", False),
        broker=over.pop("broker", FakeBroker()),
        kill_switch=over.pop("kill_switch", ks),
        limits=SimpleNamespace(allowed_instruments=frozenset({"EURUSD"}), baseline_equity=D("140")),
        db_session=None,
        pipeline=FakePipeline(),
        scheduler=SafeScheduler(),
        session_state=None,
        last_result=None,
    )
    for k, v in over.items():
        setattr(state, k, v)
    hb.register_runtime_jobs(state, interval_seconds=1)
    return state


def run_once(state):
    state.scheduler.tick()
    return state.last_result


# --- الامتناع: كل حارس يمنع استدعاء الخط بنفسه --------------------------

def test_local_pause_stops_before_the_pipeline(monkeypatch):
    state = build_state(monkeypatch, locally_paused=True)
    result = run_once(state)
    assert result.reason_code == "LOCALLY_PAUSED"
    assert state.pipeline.calls == []


def test_disconnected_broker_never_reaches_the_pipeline(monkeypatch):
    """
    الأهمّ: تشغيل الخط والوسيط مفصول **يُفعّل قاطع الطوارئ**. وحلقةٌ كل دقيقة
    كانت ستحوّل انقطاعاً عابراً إلى توقّف يحتاج موافقة مكتوبة لرفعه.
    """
    state = build_state(monkeypatch, broker=FakeBroker(healthy=False))
    result = run_once(state)
    assert result.reason_code == "BROKER_UNREACHABLE"
    assert state.pipeline.calls == [], "الانقطاع يُقال، ولا يُصعَّد"


def test_a_raising_health_check_is_treated_as_disconnected(monkeypatch):
    state = build_state(monkeypatch, broker=FakeBroker(healthy=RuntimeError("شبكة")))
    result = run_once(state)
    assert result.reason_code == "BROKER_UNREACHABLE"
    assert state.pipeline.calls == []


def test_active_kill_switch_stops_before_the_pipeline(monkeypatch):
    ks = SimpleNamespace(
        is_active=True,
        state=SimpleNamespace(current_event=SimpleNamespace(reason_ar="بلغت الحد اليومي")),
    )
    state = build_state(monkeypatch, kill_switch=ks)
    result = run_once(state)
    assert result.reason_code == "HALTED"
    assert "بلغت الحد اليومي" in result.reason_ar
    assert state.pipeline.calls == []


def test_too_few_bars_is_refused_not_evaluated(monkeypatch):
    state = build_state(monkeypatch, broker=FakeBroker(bars=10))
    result = run_once(state)
    assert result.reason_code == "INSUFFICIENT_BARS"
    assert state.pipeline.calls == [], "لا يُقيَّم على بيانات ناقصة"


# --- المسار الكامل ------------------------------------------------------

def test_a_healthy_cycle_calls_the_pipeline_with_real_inputs(monkeypatch):
    state = build_state(monkeypatch)
    result = run_once(state)
    assert len(state.pipeline.calls) == 1
    call = state.pipeline.calls[0]
    assert call["symbol"] == "EURUSD"
    assert len(call["bars"]) >= hb.BARS_NEEDED // 2
    assert call["macro"].blocks_trading is False, "لا فيتو مُختلَق من غياب مزوّد"
    assert result.reason_code == "NO_SETUP"


def test_risk_state_is_re_read_every_cycle(monkeypatch):
    """الخسائر تتراكم بين الدورات — حالةٌ تُقرأ مرة واحدة تكذب بعد أول صفقة."""
    reads: list[int] = []
    monkeypatch.setattr(hb, "load_session_state", lambda *a, **k: reads.append(1) or "STATE")
    state = build_state(monkeypatch)
    monkeypatch.setattr(hb, "load_session_state", lambda *a, **k: reads.append(1) or "STATE")
    run_once(state)
    state.scheduler.jobs[hb.DECISION_JOB].next_run_utc = now_utc()
    run_once(state)
    assert len(reads) == 2


# --- القيد البنيوي ------------------------------------------------------

def test_the_decision_job_is_analysis_never_mutating(monkeypatch):
    state = build_state(monkeypatch)
    assert state.scheduler.jobs[hb.DECISION_JOB].kind is JobKind.ANALYSIS


def test_the_scheduler_refuses_a_mutating_job_at_registration(monkeypatch):
    """المنع عند التسجيل لا عند التشغيل — قيد بنيوي لا سلوكي."""
    state = build_state(monkeypatch)
    with pytest.raises(UnsafeScheduledJob):
        state.scheduler.register(
            "sender", kind=JobKind.MUTATING, interval=timedelta(seconds=1), func=lambda: None
        )


def test_a_failing_cycle_does_not_stop_later_cycles(monkeypatch):
    """خادمٌ يموت لأن تقييماً فشل أسوأ من تقييم فاشل."""
    state = build_state(monkeypatch)
    boom = SimpleNamespace(health_check=lambda: (_ for _ in ()).throw(ValueError("boom")))
    state.broker = boom
    run_once(state)
    state.broker = FakeBroker()
    state.scheduler.jobs[hb.DECISION_JOB].next_run_utc = now_utc()
    result = run_once(state)
    assert result.reason_code == "NO_SETUP", "الحلقة تعافت"
