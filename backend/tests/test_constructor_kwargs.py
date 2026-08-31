"""
لا يُمرَّر وسيطٌ باسمٍ لا يملكه الصنف.

## العطل الذي أنتج هذا الملف

خمسة مواضع بنت `Sourced(...)` بوسيطٍ اسمه `observed_at_utc` — **وهو غير
موجود**. الصنف يحمل زمنين: `source_timestamp_utc` (متى رُصدت القيمة عند
مصدرها) و`retrieved_at_utc` (متى جلبناها). فاختُرع اسمٌ ثالث يجمعهما،
وسقط الوسيطان الحقيقيان — وكلاهما مطلوب.

ولم يكشفه شيء: بايثون لا تفحص أسماء الوسائط إلا عند **تنفيذ** السطر،
والخمسة في مسار مزوّدٍ لم يُستدعَ في اختبارٍ واحد. فناموا حتى أوّل نداء
حقيقي على الخادم.

**والأسوأ أنهم كانوا مختبئين خلف عطل آخر:** `SourceReliability.UNRELIABLE`
كانت تنفجر في السطر السابق لهم، فلمّا أُصلحت ظهر هذا. عطلٌ يحجب عطلاً —
ولذلك لا يكفي إصلاح الحالة، بل يُبنى فحصٌ يمسح الصنف كلّه دفعةً واحدة.

## علاقته بـ`test_enum_members.py`

نفس العائلة: **اسمٌ كُتب من الذاكرة لا من التعريف**، في مسارٍ لا يُنفَّذ.
ذاك يمسح أعضاء التعدادات، وهذا يمسح حقول أصناف البيانات.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import pkgutil
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _dataclasses_by_name() -> dict[str, type]:
    """
    كل أصناف البيانات في الحزمة، مفهرسةً بالاسم.

    الأسماء المكرّرة تُسقَط: صنفان بالاسم نفسه في وحدتين يجعلان المطابقة
    بالاسم تخميناً، والتخمين هنا يُنتج إنذاراً كاذباً — وهو أسوأ من فحصٍ
    أضيق، لأنه يعلّم القارئ تجاهل الفحص.
    """
    found: dict[str, type] = {}
    duplicates: set[str] = set()
    for module in pkgutil.walk_packages([str(APP)], prefix="app."):
        try:
            mod = importlib.import_module(module.name)
        except Exception:  # noqa: BLE001
            continue
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if not isinstance(obj, type) or not dataclasses.is_dataclass(obj):
                continue
            existing = found.get(obj.__name__)
            if existing is not None and existing is not obj:
                duplicates.add(obj.__name__)
            found.setdefault(obj.__name__, obj)
    for name in duplicates:
        found.pop(name, None)
    return found


def _accepted_names(klass: type) -> set[str]:
    """الحقول التي يقبلها المُنشئ — الموروثة منها، وبلا `init=False`."""
    return {f.name for f in dataclasses.fields(klass) if f.init}


def _keyword_calls() -> list[tuple[Path, int, str, str]]:
    """(الملف، السطر، اسم الصنف، اسم الوسيط) لكل نداء `Name(kw=...)`."""
    out: list[tuple[Path, int, str, str]] = []
    for path in APP.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            for keyword in node.keywords:
                if keyword.arg is None:  # ‎**kwargs — لا يُفحَص اسمُه
                    continue
                out.append((path, node.lineno, node.func.id, keyword.arg))
    return out


def test_no_call_passes_a_field_the_dataclass_does_not_have():
    known = _dataclasses_by_name()
    assert known, "لم يُعثر على أي صنف بيانات — الفحص نفسه معطّل"

    problems: list[str] = []
    for path, lineno, class_name, keyword in _keyword_calls():
        klass = known.get(class_name)
        if klass is None:
            continue  # ليس صنف بيانات نعرفه — خارج نطاق هذا الفحص
        accepted = _accepted_names(klass)
        if keyword in accepted:
            continue
        rel = path.relative_to(APP.parent)
        problems.append(
            f"{rel}:{lineno} — {class_name}(...) لا يقبل «{keyword}». "
            f"المتاح: {', '.join(sorted(accepted))}"
        )

    assert not problems, "وسائط مُختلَقة:\n  " + "\n  ".join(problems)


def test_sourced_keeps_its_two_distinct_timestamps():
    """
    حارسٌ صريح على الاسم الذي أخطأنا فيه.

    ودمجُ الزمنين ليس تبسيطاً بل عطلٌ في الأمان: `age_seconds` تُحسب من
    **لحظة الرصد**، فلو حملت وقت الجلب لقال النظام إن سعر فائدةٍ نُشر قبل
    ثلاثة أشهر عمرُه ثوانٍ — ولمرّ حارس الطزاجة على بيانٍ بائت.
    """
    from app.intelligence.snapshot import Sourced

    names = _accepted_names(Sourced)
    assert "source_timestamp_utc" in names
    assert "retrieved_at_utc" in names
    assert "observed_at_utc" not in names
