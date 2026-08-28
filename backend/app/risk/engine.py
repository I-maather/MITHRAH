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

from ..contracts import Balances, Decision, RiskDecision, Signal
from ..money import D
from .constitution import PauseScope, RiskLimits, constitution_fingerprint
from .costs import CommissionSchedule, CostAssumptions
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
RISK_BUDGET_EXCEEDS_REMAINING = "RISK_BUDGET_EXCEEDS_REMAINING_DAILY_BUDGET"
LIFETIME_ENTRY_LIMIT_REACHED = "LIFETIME_ENTRY_LIMIT_REACHED"
PER_ORDER_APPROVAL_REQUIRED = "PER_ORDER_APPROVAL_REQUIRED"


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
        return max(Decimal("0"), self.limits.hard_total_loss - state.total_loss)

    def risk_budget_for_next_trade(self, state: SessionRiskState) -> Decimal:
        """
        ميزانية الصفقة القادمة = أصغر قيمة بين:
          الحد المستهدف، وما تبقى من اليوم، وما تبقى من الأسبوع، وما تبقى من الإجمالي.
        بحيث لا تستطيع صفقة واحدة أن تخترق حداً أعلى.
        """
        remaining_week = max(Decimal("0"), self.limits.weekly_loss - state.week_loss)
        return min(
            self.limits.target_risk_per_trade,
            self.remaining_daily_budget(state),
            remaining_week,
            self.remaining_total_budget(state),
        )

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
        checks: list[tuple[str, bool, str]] = []
        fp = constitution_fingerprint(self.limits.mode)

        def reject(code: str, message: str) -> RiskDecision:
            checks.append((code, False, message))
            return RiskDecision(
                approved=False,
                decision=Decision.HALTED if code == KILL_SWITCH_ACTIVE else Decision.NO_TRADE,
                reason_code=code,
                reason_ar=message,
                checks=tuple(checks),
                risk_budget_usd=Decimal("0"),
                constitution_fingerprint=fp,
                decided_at_utc=now,
            )

        if kill_switch_active:
            return reject(KILL_SWITCH_ACTIVE, "Kill Switch مفعّل — ممنوع أي دخول جديد.")
        checks.append(("KILL_SWITCH", True, "Kill Switch غير مفعّل."))

        if state.total_loss >= self.limits.hard_total_loss:
            return reject(
                TOTAL_LOSS_EXHAUSTED,
                f"الخسارة الإجمالية {state.total_loss:.2f} بلغت الحد الصارم {self.limits.hard_total_loss:.2f} دولار.",
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
            scope_ar = (
                "حتى الجلسة التالية"
                if self.limits.pause_scope is PauseScope.NEXT_SESSION
                else "لبقية الأسبوع"
            )
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

        if signal.take_profit_price <= signal.entry_price or signal.stop_price >= signal.entry_price:
            return reject(NO_EXIT_PLAN, "خطة الخروج غير صالحة: الهدف والوقف غير منطقيين.")
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
        if est.total_risk > self.limits.max_risk_per_trade:
            return reject(
                "ABSOLUTE_RISK_CAP_EXCEEDED",
                f"أقصى خسارة {est.total_risk:.2f} تتجاوز الحد المطلق {self.limits.max_risk_per_trade:.2f} دولار.",
            )
        checks.append((
            "ABSOLUTE_RISK_CAP",
            True,
            f"أقصى خسارة {est.total_risk:.2f} ضمن الحد المطلق {self.limits.max_risk_per_trade:.2f} دولار.",
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
