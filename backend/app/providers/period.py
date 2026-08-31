"""
تحويل «فترة» السلسلة الاقتصادية إلى لحظة UTC.

## لماذا هذا الملف موجود

`Sourced` يحمل زمنين لا زمناً واحداً:

    source_timestamp_utc   متى **رُصدت** القيمة عند مصدرها
    retrieved_at_utc       متى **جلبناها** نحن

وخلطهما هو صنف العطل الحاكم في هذا المشروع: **حقلٌ يُعرَض ولا يُقاس من
مصدره**. فلو وُضع وقت الجلب في خانة الرصد، لقال `Sourced.age_seconds` إن
سعر فائدةٍ نُشر قبل ثلاثة أشهر عمرُه ثوانٍ — ولمرّ حارس الطزاجة على بيانٍ
بائت وهو يظنّه طازجاً. والحارس الذي يُخدَع أسوأ من الحارس الغائب.

## ولماذا الإرجاع قد يكون `None`

المصادر تكتب الفترة بأشكال مختلفة: يومية `2026-07-31`، شهرية `2026-07`،
ربعية `2026-Q2`، سنوية `2026`. وما لا يُقرأ منها لا يُخمَّن — يُعاد `None`،
فيقول `age_seconds` «لا أعرف العمر»، وهو الجواب الصحيح.

## اصطلاح البداية لا النهاية

الفترة تُردّ إلى **أوّل لحظة فيها** بتوقيت UTC. اصطلاحٌ واحد مكتوب خيرٌ من
اجتهادٍ يختلف بين مزوّد وآخر، والفارق بين بداية الشهر ونهايته لا يغيّر
قراراً في نظامٍ نافذته ساعات — أما اختلاف الاصطلاح فيغيّره.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

_DAILY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTHLY = re.compile(r"^(\d{4})-(\d{2})$")
_QUARTERLY = re.compile(r"^(\d{4})-?Q([1-4])$", re.IGNORECASE)
_ANNUAL = re.compile(r"^(\d{4})$")


def period_to_utc(period: object) -> Optional[datetime]:
    """أوّل لحظة في الفترة، أو `None` إن لم تُقرأ."""
    if not isinstance(period, str):
        return None
    text = period.strip()
    if not text:
        return None

    match = _DAILY.match(text)
    if match:
        return _at(int(match[1]), int(match[2]), int(match[3]))

    match = _MONTHLY.match(text)
    if match:
        return _at(int(match[1]), int(match[2]), 1)

    match = _QUARTERLY.match(text)
    if match:
        return _at(int(match[1]), (int(match[2]) - 1) * 3 + 1, 1)

    match = _ANNUAL.match(text)
    if match:
        return _at(int(match[1]), 1, 1)

    return None


def _at(year: int, month: int, day: int) -> Optional[datetime]:
    """تاريخٌ مستحيل (شهر 13، أو 31 فبراير) يُعاد `None` لا يُصحَّح."""
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None
