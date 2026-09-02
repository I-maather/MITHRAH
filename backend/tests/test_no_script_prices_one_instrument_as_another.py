"""
**لا سكربت يسعّر أداةً بنموذج أداةٍ أخرى.**

## العطل

`run_shadow.py` و`run_backtest.py` كانا يبنيان
`CapitalComCostModel(PROVISIONAL_EURUSD)` مهما كانت `--epic`.

وحجم نقطة اليورو `0.0001` وحجم نقطة الذهب `0.01` — **مئة ضعف**. وسبريد
اليورو `0.00007` وسبريد الذهب المقيس `0.75` — **عشرة آلاف ضعف**. والكمية
الدنيا 100 وحدة مقابل 0.01 أونصة.

فتشغيل `run_backtest.py --epic GOLD` كان يُخرج جدولاً كاملاً — معدّل فوز،
عامل ربح، توقّع، «صافي الربح X دولار» — وكل رقمٍ فيه خاطئ، ولا شيء يقول
ذلك.

## ولماذا لم يكن عطلاً يوم كُتب

لأن الاستراتيجيات كانت تُعلن `EURUSD` وحدها في `markets`، فلا تُنتج إشارةً
على غيرها مهما مُرِّر. ثم صارت `FX_MARKETS` أربع أدوات — **فانقلب سطرٌ
صحيح إلى سطرٍ يكذب، بلا أن يمسّه أحد**.

وهذا صنف عطبٍ لا تكشفه مراجعة السطر: يُكشف بسؤال «ما الذي تغيّر تحته؟».
فالفحص هنا ساكن، ويسأل السؤال نيابةً عنّا في كل مرّة.

## القاعدة

أي سكربت يبني نموذج تكلفة يجب أن يبنيه من `InstrumentRegistry` — أي من
**قياس الأداة التي يعمل عليها** — لا من ثابتٍ يحمل اسم أداةٍ بعينها.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
SCRIPTS = sorted(SCRIPTS_DIR.glob("*.py"))

#: ثوابت الاقتصاديات المسمّاة بأداةٍ بعينها. تُقرأ من الوحدة لا تُكتب هنا،
#: كي لا تشيخ القائمة حين يُضاف ثابتٌ جديد.
def instrument_constants() -> set[str]:
    from app.risk import capital_costs

    return {
        name
        for name, value in vars(capital_costs).items()
        if name.isupper() and type(value).__name__ == "InstrumentEconomics"
    }


def cost_model_arguments(path: Path) -> list[tuple[int, str]]:
    """كل وسيطٍ يُمرَّر إلى `CapitalComCostModel(...)` في هذا الملف."""
    tree = ast.parse(path.read_text(encoding="utf-8"), path.name)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "CapitalComCostModel":
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(arg, ast.Name):
                found.append((node.lineno, arg.id))
    return found


def test_the_constant_list_is_not_empty():
    """حارسٌ للحارس: قائمةٌ فارغة تجعل الفحص التالي يمرّ دائماً."""
    assert instrument_constants(), (
        "لم يُعثر على ثابت اقتصاديات واحد — الفحص التالي سيمرّ بلا أن يفحص."
    )


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_no_script_builds_a_cost_model_from_a_named_instrument_constant(path):
    """
    **الفحص الذي يعضّ.** لو أُعيد `CapitalComCostModel(PROVISIONAL_EURUSD)`
    إلى أي سكربت، سقط هذا فوراً — وذلك قبل أن يُخرج جدولاً واثقاً وخاطئاً
    على الذهب.
    """
    constants = instrument_constants()
    offenders = [
        f"{path.name}:{line} ⇐ {arg}"
        for line, arg in cost_model_arguments(path)
        if arg in constants
    ]
    assert not offenders, (
        "سكربت يسعّر بنموذج أداةٍ مسمّاة بدل قياس الأداة العاملة:\n  "
        + "\n  ".join(offenders)
        + "\nالمصدر الصحيح: InstrumentRegistry.cost_model_for(epic)."
    )


@pytest.mark.parametrize(
    "script", ["run_shadow.py", "run_backtest.py", "run_history_sweep.py"],
    ids=lambda s: s,
)
def test_the_three_pricing_scripts_read_the_registry(script):
    """
    ولا يكفي ألّا يُستعمل الثابت: يجب أن يُقرأ **السجلّ** فعلاً. سكربتٌ حذف
    الثابت ولم يقرأ قياساً يبقى بلا مصدر.
    """
    source = (SCRIPTS_DIR / script).read_text(encoding="utf-8")
    assert "InstrumentRegistry" in source, (
        f"{script} لا يقرأ قياس الأدوات — فمن أين يأتي حجم النقطة والسبريد؟"
    )
