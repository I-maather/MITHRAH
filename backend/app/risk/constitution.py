"""
RISK CONSTITUTION — دستور المخاطر.

هذا الملف هو المصدر البرمجي الوحيد لحدود المخاطر.
لا يوجد أي مسار في التطبيق يستطيع تعديل هذه القيم في وقت التشغيل:
  * لا API endpoint.
  * لا صفحة إعدادات.
  * لا Learning Module.
تعديلها = تعديل هذا الملف + commit + مراجعة + إعادة تشغيل + تسجيل في Audit Log.

رأس المال الحقيقي: 150.00 USD (تصحيح المالكة النهائي، 2026-08-28).
أي إشارة سابقة إلى 100 أو 250 دولاراً ملغاة.

ثلاثة أوضاع مخاطرة، والانتقال بينها يتطلب موافقة المالكة:

  VALIDATION           الافتراضي. Paper/Mock. لا مال حقيقي.
  LIVE_COMMISSIONING   صفقة حقيقية واحدة فقط لاختبار التكامل — وليس لاختبار الربحية.
  CONSERVATIVE_LIVE    التشغيل الحقيقي بعد نجاح Commissioning.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..money import D

# ---------------------------------------------------------------------------
# رأس المال — القيمة الوحيدة المعتمدة
# ---------------------------------------------------------------------------

INITIAL_CAPITAL_USD = D("150.00")


class RiskMode(str, Enum):
    VALIDATION = "VALIDATION"
    LIVE_COMMISSIONING = "LIVE_COMMISSIONING"
    CONSERVATIVE_LIVE = "CONSERVATIVE_LIVE"


class PauseScope(str, Enum):
    NEXT_SESSION = "NEXT_SESSION"
    REST_OF_WEEK = "REST_OF_WEEK"


# ---------------------------------------------------------------------------
# النسب لكل وضع — Frozen
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModeSpec:
    hard_total_loss_pct: Decimal
    daily_loss_pct: Decimal
    weekly_loss_pct: Decimal
    target_risk_pct: Decimal
    max_risk_pct: Decimal
    max_open_positions: int
    max_entry_orders_per_day: int
    consecutive_losses_pause: int
    pause_scope: PauseScope
    consecutive_losses_kill: int
    min_reward_risk_ratio: Decimal
    # حواجز اقتصادية هندسية (ليست من نص الدستور — انظر §"حواجز هندسية" أدناه)
    enforce_economic_viability: bool
    max_cost_ratio_of_risk: Decimal
    max_breakeven_move_pct: Decimal
    # قيود خاصة بالتشغيل التجريبي الحقيقي
    max_lifetime_entry_orders: Optional[int]
    min_notional_usd: Optional[Decimal]
    max_notional_usd: Optional[Decimal]
    requires_per_order_approval: bool
    purpose_ar: str


MODE_SPECS: dict[RiskMode, ModeSpec] = {
    RiskMode.VALIDATION: ModeSpec(
        hard_total_loss_pct=D("0.05"),      # 7.50
        daily_loss_pct=D("0.01"),           # 1.50
        weekly_loss_pct=D("0.03"),          # 4.50
        target_risk_pct=D("0.0025"),        # 0.375 → تُعرض 0.38
        max_risk_pct=D("0.005"),            # 0.75
        max_open_positions=1,
        max_entry_orders_per_day=1,
        consecutive_losses_pause=2,
        pause_scope=PauseScope.NEXT_SESSION,
        consecutive_losses_kill=3,
        min_reward_risk_ratio=D("1.5"),
        enforce_economic_viability=True,
        max_cost_ratio_of_risk=D("0.35"),
        max_breakeven_move_pct=D("0.006"),
        max_lifetime_entry_orders=None,
        min_notional_usd=None,
        max_notional_usd=None,
        requires_per_order_approval=False,
        purpose_ar="التحقق الهندسي على Paper/Mock. لا مال حقيقي.",
    ),
    RiskMode.LIVE_COMMISSIONING: ModeSpec(
        hard_total_loss_pct=D("0.05"),      # 7.50
        daily_loss_pct=D("0.01"),           # 1.50
        weekly_loss_pct=D("0.03"),          # 4.50
        target_risk_pct=D("0.005"),         # 0.75 — الصفقة التجريبية تُسمح حتى الحد الأقصى
        max_risk_pct=D("0.005"),            # 0.75 سقف مطلق يبقى سارياً
        max_open_positions=1,
        max_entry_orders_per_day=1,
        consecutive_losses_pause=1,         # أي خسارة تُنهي الوضع
        pause_scope=PauseScope.REST_OF_WEEK,
        consecutive_losses_kill=2,
        min_reward_risk_ratio=D("1.0"),     # الغرض اختبار تكامل، لا ربحية
        # ⚠️ الحواجز الاقتصادية مُعطّلة هنا **عمداً وبموافقة صريحة من المالكة**:
        # الغرض من هذه الصفقة اختبار الاتصال والتنفيذ والتأكيد والمطابقة والخروج،
        # وليس الربح. صفقة بـ5–10 دولارات ستكون بالضرورة «مسيطر عليها بالتكلفة»،
        # وهذا مقبول لأنها رسوم اختبار معلومة ومحدودة سلفاً، لا رهان على السوق.
        enforce_economic_viability=False,
        max_cost_ratio_of_risk=D("1"),
        max_breakeven_move_pct=D("1"),
        max_lifetime_entry_orders=1,        # صفقة حقيقية واحدة في عمر هذا الوضع
        min_notional_usd=D("5.00"),
        max_notional_usd=D("10.00"),
        requires_per_order_approval=True,   # لا إرسال بلا موافقة المالكة على هذا الأمر بعينه
        purpose_ar=(
            "اختبار التكامل الحقيقي مع IBKR بصفقة واحدة صغيرة: الاتصال، الإرسال، "
            "تأكيد التنفيذ، تسجيل العمولة والانزلاق، مطابقة المركز، الخروج، "
            "سجل التدقيق، و Kill Switch. ليس اختبار ربحية."
        ),
    ),
    RiskMode.CONSERVATIVE_LIVE: ModeSpec(
        hard_total_loss_pct=D("0.05"),      # 7.50
        daily_loss_pct=D("0.01"),           # 1.50
        weekly_loss_pct=D("0.02"),          # 3.00
        target_risk_pct=D("0.01"),          # 1.50 all-in
        max_risk_pct=D("0.01"),             # 1.50 all-in — لا تجاوز
        max_open_positions=1,
        max_entry_orders_per_day=1,
        consecutive_losses_pause=2,
        pause_scope=PauseScope.REST_OF_WEEK,
        consecutive_losses_kill=3,
        min_reward_risk_ratio=D("1.5"),
        enforce_economic_viability=True,
        max_cost_ratio_of_risk=D("0.35"),
        max_breakeven_move_pct=D("0.006"),
        max_lifetime_entry_orders=None,
        min_notional_usd=None,
        max_notional_usd=None,
        requires_per_order_approval=False,
        purpose_ar="التشغيل الحقيقي المحافظ بعد نجاح Commissioning وموافقة المالكة.",
    ),
}

DEFAULT_MODE = RiskMode.VALIDATION

# ---------------------------------------------------------------------------
# ثوابت عامة لا تتغير بتغير الوضع
# ---------------------------------------------------------------------------

MAX_DATA_STALENESS_SECONDS = 60
MAX_SPREAD_PCT_OF_PRICE = D("0.0015")   # 15 bps

ALLOW_OVERNIGHT_POSITIONS = False
ALLOW_EXTENDED_HOURS = False
ALLOW_MARGIN = False
ALLOW_SHORT = False
ALLOW_DERIVATIVES = False
ALLOW_FOREX = False
ALLOW_CRYPTO = False

OPENING_BLACKOUT_MINUTES = 30
CLOSING_BLACKOUT_MINUTES = 15
NEWS_BLACKOUT_MINUTES = 30


@dataclass(frozen=True)
class RiskLimits:
    """القيم المحسوبة بالدولار لوضع معيّن وBaseline معيّن."""

    mode: RiskMode
    baseline_equity: Decimal
    hard_total_loss: Decimal
    daily_loss: Decimal
    weekly_loss: Decimal
    target_risk_per_trade: Decimal
    max_risk_per_trade: Decimal
    max_open_positions: int
    max_entry_orders_per_day: int
    consecutive_losses_pause: int
    pause_scope: PauseScope
    consecutive_losses_kill: int
    min_reward_risk_ratio: Decimal
    enforce_economic_viability: bool
    max_cost_ratio_of_risk: Decimal
    max_breakeven_move_pct: Decimal
    max_lifetime_entry_orders: Optional[int]
    min_notional_usd: Optional[Decimal]
    max_notional_usd: Optional[Decimal]
    requires_per_order_approval: bool

    @staticmethod
    def for_mode(mode: RiskMode, baseline_equity: Decimal | None = None) -> "RiskLimits":
        base = D(baseline_equity) if baseline_equity is not None else INITIAL_CAPITAL_USD
        if base <= 0:
            raise ValueError("baseline equity must be positive")
        spec = MODE_SPECS[mode]
        return RiskLimits(
            mode=mode,
            baseline_equity=base,
            hard_total_loss=base * spec.hard_total_loss_pct,
            daily_loss=base * spec.daily_loss_pct,
            weekly_loss=base * spec.weekly_loss_pct,
            target_risk_per_trade=base * spec.target_risk_pct,
            max_risk_per_trade=base * spec.max_risk_pct,
            max_open_positions=spec.max_open_positions,
            max_entry_orders_per_day=spec.max_entry_orders_per_day,
            consecutive_losses_pause=spec.consecutive_losses_pause,
            pause_scope=spec.pause_scope,
            consecutive_losses_kill=spec.consecutive_losses_kill,
            min_reward_risk_ratio=spec.min_reward_risk_ratio,
            enforce_economic_viability=spec.enforce_economic_viability,
            max_cost_ratio_of_risk=spec.max_cost_ratio_of_risk,
            max_breakeven_move_pct=spec.max_breakeven_move_pct,
            max_lifetime_entry_orders=spec.max_lifetime_entry_orders,
            min_notional_usd=spec.min_notional_usd,
            max_notional_usd=spec.max_notional_usd,
            requires_per_order_approval=spec.requires_per_order_approval,
        )

    @staticmethod
    def from_baseline(baseline_equity: Decimal | None = None) -> "RiskLimits":
        """الوضع الافتراضي VALIDATION."""
        return RiskLimits.for_mode(DEFAULT_MODE, baseline_equity)

    def as_dict(self) -> dict:
        return {k: str(v) for k, v in asdict(self).items()}


DEFAULT_LIMITS = RiskLimits.for_mode(DEFAULT_MODE, INITIAL_CAPITAL_USD)


def constitution_fingerprint(mode: RiskMode = DEFAULT_MODE) -> str:
    """
    بصمة ثابتة لكل القيم الدستورية لوضع معيّن.
    تُسجَّل مع كل قرار مخاطرة، فيصبح أي تغيير في الدستور — أو أي تبديل وضع —
    مكشوفاً فوراً في Audit Log.
    """
    spec = MODE_SPECS[mode]
    payload = {
        "initial_capital": str(INITIAL_CAPITAL_USD),
        "mode": mode.value,
        "spec": {k: (str(v) if isinstance(v, (Decimal, PauseScope)) else v)
                 for k, v in asdict(spec).items()},
        "staleness_s": MAX_DATA_STALENESS_SECONDS,
        "max_spread_pct": str(MAX_SPREAD_PCT_OF_PRICE),
        "blackouts": [OPENING_BLACKOUT_MINUTES, CLOSING_BLACKOUT_MINUTES, NEWS_BLACKOUT_MINUTES],
        "flags": {
            "overnight": ALLOW_OVERNIGHT_POSITIONS,
            "extended_hours": ALLOW_EXTENDED_HOURS,
            "margin": ALLOW_MARGIN,
            "short": ALLOW_SHORT,
            "derivatives": ALLOW_DERIVATIVES,
            "forex": ALLOW_FOREX,
            "crypto": ALLOW_CRYPTO,
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()
