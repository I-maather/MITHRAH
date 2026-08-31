"""
دورة الأمر كاملة — **لا يُفتح ما لا يُغلق**.

## العطل الذي أنتج هذا الملف

وثيقة الأدلة كتبت بالاسم أن أربع دوال غير مكتوبة: الإرسال والإلغاء والإغلاق
والتعديل. **وكُتب الإرسال وحده.**

فصار النظام يستطيع — من حيث المبدأ — أن يفتح مركزاً، ولا يستطيع أن يغلقه.
ونظامٌ يفتح ولا يغلق **أخطر من نظام لا يفعل شيئاً**، لأن نصفه العامل هو
النصف الذي يدخل السوق.

ولم يكشفه اختبار: `test_cancel_close_and_update_are_blocked` كان يمرّ
بامتياز — لأن `NotImplementedError` يقع **بعد** `assert_can_execute`، فالقفل
يرفع `ExecutionLocked` أوّلاً والاختبار يراه ناجحاً. أي أن غياب الجسد كان
**مخفياً خلف الحارس**.

## القاعدة المكتوبة هنا

مسار الفتح لا يُسمح له بالوجود ما لم يوجد مسار الإغلاق. فحصٌ ساكن، لأن
الانحدار هنا صامت: تُكتب دالة إرسال جديدة يوماً وتُنسى نظيرتها، ويحرسها
القفل حتى يُرفع — فينكشف الغياب في أسوأ لحظة.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.brokers.capital.adapter import CapitalComAdapter

ADAPTER_SOURCE = Path(inspect.getfile(CapitalComAdapter))


def body_of(method_name: str) -> ast.FunctionDef:
    tree = ast.parse(ADAPTER_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return node
    raise AssertionError(f"لا دالة باسم {method_name} في المحوّل")


def raises_not_implemented(method_name: str) -> bool:
    return any(
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "NotImplementedError"
        for node in ast.walk(body_of(method_name))
    )


# ---------------------------------------------------------------------------
def test_the_closing_half_of_the_lifecycle_exists():
    """**القاعدة.** ما دام الفتح مكتوباً، فالإغلاق والإلغاء مكتوبان."""
    if raises_not_implemented("place_order"):
        pytest.skip("مسار الفتح غير مكتوب — لا يُطالَب بنظيره بعد.")

    missing = [
        name for name in ("close_position", "cancel_order")
        if raises_not_implemented(name)
    ]
    assert not missing, (
        "مسار الفتح مكتوب ونظيره ليس كذلك: " + "، ".join(missing) + ". "
        "نظامٌ يفتح ولا يغلق أخطر من نظام لا يفعل شيئاً."
    )


@pytest.mark.parametrize("name", ["place_order", "close_position", "cancel_order"])
def test_every_mutating_path_asks_the_lock_first(name):
    """
    القفل يُسأل **قبل** أي عمل. سؤالُه بعد بناء الحمولة أو بعد نداء شبكي
    يجعل جزءاً من العمل يقع على مسارٍ يُفترض أنه مقفل.
    """
    node = body_of(name)
    source = ast.get_source_segment(ADAPTER_SOURCE.read_text(encoding="utf-8"), node) or ""
    lines = [line.strip() for line in source.splitlines()]
    guards = [
        i for i, line in enumerate(lines)
        if "assert_can_execute" in line or "_assert_executable" in line
    ]
    assert guards, f"{name} لا يسأل قفل التنفيذ إطلاقاً"

    sends = [
        i for i, line in enumerate(lines)
        if line.startswith(("body = self._post", "body = self._delete",
                            "self._post", "self._delete"))
    ]
    if sends:
        assert min(guards) < min(sends), f"{name} يرسل قبل أن يسأل القفل"


@pytest.mark.parametrize("name", ["place_order", "close_position", "cancel_order"])
def test_every_mutating_path_refuses_the_live_environment(name):
    """
    دفاعٌ في العمق مستقلّ عن القفل: البيئة الحقيقية مرفوضة في هذا الإصدار
    مهما كانت حالة الأقفال الأخرى.
    """
    source = ast.get_source_segment(
        ADAPTER_SOURCE.read_text(encoding="utf-8"), body_of(name)
    ) or ""
    assert "LiveApiBlocked" in source, f"{name} لا يرفض البيئة الحقيقية صراحةً"


@pytest.mark.parametrize("name", ["place_order", "close_position", "cancel_order"])
def test_every_mutating_path_proves_the_outcome_before_claiming_it(name):
    """
    استجابة الوسيط ليست إثبات تنفيذ. الدليل الوحيد `GET /confirms`.

    ومسارٌ يعيد نجاحاً بلا تأكيد هو نفس عائلة زرّ الإيقاف الذي كان يقول
    «تمّ» ولا يفعل — إلا أن ثمنه هنا مالٌ لا سكوت.
    """
    source = ast.get_source_segment(
        ADAPTER_SOURCE.read_text(encoding="utf-8"), body_of(name)
    ) or ""
    assert "poll_confirmation" in source, f"{name} يدّعي نتيجة بلا تأكيد"
    assert "CapitalExecutionUncertain" in source, (
        f"{name} لا يعيد الغموض صريحاً — والغموض المبتلَع أخطر من الفشل"
    )


def test_closing_reconciles_against_the_position_list():
    """
    تأكيدٌ يقول «قُبل» لا يكفي للإغلاق: **يجب أن يختفي المركز فعلاً**.
    ومركزٌ باقٍ بعد إغلاقٍ «ناجح» هو أخطر ما يمكن أن يُصدَّق.
    """
    source = ast.get_source_segment(
        ADAPTER_SOURCE.read_text(encoding="utf-8"), body_of("close_position")
    ) or ""
    assert source.count("list_positions") >= 2, (
        "الإغلاق لا يقارن قائمة المراكز قبلَ وبعد — فلا يثبت أن المركز أُغلق"
    )


def test_no_mutating_path_retries_after_an_ambiguous_send():
    """
    طلبٌ قد يكون وصل لا يُعاد. إعادةُ إرسال تفتح مركزاً ثانياً، وإعادةُ
    إغلاقٍ وقع تفتح مركزاً معاكساً.
    """
    source = ADAPTER_SOURCE.read_text(encoding="utf-8")
    for method in ("_post", "_delete"):
        node = body_of(method)
        segment = ast.get_source_segment(source, node) or ""
        assert "لا تجديد ولا إعادة محاولة" in segment or "لا إعادة محاولة" in segment, (
            f"{method} لا يُعلن قاعدة «لا إعادة محاولة»"
        )
