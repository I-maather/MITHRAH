"""
بدائلُ مشتركة لدورة القرار.

## لماذا هنا لا في كل ملف

بوابةُ الإقلاع (`runtime/startup.py`) تمنع الدخول ما لم يوجد تقريرُ إقلاعٍ
ناجح — و**غيابُ التقرير حجب**، فتقريرٌ مفقود يعني أن الفحص لم يجرِ ولا يُقرَأ
ذلك نجاحاً. وهذا ما نريده في الإنتاج بالضبط.

لكنّه يعني أنّ كلَّ حالةٍ مزيَّفة في الاختبارات تحتاج تقريراً صريحاً. ونسخُه
في كل ملف يجعل البديل يتخلّف عن الحقيقي بصمت — وهو عطلٌ وقع هنا مرّتين من
قبل: مزيّفٌ بلا `last_bars` رفع `AttributeError` داخل المجدول فبدت الدورة
كأنها لم تُستدعَ، ومزيّفٌ يعيد `"STATE"` نصّاً كسر `replace` بالطريقة نفسها.

فمكانٌ واحد يُعدَّل حين تتغيّر البوابة.
"""
from __future__ import annotations

from app.db.recovery import StartupReport, StartupVerdict


def passing_startup() -> StartupReport:
    """تقريرُ إقلاعٍ اجتاز — والتداول يبقى مقفولاً، فالفتح قرارٌ منفصل."""
    return StartupReport(
        verdict=StartupVerdict.READY_TRADING_STILL_LOCKED,
        trading_locked=True,
        kill_switch_active=False,
        risk_mode="VALIDATION",
        notes_ar=["بديلُ اختبار: بوابةُ الإقلاع اجتيزت."],
    )


def blocking_startup(reason_ar: str = "مطابقةُ الإقلاع لم تنجح.") -> StartupReport:
    return StartupReport(
        verdict=StartupVerdict.LOCKED_PENDING_RECONCILIATION,
        trading_locked=True,
        kill_switch_active=False,
        risk_mode="VALIDATION",
        reconciliation_problems=[reason_ar],
    )
