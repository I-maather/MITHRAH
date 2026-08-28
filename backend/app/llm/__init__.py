"""
LLM ISOLATION — عزل النموذج اللغوي عزلاً بنيوياً.

## ما لا يستطيع النموذج اللغوي فعله — بالبنية لا بالتعليمات

لا يحسب ولا يخترع: سعراً · مؤشراً · إصداراً اقتصادياً · خبراً · مستوى دعم أو
مقاومة · كمية · مسافة وقف · جني أرباح · سبريداً · هامشاً · قيمة نقطة · مخاطرة ·
R:R · درجة ثقة · موافقة على صفقة · جسم أمر للوسيط.

**الضمانة ليست نصاً في مطالبة.** هذه الحزمة:
  · لا تستورد `ExecutionService` ولا `RiskEngine` ولا أي محوّل وسيط
  · لا تُصدِّر دالة واحدة تعيد قراراً
  · مخرجها `str` فقط، ويمر عبر `LlmOutputGuard` قبل العرض

## ما يستطيع فعله
تلخيص بيانات مُهيكلة مُتحقَّق منها · شرح استنتاج حتمي · الترجمة إلى العربية ·
Morning Brief · شرح WHY_TRADE و WHY_NO_TRADE · مقارنة الظروف الحالية بأنماط
تاريخية **مخزَّنة سابقاً**.

## إن غاب النموذج اللغوي
يستمر الخط الحتمي كما هو، ويُولَّد تقرير قالبي بلا نموذج. الغياب لا يغيّر قراراً.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Protocol

from ..money import D


class LlmIncident(str, Enum):
    HALLUCINATION_DETECTED = "HALLUCINATION_DETECTED"
    LLM_CONTRADICTION = "LLM_CONTRADICTION"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_EMPTY = "LLM_EMPTY"


INCIDENT_AR: dict[LlmIncident, str] = {
    LlmIncident.HALLUCINATION_DETECTED: "رقم غير موجود في السجل المُتحقَّق منه.",
    LlmIncident.LLM_CONTRADICTION: "الملخص يناقض القرار الحتمي.",
    LlmIncident.LLM_UNAVAILABLE: "النموذج اللغوي غير متاح.",
    LlmIncident.LLM_EMPTY: "الملخص فارغ.",
}


class LlmUnavailable(RuntimeError):
    """يرفعها المزوّد حين يتعذّر توليد ملخص. الخط الحتمي لا يتأثر."""


class SummaryProvider(Protocol):
    """
    عقد المزوّد. لاحظي نوع الإرجاع: **`str` فقط**.
    لا يوجد شكل إرجاع يسمح للنموذج بإعادة قرار أو رقم مُهيكل.
    """

    def summarize(self, *, prompt: str, facts: Mapping[str, Any]) -> str: ...


class NullSummaryProvider:
    """المزوّد الافتراضي: لا نموذج. النظام يعمل كاملاً بدونه."""

    def summarize(self, *, prompt: str, facts: Mapping[str, Any]) -> str:
        raise LlmUnavailable("لا مزوّد ملخصات مُعدّ.")


class StaticSummaryProvider:
    """مزوّد اختباري يعيد نصاً محقوناً — بلا شبكة."""

    def __init__(self, text: str | Exception) -> None:
        self._text = text

    def summarize(self, *, prompt: str, facts: Mapping[str, Any]) -> str:
        if isinstance(self._text, Exception):
            raise self._text
        return self._text


# ---------------------------------------------------------------------------
# استخراج الأرقام
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

#: أرقام تُستثنى من فحص الاختلاق لأنها بنيوية لا مالية
#: (ترقيم قوائم، سنوات، أرقام أطر زمنية مثل H4 وM15).
_STRUCTURAL_TOKENS = re.compile(r"\b(?:[HMWD]\d+|\d{4}-\d{2}-\d{2}|\d+\s*(?:ساعة|دقيقة|يوم))")


def extract_numbers(text: str) -> set[Decimal]:
    """كل رقم في النص، بعد إزالة الرموز البنيوية."""
    cleaned = _STRUCTURAL_TOKENS.sub(" ", text)
    out: set[Decimal] = set()
    for m in _NUMBER_RE.finditer(cleaned):
        token = m.group(0).replace(",", ".")
        try:
            out.add(D(token))
        except Exception:
            continue
    return out


def _flatten_numbers(value: Any, acc: set[Decimal]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float, Decimal)):
        acc.add(D(str(value)))
        return
    if isinstance(value, str):
        for m in _NUMBER_RE.finditer(value.replace(",", ".")):
            try:
                acc.add(D(m.group(0)))
            except Exception:
                continue
        return
    if isinstance(value, Mapping):
        for v in value.values():
            _flatten_numbers(v, acc)
        return
    if isinstance(value, (list, tuple, set)):
        for v in value:
            _flatten_numbers(v, acc)


def verified_numbers(facts: Mapping[str, Any]) -> set[Decimal]:
    """كل رقم موجود فعلاً في السجل المُتحقَّق منه."""
    acc: set[Decimal] = set()
    _flatten_numbers(facts, acc)
    # أشكال مكافئة: 0.50 و0.5 و.5 يجب أن تُقبل جميعاً.
    expanded = set(acc)
    for n in acc:
        expanded.add(n.normalize())
        expanded.add(D(f"{n:.2f}"))
        expanded.add(D(f"{n:.1f}"))
        expanded.add(D(f"{n:.0f}"))
    return expanded


@dataclass(frozen=True)
class GuardResult:
    """
    نتيجة الحراسة. `text` هو ما يُعرض للمالكة — إما ملخص النموذج بعد اجتيازه
    الفحص، أو الشرح القالبي الحتمي.

    **`decision_changed` قيمته False دائماً وفي كل مسار.**
    """

    text: str
    used_llm: bool
    incidents: tuple[LlmIncident, ...]
    invented_numbers: tuple[str, ...]
    decision_changed: bool = False

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "used_llm": self.used_llm,
            "incidents": [
                {"code": i.value, "reason_ar": INCIDENT_AR[i]} for i in self.incidents
            ],
            "invented_numbers": list(self.invented_numbers),
            "decision_changed": self.decision_changed,
        }


#: عبارات تدل على أن الملخص يدّعي صفقة بينما القرار الحتمي هو NO_TRADE، والعكس.
_TRADE_CLAIMS = ("ندخل", "نشتري", "نبيع", "الصفقة مقبولة", "أنصح بالدخول", "فرصة مؤكدة",
                 "افتحي صفقة", "يُنصح بالشراء", "يُنصح بالبيع")
_NO_TRADE_CLAIMS = ("لا صفقة", "لا توجد صفقة", "NO_TRADE", "امتناع", "لا ندخل")


class LlmOutputGuard:
    """
    حارس مخرجات النموذج. يعمل **بعد** اتخاذ القرار الحتمي، فلا يستطيع التأثير عليه.
    """

    def __init__(self, *, incident_sink: Optional[list[dict]] = None) -> None:
        self.incidents_log: list[dict] = incident_sink if incident_sink is not None else []

    def check(
        self,
        summary: str,
        *,
        facts: Mapping[str, Any],
        deterministic_decision: str,
        fallback_text: str,
        now: Optional[datetime] = None,
    ) -> GuardResult:
        incidents: list[LlmIncident] = []
        invented: list[str] = []

        if not summary or not summary.strip():
            incidents.append(LlmIncident.LLM_EMPTY)
            self._record(LlmIncident.LLM_EMPTY, now, {})
            return GuardResult(fallback_text, False, tuple(incidents), ())

        # 1) أرقام مختلقة
        allowed = verified_numbers(facts)
        for n in sorted(extract_numbers(summary)):
            if n not in allowed and n.normalize() not in allowed:
                invented.append(str(n))

        if invented:
            incidents.append(LlmIncident.HALLUCINATION_DETECTED)
            # ⚠️ لا تُسجَّل بيانات حساسة — الأرقام المختلقة فقط وعددها.
            self._record(
                LlmIncident.HALLUCINATION_DETECTED, now,
                {"invented_count": len(invented), "invented": invented[:10]},
            )

        # 2) مناقضة القرار الحتمي
        lowered = summary
        claims_trade = any(p in lowered for p in _TRADE_CLAIMS)
        claims_no_trade = any(p in lowered for p in _NO_TRADE_CLAIMS)
        contradicts = (
            (deterministic_decision == "NO_TRADE" and claims_trade and not claims_no_trade)
            or (deterministic_decision == "TRADE" and claims_no_trade and not claims_trade)
            or (deterministic_decision == "HALTED" and claims_trade)
        )
        if contradicts:
            incidents.append(LlmIncident.LLM_CONTRADICTION)
            self._record(
                LlmIncident.LLM_CONTRADICTION, now,
                {"deterministic_decision": deterministic_decision},
            )

        if incidents:
            # يُطرح الملخص ويُعرض الشرح القالبي. القرار الحتمي **لم يتغيّر**.
            return GuardResult(fallback_text, False, tuple(incidents), tuple(invented))

        return GuardResult(summary, True, (), ())

    def explain(
        self,
        provider: SummaryProvider,
        *,
        prompt: str,
        facts: Mapping[str, Any],
        deterministic_decision: str,
        fallback_text: str,
        now: Optional[datetime] = None,
    ) -> GuardResult:
        """
        المسار الكامل: محاولة توليد، ثم حراسة. غياب النموذج ليس خطأً —
        يُنتج الشرح القالبي ويستمر كل شيء.
        """
        try:
            summary = provider.summarize(prompt=prompt, facts=facts)
        except LlmUnavailable:
            self._record(LlmIncident.LLM_UNAVAILABLE, now, {})
            return GuardResult(fallback_text, False, (LlmIncident.LLM_UNAVAILABLE,), ())
        except Exception:
            # أي عطل في المزوّد يُعامَل كغياب. لا استثناء يتسرّب إلى الخط الحتمي.
            self._record(LlmIncident.LLM_UNAVAILABLE, now, {})
            return GuardResult(fallback_text, False, (LlmIncident.LLM_UNAVAILABLE,), ())

        return self.check(
            summary,
            facts=facts,
            deterministic_decision=deterministic_decision,
            fallback_text=fallback_text,
            now=now,
        )

    def _record(self, incident: LlmIncident, now: Optional[datetime], extra: dict) -> None:
        self.incidents_log.append(
            {
                "incident": incident.value,
                "reason_ar": INCIDENT_AR[incident],
                "at_utc": now.isoformat() if now else None,
                **extra,
            }
        )


__all__ = [
    "LlmIncident",
    "INCIDENT_AR",
    "LlmUnavailable",
    "SummaryProvider",
    "NullSummaryProvider",
    "StaticSummaryProvider",
    "LlmOutputGuard",
    "GuardResult",
    "extract_numbers",
    "verified_numbers",
]
