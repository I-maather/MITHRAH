"""
تجربة الحساب التجريبي — **مقفلة عن الحقيقي بالبنية**.

هذا الملف يفترض سوء النيّة والسهو معاً: بيئةٌ مضبوطة بالكامل لتشغيل
استراتيجيةٍ غير معتمدة، ووسيطٌ حقيقي. والمطلوب أن **لا يقع شيء**.

## لماذا وُجدت التجربة أصلاً

الخط لا يشغّل إلا `APPROVED`، وعددها صفر — فالنظام على التجريبي لا يفتح
صفقة أبداً. والحلّ الخاطئ الواضح: تغيير حالة الاستراتيجية إلى `APPROVED`،
وهو يفتحها على الحسابين معاً ويجعل الاعتماد تعديلَ سطر.

فالاعتماد التجريبي ليس حالةً بل قائمة أسماء، تُلغى بالكامل ما لم يقل
الوسيط إنه تجريبي **صراحةً**.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.runtime.demo_trial import (
    DEMO_TRIAL_ENV,
    DEMO_TRIAL_REFERENCE_ENV,
    DEMO_TRIAL_RESOLUTION_ENV,
    DEMO_TRIAL_STRATEGIES_ENV,
    demo_trial_for,
    read_demo_trial,
)

FULL_ENV = {
    DEMO_TRIAL_ENV: "1",
    DEMO_TRIAL_STRATEGIES_ENV: "TREND_PULLBACK_V2,BREAKOUT_RETEST",
    DEMO_TRIAL_RESOLUTION_ENV: "HOUR",
    DEMO_TRIAL_REFERENCE_ENV: "MAATHER-2026-09-02",
}


def broker(*, is_live):
    return SimpleNamespace(is_live=is_live, name="TEST_BROKER")


# -- القراءة من البيئة -------------------------------------------------------

def test_a_complete_environment_reads_as_active():
    trial = read_demo_trial(FULL_ENV)
    assert trial.enabled and trial.active
    assert trial.strategies == {"TREND_PULLBACK_V2", "BREAKOUT_RETEST"}
    assert trial.resolution == "HOUR"


#: الشروط **اللازمة**. والدقّة ليست منها: غيابها يعني «يومية» لا «مطفأة»،
#: وهو الافتراض الأسلم — أبطأ إشارةً لا أخطر.
REQUIRED = (DEMO_TRIAL_ENV, DEMO_TRIAL_STRATEGIES_ENV, DEMO_TRIAL_REFERENCE_ENV)


@pytest.mark.parametrize("missing", REQUIRED)
def test_any_missing_piece_disables_the_whole_thing(missing):
    """ثلاثة شروط مجتمعة — وأيّ واحدٍ ناقص يُطفئ التجربة كاملةً."""
    env = {k: v for k, v in FULL_ENV.items() if k != missing}
    trial = read_demo_trial(env)
    assert not trial.active
    assert trial.note_ar, "الإطفاء بلا سببٍ مكتوب يترك المالكة تخمّن"


def test_a_missing_resolution_falls_back_to_daily_not_to_off():
    env = {k: v for k, v in FULL_ENV.items() if k != DEMO_TRIAL_RESOLUTION_ENV}
    trial = read_demo_trial(env)
    assert trial.active and trial.resolution == "DAY"


def test_an_unknown_resolution_is_refused_not_passed_to_the_broker():
    trial = read_demo_trial({**FULL_ENV, DEMO_TRIAL_RESOLUTION_ENV: "EVERY_TICK"})
    assert not trial.active
    assert "EVERY_TICK" in trial.note_ar


def test_the_reference_is_required_exactly_as_the_execution_lock_requires_it():
    # نفس شرط `ExecutionLock.authorise` — كي لا يُفتَح القفل بلا مرجع.
    trial = read_demo_trial({**FULL_ENV, DEMO_TRIAL_REFERENCE_ENV: "   "})
    assert not trial.active


# -- البوابة: الوسيط ---------------------------------------------------------

def test_a_live_broker_cancels_the_trial_completely():
    """**الفحص الذي يهمّ.** بيئةٌ كاملة + وسيطٌ حقيقي ⇒ لا شيء."""
    trial = demo_trial_for(broker(is_live=True), read_demo_trial(FULL_ENV))
    assert not trial.active
    assert trial.strategies == frozenset()
    assert "حقيقي" in trial.note_ar


def test_a_broker_that_does_not_say_is_treated_as_live():
    """
    غيابُ الصفة ليس «تجريبي» — وسيطٌ لا نعرف نوعه يُعامَل معاملة الأخطر.
    """
    trial = demo_trial_for(SimpleNamespace(name="مجهول"), read_demo_trial(FULL_ENV))
    assert not trial.active


@pytest.mark.parametrize("truthy_but_not_false", [0, "", None, "false"])
def test_only_a_literal_false_opens_the_gate(truthy_but_not_false):
    """
    `is_live == 0` و`is_live == ""` كلاهما «زائف» في بايثون — ولا يعني أيٌّ
    منهما «حساب تجريبي». الفحص على `is False` حرفاً لا على الصدق المنطقي.
    """
    trial = demo_trial_for(broker(is_live=truthy_but_not_false), read_demo_trial(FULL_ENV))
    assert not trial.active


def test_a_demo_broker_opens_it():
    trial = demo_trial_for(broker(is_live=False), read_demo_trial(FULL_ENV))
    assert trial.active
    assert trial.strategies == {"TREND_PULLBACK_V2", "BREAKOUT_RETEST"}


# -- البوابة الثانية: عند موضع الاستعمال لا عند موضع البناء ------------------

def _pipeline(*, is_live, trial_strategies):
    """
    خطٌّ بأقلّ ما يلزم — لا يُشغَّل، يُسأل عن قائمة المعتمدات وحدها.

    والحارس المفحوص هنا هو الثاني: لو بُني الخط في مسارٍ آخر بقائمة تجربة
    وهو على وسيطٍ حقيقي، وجب أن يرفض بنفسه. حارسٌ في موضع البناء وحده يمرّ
    من حوله كل من يبني الخط بنفسه.
    """
    from app.pipeline.runner import Pipeline

    class _Strategy:
        def __init__(self, name, state):
            self.metadata = SimpleNamespace(
                name=name, state=SimpleNamespace(value=state)
            )

        def evaluate(self, **_):
            return None

    return Pipeline(
        broker=SimpleNamespace(is_live=is_live, name="X"),
        risk_engine=None, kill_switch=None, audit=None, execution=None,
        strategies=[_Strategy("TREND_PULLBACK_V2", "RESEARCH"),
                    _Strategy("OLD_ONE", "DISABLED")],
        schedule=None, assumptions=None, blackouts=None,
        trial_strategies=frozenset(trial_strategies),
    )


def _selected(pipeline):
    """**يستدعي الدالّة الحقيقية** — لا ينسخ منطقها.

    أوّل كتابةٍ لهذا الملف نسخت سطر الاختيار هنا. فحين جُرّبت طفرةٌ تحذف قفل
    الوسيط من `runner.py`، بقيت هذه الفحوص خضراء: كانت تختبر النسخة لا
    الأصل. فاستُخرج المنطق إلى `Pipeline.runnable_strategies`.
    """
    return [s.metadata.name for s in pipeline.runnable_strategies()]


def test_the_pipeline_itself_refuses_the_trial_on_a_live_broker():
    p = _pipeline(is_live=True, trial_strategies={"TREND_PULLBACK_V2"})
    assert _selected(p) == []


def test_the_pipeline_runs_the_trial_strategy_on_a_demo_broker():
    p = _pipeline(is_live=False, trial_strategies={"TREND_PULLBACK_V2"})
    assert _selected(p) == ["TREND_PULLBACK_V2"]


def test_a_disabled_strategy_is_never_run_even_if_named():
    """`DISABLED` قرارُ إيقافٍ صريح — والتجربة لا تنقضه."""
    p = _pipeline(is_live=False, trial_strategies={"OLD_ONE"})
    assert _selected(p) == []


def test_without_a_trial_list_nothing_runs():
    p = _pipeline(is_live=False, trial_strategies=set())
    assert _selected(p) == []


def test_the_real_pipeline_source_still_carries_both_guards():
    """
    الفحص أعلاه ينسخ المنطق — والنسخة تُصدَّق فقط إن بقي الأصل كما هو.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app" / "pipeline" / "runner.py"
    body = source.read_text(encoding="utf-8")
    # `run` يستدعي الدالّة ولا يكرّر منطقها — وإلّا عاد الفرع الثاني بلا حارس.
    assert "approved = self.runnable_strategies()" in body
    assert body.count("trial_strategies and getattr") == 1
