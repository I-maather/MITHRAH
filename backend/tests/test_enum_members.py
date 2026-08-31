"""
لا يُذكَر عضو تعداد غير موجود.

## العطل الذي أنتج هذا الملف

ثلاثة مواضع كتبت `SourceReliability.UNRELIABLE` — وهي **غير موجودة**؛
الصحيح `UNVERIFIED`. والاسم كُتب من الذاكرة لا من التعداد.

ولم يكشفه شيء: المفسّر لا يفحص أعضاء التعداد إلا عند **تنفيذ** السطر،
والسطور الثلاثة كلها في مسارات `except` — أي لا تُنفَّذ إلا حين يُخفق
المزوّد. فبقيت نائمة حتى أوّل نداء حقيقي على الخادم، ثم انفجرت داخل معالج
خطأ: **العطل الذي يظهر وأنتِ تعالجين عطلاً**.

## ما يفحصه

كل `Enum.MEMBER` مكتوب في شجرة المصدر، مقابل أعضاء التعداد الحقيقية. فحصٌ
ساكن لا يحتاج تنفيذ السطر، فيمسك ما في مسارات الاستثناء والفروع النادرة.
"""
from __future__ import annotations

import ast
import enum
import importlib
import pkgutil
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _enum_classes() -> dict[str, type[enum.Enum] | None]:
    """
    تعدادات الحزمة مفهرسةً بالاسم — و`None` لكل اسمٍ يحمله **أكثر من تعداد**.

    في المشروع تعدادان اسمهما `Severity`: واحد للإشعارات (INFO/WARNING/
    CRITICAL) وآخر للتناقضات (CRITICAL/MAJOR/MINOR). والفهرسة بالاسم وحده
    جعلت الفحص يقيس أعضاء أحدهما بجدول الآخر، فأبلغ عن ستة أعطال لا وجود
    لها. وفحصٌ يُنذر كاذباً يُهجَر بعد ثالث إنذار، فيصير كأنه غير موجود.

    فالاسم المكرّر يُتخطّى صراحةً: تمييزُه يحتاج تتبّع الاستيرادات في كل
    ملف، وذلك ثمنٌ لا يُدفع هنا — والأسماء الفريدة تكفي لمسك ما نبحث عنه.
    """
    found: dict[str, type[enum.Enum] | None] = {}
    seen: dict[str, type] = {}
    for module in pkgutil.walk_packages([str(APP)], prefix="app."):
        try:
            mod = importlib.import_module(module.name)
        except Exception:  # noqa: BLE001
            continue  # وحدة لا تُستورد وحدها ليست موضوع هذا الاختبار
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if isinstance(obj, type) and issubclass(obj, enum.Enum) and obj is not enum.Enum:
                previous = seen.get(obj.__name__)
                if previous is None:
                    seen[obj.__name__] = obj
                    found[obj.__name__] = obj
                elif previous is not obj:
                    found[obj.__name__] = None      # اسمٌ مكرّر — لا يُقاس
    return found


def _referenced_members() -> list[tuple[Path, int, str, str]]:
    """(الملف، السطر، اسم التعداد، اسم العضو) لكل `Name.ATTR` بحروف كبيرة."""
    out: list[tuple[Path, int, str, str]] = []
    for path in APP.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id[:1].isupper()
                and node.attr.isupper()
                and node.attr.replace("_", "").isalnum()
            ):
                out.append((path, node.lineno, node.value.id, node.attr))
    return out


def test_no_reference_to_a_nonexistent_enum_member():
    enums = _enum_classes()
    assert enums, "لم يُعثر على أي تعداد — الفحص نفسه معطّل"

    problems: list[str] = []
    for path, lineno, enum_name, member in _referenced_members():
        if enum_name not in enums:
            continue                      # ليس تعداداً نعرفه
        klass = enums[enum_name]
        if klass is None:
            continue                      # اسمٌ يحمله أكثر من تعداد
        if member in klass.__members__:
            continue
        rel = path.relative_to(APP.parent)
        valid = ", ".join(sorted(klass.__members__))
        problems.append(f"{rel}:{lineno} — {enum_name}.{member} غير موجود. المتاح: {valid}")

    assert not problems, "أعضاء تعداد مُختلَقة:\n  " + "\n  ".join(problems)


def test_source_reliability_has_no_member_named_unreliable():
    """
    حارسٌ صريح على الاسم الذي أخطأنا فيه: `UNRELIABLE` تبدو صحيحة وليست كذلك،
    و`UNVERIFIED` هي المقصودة — «لا يُبنى عليه قرار».
    """
    from app.intelligence.snapshot import SourceReliability

    assert "UNRELIABLE" not in SourceReliability.__members__
    assert "UNVERIFIED" in SourceReliability.__members__
