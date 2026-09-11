"""
Risk Engine — الحَكَم النهائي.

لا يستطيع أي مكوّن آخر تجاوزه: الـpipeline لا يملك مساراً لإنشاء OrderIntent
إلا من RiskDecision موافِقة صادرة من هنا. Kill Switch وحده أعلى منه.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..contracts import Balances, Broker, Decision, RiskDecision, Side, Signal, StopKind
from ..money import D
from .constitution import (
    ALLOW_SHORT,
    CFD_ALLOW_SHORT,
    PauseScope,
    RiskLimits,
    RiskMode,
    constitution_fingerprint,
    exposure_bucket,
)
from .costs import CommissionSchedule, CostAssumptions
from .size_ladder import (
    BROKER_MIN_QUANTITY_RISK_EXCEEDED,
    MARGIN_EXCEEDS_AVAILABLE,
    POSITION_SIZE_ROUNDED_TO_ZERO,
    build_ladder,
)
from .sizing import size_position

# reason codes
KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
DAILY_LOSS_EXHAUSTED = "DAILY_LOSS_BUDGET_EXHAUSTED"
WEEKLY_LOSS_EXHAUSTED = "WEEKLY_LOSS_BUDGET_EXHAUSTED"
TOTAL_LOSS_EXHAUSTED = "TOTAL_LOSS_BUDGET_EXHAUSTED"
CONSECUTIVE_LOSS_PAUSE = "CONSECUTIVE_LOSS_PAUSE"
MAX_OPEN_POSITIONS_REACHED = "MAX_OPEN_POSITIONS_REACHED"
DAILY_ENTRY_LIMIT_REACHED = "DAILY_ENTRY_LIMIT_REACHED"
REWARD_RISK_TOO_LOW = "REWARD_RISK_TOO_LOW"
NEWS_BLACKOUT = "NEWS_BLACKOUT"
NO_EXIT_PLAN = "NO_EXIT_PLAN"
#: البيع ممنوعٌ **بالسياسة** — لا لأن خطة الخروج مكسورة.
SHORT_NOT_ALLOWED = "SHORT_NOT_ALLOWED"
RISK_BUDGET_EXCEEDS_REMAINING = "RISK_BUDGET_EXCEEDS_REMAINING_DAILY_BUDGET"
LIFETIME_ENTRY_LIMIT_REACHED = "LIFETIME_ENTRY_LIMIT_REACHED"
PER_ORDER_APPROVAL_REQUIRED = "PER_ORDER_APPROVAL_REQUIRED"
MODE_FORBIDS_ENTRIES = "MODE_FORBIDS_ENTRIES"
INSTRUMENT_NOT_ALLOWED_IN_MODE = "INSTRUMENT_NOT_ALLOWED_IN_MODE"
OPERATIONAL_DRAWDOWN_STOP = "OPERATIONAL_DRAWDOWN_STOP_REACHED"
ACCOUNT_SIZE_INSUFFICIENT_FOR_BROKER_MINIMUM = "ACCOUNT_SIZE_INSUFFICIENT"
CFD_QUANTITY_BELOW_BROKER_MINIMUM = "QUANTITY_BELOW_BROKER_MINIMUM"
#: يُستورَد من `size_ladder` (انظر كتلة الاستيراد) كي لا يوجد للسبب رمزان.
NET_REWARD_RISK_TOO_LOW = "NET_REWARD_RISK_TOO_LOW"
EXPOSURE_BUCKET_OCCUPIED = "EXPOSURE_BUCKET_ALREADY_OCCUPIED"


def _margin_binder(limits, balances) -> str:
    """أيُّ السقفين ربط: رصيد الوسيط أم رأس المال المخصَّص."""
    available = D(balances.available_for_new_trade)
    return (
        "رصيد الحساب عند الوسيط"
        if available < limits.allocated_margin_per_position
        else "رأس المال المخصَّص"
    )


@dataclass(frozen=True)
class SessionRiskState:
    """كل ما يحتاجه المحرك ليعرف أين نحن اليوم/هذا الأسبوع."""

    baseline_equity: Decimal
    current_equity: Decimal
    realized_pnl_today: Decimal
    realized_pnl_week: Decimal
    unrealized_pnl: Decimal
    open_positions: int
    entry_orders_today: int
    consecutive_losses: int
    lifetime_entry_orders: int = 0
    owner_approved_this_order: bool = False
    in_news_blackout: bool = False
    news_blackout_reason_ar: str = ""
    #: رموز المراكز المفتوحة الآن. `open_positions` يعدّها ولا يسمّيها —
    #: والعدد وحده لا يكفي لمنع ثلاثة مراكز على مصدر تعرّض واحد.
    open_symbols: tuple[str, ...] = ()
    #: **حرارةُ المحفظة** — مجموعُ ما تخسره المراكزُ المفتوحة عند وقوفها.
    open_risk_at_stop: Decimal = Decimal("0")
    #: مراكزُ مفتوحةٌ لا وقفَ معروفاً لها. **ليست خطراً صفراً.**
    #:
    #: مجموعٌ فيه مجهولٌ ليس مجموعاً؛ فوجودُ واحدٍ منها يجعل الحرارة غير
    #: قابلةٍ للحساب، ويُغلق البابُ حتى تُعرَف — الجهلُ يُعلَن ولا يُحسب صفراً.
    open_risk_unknown: int = 0
    #: صفقاتٌ مغلقةٌ لا نعرف نتيجتها. **ليست ربحاً صفراً.**
    #:
    #: `realized_pnl_today` تجمع المعلوم وحده، فوجودُ مجهولٍ يعني أنّ
    #: `day_loss` قد تكون أقلَّ من الحقيقة — والعدّادُ الذي يحمي رأس المال
    #: لا يجوز أن يُقلّل. فيُعَدّ الجهل هنا صراحةً، ويُحجَب به فتحُ صفقةٍ
    #: جديدة في `heartbeat` حتى يُعرَف.
    unknown_realised_closes: int = 0

    #: **هل `current_equity` قراءةٌ حيّةٌ من الوسيط؟**
    #:
    #: `False` تعني أنّ الحقل مملوءٌ بأفضل تقديرٍ (الأساس + المحقَّق) كي لا
    #: ينهار قارئ، **وليس أنّه معروف**. وكلُّ قرارٍ يُبنى عليه محجوبٌ عند
    #: البوّابة: حاجزُ التراجع يقيس مسافةً إلى حدٍّ حقيقي، والمراكزُ المفتوحة
    #: تحمل ربحاً وخسارةً غير محقَّقة تُغيّر تلك المسافة الآن لا عند الإغلاق.
    equity_known: bool = False
    #: رصيدُ الحساب كما يقوله الوسيط — **للكفاية والهامش وكشف الانحراف**،
    #: ولا يحلّ محلّ الحصّة المخصَّصة في قياس التراجع.
    broker_equity: Optional[Decimal] = None
    #: زمنُ لقطة الحساب. `None` يعني لم تُقرأ.
    equity_as_of_utc: Optional[datetime] = None
    #: أقدمُ من العتبة (١٢٠ ثانية) ⇒ لا يُبنى عليها قرار.
    equity_stale: bool = True
    equity_reason_ar: str = ""

    @property
    def total_loss(self) -> Decimal:
        return max(Decimal("0"), self.baseline_equity - self.current_equity)

    @property
    def day_loss(self) -> Decimal:
        return max(Decimal("0"), -(self.realized_pnl_today + self.unrealized_pnl))

    @property
    def week_loss(self) -> Decimal:
        return max(Decimal("0"), -(self.realized_pnl_week + self.unrealized_pnl))


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def remaining_daily_budget(self, state: SessionRiskState) -> Decimal:
        return max(Decimal("0"), self.limits.daily_loss - state.day_loss)

    def remaining_total_budget(self, state: SessionRiskState) -> Decimal:
        """يقيس المسافة إلى الحد **التشغيلي** لا إلى الحاجز المطلق."""
        return max(Decimal("0"), self.limits.effective_drawdown_stop() - state.total_loss)

    def _short_allowed(self) -> bool:
        """
        سياسة البيع **من الدستور**، ولكل وسيطٍ علَمُه.

        وكانت هذه القراءة معدومة: العلَمان مكتوبان ومنشوران في البصمة ولا
        يُقرآن. فالسياسة تُنشَر ولا تُنفَّذ — وهو العيب الحاكم في صورة
        نادرة: قيمةٌ تُعرَض ولا تُقرأ **في موضع تنفيذها هي**.
        """
        if self.limits.broker is Broker.CAPITAL_COM:
            return CFD_ALLOW_SHORT
        return ALLOW_SHORT

    def remaining_weekly_budget(self, state: SessionRiskState) -> Decimal:
        return max(Decimal("0"), self.limits.weekly_loss - state.week_loss)

    def remaining_portfolio_heat(self, state: SessionRiskState) -> Decimal:
        """
        ما تبقّى تحت سقف حرارة المحفظة.

        **لا بوّابةَ رفضٍ جديدة**: هذا طرفٌ في `hard_risk_ceiling`، فيضيق
        السقفُ ويبحث سلّمُ الأحجام عن حجمٍ يدخل تحته. ولا يُرفَض إلا إن
        أثبت السلّمُ أنّ أصغرَ حجمٍ ممكنٍ عند الوسيط ما زال فوقه — وهو نصُّ
        فلسفة المشاركة: الحارسُ يضيّق المساحة ولا يغلق الباب.

        والاستثناءُ الوحيد مقصود: مركزٌ مفتوحٌ بلا وقفٍ معروف ⇒ صفر.
        """
        cap = self.limits.max_portfolio_risk
        if cap is None:
            return Decimal("Infinity")
        if state.open_risk_unknown > 0:
            return Decimal("0")
        return max(Decimal("0"), cap - state.open_risk_at_stop)

    def hard_risk_ceiling(self, state: SessionRiskState) -> Decimal:
        """
        **السقف الذي لا يُتجاوَز** — لا التفضيل.

        الأصغر بين: الحدّ الصلب للصفقة (وهو نفسه الأصغر بين الحدّ الدولاري
        ونسبة حقوق الملكية)، وما تبقّى من اليوم، ومن الأسبوع، ومن الإجمالي.

        وهذه هي البوابة التي تحكم قبول الصفقة. أمّا `target_risk_for_next_trade`
        فتفضيلٌ يُختار به **الحجم**، لا يُرفض به.
        """
        return min(
            self.limits.effective_max_risk(state.current_equity),
            self.remaining_daily_budget(state),
            self.remaining_weekly_budget(state),
            self.remaining_total_budget(state),
            self.remaining_portfolio_heat(state),
        )

    def target_risk_for_next_trade(self, state: SessionRiskState) -> Decimal:
        """المخاطرة المفضّلة، مقصوصةً بالسقف الصلب. **تفضيلٌ لا سقف.**"""
        return min(self.limits.target_risk_per_trade, self.hard_risk_ceiling(state))

    def risk_budget_for_next_trade(self, state: SessionRiskState) -> Decimal:
        """
        ميزانية الصفقة القادمة = أصغر قيمة بين:
          الحد المستهدف، وما تبقى من اليوم، وما تبقى من الأسبوع، وما تبقى من الإجمالي.

        تبقى كما هي **لمسار الأسهم** حيث الكمية متغيّرٌ متّصل: هناك يمكن
        بلوغ الهدف بالضبط، فالهدف ميزانيةٌ حقيقية.

        وفي مسار الـCFD الكمية درجاتٌ يفرضها الوسيط، فالهدف لا يُبلَغ عادةً
        بالضبط — واستعمالُه سقفَ رفضٍ هناك كان يرفض فرصاً تحت الحدّ الصلب.
        انظر `hard_risk_ceiling`.
        """
        return self.target_risk_for_next_trade(state)

    def _run_gates(
        self,
        *,
        signal: Signal,
        state: SessionRiskState,
        kill_switch_active: bool,
        now: datetime,
    ) -> tuple[Optional[RiskDecision], list[tuple[str, bool, str]], Decimal]:
        """
        سلسلة البوابات المشتركة بين كل الوسطاء.

        تعيد (رفض أو None، قائمة الفحوص، ميزانية المخاطرة).
        هذه هي النقطة التي تجعل النظام محايداً تجاه الوسيط: نفس القواعد
        تماماً تُطبَّق على أسهم IBKR وعلى CFD من Capital.com.
        """
        checks: list[tuple[str, bool, str]] = []
        fp = constitution_fingerprint(self.limits.mode, self.limits.broker)

        def reject(code: str, message: str):
            checks.append((code, False, message))
            return (
                RiskDecision(
                    approved=False,
                    decision=Decision.HALTED if code == KILL_SWITCH_ACTIVE else Decision.NO_TRADE,
                    reason_code=code,
                    reason_ar=message,
                    checks=tuple(checks),
                    risk_budget_usd=Decimal("0"),
                    constitution_fingerprint=fp,
                    decided_at_utc=now,
                ),
                checks,
                Decimal("0"),
            )

        if kill_switch_active:
            return reject(KILL_SWITCH_ACTIVE, "Kill Switch مفعّل — ممنوع أي دخول جديد.")
        checks.append(("KILL_SWITCH", True, "Kill Switch غير مفعّل."))

        if not self.limits.allows_entries:
            return reject(
                MODE_FORBIDS_ENTRIES,
                f"وضع {self.limits.mode.value} لا يسمح بأي دخول جديد. "
                "الخروج منه يتطلب مراجعة مكتملة وتفويضاً صريحاً من المالكة.",
            )
        checks.append((
            "MODE_ALLOWS_ENTRIES", True,
            f"وضع {self.limits.mode.value} يسمح بتقييم الدخول.",
        ))

        if self.limits.allowed_instruments and signal.symbol.upper() not in {
            s.upper() for s in self.limits.allowed_instruments
        }:
            return reject(
                INSTRUMENT_NOT_ALLOWED_IN_MODE,
                f"الأداة {signal.symbol} خارج قائمة أدوات وضع {self.limits.mode.value} "
                f"({', '.join(sorted(self.limits.allowed_instruments))}).",
            )

        if state.total_loss >= self.limits.hard_total_loss:
            return reject(
                TOTAL_LOSS_EXHAUSTED,
                f"الخسارة الإجمالية {state.total_loss:.2f} بلغت الحد الصارم {self.limits.hard_total_loss:.2f} دولار.",
            )
        operational_stop = self.limits.effective_drawdown_stop()
        if operational_stop < self.limits.hard_total_loss and state.total_loss >= operational_stop:
            return reject(
                OPERATIONAL_DRAWDOWN_STOP,
                f"الخسارة الإجمالية {state.total_loss:.2f} بلغت الحد التشغيلي "
                f"{operational_stop:.2f} دولار (قبل الحاجز المطلق "
                f"{self.limits.hard_total_loss:.2f} بمقدار احتياطي الفجوة).",
            )
        if state.week_loss >= self.limits.weekly_loss:
            return reject(
                WEEKLY_LOSS_EXHAUSTED,
                f"خسارة الأسبوع {state.week_loss:.2f} بلغت الحد {self.limits.weekly_loss:.2f} دولار.",
            )
        if state.day_loss >= self.limits.daily_loss:
            return reject(
                DAILY_LOSS_EXHAUSTED,
                f"خسارة اليوم {state.day_loss:.2f} بلغت الحد {self.limits.daily_loss:.2f} دولار.",
            )
        checks.append((
            "LOSS_BUDGETS",
            True,
            f"متبقٍ اليوم {self.remaining_daily_budget(state):.2f} ومن الإجمالي {self.remaining_total_budget(state):.2f} دولار.",
        ))

        if state.consecutive_losses >= self.limits.consecutive_losses_pause:
            scope_ar = {
                PauseScope.NEXT_SESSION: "حتى الجلسة التالية",
                PauseScope.REST_OF_WEEK: "لبقية الأسبوع",
                PauseScope.LOCKED_REVIEW: (
                    "والانتقال إلى LOCKED_REVIEW — لا استئناف تلقائي غداً، "
                    "ويلزم مراجعة مكتملة وتفويض صريح من المالكة"
                ),
            }[self.limits.pause_scope]
            return reject(
                CONSECUTIVE_LOSS_PAUSE,
                f"{state.consecutive_losses} خسائر متتالية — توقف {scope_ar}.",
            )
        checks.append(("CONSECUTIVE_LOSSES", True, f"خسائر متتالية: {state.consecutive_losses}."))

        if state.open_positions >= self.limits.max_open_positions:
            return reject(
                MAX_OPEN_POSITIONS_REACHED,
                f"عدد المراكز المفتوحة {state.open_positions} بلغ الحد {self.limits.max_open_positions}.",
            )
        if state.entry_orders_today >= self.limits.max_entry_orders_per_day:
            return reject(
                DAILY_ENTRY_LIMIT_REACHED,
                f"أوامر الدخول اليوم {state.entry_orders_today} بلغت الحد {self.limits.max_entry_orders_per_day}.",
            )
        checks.append(("POSITION_COUNTS", True, "ضمن حدود المراكز وأوامر الدخول اليومية."))

        # --- سقف مصدر التعرّض ------------------------------------------
        # ثلاثة مراكز على ثلاث أدوات ليست ثلاث فرص إن كانت تتحرّك بالسبب
        # نفسه: هي **رهانٌ واحد بثلاثة أضعاف الحجم**، وحدود المخاطرة تحسبه
        # ثلاثة فتكذب بثلاثة أضعاف. والعدّ وحده لا يرى ذلك — يحتاج الأسماء.
        bucket = exposure_bucket(signal.symbol)
        same = [sym for sym in state.open_symbols if exposure_bucket(sym) == bucket]
        if len(same) >= self.limits.max_positions_per_exposure_bucket:
            return reject(
                EXPOSURE_BUCKET_OCCUPIED,
                f"مصدر التعرّض «{bucket}» مشغول بـ{len(same)} مركزاً "
                f"({'، '.join(same)}) — والحدّ {self.limits.max_positions_per_exposure_bucket}. "
                f"فتحُ {signal.symbol} فوقه يضاعف الرهان نفسه ولا يوزّعه.",
            )
        checks.append((
            "EXPOSURE_BUCKET", True,
            f"مصدر التعرّض «{bucket}» غير مشغول. الارتباط عبر الدولار "
            f"غير مقيس — الفصل على الطرف غير الدولاري وحده.",
        ))

        if (
            self.limits.max_lifetime_entry_orders is not None
            and state.lifetime_entry_orders >= self.limits.max_lifetime_entry_orders
        ):
            return reject(
                LIFETIME_ENTRY_LIMIT_REACHED,
                f"وضع {self.limits.mode.value} يسمح بـ{self.limits.max_lifetime_entry_orders} "
                f"أمر دخول في عمره كله، وقد استُهلك. يجب تعطيل الوضع والانتقال بموافقة المالكة.",
            )

        if self.limits.requires_per_order_approval and not state.owner_approved_this_order:
            return reject(
                PER_ORDER_APPROVAL_REQUIRED,
                f"وضع {self.limits.mode.value} يتطلب موافقة صريحة من المالكة على هذا الأمر "
                "بعينه قبل الإرسال.",
            )
        if self.limits.requires_per_order_approval:
            checks.append(("OWNER_APPROVAL", True, "موافقة المالكة على هذا الأمر مسجّلة."))

        if state.in_news_blackout:
            return reject(NEWS_BLACKOUT, state.news_blackout_reason_ar or "نافذة حظر أخبار.")
        checks.append(("NEWS_BLACKOUT", True, "خارج نوافذ حظر الأخبار."))

        # ---------------------------------------------------------------------
        # **جهةُ الوقف تُفحَص باتجاه الصفقة، ومنعُ البيع يُقال باسمه.**
        #
        # كان الشرط: `take_profit <= entry or stop >= entry` — وهو وصفُ صفقة
        # شراءٍ وحدها. وفي البيع الوقف **فوق** الدخول والهدف **تحته**،
        # فيصدق الشرطان معاً فتُرفض كل صفقة بيعٍ برسالة تقول إن خطة الخروج
        # «غير منطقية» — وهي منطقيةٌ تماماً، والمنطق المكسور هو الفحص.
        #
        # وثلاثٌ من أربع استراتيجيات تُصدر بيعاً، وتُعلنه في فرضيّتها:
        # «صعوداً كان أو هبوطاً». فنحو نصف الإشارات كان يُقتل بسببٍ كاذب.
        #
        # وأخطر من ذلك: `CFD_ALLOW_SHORT = False` مكتوبةٌ في الدستور،
        # ومنشورةٌ في بصمته، **ولا تُقرأ في أي موضع**. فكان منعُ البيع يقع
        # **بالصدفة** عبر حسابٍ مكسور، ويُبلَّغ برمزٍ يخصّ شيئاً آخر. وسياسةٌ
        # تُفرَض بالغلط تسقط يوم يُصلَح الغلط — بلا أن ينتبه أحد.
        #
        # ⇒ يُفصل السؤالان: الجهةُ تُفحص باتجاه الصفقة، والسياسة تُقرأ من
        #   موضعها وتُرفض باسمها. والسلوك لم يتغيّر: البيع يبقى ممنوعاً —
        #   لكن بقرارٍ مكتوب لا بكسرٍ في المعادلة.
        # ---------------------------------------------------------------------
        if not signal.exit_plan_is_sane:
            return reject(
                NO_EXIT_PLAN,
                "خطة الخروج غير صالحة: الوقف أو الهدف في الجهة الخطأ من الدخول "
                f"({signal.side.value}: دخول {signal.entry_price}، وقف {signal.stop_price}، "
                f"هدف {signal.take_profit_price}).",
            )
        if signal.side is Side.SELL and not self._short_allowed():
            return reject(
                SHORT_NOT_ALLOWED,
                "البيع على المكشوف ممنوع بالدستور "
                f"({'CFD_ALLOW_SHORT' if self.limits.broker is Broker.CAPITAL_COM else 'ALLOW_SHORT'}"
                " = False) — والخطة صالحة، والمنع سياسةٌ لا خطأ.",
            )
        rr = signal.reward_risk_ratio
        if rr < self.limits.min_reward_risk_ratio:
            return reject(
                REWARD_RISK_TOO_LOW,
                f"نسبة العائد/المخاطرة {rr:.2f} أقل من الحد {self.limits.min_reward_risk_ratio}.",
            )
        checks.append(("REWARD_RISK", True, f"نسبة العائد/المخاطرة {rr:.2f} مقبولة."))

        budget = self.risk_budget_for_next_trade(state)
        if budget <= 0:
            return reject(RISK_BUDGET_EXCEEDS_REMAINING, "لا تبقّى ميزانية مخاطرة لصفقة جديدة.")
        checks.append(("RISK_BUDGET", True, f"ميزانية الصفقة {budget:.2f} دولار."))
        return None, checks, budget

    # ------------------------------------------------------------------
    def evaluate(
        self,
        *,
        signal: Signal,
        state: SessionRiskState,
        balances: Balances,
        schedule: CommissionSchedule,
        assumptions: CostAssumptions,
        fractional_allowed: bool,
        kill_switch_active: bool,
        now: datetime,
    ) -> RiskDecision:
        """مسار الأسهم (IBKR): يحسب الكمية بحلّ عكسي من ميزانية المخاطرة."""
        fp = constitution_fingerprint(self.limits.mode, self.limits.broker)
        rejection, checks, budget = self._run_gates(
            signal=signal, state=state, kill_switch_active=kill_switch_active, now=now
        )
        if rejection is not None:
            return rejection

        def reject(code: str, message: str) -> RiskDecision:
            checks.append((code, False, message))
            return RiskDecision(
                approved=False,
                decision=Decision.NO_TRADE,
                reason_code=code,
                reason_ar=message,
                checks=tuple(checks),
                risk_budget_usd=budget,
                constitution_fingerprint=fp,
                decided_at_utc=now,
            )

        sizing = size_position(
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            risk_budget=budget,
            schedule=schedule,
            assumptions=assumptions,
            fractional_allowed=fractional_allowed,
            available_cash=balances.available_for_new_trade,
            limits=self.limits,
        )
        if not sizing.approved:
            checks.append((sizing.reason_code or "SIZING_FAILED", False, sizing.reason_ar))
            return RiskDecision(
                approved=False,
                decision=Decision.NO_TRADE,
                reason_code=sizing.reason_code,
                reason_ar=sizing.reason_ar,
                checks=tuple(checks),
                risk_budget_usd=budget,
                constitution_fingerprint=fp,
                decided_at_utc=now,
            )

        est = sizing.estimate
        assert est is not None

        # الفحص الأخير والأهم: لا يجوز أن تتجاوز الخسارة القصوى الحد المطلق أبداً.
        effective_cap = self.limits.effective_max_risk(state.current_equity)
        if est.total_risk > effective_cap:
            return reject(
                "ABSOLUTE_RISK_CAP_EXCEEDED",
                f"أقصى خسارة {est.total_risk:.2f} تتجاوز الحد الفعلي {effective_cap:.2f} دولار "
                f"(الأصغر بين الحد الدولاري ونسبة حقوق الملكية الحالية).",
            )
        checks.append((
            "ABSOLUTE_RISK_CAP",
            True,
            f"أقصى خسارة {est.total_risk:.2f} ضمن الحد الفعلي {effective_cap:.2f} دولار.",
        ))

        return RiskDecision(
            approved=True,
            decision=Decision.TRADE,
            reason_code=None,
            reason_ar=sizing.reason_ar,
            checks=tuple(checks),
            quantity=sizing.quantity,
            notional=est.notional,
            expected_risk_usd=est.total_risk,
            expected_costs_usd=est.total_costs,
            risk_budget_usd=budget,
            constitution_fingerprint=fp,
            decided_at_utc=now,
        )


    # ------------------------------------------------------------------
    def evaluate_cfd(
        self,
        *,
        signal: Signal,
        state: SessionRiskState,
        balances: Balances,
        kill_switch_active: bool,
        now: datetime,
        economics=None,
        cost_model=None,
        stop_distance_pips: Optional[Decimal] = None,
        take_profit_distance_pips: Optional[Decimal] = None,
        stop_kind: StopKind = StopKind.NORMAL,
    ) -> RiskDecision:
        """
        مسار CFD (Capital.com).

        ## الكمية متغيّرٌ **بدرجات**، لا ثابتٌ ولا متّصل

        الوسيط يفرض كميةً دنيا ودرجةَ زيادة (١٠٠ ثم ٢٠٠… على اليورو،
        و٠٫٠١ ثم ٠٫٠٢… على الذهب). فالسؤال ليس «هل الكمية الدنيا تمرّ؟»
        بل «أيُّ الأحجام الممكنة أقربُ إلى الهدف مما لا يتجاوز السقف؟».

        ## والهدف تفضيلٌ لا سقف

        بوابة القبول هي `hard_risk_ceiling` — الأصغر بين الحدّ الصلب للصفقة
        وما تبقّى من اليوم والأسبوع والإجمالي. و`target_risk` يُختار به
        الحجم من بين المسموح، ولا يُرفض به شيء.

        وكان هنا `cap = min(budget, effective_cap)` و`budget` مقصوصٌ بالهدف
        — فصار الهدف سقفَ رفضٍ فعليّاً: خسارةٌ دنيا قابلة للتنفيذ قدرها
        ١٫٠٠ دولار تُرفض وهي تحت الحدّ الصلب ١٫٥٠ الذي اعتُمد.

        `cost_model` حاضراً ⇒ يُبنى السلّم هنا. و`economics` وحدها تبقى
        مساراً مقبولاً لحجمٍ واحدٍ محسوبٍ سلفاً (اختبارات ومعاينات).
        """
        fp = constitution_fingerprint(self.limits.mode, self.limits.broker)
        rejection, checks, budget = self._run_gates(
            signal=signal, state=state, kill_switch_active=kill_switch_active, now=now
        )
        if rejection is not None:
            return rejection

        hard_ceiling = self.hard_risk_ceiling(state)
        target_risk = self.target_risk_for_next_trade(state)
        # **الهامش يُقاس على المخصَّص، لا على رصيد الحساب.** انظر
        # `allocated_margin_per_position`.
        margin_ceiling = min(
            D(balances.available_for_new_trade),
            self.limits.allocated_margin_per_position,
        )
        ladder = None

        def reject(code: str, message: str, econ=None) -> RiskDecision:
            checks.append((code, False, message))
            return RiskDecision(
                approved=False,
                decision=Decision.NO_TRADE,
                reason_code=code,
                reason_ar=message,
                checks=tuple(checks),
                quantity=getattr(econ, "size", D(0)) if econ is not None else D(0),
                notional=getattr(econ, "notional_exposure", D(0)) if econ is not None else D(0),
                expected_risk_usd=getattr(econ, "all_in_risk", D(0)) if econ is not None else D(0),
                expected_costs_usd=getattr(econ, "total_costs", D(0)) if econ is not None else D(0),
                risk_budget_usd=budget,
                constitution_fingerprint=fp,
                decided_at_utc=now,
            )

        if hard_ceiling <= 0:
            return reject(
                RISK_BUDGET_EXCEEDS_REMAINING,
                "لا تبقّى سقفُ مخاطرةٍ لصفقة جديدة (اليوم أو الأسبوع أو الإجمالي).",
            )

        # ------------------------------------------------------------------
        # السلّم — يُبنى حين يُمرَّر نموذج التكلفة.
        # ------------------------------------------------------------------
        if cost_model is not None:
            if stop_distance_pips is None or take_profit_distance_pips is None:
                return reject(
                    POSITION_SIZE_ROUNDED_TO_ZERO,
                    "لا يمكن بناء سلّم الأحجام بلا مسافتَي الوقف والهدف.",
                )
            ladder = build_ladder(
                cost_model=cost_model,
                entry_price=signal.entry_price,
                stop_distance_pips=stop_distance_pips,
                take_profit_distance_pips=take_profit_distance_pips,
                stop_kind=stop_kind,
                target_risk=target_risk,
                hard_ceiling=hard_ceiling,
                available_margin=margin_ceiling,
            )
            if not ladder.approved:
                first = ladder.candidates[0] if ladder.candidates else None
                message = f"{ladder.reason_ar} — {ladder.trace_ar()}"
                if ladder.reason_code == MARGIN_EXCEEDS_AVAILABLE:
                    # **يُسمّى القيد الذي ربط.** «الهامش لا يكفي» وحدها
                    # ترسل المالكة تبحث في رصيد الوسيط بينما القيد قد يكون
                    # رأس المال المخصَّص — وهما إصلاحان مختلفان تماماً.
                    message = (
                        f"{ladder.reason_ar} — القيد: {_margin_binder(self.limits, balances)} "
                        f"(المخصَّص {self.limits.baseline_equity:.2f} ÷ "
                        f"{self.limits.max_open_positions} مركزاً = "
                        f"{self.limits.allocated_margin_per_position:.2f}، والمتاح عند "
                        f"الوسيط {balances.available_for_new_trade:.2f}). "
                        f"{ladder.trace_ar()}"
                    )
                return reject(
                    ladder.reason_code or BROKER_MIN_QUANTITY_RISK_EXCEEDED,
                    message,
                    getattr(first, "economics", None),
                )
            economics = ladder.chosen.economics
            checks.append((
                "SIZE_LADDER",
                True,
                f"اختير الحجم {ladder.chosen.size} بخسارة كاملة "
                f"{ladder.chosen.all_in_risk:.2f} دولار — الأقرب إلى الهدف "
                f"{target_risk:.2f} تحت السقف {hard_ceiling:.2f}. {ladder.trace_ar()}",
            ))

        if economics is None:
            return reject(
                POSITION_SIZE_ROUNDED_TO_ZERO,
                "لا اقتصاديات ولا نموذج تكلفة — لا قرار.",
            )

        # وقف مضمون مفضّل في الأوضاع الحقيقية، لكنه لا يُفترض توفره.
        if self.limits.prefer_guaranteed_stop and economics.stop_kind is not StopKind.GUARANTEED:
            checks.append((
                "GUARANTEED_STOP",
                True,
                "وقف عادي: الوقف المضمون غير مستعمل — الخسارة قد تتجاوز التقدير عند الفجوة.",
            ))

        if economics.size <= D(0):
            return reject(
                POSITION_SIZE_ROUNDED_TO_ZERO,
                f"الكمية {economics.size} غير صالحة — لا صفقة بكمية صفر.",
                economics,
            )

        # ------------------------------------------------------------------
        # **البوابة الحاكمة: السقف الصلب.** الهدف ليس بوابة.
        # ------------------------------------------------------------------
        if economics.all_in_risk > hard_ceiling:
            return reject(
                BROKER_MIN_QUANTITY_RISK_EXCEEDED,
                f"الخسارة الكاملة {economics.all_in_risk:.2f} دولار عند الكمية "
                f"{economics.size} تتجاوز السقف الصلب {hard_ceiling:.2f} دولار "
                f"(الحدّ الصلب للصفقة {self.limits.effective_max_risk(state.current_equity):.2f}، "
                f"وما تبقّى اليوم {self.remaining_daily_budget(state):.2f}، "
                f"والأسبوع {self.remaining_weekly_budget(state):.2f}).",
                economics,
            )
        _over_target = economics.all_in_risk > target_risk
        checks.append((
            "ABSOLUTE_RISK_CAP",
            True,
            f"الخسارة الكاملة {economics.all_in_risk:.2f} ضمن السقف الصلب "
            f"{hard_ceiling:.2f} دولار."
            + (
                f" وهي فوق الهدف {target_risk:.2f} بـ"
                f"{economics.all_in_risk - target_risk:.2f} — والهدف تفضيلٌ لا سقف، "
                "فلا تُرفض به فرصةٌ تحت الحدّ الصلب."
                if _over_target else ""
            ),
        ))

        if economics.margin_required > margin_ceiling:
            binding = _margin_binder(self.limits, balances)
            return reject(
                MARGIN_EXCEEDS_AVAILABLE,
                f"الهامش المطلوب {economics.margin_required:.2f} يتجاوز السقف "
                f"{margin_ceiling:.2f} دولار — القيد: {binding} "
                f"(المخصَّص {self.limits.baseline_equity:.2f} ÷ "
                f"{self.limits.max_open_positions} مركزاً، والمتاح عند الوسيط "
                f"{balances.available_for_new_trade:.2f}).",
                economics,
            )
        checks.append((
            "MARGIN",
            True,
            f"الهامش {economics.margin_required:.2f} ضمن سقف {margin_ceiling:.2f} دولار "
            f"(المخصَّص {self.limits.baseline_equity:.2f} ÷ "
            f"{self.limits.max_open_positions}؛ رصيد الوسيط "
            f"{balances.available_for_new_trade:.2f}) — وهو حجز لا خسارة.",
        ))

        if self.limits.enforce_economic_viability:
            if economics.net_reward_risk_ratio < self.limits.min_reward_risk_ratio:
                return reject(
                    NET_REWARD_RISK_TOO_LOW,
                    f"نسبة العائد/المخاطرة الصافية بعد التكاليف "
                    f"{economics.net_reward_risk_ratio:.2f} أقل من الحد "
                    f"{self.limits.min_reward_risk_ratio}.",
                    economics,
                )
            if economics.cost_ratio > self.limits.max_cost_ratio_of_risk:
                return reject(
                    "COST_DOMINATED",
                    f"الاحتكاك يلتهم {economics.cost_ratio * 100:.1f}% من المخاطرة "
                    f"(الحد {self.limits.max_cost_ratio_of_risk * 100:.0f}%).",
                    economics,
                )
        checks.append((
            "NET_REWARD_RISK",
            True,
            f"العائد الصافي {economics.net_reward:.2f} ونسبته إلى المخاطرة "
            f"{economics.net_reward_risk_ratio:.2f}.",
        ))

        if economics.provisional:
            checks.append((
                "PROVISIONAL_VALUES",
                True,
                "بعض القيم مبدئية ولم تُكتشف من الوسيط — لا يُبنى تنفيذ حقيقي على هذا القرار.",
            ))

        return RiskDecision(
            approved=True,
            decision=Decision.TRADE,
            reason_code=None,
            reason_ar=(
                f"كمية {economics.size} بتعرّض {economics.notional_exposure:.2f} دولار، "
                f"هامش {economics.margin_required:.2f}، وخسارة كاملة متوقعة "
                f"{economics.all_in_risk:.2f} دولار ضمن سقف {hard_ceiling:.2f} "
                f"(الهدف {target_risk:.2f})."
            ),
            checks=tuple(checks),
            quantity=economics.size,
            notional=economics.notional_exposure,
            expected_risk_usd=economics.all_in_risk,
            expected_costs_usd=economics.total_costs,
            risk_budget_usd=budget,
            constitution_fingerprint=fp,
            decided_at_utc=now,
        )
