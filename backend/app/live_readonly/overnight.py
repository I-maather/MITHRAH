"""
OVERNIGHT FEE UNITS — الوحدة تُثبَت، ولا تُخمَّن.

## الخطأ الذي يعالجه هذا الملف

التنفيذ السابق حسب تكلفة التبييت هكذا:

    cash = abs(raw_rate) * notional

بلا أن يعرف **ما وحدة** `raw_rate`. المُدقِّق لاحظ أن الناتج كان يعني معدّلاً
قدره 0.86% لليلة — أي **314% سنوياً** — وهو رقم غير معقول لزوج رئيسي. المرجَّح
أن الوسيط يعيد القيمة **نسبةً مئوية** (0.0086 تعني 0.0086%) لا كسراً، فالتكلفة
مضخّمة **مئة ضعف**.

## لماذا لا نُصحّح بالقسمة على 100 وننتهي

لأن ذلك تخمين آخر في الاتجاه المعاكس. «الرقم يبدو كبيراً» ليس عقداً، وقد
يتغيّر سلوك الواجهة أو يختلف بين فئات الأدوات. القاعدة هنا:

    الوحدة تُثبَت من الاستجابة أو من عقد موثَّق مُعلَن في الكود.
    وإن لم تُثبَت ⇒ **لا تُحسَب تكلفة**، ويُرفع `OVERNIGHT_RATE_UNIT_UNKNOWN`.

«لا أعرف» مخرَجٌ صالح. الرقم المخترَع ليس كذلك.

## ما يُحفَظ دائماً — أربع قيم منفصلة، لا واحدة

  1. `raw_value`        القيمة كما وصلت من الوسيط، بلا مساس
  2. `unit`             الوحدة الصريحة ومصدر إثباتها
  3. `normalized_rate`  الكسر العشري لليلة (0.0086% ⇒ 0.000086)
  4. `cash_fee`         التكلفة النقدية = التعرّض × |الكسر|

خلط هذه الأربع في حقل واحد هو بالضبط ما سمح بخطأ المئة ضعف.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from ..money import D

#: رمز الفشل حين تتعذّر إقامة الوحدة.
OVERNIGHT_RATE_UNIT_UNKNOWN = "OVERNIGHT_RATE_UNIT_UNKNOWN"


class OvernightRateUnit(str, Enum):
    """وحدة معدّل التبييت كما **أُثبتت** — لا كما بدت."""

    #: القيمة نسبة مئوية: 0.0086 تعني 0.0086% ⇒ تُقسم على 100.
    PERCENT = "PERCENT"
    #: القيمة كسر عشري: 0.000086 تعني 0.0086% ⇒ تُستعمل كما هي.
    FRACTION = "FRACTION"
    #: لم تُثبَت. لا تُحسب تكلفة.
    UNKNOWN = "UNKNOWN"


class OvernightRateUnitUnknown(RuntimeError):
    """رُفع لأن الوحدة غير مُثبتة — ولا يجوز الحساب على تخمين."""

    code = OVERNIGHT_RATE_UNIT_UNKNOWN


#: الوحدة المُعلَنة تعاقدياً لـCapital.com.
#:
#: **تبقى `UNKNOWN` عمداً** إلى أن تُثبَت من وثائق الوسيط أو من حقل صريح في
#: الاستجابة. تغييرها قرارٌ موثَّق يتخذه إنسان، لا استنتاج يتخذه الكود من
#: «شكل» الرقم. التبييت ممنوع في كل ملفات التداول، فبقاؤها `UNKNOWN` لا يعطّل
#: أي قرار تداول — بل يمنع رقماً كاذباً من دخول تقرير أو Backtest.
DECLARED_CAPITAL_OVERNIGHT_UNIT: OvernightRateUnit = OvernightRateUnit.UNKNOWN

#: أسماء الحقول التي قد تحمل وحدةً صريحة في استجابة الوسيط.
_UNIT_FIELDS: tuple[str, ...] = (
    "unit", "rateUnit", "overnightFeeUnit", "feeUnit", "longRateUnit",
)

_PERCENT_TOKENS = frozenset({"PERCENT", "PERCENTAGE", "%", "PCT", "PERCENTAGES"})
_FRACTION_TOKENS = frozenset({"FRACTION", "DECIMAL", "RATIO", "RATE", "ABSOLUTE"})


@dataclass(frozen=True)
class OvernightRate:
    """
    معدّل تبييت واحد، بقيمه الأربع منفصلة.

    `cash_fee` تكون `None` كلما كانت الوحدة `UNKNOWN` — ولا تُملأ بتقدير.
    """

    raw_value: Optional[Decimal]
    raw_text: Optional[str]
    unit: OvernightRateUnit
    unit_source_ar: str
    normalized_rate: Optional[Decimal]
    cash_fee: Optional[Decimal]
    notional: Optional[Decimal]
    failure_code: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.unit is not OvernightRateUnit.UNKNOWN and self.raw_value is not None

    def as_dict(self) -> dict:
        def s(v: Optional[Decimal]) -> Optional[str]:
            return str(v) if v is not None else None

        return {
            "raw_value": s(self.raw_value),
            "raw_text": self.raw_text,
            "unit": self.unit.value,
            "unit_source_ar": self.unit_source_ar,
            "normalized_rate_per_night": s(self.normalized_rate),
            "cash_fee_one_night": s(self.cash_fee),
            "notional_used": s(self.notional),
            "failure_code": self.failure_code,
        }


def parse_unit(value: Any) -> OvernightRateUnit:
    """يحوّل نصّ وحدة إلى `OvernightRateUnit`. كل ما لا يُعرف ⇒ `UNKNOWN`."""
    if isinstance(value, str):
        token = value.strip().upper()
        if token in _PERCENT_TOKENS:
            return OvernightRateUnit.PERCENT
        if token in _FRACTION_TOKENS:
            return OvernightRateUnit.FRACTION
    return OvernightRateUnit.UNKNOWN


def resolve_unit(
    overnight_block: Any,
    *,
    declared: OvernightRateUnit = DECLARED_CAPITAL_OVERNIGHT_UNIT,
) -> tuple[OvernightRateUnit, str]:
    """
    يُثبت الوحدة بترتيب أولوية صريح:

      1. حقل وحدة **صريح** في استجابة الوسيط — أقوى دليل
      2. عقد مُعلَن في الكود (`DECLARED_CAPITAL_OVERNIGHT_UNIT`)
      3. وإلا ⇒ `UNKNOWN`

    **لا يوجد مسار رابع يستنتج الوحدة من حجم الرقم.** «0.0086 يبدو نسبة
    مئوية» ليس إثباتاً، وهو بالضبط نوع الاستنتاج الذي أنتج خطأ المئة ضعف.
    """
    if isinstance(overnight_block, dict):
        for field in _UNIT_FIELDS:
            if field in overnight_block:
                unit = parse_unit(overnight_block.get(field))
                if unit is not OvernightRateUnit.UNKNOWN:
                    return unit, f"حقل صريح في استجابة الوسيط: `{field}`."
    if declared is not OvernightRateUnit.UNKNOWN:
        return declared, "عقد مُعلَن في الكود بعد إثباته من وثائق الوسيط."
    return (
        OvernightRateUnit.UNKNOWN,
        "لم يُعلن الوسيط وحدةً، ولا عقد مُثبَت في الكود.",
    )


def normalize_rate(raw: Decimal, unit: OvernightRateUnit) -> Decimal:
    """
    يحوّل القيمة الخام إلى **كسر عشري لليلة**.

    `PERCENT`  ⇒ تُقسم على 100
    `FRACTION` ⇒ كما هي
    `UNKNOWN`  ⇒ يرفع
    """
    if unit is OvernightRateUnit.PERCENT:
        return raw / D("100")
    if unit is OvernightRateUnit.FRACTION:
        return raw
    raise OvernightRateUnitUnknown(
        "وحدة معدّل التبييت غير مُثبتة — لا يجوز التطبيع على تخمين."
    )


def compute_overnight(
    raw: Optional[Decimal],
    *,
    notional: Optional[Decimal],
    unit: OvernightRateUnit,
    unit_source_ar: str = "",
    raw_text: Optional[str] = None,
) -> OvernightRate:
    """
    يبني `OvernightRate` كاملاً. **لا يرفع**: يعيد الفشل مُصنَّفاً في الحقل
    `failure_code` كي يظهر في التقرير بدل أن يُسقط الاكتشاف.

    التكلفة النقدية = التعرّض × |الكسر المطبَّع|.
    """
    if raw is None:
        return OvernightRate(
            raw_value=None, raw_text=raw_text, unit=unit,
            unit_source_ar=unit_source_ar or "لم يُعِد الوسيط معدّلاً.",
            normalized_rate=None, cash_fee=None, notional=notional,
            failure_code="OVERNIGHT_RATE_MISSING",
        )
    if unit is OvernightRateUnit.UNKNOWN:
        return OvernightRate(
            raw_value=raw, raw_text=raw_text, unit=unit,
            unit_source_ar=unit_source_ar,
            normalized_rate=None, cash_fee=None, notional=notional,
            failure_code=OVERNIGHT_RATE_UNIT_UNKNOWN,
        )
    normalized = normalize_rate(raw, unit)
    cash = (abs(normalized) * notional) if notional is not None else None
    return OvernightRate(
        raw_value=raw, raw_text=raw_text, unit=unit,
        unit_source_ar=unit_source_ar,
        normalized_rate=normalized, cash_fee=cash, notional=notional,
        failure_code=None,
    )


def implied_annual_percent(normalized_rate: Decimal) -> Decimal:
    """
    المعدّل السنوي الضمني (365 ليلة) — **للفحص العقلي لا للتسعير**.

    رقم مثل 314% يكشف خطأ وحدات فوراً. لا يُستعمل في أي قرار.
    """
    return abs(normalized_rate) * D("365") * D("100")


__all__ = [
    "OVERNIGHT_RATE_UNIT_UNKNOWN",
    "OvernightRateUnit",
    "OvernightRateUnitUnknown",
    "OvernightRate",
    "DECLARED_CAPITAL_OVERNIGHT_UNIT",
    "parse_unit",
    "resolve_unit",
    "normalize_rate",
    "compute_overnight",
    "implied_annual_percent",
]
