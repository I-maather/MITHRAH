"""
تقرير الصحة يُقاس ولا يُدَّعى.

## العطل الذي أنتج هذا الملف

`scheduler_ok=True` كان **مثبَّتاً في الكود**. أي أن الخادم يقول «المجدول
سليم» عن مجدولٍ فارغ لم يُسجَّل فيه شيء، وعن مهامٍّ تُخفق في كل نبضة.

وكلّفنا ذلك في أوّل عطلٍ حقيقي: قال `/api/health` إن الوسيط **غير متصل**
وإن المجدول **سليم** — فلم يكن ثمّة ما يقول أسُجِّلت مهمّة إبقاء الجلسة
أصلاً، أم سُجِّلت وتُخفق، أم لم يبدأ النبض من أساسه. ثلاث علل مختلفة
تماماً، ولكلٍّ إصلاح مختلف، والتقرير يُخفيها كلّها خلف كلمة «سليم».

وهذا هو صنف العطل الحاكم لهذا المشروع بعينه: **حقلٌ يُعرَض ولا يُقاس من
مصدره** — ووقوعه في *تقرير الصحة نفسه* أسوأ مواقعه، لأنه العدسة التي
نفحص بها كل شيء آخر.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.scheduling import JobKind, SafeScheduler


class Boom(RuntimeError):
    pass


def scheduler_with(*, jobs: int = 1, failing: bool = False) -> SafeScheduler:
    scheduler = SafeScheduler()
    for index in range(jobs):
        scheduler.register(
            f"job-{index}",
            kind=JobKind.READ_ONLY,
            interval=timedelta(seconds=60),
            func=(lambda: (_ for _ in ()).throw(Boom("boom"))) if failing else (lambda: None),
        )
    return scheduler


def health_of(system) -> object:
    return system.health()


class FakeBroker:
    name = "FAKE"
    is_live = False

    def health_check(self) -> bool:
        return False


@pytest.fixture()
def system(monkeypatch):
    """نظامٌ حقيقي بمجدولٍ يُحقَن — بلا شبكة ولا وسيط."""
    from app.api.state import build_system

    state = build_system()
    state.broker = FakeBroker()          # type: ignore[assignment]
    return state


def test_an_empty_scheduler_is_not_healthy(system):
    """**العطل بعينه.** مجدولٌ فارغ يعني أن النبض لم يبدأ."""
    system.scheduler = SafeScheduler()
    report = health_of(system)
    assert report.scheduler_ok is False
    assert any("المجدول فارغ" in d for d in report.details_ar)


def test_a_scheduler_whose_jobs_fail_is_not_healthy(system):
    system.scheduler = scheduler_with(failing=True)
    system.scheduler.tick()
    report = health_of(system)
    assert report.scheduler_ok is False
    assert any("أخفقت" in d for d in report.details_ar)


def test_a_scheduler_that_ran_cleanly_is_healthy(system):
    system.scheduler = scheduler_with()
    system.scheduler.tick()
    report = health_of(system)
    assert report.scheduler_ok is True


def test_a_registered_job_that_never_ran_is_named(system):
    """
    «مسجَّلة ولم تُشغَّل» حالةٌ ثالثة تختلف عن الفراغ وعن الإخفاق: النبض
    سُجِّل ولم يدر. وخلطُها بأيّهما يُرسل القارئ إلى المكان الخطأ.
    """
    system.scheduler = scheduler_with()
    report = health_of(system)
    assert any("لم تُشغَّل بعد" in d for d in report.details_ar)


def test_the_broker_reason_reaches_the_health_report(system):
    """
    «الوسيط غير متصل» وحدها ترسل المالكة تبحث في سجلات خادمٍ لا تصلها —
    عن سببٍ يعرفه النظام ولا يقوله.
    """
    system.broker_note_ar = "تعذّر الوصل عند الإقلاع (ConnectionError)."
    report = health_of(system)
    assert any("تعذّر الوصل عند الإقلاع" in d for d in report.details_ar)


def test_no_health_field_is_a_hardcoded_true():
    """
    فحصٌ ساكن: لا حقل في تقرير الصحة يُسنَد إليه `True` نصّاً.

    الانحدار هنا صامت — يُضاف حقلٌ جديد بقيمة مؤقتة «حتى نقيسه لاحقاً»،
    ولا يأتي لاحقاً أبداً. و`clock_ok` باقٍ استثناءً معلوماً: ساعة العملية
    ليست موضع شكّ، ويُقاس انحرافها في مكان آخر.
    """
    import ast
    import inspect

    from app.api.state import SystemState

    source = inspect.getsource(SystemState.health)
    tree = ast.parse(source.lstrip())
    hardcoded = [
        node.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg
        and node.arg.endswith("_ok")
        and isinstance(node.value, ast.Constant)
        and node.value.value is True
    ]
    assert hardcoded == ["clock_ok"], (
        "حقول صحة مثبَّتة على True بلا قياس: " + "، ".join(hardcoded)
    )
