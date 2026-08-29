"""
PROVIDER PROBE — يُثبت قدرة الخطة، ولا يبني على ظن.

## لماذا مسبار منفصل

وثائق FMP لم تُسعِفنا في معرفة ما إذا كان التقويم مشمولاً بالخطة المجانية،
ولا في شكل رد المنع. والسؤال لا يُجاب من الوثيقة — يُجاب بطلب واحد بمفتاح
المالكة على جهازها.

المسبار **طلب واحد**، وقراءة فقط، ويميّز خمس نتائج لا نتيجتين:

    ENDPOINT_AVAILABLE   الاستجابة مطابقة للعقد المتوقَّع
    AUTH_FAILED          المفتاح مرفوض
    UNAVAILABLE_PLAN     نقطة النهاية خارج الخطة
    RATE_LIMITED         تجاوز الحد
    MALFORMED            وصلت استجابة بشكل غير متوقَّع

الفرق بين الثلاثة الأخيرة عملي: الأول ينتظر، والثاني يحتاج قراراً بالاشتراك،
والثالث يحتاج تعديل مُطبِّع. خلطها في «فشل» واحد يضيّع أسابيع.

**لا يُشغَّل تلقائياً** ولا في أي اختبار — يُشغَّل بأمر صريح من المالكة.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .fmp_calendar import (
    CONTRACT_NOTE_AR,
    CREDENTIAL_NAME as FMP_CREDENTIAL,
    FmpEconomicCalendarProvider,
)
from .results import ProviderResultState

PROBE_ENDPOINT_AVAILABLE = "ENDPOINT_AVAILABLE"

#: المسابر المتاحة. إضافة مسبار تتطلب تعديل هذه القائمة عمداً.
AVAILABLE_PROBES: tuple[str, ...] = ("fmp-calendar",)


@dataclass(frozen=True)
class ProbeOutcome:
    probe: str
    verdict: str
    state: ProviderResultState
    detail_ar: str
    http_status: Optional[int] = None
    record_count: int = 0
    contract_note_ar: str = ""

    @property
    def usable(self) -> bool:
        return self.verdict == PROBE_ENDPOINT_AVAILABLE

    def as_dict(self) -> dict:
        return {
            "probe": self.probe,
            "verdict": self.verdict,
            "state": self.state.value,
            "detail_ar": self.detail_ar,
            "http_status": self.http_status,
            "record_count": self.record_count,
            "contract_note_ar": self.contract_note_ar,
            "usable": self.usable,
        }

    def report_ar(self) -> str:
        lines = [
            f"مسبار: {self.probe}",
            f"النتيجة: **{self.verdict}**",
            f"الحالة: {self.state.value}",
            f"HTTP: {self.http_status if self.http_status is not None else '—'}",
            f"سجلات مقروءة: {self.record_count}",
            "",
            self.detail_ar,
        ]
        if self.contract_note_ar:
            lines += ["", self.contract_note_ar]
        lines += [
            "",
            "**لم يُشترَ اشتراك، ولم يُبدَّل مزوّد، ولم يُرسَل أي أمر تداول.**",
        ]
        return "\n".join(lines)


def probe_fmp_calendar(
    provider: FmpEconomicCalendarProvider,
    *,
    now_utc: Optional[datetime] = None,
    window_days: int = 7,
) -> ProbeOutcome:
    """
    طلب **واحد** لنافذة قصيرة. النافذة القصيرة مقصودة: تكفي لإثبات القدرة
    ولا تستهلك من حد الطلبات اليومي أكثر من اللازم.
    """
    now = now_utc or datetime.now(timezone.utc)
    result = provider.fetch(
        currencies=("USD", "EUR"),
        window_start_utc=now,
        window_end_utc=now + timedelta(days=window_days),
        now_utc=now,
    )

    verdict_by_state = {
        ProviderResultState.FRESH: PROBE_ENDPOINT_AVAILABLE,
        ProviderResultState.PARTIAL: PROBE_ENDPOINT_AVAILABLE,
        ProviderResultState.AUTH_FAILED: ProviderResultState.AUTH_FAILED.value,
        ProviderResultState.UNAVAILABLE_PLAN: ProviderResultState.UNAVAILABLE_PLAN.value,
        ProviderResultState.RATE_LIMITED: ProviderResultState.RATE_LIMITED.value,
        ProviderResultState.MALFORMED: ProviderResultState.MALFORMED.value,
    }
    verdict = verdict_by_state.get(result.state, result.state.value)

    guidance = {
        PROBE_ENDPOINT_AVAILABLE: (
            "نقطة النهاية متاحة. راجعي أسماء الحقول في السجلات المقروءة "
            "وثبّتي العقد في `fmp_calendar.py`."
        ),
        ProviderResultState.AUTH_FAILED.value: (
            "المفتاح مرفوض. أعيدي ضبطه بـ`scripts/configure_provider_credentials.sh` "
            "— ولا يُلصَق مفتاح في المحادثة."
        ),
        ProviderResultState.UNAVAILABLE_PLAN.value: (
            "التقويم خارج خطتك الحالية. **لا يُشترى اشتراك تلقائياً ولا يُبدَّل "
            "مزوّد** — القرار قرارك، والنظام يبقى بلا تقويم ويُسقط الأهلية."
        ),
        ProviderResultState.RATE_LIMITED.value: (
            "تجاوز حد المعدّل. أعيدي المحاولة لاحقاً — لا يُلحّ المسبار."
        ),
        ProviderResultState.MALFORMED.value: (
            "الاستجابة وصلت بشكل غير متوقَّع. هذه **ليست** مشكلة خطة ولا مفتاح: "
            "احفظي الشكل الفعلي وعدّلي المُطبِّع."
        ),
    }

    return ProbeOutcome(
        probe="fmp-calendar",
        verdict=verdict,
        state=result.state,
        detail_ar=guidance.get(verdict, result.detail_ar) + f"\n\n{result.detail_ar}",
        http_status=result.http_status,
        record_count=len(result.records),
        contract_note_ar=CONTRACT_NOTE_AR,
    )


__all__ = [
    "AVAILABLE_PROBES",
    "PROBE_ENDPOINT_AVAILABLE",
    "ProbeOutcome",
    "probe_fmp_calendar",
    "FMP_CREDENTIAL",
]
