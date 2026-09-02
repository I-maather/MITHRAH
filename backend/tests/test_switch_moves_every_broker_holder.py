"""
تبديل الحساب يجب أن يبدّله **في كل موضعٍ يحمله**.

## العطل

`_mobile_switch_environment` كان يكتب `sys_state.broker` وحده. والخط
(`pipeline.broker`) وخدمة التنفيذ (`execution.broker`) يحملان مرجعهما
الخاص المضبوط عند الإقلاع.

    الشاشة تقرأ من الحساب الجديد · والقرار والتنفيذ على القديم.

والاتجاه الخطير واضح: تبديلٌ من الحقيقي إلى التجريبي يُري المالكة «تجريبي»
بينما النظام ما زال ينفّذ على حسابها الحقيقي.

وهو العطل الحاكم بصورةٍ تاسعة: نسختان لحقيقةٍ واحدة تفترقان.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.brokers.capital.safety import ExecutionLock
from app.main import _install_broker


def state():
    old = SimpleNamespace(is_live=False, name="OLD", execution_lock=ExecutionLock.locked())
    return SimpleNamespace(
        broker=old,
        pipeline=SimpleNamespace(broker=old, trial_strategies=frozenset({"TREND_PULLBACK_V2"})),
        execution=SimpleNamespace(broker=old),
        demo_trial_note_ar="",
    )


def test_every_holder_moves_together():
    sys_state = state()
    new = SimpleNamespace(is_live=False, name="NEW", execution_lock=ExecutionLock.locked())
    _install_broker(sys_state, new)
    assert sys_state.broker is new
    assert sys_state.pipeline.broker is new
    assert sys_state.execution.broker is new


def test_switching_to_live_drops_the_demo_trial():
    """
    إذن التجربة لا يُحمَل إلى الحساب الحقيقي. والقائمة تُفرَّغ، فلا تُقيَّم
    استراتيجيةٌ غير معتمدة على مالٍ حقيقي.
    """
    sys_state = state()
    live = SimpleNamespace(is_live=True, name="LIVE", execution_lock=ExecutionLock.locked())
    _install_broker(sys_state, live)
    assert sys_state.pipeline.trial_strategies == frozenset()


def test_switching_to_live_leaves_execution_locked():
    sys_state = state()
    live = SimpleNamespace(is_live=True, name="LIVE", execution_lock=ExecutionLock.locked())
    _install_broker(sys_state, live)
    assert live.execution_lock.unlocked is False


def test_the_note_says_why_the_trial_was_cancelled(monkeypatch):
    """
    «مطفأة» وحدها لا تقول شيئاً. والسبب هنا هو الوسيط — فيُكتب.
    وتُضبط البيئة كاملةً كي يكون **الوسيطُ** هو ما ألغى التجربة، لا نقصٌ
    في الإعداد: فحصٌ يمرّ لأن العلم مطفأ أصلاً لا يفحص البوّابة.
    """
    from app.runtime.demo_trial import (
        DEMO_TRIAL_ENV,
        DEMO_TRIAL_REFERENCE_ENV,
        DEMO_TRIAL_STRATEGIES_ENV,
    )

    monkeypatch.setenv(DEMO_TRIAL_ENV, "1")
    monkeypatch.setenv(DEMO_TRIAL_STRATEGIES_ENV, "TREND_PULLBACK_V2")
    monkeypatch.setenv(DEMO_TRIAL_REFERENCE_ENV, "REF-1")

    sys_state = state()
    live = SimpleNamespace(is_live=True, name="LIVE", execution_lock=ExecutionLock.locked())
    _install_broker(sys_state, live)
    assert "حقيقي" in sys_state.demo_trial_note_ar
    assert sys_state.pipeline.trial_strategies == frozenset()


def test_a_demo_broker_keeps_the_trial_and_reopens_the_lock(monkeypatch):
    from app.runtime.demo_trial import (
        DEMO_TRIAL_ENV,
        DEMO_TRIAL_REFERENCE_ENV,
        DEMO_TRIAL_STRATEGIES_ENV,
    )

    monkeypatch.setenv(DEMO_TRIAL_ENV, "1")
    monkeypatch.setenv(DEMO_TRIAL_STRATEGIES_ENV, "TREND_PULLBACK_V2")
    monkeypatch.setenv(DEMO_TRIAL_REFERENCE_ENV, "REF-1")

    sys_state = state()
    demo = SimpleNamespace(is_live=False, name="DEMO2", execution_lock=ExecutionLock.locked())
    _install_broker(sys_state, demo)
    assert sys_state.pipeline.trial_strategies == {"TREND_PULLBACK_V2"}
    # المحوّل الجديد يُبنى مغلقاً؛ والتجربة الصالحة تعيد فتحه.
    assert demo.execution_lock.unlocked is True


def test_no_other_place_assigns_the_broker_on_a_switch():
    """
    الحارس يبقى صحيحاً ما دام موضع التركيب واحداً. وكتابةٌ ثانية لـ
    `sys_state.broker` في مسار التبديل تعيد الافتراق.
    """
    from pathlib import Path

    body = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    # الإسناد الوحيد داخل الدالّة نفسها، والنداء الوحيد من مسار التبديل.
    assert body.count("sys_state.broker = candidate") == 1
    # مرّتان: التعريف والنداء الوحيد.
    assert body.count("_install_broker(sys_state, candidate)") == 2
    helper = body[body.index("def _install_broker"): body.index("def _mobile_switch_environment")]
    assert "sys_state.broker = candidate" in helper
