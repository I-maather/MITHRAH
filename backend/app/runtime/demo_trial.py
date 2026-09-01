"""
تجربة الحساب التجريبي — **الطريق الوحيد الذي يُشغِّل استراتيجيةً غير معتمدة،
وهو مقفلٌ عن الحساب الحقيقي بالبنية لا بالانتباه.**

## لماذا وُجد هذا الملف

الخط لا يشغّل إلا استراتيجيةً حالتها `APPROVED` (`pipeline/runner.py`)،
وعددها **صفر**. فالنظام على التجريبي لا يفتح صفقة واحدة أبداً — وهو صحيح
للحساب الحقيقي، ومانعٌ بلا فائدة للتجريبي: التجربة على مالٍ وهمي هي بالضبط
البوابة التالية (`Shadow`) التي يشترطها الاعتماد.

والحلّ الخاطئ الواضح: تغيير حالة الاستراتيجيات إلى `APPROVED`. وهو يفتحها
**على الحسابين معاً**، ويجعل الاعتماد قراراً يُتَّخذ بتعديل سطرٍ في ملف —
وهذا بالضبط ما بُنيت الحالة لمنعه.

## القاعدة

الاعتماد التجريبي **ليس حالة استراتيجية**، بل قائمة أسماءٍ تُقرأ من البيئة
وتُصفَّى بالوسيط المتصل:

    القائمة تُلغى بالكامل ما لم يكن `broker.is_live is False` **حرفياً**.

و`getattr(broker, "is_live", True)` — الافتراض عند غياب الصفة **حقيقي**،
فيُغلَق. وسيطٌ لا نعرف نوعه يُعامَل معاملة الأخطر.

## وما لا يفعله هذا الملف

لا يمسّ `LIVE_TRADING`، ولا `LIVE_API_ENABLED`، ولا قاطع الطوارئ، ولا حدود
المخاطرة. ولا يجعل نتيجةً تجريبيةً اعتماداً: الاستراتيجية تبقى `RESEARCH`
في سجلّها، وتقرير المسح يبقى هو الدليل.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

#: تشغيل التجربة. أي قيمة غير الثلاث ⇒ مطفأة.
DEMO_TRIAL_ENV = "DEMO_TRIAL_ENABLED"
#: أسماء الاستراتيجيات، مفصولة بفواصل. الاسم لا المفتاح: `TREND_PULLBACK_V2`.
DEMO_TRIAL_STRATEGIES_ENV = "DEMO_TRIAL_STRATEGIES"
#: دقّة الشموع التي تقرأها حلقة القرار.
DEMO_TRIAL_RESOLUTION_ENV = "DEMO_TRIAL_RESOLUTION"
#: مرجع موافقة المالكة — يلزم لفتح قفل التنفيذ، ويُكتب في سجل التدقيق.
DEMO_TRIAL_REFERENCE_ENV = "DEMO_TRIAL_APPROVAL_REF"

TRUTHY = frozenset({"1", "true", "yes"})

#: الدقّات التي يقبلها الوسيط. أي غيرها يُرفض ولا يُمرَّر إليه.
ALLOWED_RESOLUTIONS: tuple[str, ...] = (
    "DAY", "HOUR_4", "HOUR", "MINUTE_30", "MINUTE_15",
)
DEFAULT_RESOLUTION = "DAY"


@dataclass(frozen=True)
class DemoTrial:
    enabled: bool = False
    strategies: frozenset[str] = frozenset()
    resolution: str = DEFAULT_RESOLUTION
    approval_reference: str = ""
    #: سببُ الإطفاء بالنصّ — يُعرض ويُسجَّل. «مطفأة» وحدها لا تقول شيئاً.
    note_ar: str = "تجربة التجريبي مطفأة."

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.strategies)


def read_demo_trial(environ: Optional[Mapping[str, str]] = None) -> DemoTrial:
    """يقرأ الإعداد من البيئة **بلا أن يعرف الوسيط** — التصفية تأتي بعدها."""
    env = os.environ if environ is None else environ

    if (env.get(DEMO_TRIAL_ENV, "") or "").strip().lower() not in TRUTHY:
        return DemoTrial(note_ar=f"{DEMO_TRIAL_ENV} غير مرفوع — لا تجربة.")

    names = frozenset(
        part.strip().upper()
        for part in (env.get(DEMO_TRIAL_STRATEGIES_ENV, "") or "").split(",")
        if part.strip()
    )
    if not names:
        return DemoTrial(
            note_ar=f"{DEMO_TRIAL_ENV} مرفوع بلا أسماء في {DEMO_TRIAL_STRATEGIES_ENV} — لا تجربة."
        )

    reference = (env.get(DEMO_TRIAL_REFERENCE_ENV, "") or "").strip()
    if not reference:
        # نفس شرط `ExecutionLock.authorise`: لا فتح بلا مرجع موافقة مكتوب.
        return DemoTrial(
            note_ar=f"لا مرجع موافقة في {DEMO_TRIAL_REFERENCE_ENV} — لا تجربة."
        )

    resolution = (env.get(DEMO_TRIAL_RESOLUTION_ENV, "") or DEFAULT_RESOLUTION).strip().upper()
    if resolution not in ALLOWED_RESOLUTIONS:
        return DemoTrial(
            note_ar=(
                f"دقّة غير معروفة: {resolution!r}. المسموح: "
                f"{'، '.join(ALLOWED_RESOLUTIONS)} — لا تجربة."
            )
        )

    return DemoTrial(
        enabled=True,
        strategies=names,
        resolution=resolution,
        approval_reference=reference,
        note_ar=(
            f"تجربة تجريبية: {'، '.join(sorted(names))} على شموع {resolution}. "
            "لا اعتماد — الاستراتيجيات تبقى في حالة بحث."
        ),
    )


def demo_trial_for(broker: Any, trial: DemoTrial) -> DemoTrial:
    """
    **البوابة.** تُلغي التجربة إلا على وسيطٍ تجريبيٍّ صراحةً.

    وليست فحصاً على `is_live` وحده: غياب الصفة يُعامَل معاملة الحقيقي، فوسيطٌ
    وهميٌّ ناقص أو محوّلٌ جديد لا يفتح الباب بالسهو.
    """
    if not trial.enabled:
        return trial
    is_live = getattr(broker, "is_live", True)
    if is_live is not False:
        return DemoTrial(
            note_ar=(
                "التجربة مطفأة: الوسيط ليس حساباً تجريبياً صراحةً "
                f"({getattr(broker, 'name', 'وسيط غير معروف')}). "
                "ولا تُفتَح استراتيجيةٌ غير معتمدة على حسابٍ حقيقي."
            )
        )
    return replace(trial)


__all__ = [
    "DemoTrial", "read_demo_trial", "demo_trial_for",
    "DEMO_TRIAL_ENV", "DEMO_TRIAL_STRATEGIES_ENV",
    "DEMO_TRIAL_RESOLUTION_ENV", "DEMO_TRIAL_REFERENCE_ENV",
    "ALLOWED_RESOLUTIONS", "DEFAULT_RESOLUTION",
]
