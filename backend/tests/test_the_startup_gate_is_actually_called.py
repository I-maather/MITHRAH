"""
بوابةُ الإقلاع — **مركَّبةٌ لا مكتوبةً فحسب**.

## العيب الذي يحرسه هذا الملف

`run_startup_recovery` كُتب في 0.2 واختُبر وحدوياً: يقرأ قاطع الطوارئ الدائم،
ويبحث عن محاولات تنفيذٍ غير محسومة، ويطابق مراكزنا بمراكز الوسيط، ويقفل عند
أي شكّ. ثم لم يُستدعَ من أيّ مكان في الخادم — بحثٌ في المستودع كلّه لا يجد له
نداءً واحداً خارج اختباراته.

وهو نفس عيب طبقة الجوال قبل 0.5.6، وقد صار له اختبارٌ دائم يومها بالجملة
نفسها: **اختبارُ الوحدة يثبت أن القطعة صحيحة، ولا يثبت أنها مركَّبة.**

فهنا اختباران متكاملان: أنّ الخادم يستدعيها عند الإقلاع فعلاً، وأنّ حكمها
يمنع الدخول ولا يمنع المراقبة.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.recovery import StartupReport, StartupVerdict
from app.runtime.startup import STARTUP_RECONCILIATION_PENDING, blocks_new_entries
from tests.runtime_fixtures import blocking_startup, passing_startup


# --- ١ · الحكم ---------------------------------------------------------------


def test_a_missing_report_blocks():
    """**الغياب حجب.** تقريرٌ مفقود يعني أن الفحص لم يجرِ — لا أنه نجح."""
    assert blocks_new_entries(SimpleNamespace()) is not None
    assert blocks_new_entries(SimpleNamespace(startup=None)) is not None


def test_a_passing_report_opens_the_gate():
    assert blocks_new_entries(SimpleNamespace(startup=passing_startup())) is None


def test_a_reconciliation_problem_is_quoted_not_summarised():
    reason = "مركز غير معروف لدينا موجود في حساب الوسيط: GOLD كمية -0.01."
    message = blocks_new_entries(SimpleNamespace(startup=blocking_startup(reason)))
    assert message is not None and reason in message


def test_a_persistent_kill_switch_blocks_after_a_restart():
    report = StartupReport(
        verdict=StartupVerdict.LOCKED_KILL_SWITCH,
        trading_locked=True, kill_switch_active=True, risk_mode="VALIDATION",
    )
    message = blocks_new_entries(SimpleNamespace(startup=report))
    assert message is not None and "قاطع الطوارئ" in message


def test_an_unresolved_execution_blocks_and_forbids_resending():
    report = StartupReport(
        verdict=StartupVerdict.LOCKED_UNKNOWN_EXECUTION,
        trading_locked=True, kill_switch_active=False, risk_mode="VALIDATION",
        unresolved_attempts=["idem-1", "idem-2"],
    )
    message = blocks_new_entries(SimpleNamespace(startup=report))
    assert message is not None
    assert "2" in message
    # الرسالة نفسها تمنع العلاج الخاطئ: إعادة الإرسال تُنشئ أمراً ثانياً.
    assert "إعادة الإرسال" in message


# --- ٢ · التركيب في الدورة ---------------------------------------------------


def _cycle_state(monkeypatch, *, startup):
    """حالةٌ أدنى ما يكفي لتشغيل دورةٍ واحدة."""
    from decimal import Decimal

    import app.runtime.heartbeat as hb
    from app.scheduling import SafeScheduler

    class _Broker:
        calls = 0

        def list_open_positions_detailed(self):
            type(self).calls += 1
            return []

        def list_recent_transactions(self):
            return []

        def get_orders(self, account_id=""):
            return []

        def get_balances(self, account_id=""):
            return SimpleNamespace(account_id="TEST", total_cash=Decimal("140"))

        def health_check(self):
            return True

    monkeypatch.setattr(hb, "register_runtime_jobs", hb.register_runtime_jobs)
    broker = _Broker()
    type(broker).calls = 0
    state = SimpleNamespace(
        locally_paused=False,
        broker=broker,
        kill_switch=SimpleNamespace(is_active=False, state=SimpleNamespace(current_event=None)),
        limits=SimpleNamespace(allowed_instruments=frozenset({"EURUSD"}), baseline_equity=Decimal("140")),
        db_session=None, last_bars={}, pipeline=None,
        scheduler=SafeScheduler(), session_state=None, last_result=None,
        startup=startup,
    )
    hb.register_runtime_jobs(state, interval_seconds=1)
    return state, broker


def test_a_blocked_gate_stops_entries_but_not_monitoring(monkeypatch):
    """
    الحجب يمنع **الدخول** لا **الرؤية**. مركزٌ لا يُرى لا يُدار، ومركزٌ لا
    يُدار ليس موقوفاً — هو متروك. وهذا ما وقع فعلاً يوم بقيت خمسةُ مراكز
    ساعاتٍ بلا مراقبة.
    """
    state, broker = _cycle_state(monkeypatch, startup=blocking_startup())
    state.scheduler.tick()

    assert state.last_result is not None
    assert state.last_result.reason_code == STARTUP_RECONCILIATION_PENDING
    assert broker.calls >= 1, "المحفظة تُقرأ رغم الحجب"
    assert state.portfolio is not None


def test_the_gate_runs_before_any_entry_is_evaluated(monkeypatch):
    """لا خطَّ قرارٍ يُستدعى ما دامت البوابة مغلقة."""
    state, _ = _cycle_state(monkeypatch, startup=blocking_startup())

    class _Exploding:
        def run(self, *a, **k):
            raise AssertionError("لا يجوز أن يُستدعى الخط والبوابة مغلقة")

    state.pipeline = _Exploding()
    state.scheduler.tick()
    assert state.last_result.reason_code == STARTUP_RECONCILIATION_PENDING


# --- ٣ · النداء عند الإقلاع ---------------------------------------------------


def test_the_server_actually_calls_the_gate_on_startup(monkeypatch):
    """
    **العيب بعينه.** لا يكفي أن يمرّ اختبارُ الوحدة على `run_startup_recovery`؛
    السؤال هل يستدعيها الخادم. هنا تُشغَّل دورةُ حياة التطبيق ويُفحَص الأثر.
    """
    import app.main as main_module

    called: list[object] = []

    def _fake_gate(state):
        called.append(state)
        state.startup = passing_startup()
        return state.startup

    monkeypatch.setattr("app.runtime.startup.run", _fake_gate)

    state = SimpleNamespace()
    monkeypatch.setattr(main_module, "system", lambda: state)
    monkeypatch.setattr(main_module, "register_runtime_jobs", lambda *a, **k: None)

    class _Beat:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        async def stop(self):
            pass

    monkeypatch.setattr(main_module, "Heartbeat", _Beat)

    import asyncio

    async def _drive():
        async with main_module._lifespan(SimpleNamespace(state=SimpleNamespace())):
            pass

    asyncio.run(_drive())

    assert called, "الخادم لم يستدعِ بوابة الإقلاع عند الإقلاع"
    assert getattr(state, "startup", None) is not None
