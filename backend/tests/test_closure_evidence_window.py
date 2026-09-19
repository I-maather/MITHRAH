"""
نافذةُ دليل الإغلاق — اختبارُ انحدار.

في ١٩ سبتمبر ٢٠٢٦ بقي النظام مقفولاً أربعة أيام: `ledger.sync` تطلب دليلَ
إغلاقٍ من دفتر المعاملات قبل أن تكتب `CLOSED` — وهذا صواب — لكنّ الدليل كان
يُطلب من نافذة ٢٤ ساعة والمركزان أُغلقا قبل ٧٢. فلم يُوجد الدليلُ أبداً، وبلغ
عدّادُ الغياب ١٣٤، وبقيت بوّابةُ الإقلاع مقفلة.

وسقفُ `lastPeriod` عند هذا الوسيط يومٌ واحد؛ ما زاد يُردّ بـ400
`error.invalid.lastPeriod`. والصيغةُ التي تُجيب لما زاد قيست على الديمو:

    from=2026-09-14T00:00:00      → 200 ببيانات
    from=2026-09-14T00:00:00Z     → 400
    from=2026-09-14               → 400

فهذه الاختبارات تحرس الصيغةَ والنافذة معاً. وأيُّ تعديلٍ يُعيد النافذة إلى
يومٍ واحد يُسقطها — وهو المقصود.
"""
from __future__ import annotations

import inspect
import re

import app.brokers.capital.adapter as adapter_module

DAY = 86400


def _adapter_class():
    for value in vars(adapter_module).values():
        if isinstance(value, type) and hasattr(value, "list_recent_transactions"):
            return value
    raise AssertionError("لم يُعثر على محوّل Capital الذي يقرأ دفتر المعاملات.")


def _captured_query(seconds: int) -> str:
    """يلتقط الاستعلام دون أيّ اتصالٍ بالشبكة."""
    calls: list[str] = []
    obj = object.__new__(_adapter_class())
    obj._require_connection = lambda: None
    obj._get = lambda path: (calls.append(path), {"transactions": []})[1]
    obj.list_recent_transactions(last_period_seconds=seconds)
    assert len(calls) == 1, calls
    return calls[0].split("?", 1)[1]


def test_window_within_a_day_uses_last_period():
    assert _captured_query(DAY) == "lastPeriod=86400"
    assert _captured_query(600) == "lastPeriod=600"


def test_window_beyond_a_day_never_sends_last_period():
    query = _captured_query(30 * DAY)
    assert "lastPeriod" not in query, query
    assert query.startswith("from="), query


def test_from_is_naive_iso_seconds():
    value = _captured_query(30 * DAY)[len("from="):]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value), value
    assert "Z" not in value and "+" not in value, value


def test_default_window_outlives_the_incident():
    """المركزان أُغلقا قبل ٩٦ ساعة. نافذةٌ لا تبلغها تُعيد القفل الأبديّ."""
    default = (
        inspect.signature(_adapter_class().list_recent_transactions)
        .parameters["last_period_seconds"]
        .default
    )
    assert default > 4 * DAY, default
