"""
فحصٌ ساكن: لا دالة في `scripts/` تنادي اسماً لا وجود له.

## العطل الذي أنتج هذا الملف (2026-09-01)

فُصلت حلقةٌ من `main` إلى دالة `run_one_strategy` لتمرّ على ثلاث
استراتيجيات. وبقي في جسدها سطران يقولان `a.resolutions` و`a.transplant` —
و`a` هي وسائط سطر الأوامر، معرّفةٌ في `main` وحدها.

فانفجر السكربت **على الخادم بعد الاتصال بالوسيط**، في منتصف تشغيلٍ طُلب من
المالكة. والسبب سطران لا يحتاجان بيانات سوق ولا شبكة ليُكتشفا.

## ولماذا لم تكشفه الاختبارات

`scripts/` بلا تغطية: كلها تحتاج شبكةً وأسراراً، فلا تُشغَّل في المجموعة.
واستيرادُ الوحدة يمرّ لأن الخطأ **داخل جسد دالة** لا يُنفَّذ عند الاستيراد.

⇒ مسارٌ لا يُسلَك إلا على الخادم، فلا ينكشف إلا هناك. نفس العائلة الحاكمة —
وهذا الفحص هو الردّ عليها: يُنفَّذ ما لا يُنفَّذ، ساكناً.

## ما يفحصه بالضبط

لكل دالة: كل اسمٍ حرّ تستعمله يجب أن يكون **مبنيّاً**، أو معرَّفاً على مستوى
الوحدة، أو مسنَداً داخلها (وسيطاً كان أو استيراداً محلياً أو متغيّراً).
"""
from __future__ import annotations

import builtins
import symtable
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[2] / "scripts").glob("*.py"))
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def undefined_names(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    table = symtable.symtable(source, path.name, "exec")
    module_level = {s.get_name() for s in table.get_symbols()}
    found: list[str] = []

    def walk(scope: symtable.SymbolTable, trail: str) -> None:
        for child in scope.get_children():
            here = f"{trail}.{child.get_name()}"
            if child.get_type() == "function":
                for symbol in child.get_symbols():
                    name = symbol.get_name()
                    if symbol.is_assigned() or symbol.is_parameter():
                        continue
                    if name in BUILTINS or name in module_level:
                        continue
                    # اسمٌ من نطاقٍ محيط (دالة داخل دالة) مقبول.
                    if symbol.is_free() or symbol.is_local():
                        continue
                    found.append(f"{here}: {name}")
            walk(child, here)

    walk(table, path.stem)
    return found


def test_the_scripts_directory_is_not_empty():
    """فحصٌ يمرّ على لا شيء يمرّ دائماً — وهو أسوأ من غيابه."""
    assert len(SCRIPTS) >= 5, f"لم يُعثر إلا على {len(SCRIPTS)} سكربت"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_no_function_calls_a_name_that_exists_nowhere(script):
    """
    **العطل بعينه:** `a.resolutions` داخل دالةٍ لا تعرف `a`.

    وهو لا يُكتشف بالاستيراد لأن الخطأ في جسد دالةٍ لا تُنفَّذ، ولا بالاختبارات
    لأن هذه السكربتات تحتاج شبكةً وأسراراً فلا تُشغَّل.
    """
    problems = undefined_names(script)
    assert not problems, (
        f"أسماء لا وجود لها في {script.name}:\n  " + "\n  ".join(problems)
    )
