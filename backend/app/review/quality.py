"""
تقييمُ جودة القرار والتنفيذ — وحدُّ ما يجوز أن يُكتَب.

النتيجة ليست حكماً على القرار. صفقةٌ رابحة قد تكون قراراً رديئاً نجا، وصفقةٌ
خاسرة قد تكون قراراً سليماً لم يُوفَّق. فإذا قِيس القرارُ بنتيجته صار النظام
يتعلّم الحظّ ويسمّيه مهارة — ويستنسخ أسوأ قراراته لأنها ربحت مرّة.

ولذلك ثلاث قواعد يفرضها هذا الملف:

1. **`None` حالةٌ ثالثة.** «لم يُقيَّم» ليست «مقبولاً» ولا «سيّئاً». وكلُّ
   قارئٍ يراها `UNKNOWN` صريحةً مع `assessed=False` — لا فراغاً يملؤه بظنّه.
2. **لا استنتاج من النتيجة.** لا دالّة هنا تقرأ `realised_pnl`. والصفقات
   التي سبقت هذه الأعمدة تبقى `None` أبداً.
3. **لا تقييم بلا مصدر.** المصدر والنسخة والتاريخ تُكتب مع التقييم في
   معاملةٍ واحدة، أو لا يُكتب التقييم. وتقييمٌ لا يُعرف من أصدره ولا بأيّ
   قواعد لا يُراجَع ولا يُعاد إنتاجه — فهو رأيٌ لا سجلّ.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..clock import now_utc
from ..db.models import PositionBookRow

#: ما يُقرأ حين لا تقييم. **رمزٌ لا فراغ**: الفراغ يُملأ، والرمز يُسأل عنه.
QUALITY_UNKNOWN = "UNKNOWN"

#: سلّم جودة القرار — عن العملية، لا عن النتيجة.
QUALITY_SOUND = "SOUND"            # القواعد اكتملت والدليل كان كافياً
QUALITY_MARGINAL = "MARGINAL"      # مرّ ضمن الحدود لكن بهامشٍ ضيّق
QUALITY_UNSOUND = "UNSOUND"        # خولفت قاعدة أو نقص دليل

DECISION_QUALITIES = frozenset({QUALITY_SOUND, QUALITY_MARGINAL, QUALITY_UNSOUND})

#: سلّم جودة التنفيذ — عن الطريق بين القرار والمركز.
EXECUTION_CLEAN = "CLEAN"          # مُلئ كما قُصد، والحماية ثبتت
EXECUTION_DEGRADED = "DEGRADED"    # انزلاقٌ أو تأخّرٌ أو تنفيذٌ جزئي
EXECUTION_FAILED = "FAILED"        # لم يُنفَّذ، أو نُفّذ بلا حماية

EXECUTION_QUALITIES = frozenset({EXECUTION_CLEAN, EXECUTION_DEGRADED, EXECUTION_FAILED})

#: مصادر التقييم المسموحة. `RULES` قواعدُ محسوبة، `MODEL` حكمُ نموذج،
#: `HUMAN` حكمُ المالكة. ولا رابع: مصدرٌ مجهول لا يُكتَب.
SOURCE_RULES = "RULES"
SOURCE_MODEL = "MODEL"
SOURCE_HUMAN = "HUMAN"

ASSESSMENT_SOURCES = frozenset({SOURCE_RULES, SOURCE_MODEL, SOURCE_HUMAN})


class AssessmentRefused(ValueError):
    """تقييمٌ رُفض قبل أن يُكتَب. الرفضُ هنا أرخص من سجلٍّ لا يُصدَّق."""


@dataclass(frozen=True)
class QualityView:
    """ما يُعرَض للقارئ — وفيه دائماً **هل قُيّم**، لا القيمة وحدها."""

    decision: str
    execution: str
    assessed: bool
    source: Optional[str]
    version: Optional[str]
    assessed_at_utc: Optional[datetime]
    reason_ar: str

    def as_dict(self) -> dict:
        return {
            "decision_quality": self.decision,
            "execution_quality": self.execution,
            "assessed": self.assessed,
            "assessment_source": self.source,
            "assessment_version": self.version,
            "assessed_at_utc": (
                self.assessed_at_utc.isoformat() if self.assessed_at_utc else None
            ),
            "reason_ar": self.reason_ar,
        }


def read_quality(row: PositionBookRow) -> QualityView:
    """
    يقرأ التقييم كما هو — **ولا يشتقّه من شيء**.

    لاحظ ما لا تفعله هذه الدالّة: لا تنظر إلى `realised_pnl`، ولا إلى
    `state`، ولا إلى الاستراتيجية. صفٌّ بلا تقييم يعود `UNKNOWN` مهما كانت
    نتيجته — لأنّ اشتقاق التقييم من النتيجة هو بالضبط الخطأ الذي وُجد
    التقييمُ ليمنعه.
    """
    decision = row.decision_quality
    execution = row.execution_quality
    assessed = bool(decision or execution)
    if not assessed:
        return QualityView(
            decision=QUALITY_UNKNOWN,
            execution=QUALITY_UNKNOWN,
            assessed=False,
            source=None,
            version=None,
            assessed_at_utc=None,
            reason_ar=(
                "لم تُقيَّم هذه الصفقة. وهذا ليس حكماً عليها: التقييم يُكتَب "
                "بمصدرٍ ونسخةٍ وتاريخ، أو لا يُكتَب."
            ),
        )
    return QualityView(
        decision=decision or QUALITY_UNKNOWN,
        execution=execution or QUALITY_UNKNOWN,
        assessed=True,
        source=row.assessment_source,
        version=row.assessment_version,
        assessed_at_utc=row.assessed_at_utc,
        reason_ar=(
            f"قُيّمت بمصدر {row.assessment_source} نسخة {row.assessment_version}"
        ),
    )


def record_assessment(
    session: Session,
    row: PositionBookRow,
    *,
    decision: Optional[str],
    execution: Optional[str],
    source: str,
    version: str,
    at: Optional[datetime] = None,
    audit=None,
) -> QualityView:
    """
    يكتب تقييماً **مع نَسَبه**، أو يرفض.

    الرفض يسبق الكتابة دائماً: قيمةٌ خارج السلّم، أو مصدرٌ مجهول، أو نسخةٌ
    فارغة — أيُّها كان، لا يُلمَس الصفّ. ولا يُكتب تقييمٌ على مركزٍ ما زال
    مفتوحاً: جودةُ التنفيذ لا تُعرَف قبل أن يُغلَق ويُطابَق.
    """
    if decision is not None and decision not in DECISION_QUALITIES:
        raise AssessmentRefused(
            f"جودة قرار غير معروفة: {decision!r}. المسموح: {sorted(DECISION_QUALITIES)}"
        )
    if execution is not None and execution not in EXECUTION_QUALITIES:
        raise AssessmentRefused(
            f"جودة تنفيذ غير معروفة: {execution!r}. المسموح: {sorted(EXECUTION_QUALITIES)}"
        )
    if decision is None and execution is None:
        raise AssessmentRefused("لا شيء يُكتَب: التقييمان كلاهما None.")
    if source not in ASSESSMENT_SOURCES:
        raise AssessmentRefused(
            f"مصدر تقييم مجهول: {source!r}. المسموح: {sorted(ASSESSMENT_SOURCES)}"
        )
    if not (version or "").strip():
        raise AssessmentRefused(
            "تقييمٌ بلا نسخة لا يُعاد إنتاجه. اكتبي نسخة القواعد أو النموذج."
        )

    when = at or now_utc()
    if decision is not None:
        row.decision_quality = decision
    if execution is not None:
        row.execution_quality = execution
    row.assessment_source = source
    row.assessment_version = version.strip()
    row.assessed_at_utc = when
    session.commit()

    if audit is not None:
        try:
            from ..audit.log import Actor, AuditAction  # noqa: PLC0415

            audit.record(
                actor=Actor.SYSTEM if source != SOURCE_HUMAN else Actor.OWNER,
                action=AuditAction.CONFIG_CHANGE,
                decision=f"ASSESSMENT {row.broker_deal_id}",
                reason_ar=(
                    f"تقييمُ صفقة {row.broker_deal_id}: قرار="
                    f"{row.decision_quality or QUALITY_UNKNOWN} تنفيذ="
                    f"{row.execution_quality or QUALITY_UNKNOWN} "
                    f"بمصدر {source} نسخة {row.assessment_version}."
                ),
                source="review.quality",
            )
        except Exception:  # noqa: BLE001
            # سجلُّ التدقيق لا يُبطل التقييم المكتوب، لكنّ سقوطه يُرى.
            import logging  # noqa: PLC0415

            logging.getLogger(__name__).warning(
                "assessment recorded but audit failed for %s", row.broker_deal_id
            )

    return read_quality(row)


__all__ = [
    "QUALITY_UNKNOWN",
    "QUALITY_SOUND",
    "QUALITY_MARGINAL",
    "QUALITY_UNSOUND",
    "EXECUTION_CLEAN",
    "EXECUTION_DEGRADED",
    "EXECUTION_FAILED",
    "DECISION_QUALITIES",
    "EXECUTION_QUALITIES",
    "ASSESSMENT_SOURCES",
    "SOURCE_RULES",
    "SOURCE_MODEL",
    "SOURCE_HUMAN",
    "AssessmentRefused",
    "QualityView",
    "read_quality",
    "record_assessment",
]
