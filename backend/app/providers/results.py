"""
PROVIDER RESULT STATES — «لا أعرف» ليست «لا يوجد».

## القاعدة التي يفرضها هذا الملف

    قائمة أحداث فارغة **لا تعني** «لا أحداث اليوم».
    قد تعني: انتهت المهلة · انتهى الحد · فشلت المصادقة · الخطة لا تشمل
    نقطة النهاية · تغيّر شكل الاستجابة.

الفرق بين التفسيرين هو الفرق بين تداولٍ في ساعة قرار الفيدرالي وتداولٍ في
ساعة هادئة. لذلك **لا مزوّد يعيد بيانات مجرّدة** — كل استدعاء يعيد
`ProviderResult` يحمل حالته صراحةً، وحالة `UNAVAILABLE` تُسقط الأهلية
للتداول الحقيقي بدل أن تمرّ كـ«صفر أحداث».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, Sequence, TypeVar

T = TypeVar("T")


class ProviderResultState(str, Enum):
    """الحالات التسع. لا حالة عاشرة، ولا حالة ضمنية."""

    #: بيانات كاملة وحديثة ضمن نافذة الطزاجة المُعلَنة.
    FRESH = "FRESH"
    #: بيانات صحيحة لكنها أقدم من نافذة الطزاجة. **لا تصلح لأهلية Live.**
    STALE = "STALE"
    #: بعض المصادر نجحت وبعضها فشل. النقص مُسمّى صراحةً.
    PARTIAL = "PARTIAL"
    #: تعذّر الوصول: شبكة، مهلة، خطأ خادم.
    UNAVAILABLE = "UNAVAILABLE"
    #: نقطة النهاية غير مشمولة بخطة الاشتراك الحالية.
    UNAVAILABLE_PLAN = "UNAVAILABLE_PLAN"
    #: المفتاح مرفوض أو ناقص.
    AUTH_FAILED = "AUTH_FAILED"
    #: تجاوز حد المعدّل لدى المزوّد.
    RATE_LIMITED = "RATE_LIMITED"
    #: الاستجابة وصلت لكن شكلها لا يطابق العقد المتوقَّع.
    MALFORMED = "MALFORMED"
    #: حالة لم تُصنَّف. تُعامَل معاملة `UNAVAILABLE` في كل قرار.
    UNKNOWN = "UNKNOWN"


#: الحالات التي تُنتج بيانات صالحة للاستعمال في **قرار** — لا للعرض فقط.
USABLE_FOR_DECISION: frozenset[ProviderResultState] = frozenset({
    ProviderResultState.FRESH,
})

#: الحالات التي يجوز عرضها في الواجهة مع وسم صريح، ولا تدخل قراراً.
DISPLAY_ONLY: frozenset[ProviderResultState] = frozenset({
    ProviderResultState.STALE,
    ProviderResultState.PARTIAL,
})

#: الحالات التي تعني **فشلاً** يجب أن يظهر في لوحة صحة المزوّدين.
FAILURE_STATES: frozenset[ProviderResultState] = frozenset({
    ProviderResultState.UNAVAILABLE,
    ProviderResultState.UNAVAILABLE_PLAN,
    ProviderResultState.AUTH_FAILED,
    ProviderResultState.RATE_LIMITED,
    ProviderResultState.MALFORMED,
    ProviderResultState.UNKNOWN,
})

assert (
    USABLE_FOR_DECISION | DISPLAY_ONLY | FAILURE_STATES
    == frozenset(ProviderResultState)
), "كل حالة يجب أن تُصنَّف — لا حالة بلا تصنيف."


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    """
    نتيجة استدعاء مزوّد واحد.

    `records` فارغة **لا تعني شيئاً بذاتها** — يجب قراءة `state` معها دائماً.
    ولهذا لا توجد طريقة للحصول على السجلات بلا الحالة.
    """

    provider: str
    state: ProviderResultState
    records: tuple[T, ...] = ()
    retrieved_at_utc: Optional[datetime] = None
    #: نافذة الطزاجة المُعلَنة لهذا النوع من البيانات (ثوانٍ).
    freshness_window_seconds: Optional[float] = None
    #: عمر أقدم سجل عند الاسترجاع.
    data_age_seconds: Optional[float] = None
    #: رمز خطأ مُنقّى — **لا يحتوي مفتاحاً ولا سلسلة استعلام**.
    error_code: Optional[str] = None
    detail_ar: str = ""
    #: ما نقص تحديداً في حالة `PARTIAL`.
    missing: tuple[str, ...] = ()
    http_status: Optional[int] = None

    @property
    def usable_for_decision(self) -> bool:
        return self.state in USABLE_FOR_DECISION

    @property
    def is_failure(self) -> bool:
        return self.state in FAILURE_STATES

    @property
    def means_no_data_exists(self) -> bool:
        """
        **الميثود الوحيد** الذي يجيز تفسير القائمة الفارغة بأنها «لا يوجد».

        يشترط `FRESH` صراحةً: أي حالة أخرى مع قائمة فارغة تعني «لا نعرف»،
        وهو ما يجب أن يُسقط الأهلية لا أن يفتح الباب.
        """
        return self.state is ProviderResultState.FRESH and not self.records

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "state": self.state.value,
            "record_count": len(self.records),
            "retrieved_at_utc": (
                self.retrieved_at_utc.isoformat() if self.retrieved_at_utc else None
            ),
            "freshness_window_seconds": self.freshness_window_seconds,
            "data_age_seconds": self.data_age_seconds,
            "error_code": self.error_code,
            "detail_ar": self.detail_ar,
            "missing": list(self.missing),
            "http_status": self.http_status,
            "usable_for_decision": self.usable_for_decision,
        }


def merge_states(states: Sequence[ProviderResultState]) -> ProviderResultState:
    """
    يدمج حالات عدة مزوّدين في حالة واحدة — **بالأسوأ يفوز**.

    مصدرٌ واحد فاشل بين ثلاثة لا يُنتج نتيجة «طازجة»؛ يُنتج `PARTIAL` على
    الأقل. والتفاؤل هنا هو ما يُنتج تداولاً على معلومة ناقصة.
    """
    if not states:
        return ProviderResultState.UNAVAILABLE
    unique = set(states)
    if unique == {ProviderResultState.FRESH}:
        return ProviderResultState.FRESH
    if ProviderResultState.FRESH in unique or ProviderResultState.STALE in unique:
        # نجح بعضها ⇒ جزئي، لا طازج.
        if unique <= {ProviderResultState.FRESH, ProviderResultState.STALE}:
            return ProviderResultState.STALE
        return ProviderResultState.PARTIAL
    # لا نجاح إطلاقاً — تُعاد أشد حالة فشل دلالةً.
    for candidate in (
        ProviderResultState.AUTH_FAILED,
        ProviderResultState.UNAVAILABLE_PLAN,
        ProviderResultState.RATE_LIMITED,
        ProviderResultState.MALFORMED,
        ProviderResultState.UNAVAILABLE,
    ):
        if candidate in unique:
            return candidate
    return ProviderResultState.UNKNOWN


__all__ = [
    "ProviderResultState",
    "ProviderResult",
    "USABLE_FOR_DECISION",
    "DISPLAY_ONLY",
    "FAILURE_STATES",
    "merge_states",
]
