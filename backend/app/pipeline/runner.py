"""
The daily pipeline — خط القرار.

الترتيب إلزامي، وكل مرحلة تستطيع إيقاف الخط بقرار NO_TRADE:

  0. Kill Switch gate
  1. Market Regime / Market status
  2. Macro Risk  (veto only)
  3. Scheduled News Risk (veto only)
  4. Technical State + Market Structure  (داخل الاستراتيجية)
  5. Strategy Eligibility
  6. Risk Review
  7. Order Preview
  8. Execution
  9. Reconciliation
 10. Audit

Macro و News يستطيعان المنع فقط، ولا يستطيعان فرض صفقة.
كل نتيجة — بما فيها NO_TRADE — تُكتب في Audit Log.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Sequence

from ..audit.log import Actor, AuditAction, AuditLog
from ..brokers.base import BrokerAdapter, BrokerNotConnected
from ..clock import now_utc, forex_market_status
from ..contracts import Bar, Decision, RiskDecision, Signal
from ..eligibility.allowlist import check_eligibility
from ..execution.orders import (
    ExecutionService,
    SubmissionOutcome,
    SubmissionResult,
    build_order_intent,
    reconcile,
)
from ..killswitch.engine import KillSwitch, KillSwitchTrigger
from ..money import D
from ..risk.constitution import NEWS_BLACKOUT_MINUTES
from ..risk.costs import CommissionSchedule, CostAssumptions
from ..risk.engine import RiskEngine, SessionRiskState
from ..strategies.base import Strategy


@dataclass(frozen=True)
class MacroAssessment:
    """يمنع فقط. لا يستطيع فرض صفقة."""

    blocks_trading: bool
    reason_ar: str


@dataclass(frozen=True)
class NewsBlackout:
    symbol: Optional[str]
    starts_utc: datetime
    ends_utc: datetime
    title_ar: str
    source: str

    def covers(self, at: datetime, symbol: str) -> bool:
        if self.symbol is not None and self.symbol != symbol:
            return False
        return self.starts_utc <= at <= self.ends_utc


@dataclass
class BlackoutCalendar:
    """
    تقويم حظر يدوي. لا نخترع أخباراً: إن لم يوجد مصدر رسمي موثوق،
    نستخدم هذا التقويم اليدوي، وإن كان فارغاً وغير مؤكد => NO_TRADE.
    """

    entries: list[NewsBlackout] = field(default_factory=list)
    confirmed_for: set[date] = field(default_factory=set)

    def is_confirmed(self, day: date) -> bool:
        return day in self.confirmed_for

    def active(self, at: datetime, symbol: str) -> Optional[NewsBlackout]:
        for e in self.entries:
            if e.covers(at, symbol):
                return e
        return None


@dataclass(frozen=True)
class PipelineResult:
    decision: Decision
    reason_code: Optional[str]
    reason_ar: str
    stage: str
    signal: Optional[Signal] = None
    risk_decision: Optional[RiskDecision] = None
    submission: Optional[SubmissionResult] = None
    reconciliation_ok: Optional[bool] = None
    at_utc: datetime = field(default_factory=now_utc)
    #: تشخيص كل استراتيجية شُغّلت — «لماذا لم تُشِر» بالأرقام.
    #: فارغةٌ حين يقف الخط قبل مرحلة الاستراتيجية، وذلك صادق: لم تُسأل.
    assessments: tuple = ()

    @property
    def one_line_ar(self) -> str:
        if self.decision is Decision.TRADE:
            return f"تنفيذ: {self.reason_ar}"
        if self.decision is Decision.HALTED:
            return f"متوقف: {self.reason_ar}"
        return f"لا تداول اليوم — {self.reason_ar}"


class Pipeline:
    def __init__(
        self,
        *,
        broker: BrokerAdapter,
        risk_engine: RiskEngine,
        kill_switch: KillSwitch,
        audit: AuditLog,
        execution: ExecutionService,
        strategies: Sequence[Strategy],
        schedule: CommissionSchedule,
        assumptions: CostAssumptions,
        blackouts: BlackoutCalendar,
        allow_live_submission: bool = False,
        #: أسماء استراتيجيات مسموحة **على التجريبي وحده**. انظري
        #: `app/runtime/demo_trial.py`. فارغةٌ في كل مسارٍ آخر.
        trial_strategies: frozenset[str] = frozenset(),
    ) -> None:
        self.broker = broker
        self.risk = risk_engine
        self.kill_switch = kill_switch
        self.audit = audit
        self.execution = execution
        self.strategies = list(strategies)
        self.schedule = schedule
        self.assumptions = assumptions
        self.blackouts = blackouts
        self.allow_live_submission = allow_live_submission
        self.trial_strategies = frozenset(trial_strategies)

    # -- helpers ------------------------------------------------------------
    def _no_trade(self, stage: str, code: str, message: str, at: datetime) -> PipelineResult:
        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.NO_TRADE, decision=code,
            reason_ar=message, source=stage, at=at,
        )
        return PipelineResult(Decision.NO_TRADE, code, message, stage, at_utc=at)

    def runnable_strategies(self) -> list:
        """
        الاستراتيجيات التي يحقّ لها أن تُقيّم الآن.

        **دالّة لا سطرٌ داخل `run`** عن قصد: كانت منطقاً مكتوباً في موضع
        واحدٍ يستحيل استدعاؤه من اختبارٍ بلا تشغيل الخط كاملاً، فكُتب له
        اختبارٌ **ينسخ المنطق** — ونسخةٌ في اختبار لا تسقط حين يتغيّر الأصل.
        وهو العطل الحاكم في هذا المشروع مرّةً أخرى: اختبارٌ يمرّ لسببٍ غير
        الذي كُتب له.

        فالمنطق هنا، ويُستدعى من الاختبار كما يُستدعى من `run`.
        """
        approved = [s for s in self.strategies if s.metadata.state.value == "APPROVED"]
        # الاستثناء التجريبي — مقفلٌ على الوسيط **هنا**، عند موضع الاستعمال،
        # لا عند موضع البناء وحده. و`getattr(..., True)` تُغلق عند غياب
        # الصفة: وسيطٌ لا نعرف نوعه يُعامَل معاملة الحقيقي.
        if self.trial_strategies and getattr(self.broker, "is_live", True) is False:
            already = {id(s) for s in approved}
            approved += [
                s for s in self.strategies
                if id(s) not in already
                and s.metadata.name.upper() in self.trial_strategies
                and s.metadata.state.value != "DISABLED"
            ]
        return approved

    # -- main ---------------------------------------------------------------
    def run(
        self,
        *,
        symbol: str,
        bars: Sequence[Bar],
        state: SessionRiskState,
        macro: MacroAssessment,
        now: Optional[datetime] = None,
    ) -> PipelineResult:
        now = now or now_utc()
        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.PIPELINE_RUN, decision="START",
            reason_ar=f"بدء خط القرار للرمز {symbol}.", source="Pipeline", at=now,
        )

        # 0) Kill Switch
        if not self.kill_switch.allows_new_entries():
            ev = self.kill_switch.state.current_event
            message = f"Kill Switch مفعّل: {ev.reason_ar if ev else 'سبب غير مسجل'}"
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.NO_TRADE, decision="HALTED",
                reason_ar=message, source="KillSwitch", at=now,
            )
            return PipelineResult(Decision.HALTED, "KILL_SWITCH_ACTIVE", message, "kill_switch", at_utc=now)

        # 1) Broker + market status
        try:
            if not self.broker.health_check():
                raise BrokerNotConnected("فحص صحة الوسيط فشل")
            balances = self.broker.get_balances(self.broker.get_accounts()[0])
            permissions = self.broker.get_trading_permissions(balances.account_id)
            quote = self.broker.get_market_data(symbol)
            details = self.broker.get_instrument_details(symbol)
        except BrokerNotConnected as exc:
            self.kill_switch.trigger(
                KillSwitchTrigger.BROKER_DISCONNECTED, reason_ar=str(exc), at=now
            )
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.KILL_SWITCH_TRIGGERED,
                decision="BROKER_DISCONNECTED", reason_ar=str(exc), source="Pipeline", at=now,
            )
            return PipelineResult(Decision.HALTED, "BROKER_DISCONNECTED", str(exc), "broker", at_utc=now)
        except Exception as exc:  # noqa: BLE001
            return self._no_trade("broker", "BROKER_ERROR", f"خطأ من الوسيط: {exc}", now)

        market = forex_market_status(now)

        # 2) Macro veto
        if macro.blocks_trading:
            return self._no_trade("macro", "MACRO_VETO", macro.reason_ar, now)

        # 3) News blackout
        if not self.blackouts.is_confirmed(now.date()):
            return self._no_trade(
                "news",
                "NEWS_CALENDAR_UNCONFIRMED",
                "تقويم الأخبار لهذا اليوم غير مؤكد. النظام لا يخترع أخباراً — القرار NO_TRADE.",
                now,
            )
        active_blackout = self.blackouts.active(now, symbol)
        if active_blackout is not None:
            return self._no_trade(
                "news", "NEWS_BLACKOUT",
                f"نافذة حظر أخبار نشطة: {active_blackout.title_ar} (المصدر: {active_blackout.source}).",
                now,
            )

        # 4/5) Eligibility
        eligibility = check_eligibility(
            symbol=symbol, quote=quote, details=details, permissions=permissions,
            balances=balances, market_is_open=market.is_open,
            minutes_since_open=market.minutes_since_open,
            minutes_to_close=market.minutes_to_close, now=now,
        )
        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.ELIGIBILITY_DECISION,
            decision="ELIGIBLE" if eligibility.eligible else (eligibility.reason_code or "INELIGIBLE"),
            reason_ar=eligibility.reason_ar, source="Eligibility",
            after={"checks": [list(c) for c in eligibility.checks]}, at=now,
        )
        if not eligibility.eligible:
            return PipelineResult(
                Decision.NO_TRADE, eligibility.reason_code, eligibility.reason_ar, "eligibility", at_utc=now
            )

        # 5b) Strategy — APPROVED فقط، وتجربةُ التجريبي استثناءٌ مُسمّى
        #
        # الاستثناء **مقفلٌ على الوسيط هنا أيضاً**، لا في مكان البناء وحده:
        # حارسٌ في موضع البناء يمرّ من حوله أي مسارٍ يبني الخط بنفسه — وهذا
        # موضع الاستعمال. و`getattr(..., True)` تُغلق عند غياب الصفة: وسيطٌ
        # لا نعرف نوعه يُعامَل معاملة الحقيقي.
        approved = self.runnable_strategies()
        if not approved:
            return self._no_trade(
                "strategy", "NO_APPROVED_STRATEGY",
                "لا توجد استراتيجية معتمدة. كل الاستراتيجيات في حالة بحث أو معطّلة.", now,
            )

        signal: Optional[Signal] = None
        assessments: list[tuple[str, object]] = []
        for strategy in approved:
            assessment = strategy.assess(
                symbol=symbol, bars=list(bars), quote=quote, now=now
            )
            assessments.append((
                f"{strategy.metadata.name}@{strategy.metadata.version}", assessment,
            ))
            signal = assessment.signal
            if signal is not None:
                break

        if signal is None:
            # **السبب لا الجملة.** كان يُعاد «لا توجد فرصة مطابقة» وحدها،
            # وهي نفسها سواء كان ADX عند 24.9 أو عند 8. والفرق بينهما هو
            # الفرق بين «انتظري» و«هذه الاستراتيجية لا تناسب هذا السوق».
            detail = " · ".join(
                f"{key}: {a.summary_ar}" for key, a in assessments
            ) or "لم تُشغَّل استراتيجية."
            result = self._no_trade(
                "strategy", "NO_SETUP",
                f"لا فرصة مطابقة. {detail}", now,
            )
            return replace(result, assessments=tuple(assessments))

        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.SIGNAL_GENERATED, decision="SIGNAL",
            reason_ar=signal.rationale_ar, source=f"{signal.strategy_name}@{signal.strategy_version}",
            after=signal.model_dump(mode="json"), at=now,
        )

        # 6) Risk review
        decision = self.risk.evaluate(
            signal=signal, state=state, balances=balances, schedule=self.schedule,
            assumptions=self.assumptions, fractional_allowed=eligibility.fractional_allowed,
            kill_switch_active=self.kill_switch.is_active, now=now,
        )
        self.audit.record(
            actor=Actor.RISK_ENGINE, action=AuditAction.RISK_DECISION,
            decision=decision.decision.value if decision.approved else (decision.reason_code or "REJECTED"),
            reason_ar=decision.reason_ar, source="RiskEngine",
            after=decision.model_dump(mode="json"), at=now,
        )
        if not decision.approved:
            return PipelineResult(
                Decision.NO_TRADE, decision.reason_code, decision.reason_ar, "risk",
                signal=signal, risk_decision=decision, at_utc=now,
            )

        # 7) Order intent + preview + 8) execution
        intent = build_order_intent(
            signal=signal, decision=decision, trading_day=now.date().isoformat(),
            instrument_snapshot=details.model_dump(mode="json"),
            max_slippage_abs=(quote.spread * D("2")), now=now,
        )
        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.ORDER_INTENT_CREATED, decision="CREATED",
            reason_ar=intent.exit_plan_ar, source="Pipeline",
            after=intent.model_dump(mode="json"), related_id=intent.client_order_id, at=now,
        )

        if not self.allow_live_submission and self.broker.is_live:
            return self._no_trade(
                "execution", "LIVE_SUBMISSION_LOCKED",
                "التنفيذ الحقيقي مقفل. النية أُنشئت وسُجّلت ولم تُرسل.", now,
            )

        submission = self.execution.submit(intent)
        if submission.requires_kill_switch:
            trigger = {
                SubmissionOutcome.DUPLICATE_BLOCKED: KillSwitchTrigger.DUPLICATE_ORDER,
                SubmissionOutcome.UNCONFIRMED: KillSwitchTrigger.EXECUTION_CONFIRMATION_FAILED,
                SubmissionOutcome.SIZE_MISMATCH: KillSwitchTrigger.SIZE_EXCEEDS_EXPECTED,
                SubmissionOutcome.SLIPPAGE_EXCEEDED: KillSwitchTrigger.SIZE_EXCEEDS_EXPECTED,
            }.get(submission.outcome, KillSwitchTrigger.STRATEGY_ANOMALY)
            ev = self.kill_switch.trigger(trigger, reason_ar=submission.reason_ar, at=now)
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.KILL_SWITCH_TRIGGERED,
                decision=ev.trigger.value, reason_ar=ev.reason_ar, source="Pipeline",
                related_id=intent.client_order_id, at=now,
            )
            return PipelineResult(
                Decision.HALTED, submission.outcome.value, submission.reason_ar, "execution",
                signal=signal, risk_decision=decision, submission=submission, at_utc=now,
            )

        if submission.outcome in (SubmissionOutcome.REJECTED, SubmissionOutcome.PREVIEW_REJECTED):
            return PipelineResult(
                Decision.NO_TRADE, submission.outcome.value, submission.reason_ar, "execution",
                signal=signal, risk_decision=decision, submission=submission, at_utc=now,
            )

        # 9) Reconciliation
        local = []
        if submission.order and submission.order.filled_quantity > 0:
            from ..contracts import Position

            local = [
                Position(
                    account_id=balances.account_id, symbol=symbol,
                    quantity=submission.order.filled_quantity,
                    average_cost=submission.order.average_fill_price or signal.entry_price,
                    as_of_utc=now,
                )
            ]
        recon = reconcile(
            local_positions=local,
            broker_positions=list(self.broker.get_positions(balances.account_id)),
            now=now,
        )
        self.audit.record(
            actor=Actor.SYSTEM, action=AuditAction.RECONCILIATION,
            decision="MATCHED" if recon.matched else "MISMATCH",
            reason_ar="؛ ".join(recon.discrepancies_ar) or "سجلاتنا تطابق حساب الوسيط.",
            source="Reconciliation", at=now,
        )
        if not recon.matched:
            ev = self.kill_switch.trigger(
                KillSwitchTrigger.RECONCILIATION_MISMATCH,
                reason_ar="؛ ".join(recon.discrepancies_ar), at=now,
            )
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.KILL_SWITCH_TRIGGERED,
                decision=ev.trigger.value, reason_ar=ev.reason_ar, source="Pipeline", at=now,
            )
            return PipelineResult(
                Decision.HALTED, "RECONCILIATION_MISMATCH", ev.reason_ar, "reconciliation",
                signal=signal, risk_decision=decision, submission=submission,
                reconciliation_ok=False, at_utc=now,
            )

        return PipelineResult(
            Decision.TRADE, None,
            f"{symbol}: كمية {decision.quantity} بمخاطرة {decision.expected_risk_usd:.2f} دولار.",
            "done", signal=signal, risk_decision=decision, submission=submission,
            reconciliation_ok=True, at_utc=now,
        )
