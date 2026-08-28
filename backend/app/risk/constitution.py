"""
RISK CONSTITUTION — دستور المخاطر، الإصدار 0.2.0

هذا الملف هو المصدر البرمجي الوحيد لحدود المخاطر.
لا يوجد أي مسار في التطبيق يستطيع تعديل هذه القيم في وقت التشغيل:
لا API endpoint، لا صفحة إعدادات، لا Learning Module، ولا نموذج لغوي.

رأس المال: 150.00 USD.

تغيير الإصدار 0.1.0 ← 0.2.0 (2026-08-28، هجرة إلى Capital.com):
  * أُضيف وضع LOCKED_REVIEW.
  * خسارتان متتاليتان ⇒ LOCKED_REVIEW في كل الأوضاع، **بلا استئناف تلقائي**
    في اليوم التالي. (كان في 0.1.0: توقف حتى الجلسة التالية.)
  * ثلاث خسائر عبر جلسات مُصرَّح بها منفصلة ⇒ Kill Switch دائم.
  * CONSERVATIVE_LIVE: المخاطرة = الأصغر بين 1.50 دولار و1% من حقوق الملكية الحالية.
  * أُضيف حد تشغيلي للتراجع 6.50 دولار مع احتياطي 1.00 دولار لمخاطر الفجوة،
    بحيث يبقى الحد المطلق 7.50 دولاراً حاجزاً لا هدفاً.
  * قيود الكمية صارت **حسب الوسيط**: IBKR بقيمة أمر بالدولار، و Capital.com
    بالكمية الدنيا للوسيط.
  * LIVE_COMMISSIONING: صفقة واحدة في العمر، EUR/USD فقط، TP إلزامي،
    GSL عند توفره، لا تبييت ولا عطلة نهاية أسبوع.

كل إصدار له بصمة SHA-256 تُسجَّل مع كل قرار مخاطرة.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..contracts import Broker
from ..money import D

CONSTITUTION_VERSION = "0.2.0"
CONSTITUTION_EFFECTIVE_DATE = "2026-08-28"

INITIAL_CAPITAL_USD = D("150.00")


def _scaled(base: Decimal, usd_at_reference: Optional[Decimal]) -> Optional[Decimal]:
    """يقيس قيمة دولارية مُعطاة عند رأس المال المرجعي إلى رأس مال آخر تناسبياً."""
    if usd_at_reference is None:
        return None
    return base * usd_at_reference / INITIAL_CAPITAL_USD


class RiskMode(str, Enum):
    VALIDATION = "VALIDATION"
    LIVE_COMMISSIONING = "LIVE_COMMISSIONING"
    CONSERVATIVE_LIVE = "CONSERVATIVE_LIVE"
    LOCKED_REVIEW = "LOCKED_REVIEW"


class PauseScope(str, Enum):
    NEXT_SESSION = "NEXT_SESSION"
    REST_OF_WEEK = "REST_OF_WEEK"
    LOCKED_REVIEW = "LOCKED_REVIEW"


#: الأوضاع التي تلمس مالاً حقيقياً. كلها تتطلب أقفال Live كاملة.
REAL_MONEY_MODES: frozenset[RiskMode] = frozenset(
    {RiskMode.LIVE_COMMISSIONING, RiskMode.CONSERVATIVE_LIVE}
)


@dataclass(frozen=True)
class BrokerQuantityPolicy:
    """
    كيف تُقيَّد كمية الصفقة عند وسيط معيّن.

    IBKR: بقيمة الأمر بالدولار (سهم كسري).
    Capital.com: بالكمية الدنيا المعلنة من الوسيط — لا يوجد «أمر بـ5 دولارات» في CFD.
    """

    use_broker_minimum_quantity: bool = False
    min_notional_usd: Optional[Decimal] = None
    max_notional_usd: Optional[Decimal] = None
    max_quantity_multiple_of_minimum: Optional[int] = None


@dataclass(frozen=True)
class ModeSpec:
    hard_total_loss_pct: Decimal
    daily_loss_pct: Decimal
    weekly_loss_pct: Decimal
    target_risk_pct: Decimal
    max_risk_pct: Decimal
    #: سقف إضافي كنسبة من حقوق الملكية **الحالية** (لا من Baseline). None = لا يسري.
    max_risk_pct_of_current_equity: Optional[Decimal]
    #: قيم مُعطاة بالدولار عند رأس المال المرجعي، وتُقاس تناسبياً عند تغيّره.
    #: تُستعمل بدل النسب حين تكون القيمة الدولارية هي المقصودة حرفياً،
    #: فلا ينتج عنها كسر عشري دوري يفسد المقارنة.
    operational_drawdown_stop_usd: Optional[Decimal]
    gap_slippage_reserve_usd: Optional[Decimal]
    target_risk_usd: Optional[Decimal]

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
    requires_per_order_approval: bool
    require_take_profit: bool
    prefer_guaranteed_stop: bool
    allow_overnight: bool
    allow_weekend_hold: bool
    allows_entries: bool
    #: قائمة أدوات الوضع **حسب الوسيط**. مجموعة فارغة = لا تقييد على مستوى الوضع
    #: (تبقى القائمة البيضاء في طبقة الأهلية هي الحاكمة).
    allowed_instruments_by_broker: dict[Broker, frozenset[str]]
    quantity_policy_by_broker: dict[Broker, BrokerQuantityPolicy]
    purpose_ar: str


_IBKR_COMMISSIONING_QUANTITY = BrokerQuantityPolicy(
    use_broker_minimum_quantity=False,
    min_notional_usd=D("5.00"),
    max_notional_usd=D("10.00"),
)

_CAPITAL_COMMISSIONING_QUANTITY = BrokerQuantityPolicy(
    use_broker_minimum_quantity=True,
    max_quantity_multiple_of_minimum=1,
)

_OPEN_QUANTITY = BrokerQuantityPolicy()

EURUSD_ONLY: frozenset[str] = frozenset({"EURUSD"})


MODE_SPECS: dict[RiskMode, ModeSpec] = {
    RiskMode.VALIDATION: ModeSpec(
        hard_total_loss_pct=D("0.05"),          # 7.50
        daily_loss_pct=D("0.01"),               # 1.50
        weekly_loss_pct=D("0.03"),              # 4.50
        target_risk_pct=D("0.0025"),            # 0.375 → تُعرض 0.38
        max_risk_pct=D("0.005"),                # 0.75
        max_risk_pct_of_current_equity=None,
        operational_drawdown_stop_usd=None,
        gap_slippage_reserve_usd=None,
        target_risk_usd=None,
        max_open_positions=1,
        max_entry_orders_per_day=1,
        consecutive_losses_pause=2,
        pause_scope=PauseScope.LOCKED_REVIEW,
        consecutive_losses_kill=3,
        min_reward_risk_ratio=D("1.5"),
        enforce_economic_viability=True,
        max_cost_ratio_of_risk=D("0.35"),
        max_breakeven_move_pct=D("0.006"),
        max_lifetime_entry_orders=None,
        requires_per_order_approval=False,
        require_take_profit=True,
        prefer_guaranteed_stop=False,
        allow_overnight=False,
        allow_weekend_hold=False,
        allows_entries=True,
        allowed_instruments_by_broker={
            Broker.CAPITAL_COM: EURUSD_ONLY,
            Broker.IBKR: frozenset(),
            Broker.MOCK: frozenset(),
        },
        quantity_policy_by_broker={
            Broker.IBKR: _OPEN_QUANTITY,
            Broker.CAPITAL_COM: BrokerQuantityPolicy(use_broker_minimum_quantity=True),
            Broker.MOCK: _OPEN_QUANTITY,
        },
        purpose_ar="التحقق الهندسي على بيانات تجريبية. لا مال حقيقي ولا إرسال أوامر.",
    ),
    RiskMode.LIVE_COMMISSIONING: ModeSpec(
        hard_total_loss_pct=D("0.05"),          # 7.50
        daily_loss_pct=D("0.01"),               # 1.50
        weekly_loss_pct=D("0.03"),              # 4.50
        target_risk_pct=D("0.005"),             # يُتجاوَز بالقيمة الدولارية أدناه
        max_risk_pct=D("0.005"),                # 0.75 الحد المطلق
        max_risk_pct_of_current_equity=None,
        operational_drawdown_stop_usd=None,
        gap_slippage_reserve_usd=None,
        target_risk_usd=D("0.50"),              # المفضّل صراحةً بالدولار
        max_open_positions=1,
        max_entry_orders_per_day=1,
        consecutive_losses_pause=1,             # أي خسارة تُنهي الوضع
        pause_scope=PauseScope.LOCKED_REVIEW,
        consecutive_losses_kill=2,
        min_reward_risk_ratio=D("1.0"),
        # ⚠️ الحواجز الاقتصادية معطّلة **عمداً وبموافقة صريحة**:
        # غرض هذه الصفقة اختبار التكامل (اتصال، إرسال، تأكيد، مطابقة، خروج)،
        # لا الربح. تكلفتها معلومة سلفاً ومحدودة بسقف 0.75 دولار.
        enforce_economic_viability=False,
        max_cost_ratio_of_risk=D("1"),
        max_breakeven_move_pct=D("1"),
        max_lifetime_entry_orders=1,
        requires_per_order_approval=True,
        require_take_profit=True,
        prefer_guaranteed_stop=True,
        allow_overnight=False,
        allow_weekend_hold=False,
        allows_entries=True,
        allowed_instruments_by_broker={
            Broker.CAPITAL_COM: EURUSD_ONLY,
            Broker.IBKR: frozenset(),
            Broker.MOCK: frozenset(),
        },
        quantity_policy_by_broker={
            Broker.IBKR: _IBKR_COMMISSIONING_QUANTITY,
            Broker.CAPITAL_COM: _CAPITAL_COMMISSIONING_QUANTITY,
            Broker.MOCK: _IBKR_COMMISSIONING_QUANTITY,
        },
        purpose_ar=(
            "صفقة حقيقية واحدة في العمر لاختبار التكامل: الاتصال، الإرسال، تأكيد "
            "الوسيط، تسجيل السبريد والانزلاق، مطابقة المركز، الخروج، سجل التدقيق، "
            "و Kill Switch. ليست اختبار ربحية. بعد الإغلاق ينتقل النظام إلى LOCKED_REVIEW."
        ),
    ),
    RiskMode.CONSERVATIVE_LIVE: ModeSpec(
        hard_total_loss_pct=D("0.05"),          # 7.50 — حاجز مطلق
        daily_loss_pct=D("0.01"),               # 1.50
        weekly_loss_pct=D("0.02"),              # 3.00
        target_risk_pct=D("0.01"),              # 1.50 all-in
        max_risk_pct=D("0.01"),                 # 1.50 all-in
        max_risk_pct_of_current_equity=D("0.01"),
        operational_drawdown_stop_usd=D("6.50"),
        gap_slippage_reserve_usd=D("1.00"),
        target_risk_usd=None,
        max_open_positions=1,
        max_entry_orders_per_day=1,
        consecutive_losses_pause=2,
        pause_scope=PauseScope.LOCKED_REVIEW,
        consecutive_losses_kill=3,
        min_reward_risk_ratio=D("1.5"),
        enforce_economic_viability=True,
        max_cost_ratio_of_risk=D("0.35"),
        max_breakeven_move_pct=D("0.006"),
        max_lifetime_entry_orders=None,
        requires_per_order_approval=False,
        require_take_profit=True,
        prefer_guaranteed_stop=True,
        allow_overnight=False,
        allow_weekend_hold=False,
        allows_entries=True,
        allowed_instruments_by_broker={
            Broker.CAPITAL_COM: EURUSD_ONLY,
            Broker.IBKR: frozenset(),
            Broker.MOCK: frozenset(),
        },
        quantity_policy_by_broker={
            Broker.IBKR: _OPEN_QUANTITY,
            Broker.CAPITAL_COM: BrokerQuantityPolicy(use_broker_minimum_quantity=True),
            Broker.MOCK: _OPEN_QUANTITY,
        },
        purpose_ar=(
            "التشغيل الحقيقي المحافظ بعد نجاح Commissioning وموافقة منفصلة. "
            "EUR/USD فقط في الإصدار الأول."
        ),
    ),
    RiskMode.LOCKED_REVIEW: ModeSpec(
        hard_total_loss_pct=D("0.05"),
        daily_loss_pct=D("0"),
        weekly_loss_pct=D("0"),
        target_risk_pct=D("0"),
        max_risk_pct=D("0"),
        max_risk_pct_of_current_equity=None,
        operational_drawdown_stop_usd=None,
        gap_slippage_reserve_usd=None,
        target_risk_usd=None,
        max_open_positions=1,
        max_entry_orders_per_day=0,
        consecutive_losses_pause=0,
        pause_scope=PauseScope.LOCKED_REVIEW,
        consecutive_losses_kill=1,
        min_reward_risk_ratio=D("999"),
        enforce_economic_viability=True,
        max_cost_ratio_of_risk=D("0"),
        max_breakeven_move_pct=D("0"),
        max_lifetime_entry_orders=0,
        requires_per_order_approval=True,
        require_take_profit=True,
        prefer_guaranteed_stop=True,
        allow_overnight=False,
        allow_weekend_hold=False,
        allows_entries=False,
        allowed_instruments_by_broker={},
        quantity_policy_by_broker={},
        purpose_ar=(
            "مراجعة إلزامية. لا دخول جديد إطلاقاً. الخروج من هذا الوضع يتطلب "
            "مراجعة مكتملة وتفويضاً صريحاً من المالكة — ولا يحدث تلقائياً أبداً."
        ),
    ),
}

DEFAULT_MODE = RiskMode.VALIDATION
DEFAULT_BROKER = Broker.CAPITAL_COM

# ---------------------------------------------------------------------------
# ثوابت عامة
# ---------------------------------------------------------------------------

MAX_DATA_STALENESS_SECONDS = 60
MAX_SPREAD_PCT_OF_PRICE = D("0.0015")

ALLOW_OVERNIGHT_POSITIONS = False
ALLOW_EXTENDED_HOURS = False
ALLOW_MARGIN = False          # لأسهم IBKR. CFD رافعة بطبيعته — انظر §CFD أدناه.
ALLOW_SHORT = False
ALLOW_DERIVATIVES = False
ALLOW_FOREX = False           # مرجع سياسة V1 لأسهم IBKR
ALLOW_CRYPTO = False

OPENING_BLACKOUT_MINUTES = 30
CLOSING_BLACKOUT_MINUTES = 15
NEWS_BLACKOUT_MINUTES = 30

#: سياسة CFD منفصلة عن سياسة أسهم IBKR أعلاه.
#: Capital.com CFD يستعمل رافعة بالتعريف؛ ما نمنعه هو أن تُترجم الرافعة
#: إلى خسارة تتجاوز الحد الدولاري، لا الرافعة نفسها.
CFD_ALLOW_SHORT = False
CFD_ALLOW_HEDGING = False
CFD_REQUIRE_BROKER_STOP = True
CFD_REQUIRE_BROKER_TAKE_PROFIT = True


@dataclass(frozen=True)
class RiskLimits:
    """القيم المحسوبة بالدولار لوضع ووسيط وBaseline محددين."""

    mode: RiskMode
    broker: Broker
    constitution_version: str
    baseline_equity: Decimal
    hard_total_loss: Decimal
    daily_loss: Decimal
    weekly_loss: Decimal
    target_risk_per_trade: Decimal
    max_risk_per_trade: Decimal
    max_risk_pct_of_current_equity: Optional[Decimal]
    operational_drawdown_stop: Optional[Decimal]
    gap_slippage_reserve: Optional[Decimal]
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
    requires_per_order_approval: bool
    require_take_profit: bool
    prefer_guaranteed_stop: bool
    allow_overnight: bool
    allow_weekend_hold: bool
    allows_entries: bool
    allowed_instruments: frozenset[str]
    quantity_policy: BrokerQuantityPolicy

    # --- توافق مع 0.1.0 (تُستعمل في مسار IBKR فقط) ---------------------
    @property
    def min_notional_usd(self) -> Optional[Decimal]:
        return self.quantity_policy.min_notional_usd

    @property
    def max_notional_usd(self) -> Optional[Decimal]:
        return self.quantity_policy.max_notional_usd

    @property
    def use_broker_minimum_quantity(self) -> bool:
        return self.quantity_policy.use_broker_minimum_quantity

    @staticmethod
    def for_mode(
        mode: RiskMode,
        baseline_equity: Decimal | None = None,
        broker: Broker = DEFAULT_BROKER,
    ) -> "RiskLimits":
        base = D(baseline_equity) if baseline_equity is not None else INITIAL_CAPITAL_USD
        if base <= 0:
            raise ValueError("baseline equity must be positive")
        spec = MODE_SPECS[mode]
        policy = spec.quantity_policy_by_broker.get(broker, BrokerQuantityPolicy())
        return RiskLimits(
            mode=mode,
            broker=broker,
            constitution_version=CONSTITUTION_VERSION,
            baseline_equity=base,
            hard_total_loss=base * spec.hard_total_loss_pct,
            daily_loss=base * spec.daily_loss_pct,
            weekly_loss=base * spec.weekly_loss_pct,
            target_risk_per_trade=(
                _scaled(base, spec.target_risk_usd)
                if spec.target_risk_usd is not None
                else base * spec.target_risk_pct
            ),
            max_risk_per_trade=base * spec.max_risk_pct,
            max_risk_pct_of_current_equity=spec.max_risk_pct_of_current_equity,
            operational_drawdown_stop=_scaled(base, spec.operational_drawdown_stop_usd),
            gap_slippage_reserve=_scaled(base, spec.gap_slippage_reserve_usd),
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
            requires_per_order_approval=spec.requires_per_order_approval,
            require_take_profit=spec.require_take_profit,
            prefer_guaranteed_stop=spec.prefer_guaranteed_stop,
            allow_overnight=spec.allow_overnight,
            allow_weekend_hold=spec.allow_weekend_hold,
            allows_entries=spec.allows_entries,
            allowed_instruments=spec.allowed_instruments_by_broker.get(broker, frozenset()),
            quantity_policy=policy,
        )

    @staticmethod
    def from_baseline(
        baseline_equity: Decimal | None = None, broker: Broker = Broker.IBKR
    ) -> "RiskLimits":
        """
        الوضع الافتراضي VALIDATION.
        الوسيط الافتراضي هنا IBKR للحفاظ على سلوك 0.1.0 في المسارات القديمة.
        """
        return RiskLimits.for_mode(DEFAULT_MODE, baseline_equity, broker)

    def effective_max_risk(self, current_equity: Optional[Decimal] = None) -> Decimal:
        """
        الحد الفعلي = الأصغر بين الحد الدولاري ونسبة حقوق الملكية الحالية.
        الرصيد المرتفع لا يرفع المخاطرة فوق الحد الدولاري أبداً.
        """
        cap = self.max_risk_per_trade
        if self.max_risk_pct_of_current_equity is not None and current_equity is not None:
            cap = min(cap, D(current_equity) * self.max_risk_pct_of_current_equity)
        return max(D("0"), cap)

    def effective_drawdown_stop(self) -> Decimal:
        """
        الحد التشغيلي إن وُجد، وإلا الحد المطلق.
        وجود احتياطي فجوة يعني أننا نتوقف قبل الحاجز لا عنده.
        """
        return self.operational_drawdown_stop or self.hard_total_loss

    def as_dict(self) -> dict:
        data = asdict(self)
        data["allowed_instruments"] = sorted(self.allowed_instruments)
        data["quantity_policy"] = {
            k: (str(v) if isinstance(v, Decimal) else v)
            for k, v in asdict(self.quantity_policy).items()
        }
        return {
            k: (str(v) if isinstance(v, (Decimal, Enum)) else v) for k, v in data.items()
        }


DEFAULT_LIMITS = RiskLimits.for_mode(DEFAULT_MODE, INITIAL_CAPITAL_USD, Broker.IBKR)


def constitution_fingerprint(
    mode: RiskMode = DEFAULT_MODE, broker: Broker = DEFAULT_BROKER
) -> str:
    """
    بصمة ثابتة لكل القيم الدستورية لوضع ووسيط معيّنين.
    أي تغيير في الدستور أو تبديل وضع أو وسيط يظهر فوراً في Audit Log.
    """
    spec = MODE_SPECS[mode]
    policy = spec.quantity_policy_by_broker.get(broker, BrokerQuantityPolicy())
    payload = {
        "constitution_version": CONSTITUTION_VERSION,
        "effective_date": CONSTITUTION_EFFECTIVE_DATE,
        "initial_capital": str(INITIAL_CAPITAL_USD),
        "mode": mode.value,
        "broker": broker.value,
        "spec": {
            k: sorted(v) if isinstance(v, frozenset) else str(v)
            for k, v in asdict(spec).items()
            if k not in ("quantity_policy_by_broker", "allowed_instruments_by_broker")
        },
        "quantity_policy": {k: str(v) for k, v in asdict(policy).items()},
        "allowed_instruments": sorted(spec.allowed_instruments_by_broker.get(broker, frozenset())),
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
        "cfd_flags": {
            "short": CFD_ALLOW_SHORT,
            "hedging": CFD_ALLOW_HEDGING,
            "require_broker_stop": CFD_REQUIRE_BROKER_STOP,
            "require_broker_take_profit": CFD_REQUIRE_BROKER_TAKE_PROFIT,
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()
