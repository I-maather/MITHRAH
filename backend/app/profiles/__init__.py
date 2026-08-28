"""
TRADING PROFILES — ملفات التداول القابلة للاختيار.

ثلاثة ملفات فقط. **لا يوجد ملف «مخاطرة عالية» غير مقيَّد.**

  CAPITAL_PRESERVATION  متحفّظ
  BALANCED              متوازن
  ACTIVE_CONTROLLED     نشط محسوب

المبدأ الحاكم — وهو أهم سطر في هذا الملف:

    الملف المختار يغيّر **حجم المخاطرة المسموح وتواتر الفرص فقط**.
    لا يغيّر — ولا يستطيع أن يغيّر — أياً مما يلي:

      * متطلبات جودة البيانات
      * عمق التحليل
      * فحوص الأخبار والتقويم الاقتصادي
      * متطلبات التحقق من الاستراتيجية
      * الحد الأدنى لنسبة العائد/المخاطرة الصافية
      * وجوب وقف الخسارة
      * تأكيد الوسيط
      * المراجعة المستقلة
      * حماية Kill Switch
      * حاجز الخسارة الإجمالي للحساب

الملف الأكثر نشاطاً **لا يجبر النظام على التداول أبداً**.
`NO_TRADE` قرار صحيح ومفضَّل كلما كانت الأدلة ناقصة أو متناقضة.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..money import D
from ..risk.constitution import INITIAL_CAPITAL_USD

PROFILE_SYSTEM_VERSION = "0.3.0"
PROFILE_SYSTEM_EFFECTIVE_DATE = "2026-08-28"


class TradingProfile(str, Enum):
    CAPITAL_PRESERVATION = "CAPITAL_PRESERVATION"
    BALANCED = "BALANCED"
    ACTIVE_CONTROLLED = "ACTIVE_CONTROLLED"


#: ترتيب المخاطرة تصاعدياً. يُستعمل لتحديد ما إذا كان التبديل رفعاً أم خفضاً.
#: لا يوجد مستوى رابع، ولا يمكن إضافة واحد في وقت التشغيل.
PROFILE_RISK_ORDER: dict[TradingProfile, int] = {
    TradingProfile.CAPITAL_PRESERVATION: 0,
    TradingProfile.BALANCED: 1,
    TradingProfile.ACTIVE_CONTROLLED: 2,
}

DEFAULT_PROFILE = TradingProfile.CAPITAL_PRESERVATION
#: الملف الافتراضي **بعد** اكتمال التحقق من الاستراتيجية — ليس اليوم.
DEFAULT_PROFILE_AFTER_VALIDATION = TradingProfile.BALANCED


# ---------------------------------------------------------------------------
# دستور الخسارة العام — يسري على كل الملفات ولا يُعاد ضبطه بالتبديل
# ---------------------------------------------------------------------------

#: الحد التشغيلي للتراجع الكلي. النظام يتوقف هنا، قبل الحاجز.
GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD = D("6.50")

#: احتياطي الفجوة والانزلاق. يفصل الحد التشغيلي عن الحاجز المطلق.
GLOBAL_GAP_SLIPPAGE_RESERVE_USD = D("1.00")

#: الحاجز المطلق المقصود لخسارة الحساب من رأس المال الابتدائي.
#: ⚠️ الوقف العادي **لا يضمنه** عند الفجوة السعرية. هذا إفصاح لا تحفّظ شكلي.
GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD = D("7.50")

assert (
    GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD + GLOBAL_GAP_SLIPPAGE_RESERVE_USD
    == GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD
), "الحد التشغيلي + الاحتياطي يجب أن يساويا الحاجز المطلق بالضبط."

#: فترة التهدئة قبل أن تصبح المخاطرة الأعلى متاحة فعلياً.
PROFILE_UPGRADE_COOLING_HOURS = 24

#: العدّادات التي **لا** يُعاد ضبطها عند تبديل الملف — أبداً، بأي اتجاه.
#: أي إضافة إلى هذه القائمة تعني حماية أكثر؛ أي حذف منها يكسر اختباراً.
NON_RESETTABLE_ON_PROFILE_CHANGE: frozenset[str] = frozenset({
    "daily_loss",
    "weekly_loss",
    "consecutive_losses",
    "total_drawdown",
    "open_risk",
    "kill_switch_state",
    "strategy_validation_history",
})


class ProfileChangeRefusal(str, Enum):
    """أسباب رفض تبديل الملف. كل سبب له اختبار."""

    OPEN_POSITION = "OPEN_POSITION"
    PENDING_OR_UNKNOWN_ORDER = "PENDING_OR_UNKNOWN_ORDER"
    RISK_ENGINE_UNHEALTHY = "RISK_ENGINE_UNHEALTHY"
    ACTIVE_LOSS_LOCK = "ACTIVE_LOSS_LOCK"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    COOLING_PERIOD_ACTIVE = "COOLING_PERIOD_ACTIVE"
    OWNER_CONFIRMATION_MISSING = "OWNER_CONFIRMATION_MISSING"
    SAME_PROFILE = "SAME_PROFILE"
    UNKNOWN_PROFILE = "UNKNOWN_PROFILE"


REFUSAL_TEXT_AR: dict[ProfileChangeRefusal, str] = {
    ProfileChangeRefusal.OPEN_POSITION: "يوجد مركز مفتوح. لا يُرفع مستوى المخاطرة ومركز قائم.",
    ProfileChangeRefusal.PENDING_OR_UNKNOWN_ORDER: (
        "يوجد أمر معلّق أو حالة تنفيذ غير معلومة (UNKNOWN). "
        "الحالة غير المعلومة أخطر من الفشل — تُحلّ أولاً."
    ),
    ProfileChangeRefusal.RISK_ENGINE_UNHEALTHY: "محرك المخاطر ليس في حالة سليمة.",
    ProfileChangeRefusal.ACTIVE_LOSS_LOCK: "يوجد قفل خسارة نشط (يومي أو أسبوعي أو خسائر متتالية).",
    ProfileChangeRefusal.KILL_SWITCH_ACTIVE: "Kill Switch مفعّل. لا تبديل يرفع المخاطرة.",
    ProfileChangeRefusal.COOLING_PERIOD_ACTIVE: "فترة التهدئة (24 ساعة) لم تكتمل بعد.",
    ProfileChangeRefusal.OWNER_CONFIRMATION_MISSING: "رفع مستوى المخاطرة يتطلب تأكيداً صريحاً من المالكة.",
    ProfileChangeRefusal.SAME_PROFILE: "الملف المطلوب هو الملف الحالي نفسه.",
    ProfileChangeRefusal.UNKNOWN_PROFILE: "ملف غير معروف.",
}


@dataclass(frozen=True)
class ProfileSpec:
    """
    مواصفة ملف تداول.

    كل حقل هنا يخص **الحجم أو التواتر أو عتبة الجودة**.
    لا يوجد حقل واحد يستطيع تخفيف بوابة تحليلية أو أمنية — بالتصميم.
    """

    name_ar: str
    description_ar: str

    # -- الحجم -------------------------------------------------------------
    max_risk_per_trade_usd: Decimal
    max_risk_pct_of_current_equity: Decimal
    max_daily_loss_usd: Decimal
    max_weekly_loss_usd: Decimal

    # -- التواتر -----------------------------------------------------------
    max_open_positions: int
    max_entry_orders_per_day: int
    #: خسارة واحدة بكامل المخاطرة تُنهي تداول اليوم (نشط محسوب).
    full_risk_loss_ends_day: bool

    # -- عتبات الجودة (تُشدَّد فقط، لا تُخفَّف) -------------------------------
    min_net_reward_risk: Decimal
    min_quality_score: int

    # -- ثوابت لا تتغيّر بين الملفات (مكرَّرة صراحةً لتُختبَر) -----------------
    allow_overnight: bool = False
    allow_weekend_hold: bool = False
    allowed_instruments: frozenset[str] = frozenset({"EURUSD"})


PROFILE_SPECS: dict[TradingProfile, ProfileSpec] = {
    TradingProfile.CAPITAL_PRESERVATION: ProfileSpec(
        name_ar="متحفّظ",
        description_ar=(
            "أعلى جودة فقط. أصغر مخاطرة. الغرض حماية رأس المال أولاً، "
            "وأي شك يعني NO_TRADE."
        ),
        max_risk_per_trade_usd=D("0.50"),
        max_risk_pct_of_current_equity=D("0.0035"),   # 0.35%
        max_daily_loss_usd=D("0.75"),
        max_weekly_loss_usd=D("1.50"),
        max_open_positions=1,
        max_entry_orders_per_day=1,
        full_risk_loss_ends_day=False,
        min_net_reward_risk=D("1.75"),
        min_quality_score=90,
    ),
    TradingProfile.BALANCED: ProfileSpec(
        name_ar="متوازن",
        description_ar=(
            "الملف الافتراضي **بعد** اكتمال التحقق من الاستراتيجية. "
            "توازن بين تكرار الفرص وحجم المخاطرة."
        ),
        max_risk_per_trade_usd=D("0.75"),
        max_risk_pct_of_current_equity=D("0.0050"),   # 0.50%
        max_daily_loss_usd=D("1.50"),
        max_weekly_loss_usd=D("3.00"),
        max_open_positions=1,
        max_entry_orders_per_day=1,
        full_risk_loss_ends_day=False,
        min_net_reward_risk=D("1.5"),
        min_quality_score=85,
    ),
    TradingProfile.ACTIVE_CONTROLLED: ProfileSpec(
        name_ar="نشط محسوب",
        description_ar=(
            "حجم أكبر **بنفس الأدلة تماماً**. لا يقبل دليلاً أضعف، ولا يخفض عتبة "
            "الثقة، ولا يتداول أكثر لمجرد أن يكون نشطاً. خسارة واحدة بكامل "
            "المخاطرة تُنهي تداول اليوم."
        ),
        max_risk_per_trade_usd=D("1.50"),
        max_risk_pct_of_current_equity=D("0.0100"),   # 1%
        max_daily_loss_usd=D("1.50"),
        max_weekly_loss_usd=D("3.00"),
        max_open_positions=1,
        max_entry_orders_per_day=1,
        full_risk_loss_ends_day=True,
        min_net_reward_risk=D("1.5"),
        min_quality_score=85,
    ),
}


#: ما يُمنع في كل الملفات بلا استثناء — وبصراحة في «النشط المحسوب» أيضاً.
UNIVERSALLY_FORBIDDEN: tuple[str, ...] = (
    "قبول أدلة أضعف",
    "خفض عتبة الثقة",
    "زيادة التواتر لمجرد النشاط",
    "توسيع أو إلغاء حدود الخسارة",
    "المتوسط الهابط (averaging down)",
    "مارتينجيل",
    "التهرّم (pyramiding)",
    "تداول الانتقام",
    "إعادة الفتح تلقائياً بعد خسارة",
    "التداول حين يرفض ملف آخر الإعداد لأسباب بيانات أو استراتيجية",
)


@dataclass(frozen=True)
class ProfileLimits:
    """الحدود المحسوبة بالدولار لملف معيّن عند حقوق ملكية معيّنة."""

    profile: TradingProfile
    profile_system_version: str
    name_ar: str
    equity_used: Decimal

    max_risk_per_trade: Decimal
    max_daily_loss: Decimal
    max_weekly_loss: Decimal
    operational_drawdown_stop: Decimal
    gap_slippage_reserve: Decimal
    absolute_loss_boundary: Decimal

    max_open_positions: int
    max_entry_orders_per_day: int
    full_risk_loss_ends_day: bool
    min_net_reward_risk: Decimal
    min_quality_score: int
    allow_overnight: bool
    allow_weekend_hold: bool
    allowed_instruments: frozenset[str]

    @staticmethod
    def for_profile(
        profile: TradingProfile, current_equity: Optional[Decimal] = None
    ) -> "ProfileLimits":
        spec = PROFILE_SPECS[profile]
        equity = D(current_equity) if current_equity is not None else INITIAL_CAPITAL_USD
        if equity <= 0:
            raise ValueError("حقوق الملكية يجب أن تكون موجبة.")

        # الحد لكل صفقة = **الأصغر** بين السقف الدولاري ونسبة حقوق الملكية الحالية.
        # الحساب المتراجع يقلّص المخاطرة تلقائياً؛ الحساب المرتفع لا يرفعها
        # فوق السقف الدولاري أبداً.
        pct_cap = equity * spec.max_risk_pct_of_current_equity
        per_trade = min(spec.max_risk_per_trade_usd, pct_cap)

        return ProfileLimits(
            profile=profile,
            profile_system_version=PROFILE_SYSTEM_VERSION,
            name_ar=spec.name_ar,
            equity_used=equity,
            max_risk_per_trade=per_trade,
            max_daily_loss=spec.max_daily_loss_usd,
            max_weekly_loss=spec.max_weekly_loss_usd,
            operational_drawdown_stop=GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD,
            gap_slippage_reserve=GLOBAL_GAP_SLIPPAGE_RESERVE_USD,
            absolute_loss_boundary=GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD,
            max_open_positions=spec.max_open_positions,
            max_entry_orders_per_day=spec.max_entry_orders_per_day,
            full_risk_loss_ends_day=spec.full_risk_loss_ends_day,
            min_net_reward_risk=spec.min_net_reward_risk,
            min_quality_score=spec.min_quality_score,
            allow_overnight=spec.allow_overnight,
            allow_weekend_hold=spec.allow_weekend_hold,
            allowed_instruments=spec.allowed_instruments,
        )

    def as_display_dict(self) -> dict:
        return {
            "profile": self.profile.value,
            "name_ar": self.name_ar,
            "profile_system_version": self.profile_system_version,
            "equity_used": f"{self.equity_used:.2f}",
            "max_risk_per_trade": f"{self.max_risk_per_trade:.2f}",
            "max_daily_loss": f"{self.max_daily_loss:.2f}",
            "max_weekly_loss": f"{self.max_weekly_loss:.2f}",
            "operational_drawdown_stop": f"{self.operational_drawdown_stop:.2f}",
            "gap_slippage_reserve": f"{self.gap_slippage_reserve:.2f}",
            "absolute_loss_boundary": f"{self.absolute_loss_boundary:.2f}",
            "max_open_positions": self.max_open_positions,
            "max_entry_orders_per_day": self.max_entry_orders_per_day,
            "full_risk_loss_ends_day": self.full_risk_loss_ends_day,
            "min_net_reward_risk": f"{self.min_net_reward_risk:.2f}",
            "min_quality_score": self.min_quality_score,
            "allow_overnight": self.allow_overnight,
            "allow_weekend_hold": self.allow_weekend_hold,
            "allowed_instruments": sorted(self.allowed_instruments),
        }


def is_upgrade(current: TradingProfile, requested: TradingProfile) -> bool:
    """هل التبديل يرفع المخاطرة؟ الرفع وحده هو ما يحتاج تهدئة وتأكيداً."""
    return PROFILE_RISK_ORDER[requested] > PROFILE_RISK_ORDER[current]


def profile_fingerprint(profile: TradingProfile) -> str:
    """بصمة SHA-256 لكل قيم الملف + دستور الخسارة العام."""
    spec = PROFILE_SPECS[profile]
    payload = {
        "profile_system_version": PROFILE_SYSTEM_VERSION,
        "effective_date": PROFILE_SYSTEM_EFFECTIVE_DATE,
        "profile": profile.value,
        "risk_rank": PROFILE_RISK_ORDER[profile],
        "spec": {
            k: (sorted(v) if isinstance(v, frozenset) else str(v))
            for k, v in asdict(spec).items()
        },
        "global_loss_constitution": {
            "operational_drawdown_stop": str(GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD),
            "gap_slippage_reserve": str(GLOBAL_GAP_SLIPPAGE_RESERVE_USD),
            "absolute_loss_boundary": str(GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD),
            "cooling_hours": PROFILE_UPGRADE_COOLING_HOURS,
        },
        "non_resettable": sorted(NON_RESETTABLE_ON_PROFILE_CHANGE),
        "universally_forbidden": list(UNIVERSALLY_FORBIDDEN),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


__all__ = [
    "TradingProfile",
    "ProfileSpec",
    "ProfileLimits",
    "ProfileChangeRefusal",
    "PROFILE_SPECS",
    "PROFILE_RISK_ORDER",
    "PROFILE_SYSTEM_VERSION",
    "PROFILE_UPGRADE_COOLING_HOURS",
    "GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD",
    "GLOBAL_GAP_SLIPPAGE_RESERVE_USD",
    "GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD",
    "NON_RESETTABLE_ON_PROFILE_CHANGE",
    "UNIVERSALLY_FORBIDDEN",
    "REFUSAL_TEXT_AR",
    "DEFAULT_PROFILE",
    "DEFAULT_PROFILE_AFTER_VALIDATION",
    "is_upgrade",
    "profile_fingerprint",
]


#: ما **لا** يغيّره اختيار الملف أبداً — يُعرض في الواجهة وتحرسه اختبارات.
#: الملف يغيّر حجم المخاطرة وتواتر الفرص فقط. أي إضافة هنا حماية أكثر.
NEVER_WEAKENED_BY_PROFILE: tuple[str, ...] = (
    "متطلبات جودة البيانات",
    "عمق التحليل",
    "فحوص الأخبار والتقويم الاقتصادي",
    "متطلبات التحقق من الاستراتيجية",
    "الحد الأدنى للعائد/المخاطرة الصافي",
    "وجوب وقف الخسارة",
    "تأكيد الوسيط",
    "المراجعة المستقلة",
    "حماية Kill Switch",
    "حاجز الخسارة الإجمالي للحساب",
)

__all__.append("NEVER_WEAKENED_BY_PROFILE")
