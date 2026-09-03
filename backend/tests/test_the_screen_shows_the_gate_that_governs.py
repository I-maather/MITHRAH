"""
بوابةٌ تُعرَض ولا تحكم، تحجب البوابة التي تحكم.

## العطل

`LIVE_TRADING=false` مثبّتةٌ في وحدة الخدمة على الخادم ولا يمسّها شيء —
بقصد، فهي حارس الحساب **الحقيقي**. وكانت تُدرَج في `blocked_by` دائماً.

فكانت الشاشة الرئيسية تقول للمالكة كل يوم:

    التداول ممنوع — التداول الحقيقي مُعطَّل

وهي على الحساب **التجريبي**، حيث لا شأن لهذه الراية بشيء: مسار التنفيذ
لا يقرأها إطلاقاً — الفحص الوحيد المتعلّق بها
(`allow_live_submission`) لا يُطبَّق إلا حين `broker.is_live`.

أي أن المحرّك كان سيرسل، والشاشة تقول ممنوع. ففتحت التطبيق أياماً تقرأ
منعاً لا يحكم شيئاً، بينما سبب غياب الصفقات في موضعٍ آخر تماماً.

## الصنف

هو صنف المشروع الحاكم في أضرّ صوره: القيمة المعروضة صحيحةٌ في ذاتها
(الراية `false` فعلاً)، لكنها **تُعرَض عن مسارٍ غير المسار الجاري** —
فتحجب بضجيجها البوابةَ التي تحكم فعلاً.

## القاعدة

البوابة تُعرَض للمسار الذي نحن فيه. وحارس الحقيقي يبقى كما هو للحقيقي.
"""
from __future__ import annotations

import pytest


class Broker:
    name = "FAKE"

    def __init__(self, *, is_live: bool) -> None:
        self.is_live = is_live

    def health_check(self) -> bool:
        return True


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.api.state import build_system
    from app.main import app, system as system_dep

    state = build_system()
    app.dependency_overrides[system_dep] = lambda: state
    try:
        yield TestClient(app), state
    finally:
        app.dependency_overrides.pop(system_dep, None)


def gates_of(state, market_open: bool = True):
    from app.main import _trading_gates

    market = type("M", (), {"is_open": market_open})()
    return _trading_gates(state, market)


def test_a_demo_broker_is_not_told_the_live_switch_is_off(client):
    """**العطل بعينه.** الراية تخصّ الحقيقي، والحساب تجريبي."""
    _, state = client
    state.broker = Broker(is_live=False)
    state.settings.live_trading = False
    assert "التداول الحقيقي مُعطَّل" not in gates_of(state)["blocked_by"]


def test_a_live_broker_is_still_guarded_by_it(client):
    """
    ولم يُضعَّف حارس المال الحقيقي — هو موضعه الصحيح. وصياغةُ السبب
    محروسةٌ هنا بعد أن انتقلت من `test_api.py`: يُكتب **سبب المنع** لا
    **الشرط المطلوب**، فلا تقرأ المالكة «ممنوع بسبب: التداول مُفعَّل».
    """
    _, state = client
    state.broker = Broker(is_live=True)
    state.settings.live_trading = False
    blocked = gates_of(state)["blocked_by"]
    assert "التداول الحقيقي مُعطَّل" in blocked
    assert "التداول الحقيقي مُفعَّل" not in blocked


def test_a_broker_that_will_not_say_is_treated_as_live(client):
    """
    الغياب لا يُقرأ تجريبياً. وسيطٌ لا يقول `is_live is False` صراحةً
    يُعامَل معاملة الحقيقي — يفشل مغلقاً.
    """
    _, state = client
    state.broker = Broker(is_live=None)  # type: ignore[arg-type]
    state.settings.live_trading = False
    assert "التداول الحقيقي مُعطَّل" in gates_of(state)["blocked_by"]


def test_the_other_gates_are_untouched_on_demo(client):
    """
    **حارسٌ للحارس.** لو صار المسار التجريبي يفتح كل شيء لصار الإصلاح
    فتحاً لا تصحيحاً. البوابات الأخرى تبقى تحكم على التجريبي.
    """
    _, state = client
    state.broker = Broker(is_live=False)
    state.locally_paused = True
    blocked = gates_of(state, market_open=False)["blocked_by"]
    assert "التشغيل موقوف محلياً" in blocked
    assert "السوق مغلق" in blocked
    assert "قفل التنفيذ مغلق" in blocked
    assert gates_of(state, market_open=False)["trading_allowed"] is False


def test_a_clean_demo_setup_is_actually_allowed(client):
    """
    **وبلا هذا الفحص، ما سبقه بلا معنى:** لو بقيت بوابةٌ أخرى مغلقةً
    أبداً لظلّت الشاشة تقول «ممنوع» ولو أُصلحت هذه.
    """
    from datetime import datetime, timezone

    from app.brokers.capital.safety import ExecutionLock

    _, state = client
    state.broker = Broker(is_live=False)
    state.settings.live_trading = False
    state.locally_paused = False
    state.execution_lock = ExecutionLock.locked().authorise(
        owner_authorization_reference="TEST-REF",
        reason_ar="فحصٌ آليّ لبوابات الشاشة لا غير.",
        at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    result = gates_of(state, market_open=True)
    assert result["trading_allowed"] is True, result["blocked_by"]
