"""
سياسةُ إدارة المركز — **معلَنةٌ لكلّ استراتيجيةٍ بإصدارها، ومُثبَتةٌ بدليل**.

## المسألة

`exit_conditions_ar` في كل استراتيجيةٍ نثرٌ عربيّ جميل:

    «وقفٌ عند الدخول ∓ 1.5×ATR14.»
    «هدفٌ عند الدخول ± 3.0×ATR14.»
    «لا مبيت: تُغلق قبل نهاية الجلسة.»

وثالثُها **خروجٌ زمنيّ مُعلَن ولا يُنفَّذ**: لا سطرَ في المشروع يغلق مركزاً
قبل نهاية الجلسة. وهو نفس العيب الحاكم الذي أكلَ `timeframe` من قبل — قيمةٌ
تُعلَن ولا تُقرأ — لكنّ أثره هنا مركزٌ يبيت وقد قيل إنّه لا يبيت.

## القاعدة

الإدارةُ لا تُشتقّ من نصّ. تُعلَن حقولاً: أيُّ قدرةٍ مفعّلة، وبأيّ معاملات،
وبأيّ إصدار سياسة، **وبأيّ دليل**.

والافتراضُ الصامت هو الخروج الثابت المعتمد وحده: `FIXED_EXIT`. أيُّ قدرةٍ
ديناميكية — تعادل، أو مطاردة، أو خروجٌ زمنيّ، أو جني جزئيّ — تحتاج دليلاً
مُسمّى (اختبارٌ تاريخيّ، وخارجَ العيّنة، وورقيّ) وإلا **رُفض تسجيلها**.

فالنتيجة اليوم صريحة: لا سياسةَ ديناميكيةٍ واحدة مفعّلة، لأنّ لا دليلَ لواحدة.
والمحرّك موجودٌ ومختبَرٌ ومحروس، ينتظر الدليل لا العكس. وهذا أصدق من قواعد
تُطبَّق على كلّ الصفقات لأنها «معقولة».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Capability(str, Enum):
    """قدرات الإدارة — كلٌّ تُعلَن أو لا توجد."""

    #: الوقف والهدف المعتمدان عند الدخول، بلا تحريك. **الافتراض دائماً.**
    FIXED_EXIT = "FIXED_EXIT"
    #: نقلُ الوقف إلى نقطة الدخول بعد ربحٍ محدَّد بـR.
    BREAK_EVEN = "BREAK_EVEN"
    #: مطاردةُ الوقف خلف السعر بمضاعفٍ من ATR.
    TRAILING_STOP = "TRAILING_STOP"
    #: إغلاقٌ عند مدّةٍ محدَّدة أو قبل نهاية الجلسة.
    TIME_EXIT = "TIME_EXIT"
    #: إغلاقٌ حين تسقط فرضيةُ الدخول نفسها.
    THESIS_INVALIDATION = "THESIS_INVALIDATION"
    #: جنيُ جزءٍ من المركز عند مضاعفٍ من R.
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"
    #: زيادةُ المركز بعد الدخول. **يزيد المخاطرة** فيخضع لحدود الدخول كاملةً.
    SCALE_IN = "SCALE_IN"
    #: إغلاقٌ قبل حدثٍ اقتصاديّ معلوم.
    EVENT_EXIT = "EVENT_EXIT"
    #: إغلاقٌ اضطراريّ — قاطع الطوارئ أو انهيار الحماية عند الوسيط.
    EMERGENCY_EXIT = "EMERGENCY_EXIT"


#: القدرات التي **تحتاج دليلاً** قبل أن تُفعَّل.
#:
#: الخروج الثابت لا يحتاجه: هو ما وافقت عليه المخاطر عند الدخول أصلاً.
#: والخروج الاضطراريّ لا يحتاجه: هو تقليلُ مخاطرةٍ عند عطل، لا رهانٌ على
#: تحسين النتيجة.
REQUIRES_EVIDENCE = frozenset(Capability) - {
    Capability.FIXED_EXIT,
    Capability.EMERGENCY_EXIT,
}


class PolicyRejected(ValueError):
    """سياسةٌ لا تستوفي شرط الدليل — لا تُسجَّل ولا تعمل."""


@dataclass(frozen=True)
class ManagementPolicy:
    """
    سياسةُ استراتيجيةٍ واحدةٍ بإصدارٍ واحد.

    `policy_version` مستقلٌّ عن إصدار الاستراتيجية عمداً: تغييرُ الإدارة
    تغييرٌ في السلوك يجب أن يُنسَب ويُقارَن، حتى لو لم يتغيّر الدخول.
    """

    strategy_name: str
    strategy_version: str
    policy_version: str
    capabilities: frozenset[Capability] = frozenset({Capability.FIXED_EXIT})

    #: نقلُ الوقف إلى التعادل بعد هذا المضاعف من R. `None` = معطّل.
    break_even_after_r: Optional[Decimal] = None
    #: مضاعفُ ATR لمطاردة الوقف. `None` = معطّل.
    trailing_atr_multiple: Optional[Decimal] = None
    #: أقصى عمرٍ للمركز بالدقائق. `None` = معطّل.
    max_age_minutes: Optional[int] = None
    #: جني جزئيّ: (المضاعف من R، النسبة المئوية من الكمية).
    partial_take_profit: Optional[tuple[Decimal, Decimal]] = None

    #: **الدليل**: معرّفُ اختبارٍ تاريخيّ، وخارجَ العيّنة، وورقيّ.
    #: يُطلَب لكلّ قدرةٍ ديناميكية، ولا يُقبل نصّاً عامّاً.
    backtest_evidence_ar: str = ""
    out_of_sample_evidence_ar: str = ""
    paper_evidence_ar: str = ""
    notes_ar: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        dynamic = set(self.capabilities) & REQUIRES_EVIDENCE
        if not dynamic:
            return
        missing = [
            name
            for name, value in (
                ("اختبار تاريخي", self.backtest_evidence_ar),
                ("خارج العيّنة", self.out_of_sample_evidence_ar),
                ("ورقي", self.paper_evidence_ar),
            )
            if not value.strip()
        ]
        if missing:
            raise PolicyRejected(
                f"سياسة {self.strategy_name}@{self.strategy_version} تُفعّل "
                f"{', '.join(sorted(c.value for c in dynamic))} بلا دليل: "
                f"ينقصها {'، '.join(missing)}. "
                "القاعدة الديناميكية تُقارَن بالخروج الثابت قبل أن تُشغَّل."
            )

    def has(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @property
    def is_fixed_only(self) -> bool:
        return set(self.capabilities) <= {Capability.FIXED_EXIT, Capability.EMERGENCY_EXIT}

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "strategy_version": self.strategy_version,
            "policy_version": self.policy_version,
            "capabilities": sorted(c.value for c in self.capabilities),
            "fixed_only": self.is_fixed_only,
        }


def default_policy(strategy_name: str = "", strategy_version: str = "") -> ManagementPolicy:
    """
    الافتراض: **الخروج الثابت المعتمد عند الدخول، بلا تحريك.**

    مركزٌ بلا سياسةٍ معلَنة لا يُدار بقاعدةٍ «معقولة» تُخترع له. يُترَك على ما
    وافقت عليه المخاطر، ويُراقَب.
    """
    return ManagementPolicy(
        strategy_name=strategy_name or "UNKNOWN",
        strategy_version=strategy_version or "",
        policy_version="fixed-1",
        capabilities=frozenset({Capability.FIXED_EXIT, Capability.EMERGENCY_EXIT}),
        notes_ar=("لا سياسة معلَنة لهذه الاستراتيجية — الخروج الثابت وحده.",),
    )


@dataclass
class PolicyRegistry:
    """سجلُّ السياسات. المفتاح `name@strategy_version`."""

    _policies: dict[str, ManagementPolicy] = field(default_factory=dict)

    def register(self, policy: ManagementPolicy) -> ManagementPolicy:
        key = f"{policy.strategy_name}@{policy.strategy_version}"
        self._policies[key] = policy
        return policy

    def for_strategy(self, name: str, version: str) -> ManagementPolicy:
        """
        سياسةٌ معلَنة، أو الافتراض الثابت.

        **لا يُرفع خطأ على الغياب**: الغياب حالةٌ عاديّة معناها «لا إدارة
        ديناميكية»، وهو الوضع الصحيح لكلّ استراتيجيةٍ لم يُقَم لها دليل.
        """
        return self._policies.get(f"{name}@{version}") or default_policy(name, version)

    def declared(self) -> tuple[ManagementPolicy, ...]:
        return tuple(self._policies.values())


#: السجلّ الحيّ. **فارغٌ عمداً اليوم**: لا استراتيجيةَ لها دليلُ إدارةٍ
#: ديناميكيّ بعد، فلا واحدةَ تُدار بغير خروجها الثابت المعتمد.
REGISTRY = PolicyRegistry()
