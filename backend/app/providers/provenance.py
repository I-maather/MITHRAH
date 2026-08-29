"""
PROVENANCE — من أين جاء كل رقم، ومتى، وبأي رخصة.

## لماذا سجلّ مصدر كامل لكل سجل

رقمٌ بلا مصدر لا يمكن **دحضه**. حين يتناقض خبران أو تختلف قيمتان، السؤال
الأول ليس «أيهما أصح» بل «من قال، ومتى، ونقلاً عن من». وبلا هذا السجل تصبح
الإجابة تخميناً — وهو ما تمنعه سياسة التحقق كلها.

## `raw_checksum` تحديداً

بصمة SHA-256 على القيمة **الخام كما وصلت**، قبل أي تطبيع. تكشف ثلاثة أشياء:

  * إعادة نشر الخبر نفسه من نطاق آخر (نفس البصمة ⇒ نسخة لا مصدر مستقل)
  * تعديل المزوّد قيمةً بأثر رجعي بلا إعلان
  * خطأ في التطبيع (تتغيّر القيمة المطبَّعة والبصمة ثابتة)

## `license_class`

بعض المزوّدين يسمحون بتخزين البيانات الوصفية ولا يسمحون بتخزين نص المقال.
التصنيف هنا يجعل ذلك قابلاً للفرض بالكود بدل أن يكون تذكيراً في وثيقة.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlsplit

#: إصدار مخطط السجل المطبَّع. أي تغيير في معنى حقل يرفع هذا الرقم، فلا
#: تُخلَط سجلات مخطَّطين في ذاكرة مؤقتة واحدة.
NORMALIZED_SCHEMA_VERSION = "1.0.0"


class LicenseClass(str, Enum):
    """تصنيف ما يجوز تخزينه ومدّة الاحتفاظ."""

    #: بيانات حكومية/مركزية مفتوحة — تخزين كامل مسموح.
    PUBLIC_OFFICIAL = "PUBLIC_OFFICIAL"
    #: بيانات وصفية فقط: عنوان ورابط ومصدر وطابع زمني. **لا نص مقال**.
    METADATA_ONLY = "METADATA_ONLY"
    #: مسموح بالعرض لا بإعادة النشر.
    DISPLAY_ONLY = "DISPLAY_ONLY"
    #: رخصة غير مُثبتة ⇒ يُعامَل معاملة `METADATA_ONLY` احتياطاً.
    UNKNOWN = "UNKNOWN"


class Freshness(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


def raw_checksum(value: Any) -> str:
    """
    بصمة حتمية على القيمة الخام. `sort_keys` يضمن أن ترتيب مفاتيح JSON
    لا يغيّر البصمة — وإلا لصارت البصمة تكشف ضجيجاً لا تغييراً.
    """
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def source_domain(url: Optional[str]) -> Optional[str]:
    """
    النطاق وحده — لا المسار ولا سلسلة الاستعلام.

    سلسلة الاستعلام قد تحمل مفتاح API؛ حفظها في سجل المصدر يسرّبه إلى كل
    تقرير وكل ذاكرة مؤقتة. النطاق يكفي لسياسة الثقة.
    """
    if not url:
        return None
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return None
    if not host:
        return None
    if "@" in host:          # user:pass@host — يُسقَط الجزء السرّي
        host = host.rsplit("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host.removeprefix("www.") or None


@dataclass(frozen=True)
class Provenance:
    """
    سجل المصدر الكامل. **كل حقل إلزامي في التفكير حتى لو كان `None` في القيمة**:
    `None` هنا تعني «المزوّد لم يُعطِها»، لا «غير مهمة».
    """

    provider: str                       # 1. المزوّد الذي استُدعي
    original_source: Optional[str]      # 2. المصدر الأصلي (Reuters، الفيدرالي…)
    original_url: Optional[str]         # 3. الرابط الأصلي إن وُجد
    domain: Optional[str]               # 4. نطاق المصدر
    event_timestamp_utc: Optional[datetime]     # 5. زمن الحدث/النشر
    retrieved_at_utc: datetime                  # 6. زمن الاسترجاع
    timezone_name: str                          # 7. المنطقة الزمنية المرجعية
    currency: Optional[str]                     # 8. العملة المتأثرة
    category: Optional[str]                     # 9. التصنيف
    impact: Optional[str]                       # 10. الأثر
    freshness: Freshness                        # 11. الطزاجة
    source_id: str                              # 12. معرّف فريد لدى المصدر
    raw_checksum: str                           # 13. بصمة القيمة الخام
    normalized_version: str = NORMALIZED_SCHEMA_VERSION   # 14. إصدار التطبيع
    license_class: LicenseClass = LicenseClass.UNKNOWN    # 15. الرخصة
    retention_days: Optional[int] = None                  # 16. مدّة الاحتفاظ

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "original_source": self.original_source,
            "original_url": self.original_url,
            "domain": self.domain,
            "event_timestamp_utc": (
                self.event_timestamp_utc.isoformat() if self.event_timestamp_utc else None
            ),
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "timezone": self.timezone_name,
            "currency": self.currency,
            "category": self.category,
            "impact": self.impact,
            "freshness": self.freshness.value,
            "source_id": self.source_id,
            "raw_checksum": self.raw_checksum,
            "normalized_version": self.normalized_version,
            "license_class": self.license_class.value,
            "retention_days": self.retention_days,
        }

    @property
    def may_store_full_text(self) -> bool:
        """التخزين الكامل مسموح للبيانات الرسمية المفتوحة وحدها."""
        return self.license_class is LicenseClass.PUBLIC_OFFICIAL


def build_provenance(
    *,
    provider: str,
    raw: Any,
    source_id: str,
    retrieved_at_utc: datetime,
    event_timestamp_utc: Optional[datetime] = None,
    original_source: Optional[str] = None,
    original_url: Optional[str] = None,
    currency: Optional[str] = None,
    category: Optional[str] = None,
    impact: Optional[str] = None,
    license_class: LicenseClass = LicenseClass.UNKNOWN,
    retention_days: Optional[int] = None,
    freshness_window_seconds: Optional[float] = None,
    aging_window_seconds: Optional[float] = None,
) -> Provenance:
    """يبني السجل ويحسب الطزاجة والبصمة والنطاق."""
    freshness = Freshness.UNKNOWN
    if event_timestamp_utc is not None and freshness_window_seconds is not None:
        age = (retrieved_at_utc - event_timestamp_utc).total_seconds()
        aging = aging_window_seconds if aging_window_seconds is not None else (
            freshness_window_seconds * 2
        )
        if age <= freshness_window_seconds:
            freshness = Freshness.FRESH
        elif age <= aging:
            freshness = Freshness.AGING
        else:
            freshness = Freshness.STALE

    return Provenance(
        provider=provider,
        original_source=original_source,
        original_url=original_url,
        domain=source_domain(original_url),
        event_timestamp_utc=event_timestamp_utc,
        retrieved_at_utc=retrieved_at_utc,
        timezone_name="UTC",
        currency=currency,
        category=category,
        impact=impact,
        freshness=freshness,
        source_id=source_id,
        raw_checksum=raw_checksum(raw),
        license_class=license_class,
        retention_days=retention_days,
    )


def to_utc(moment: datetime) -> datetime:
    """
    تطبيع إلى UTC. الوقت **بلا منطقة زمنية يُرفض** بدل أن يُفترض UTC:
    افتراضٌ خاطئ هنا يزيح انقطاعَ خبرٍ ثلاث ساعات فيُفتح مركز في لحظة القرار.
    """
    if moment.tzinfo is None:
        raise ValueError("الوقت بلا منطقة زمنية — لا يُفترض UTC، يُرفض.")
    return moment.astimezone(timezone.utc)


__all__ = [
    "NORMALIZED_SCHEMA_VERSION",
    "LicenseClass",
    "Freshness",
    "Provenance",
    "build_provenance",
    "raw_checksum",
    "source_domain",
    "to_utc",
]
