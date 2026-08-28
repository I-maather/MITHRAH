"""
EUR/USD MARKET INTELLIGENCE PIPELINE — سبع عشرة مرحلة بترتيب ملزم.

     1. بوابة سلامة البيانات
     2. بوابة حالة السوق
     3. بوابة التقويم الاقتصادي
     4. النظام الكلي والأساسي
     5. تقييم الأخبار المُتحقَّق منها
     6. تحليل الاتجاه متعدد الأطر
     7. تصنيف بنية السوق
     8. تحليل التقلب والسيولة
     9. مطابقة الاستراتيجية بالنظام
    10. التحقق من إعداد الدخول
    11. التحقق من التكلفة والسبريد
    12. بناء المركز والوقف
    13. نقض محرك المخاطر
    14. المراجعة المستقلة
    15. القرار النهائي
    16. الشرح المقروء للمالكة
    17. قيد التدقيق والمعايرة

**لا مرحلة لاحقة تنقض رفضاً من بوابة إلزامية سابقة.** الرفض يعيد النتيجة فوراً،
ولا يوجد مسار يستأنف بعده. هذا مفروض بالبنية: `_reject()` تعيد `PipelineResult`
نهائية، ولا يستقبل أي مكوّن لاحق «قرار مبدئي» ليعدّله.

**حلقة المراجعة قبل الصفقة ليست تكراراً حتى تظهر موافقة.** ثلاث خطوات فقط:
تحليل أساسي حتمي ← تحقق مستقل حتمي ← نقض محرك المخاطر. ثلاثتها على نفس
اللقطة، والرفض يُسجَّل ويتوقف كل شيء. **لا إعادة توليد تحليل من نموذج لغوي.**
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional, Sequence

from ..contracts import Decision, Side, StopKind
from ..money import D
from ..profiles import ProfileLimits, TradingProfile
from ..strategies.registry import (
    StrategyDefinition,
    StrategyMatch,
    StrategyDefinitionRegistry,
    match_strategy,
)
from .contradictions import (
    ContradictionInputs,
    ContradictionReport,
    detect_contradictions,
)
from .fundamentals import FundamentalAssessment, assess_fundamentals
from .gates import (
    CalendarResult,
    DataHealthResult,
    ExecutionHealth,
    HealthVerdict,
    MarketStatusResult,
    NewsResult,
    run_calendar_gate,
    run_data_health_gate,
    run_market_status_gate,
    run_news_gate,
)
from .indicators import spread_to_atr_ratio
from .providers import ProviderRegistry
from .regime import MarketRegime, RegimeAssessment, classify_regime
from .scoring import (
    MANDATORY_FAILURE_AR,
    MandatoryFailure,
    QualityScore,
    ScoreInputs,
    evaluate_quality,
)
from .snapshot import (
    UNKNOWN,
    MarketSnapshot,
    Timeframe,
    _Unknown,
    is_unknown,
)
from .structure import MultiTimeframeView, TrendDirection, analyse_all
from .verification import IndependentTradeVerifier, TradeProposal, VerificationResult


class Stage(str, Enum):
    DATA_HEALTH = "DATA_HEALTH"
    MARKET_STATUS = "MARKET_STATUS"
    ECONOMIC_CALENDAR = "ECONOMIC_CALENDAR"
    MACRO_REGIME = "MACRO_REGIME"
    VERIFIED_NEWS = "VERIFIED_NEWS"
    MULTI_TIMEFRAME = "MULTI_TIMEFRAME"
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    VOLATILITY_LIQUIDITY = "VOLATILITY_LIQUIDITY"
    STRATEGY_MATCH = "STRATEGY_MATCH"
    ENTRY_SETUP = "ENTRY_SETUP"
    COST_SPREAD = "COST_SPREAD"
    POSITION_CONSTRUCTION = "POSITION_CONSTRUCTION"
    RISK_ENGINE_VETO = "RISK_ENGINE_VETO"
    INDEPENDENT_VERIFICATION = "INDEPENDENT_VERIFICATION"
    FINAL_DECISION = "FINAL_DECISION"
    EXPLANATION = "EXPLANATION"
    AUDIT_CALIBRATION = "AUDIT_CALIBRATION"


STAGE_ORDER: tuple[Stage, ...] = tuple(Stage)

STAGE_NAME_AR: dict[Stage, str] = {
    Stage.DATA_HEALTH: "سلامة البيانات",
    Stage.MARKET_STATUS: "حالة السوق",
    Stage.ECONOMIC_CALENDAR: "التقويم الاقتصادي",
    Stage.MACRO_REGIME: "النظام الكلي والأساسي",
    Stage.VERIFIED_NEWS: "الأخبار المُتحقَّق منها",
    Stage.MULTI_TIMEFRAME: "تحليل متعدد الأطر",
    Stage.MARKET_STRUCTURE: "بنية السوق",
    Stage.VOLATILITY_LIQUIDITY: "التقلب والسيولة",
    Stage.STRATEGY_MATCH: "مطابقة الاستراتيجية",
    Stage.ENTRY_SETUP: "إعداد الدخول",
    Stage.COST_SPREAD: "التكلفة والسبريد",
    Stage.POSITION_CONSTRUCTION: "بناء المركز والوقف",
    Stage.RISK_ENGINE_VETO: "نقض محرك المخاطر",
    Stage.INDEPENDENT_VERIFICATION: "المراجعة المستقلة",
    Stage.FINAL_DECISION: "القرار النهائي",
    Stage.EXPLANATION: "الشرح",
    Stage.AUDIT_CALIBRATION: "التدقيق والمعايرة",
}

#: البوابات الإلزامية — رفضها نهائي ولا يُنقَض لاحقاً بأي درجة أو دليل.
MANDATORY_GATES: frozenset[Stage] = frozenset({
    Stage.DATA_HEALTH,
    Stage.MARKET_STATUS,
    Stage.ECONOMIC_CALENDAR,
    Stage.VERIFIED_NEWS,
    Stage.STRATEGY_MATCH,
    Stage.COST_SPREAD,
    Stage.POSITION_CONSTRUCTION,
    Stage.RISK_ENGINE_VETO,
    Stage.INDEPENDENT_VERIFICATION,
})


@dataclass(frozen=True)
class StageRecord:
    stage: Stage
    name_ar: str
    passed: bool
    detail_ar: str
    payload: dict = field(default_factory=dict)
    mandatory: bool = True

    def as_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "name_ar": self.name_ar,
            "passed": self.passed,
            "mandatory": self.mandatory,
            "detail_ar": self.detail_ar,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class EntrySetup:
    """إعداد دخول مقترح، ناتج عن قواعد الاستراتيجية المعلنة."""

    side: Side
    entry_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    stop_kind: StopKind
    confirmed: bool
    natural_stop_ar: str
    rationale_ar: str


@dataclass(frozen=True)
class ConstructedPosition:
    size: Decimal
    notional: Decimal
    margin: Decimal
    pip_value: Decimal
    spread: Decimal
    price_risk: Decimal
    fees: Decimal
    slippage_reserve: Decimal
    all_in_risk: Decimal
    gross_reward_risk: Decimal
    net_reward_risk: Decimal
    stop_pips: Decimal
    respects_broker_minimum: bool
    stop_was_not_tightened: bool = True


@dataclass(frozen=True)
class PipelineResult:
    decision: Decision
    reason_code: str
    reason_ar: str
    snapshot_id: str
    profile: TradingProfile
    stages: tuple[StageRecord, ...]
    score: Optional[QualityScore]
    contradictions: Optional[ContradictionReport]
    verification: Optional[VerificationResult]
    regime: Optional[RegimeAssessment]
    view: Optional[MultiTimeframeView]
    fundamentals: Optional[FundamentalAssessment]
    strategy: Optional[StrategyMatch]
    position: Optional[ConstructedPosition]
    setup: Optional[EntrySetup]
    missing_providers: tuple[str, ...]
    missing_data: tuple[str, ...]
    explanation_ar: str = ""
    decided_at_utc: Optional[datetime] = None

    @property
    def is_trade(self) -> bool:
        return self.decision is Decision.TRADE

    def failed_stage(self) -> Optional[StageRecord]:
        for s in self.stages:
            if not s.passed:
                return s
        return None

    def as_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reason_code": self.reason_code,
            "reason_ar": self.reason_ar,
            "snapshot_id": self.snapshot_id,
            "profile": self.profile.value,
            "stages": [s.as_dict() for s in self.stages],
            "score": self.score.as_dict() if self.score else None,
            "contradictions": self.contradictions.as_dict() if self.contradictions else None,
            "verification": self.verification.as_dict() if self.verification else None,
            "regime": self.regime.as_dict() if self.regime else None,
            "timeframes": self.view.as_dict() if self.view else None,
            "fundamentals": self.fundamentals.as_dict() if self.fundamentals else None,
            "strategy": self.strategy.as_dict() if self.strategy else None,
            "missing_providers": list(self.missing_providers),
            "missing_data": list(self.missing_data),
            "explanation_ar": self.explanation_ar,
            "decided_at_utc": self.decided_at_utc.isoformat() if self.decided_at_utc else None,
        }


@dataclass(frozen=True)
class RiskVeto:
    """نتيجة نقض محرك المخاطر — يُمرَّر من الخارج، ولا يُعاد حسابه هنا."""

    approved: bool
    reason_code: str
    reason_ar: str
    remaining_daily: Decimal
    remaining_weekly: Decimal


class MarketIntelligencePipeline:
    """
    خط استخبارات EUR/USD. حتمي بالكامل: نفس اللقطة ⇒ نفس القرار، دائماً.

    لا يستورد `ExecutionService` ولا أي محوّل وسيط، ولا يملك مساراً لإرسال أمر.
    مخرجه قرار موصوف — والتنفيذ مسؤولية طبقة أخرى مقفلة.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        strategies: StrategyDefinitionRegistry,
        verifier: IndependentTradeVerifier,
        instrument: str = "EURUSD",
        currencies: tuple[str, ...] = ("EUR", "USD"),
        required_bars: int = 60,
        max_quote_age_seconds: int = 60,
    ) -> None:
        self.registry = registry
        self.strategies = strategies
        self.verifier = verifier
        self.instrument = instrument
        self.currencies = currencies
        self.required_bars = required_bars
        self.max_quote_age_seconds = max_quote_age_seconds

    # ------------------------------------------------------------------

    def run(
        self,
        *,
        snapshot: MarketSnapshot,
        profile: TradingProfile,
        limits: ProfileLimits,
        execution: ExecutionHealth,
        now: datetime,
        build_setup: Callable[[MultiTimeframeView, RegimeAssessment, StrategyDefinition], Optional[EntrySetup]],
        construct_position: Callable[[EntrySetup, MarketSnapshot], Optional[ConstructedPosition]],
        risk_veto: Callable[[ConstructedPosition, EntrySetup], RiskVeto],
    ) -> PipelineResult:
        stages: list[StageRecord] = []
        missing_providers = self.registry.missing_names()

        def record(
            stage: Stage, passed: bool, detail: str, payload: dict | None = None
        ) -> StageRecord:
            r = StageRecord(
                stage=stage,
                name_ar=STAGE_NAME_AR[stage],
                passed=passed,
                detail_ar=detail,
                payload=payload or {},
                mandatory=stage in MANDATORY_GATES,
            )
            stages.append(r)
            return r

        def reject(
            code: str,
            reason: str,
            *,
            score: Optional[QualityScore] = None,
            contradictions: Optional[ContradictionReport] = None,
            verification: Optional[VerificationResult] = None,
            regime: Optional[RegimeAssessment] = None,
            view: Optional[MultiTimeframeView] = None,
            fundamentals: Optional[FundamentalAssessment] = None,
            strategy: Optional[StrategyMatch] = None,
            position: Optional[ConstructedPosition] = None,
            setup: Optional[EntrySetup] = None,
            decision: Decision = Decision.NO_TRADE,
        ) -> PipelineResult:
            return PipelineResult(
                decision=decision,
                reason_code=code,
                reason_ar=reason,
                snapshot_id=snapshot.snapshot_id,
                profile=profile,
                stages=tuple(stages),
                score=score,
                contradictions=contradictions,
                verification=verification,
                regime=regime,
                view=view,
                fundamentals=fundamentals,
                strategy=strategy,
                position=position,
                setup=setup,
                missing_providers=missing_providers,
                missing_data=snapshot.unknown_critical_fields(),
                decided_at_utc=now,
            )

        # --- 1. سلامة البيانات ------------------------------------------
        health = run_data_health_gate(
            snapshot, self.registry, execution,
            now=now,
            max_quote_age_seconds=self.max_quote_age_seconds,
            required_bars=self.required_bars,
        )
        record(
            Stage.DATA_HEALTH,
            health.live_eligible,
            health.verdict.value + " — " + (
                "كل الفحوص اجتازت." if health.live_eligible
                else "؛ ".join(c.detail_ar for c in health.failed()[:5])
            ),
            health.as_dict(),
        )
        if execution.kill_switch_active:
            return reject("KILL_SWITCH_ACTIVE", "Kill Switch مفعّل.", decision=Decision.HALTED)
        if not health.live_eligible:
            return reject(
                "DATA_HEALTH_" + health.verdict.value,
                "بوابة سلامة البيانات لم تُجتَز: "
                + "؛ ".join(c.detail_ar for c in health.failed()[:5]),
            )

        # --- 2. حالة السوق ----------------------------------------------
        status = run_market_status_gate(snapshot)
        record(Stage.MARKET_STATUS, status.passed, status.reason_ar, status.as_dict())
        if not status.passed:
            return reject("MARKET_NOT_OPEN", status.reason_ar)

        # --- 8-أ. التقلب والسيولة (يُحسب مبكراً لأن الحجب يعتمد عليه) -----
        daily = snapshot.series.get(Timeframe.D1)
        from .indicators import compute_indicators

        daily_ind = compute_indicators(Timeframe.D1, daily.candles if daily else ())
        spread_value = (
            snapshot.spread.value if snapshot.spread.known
            else (
                snapshot.ask.value - snapshot.bid.value
                if snapshot.ask.known and snapshot.bid.known
                else UNKNOWN
            )
        )
        s_to_atr = (
            spread_to_atr_ratio(spread_value, daily_ind.atr)
            if not is_unknown(spread_value)
            else UNKNOWN
        )
        conditions_abnormal = (
            (not is_unknown(daily_ind.volatility_percentile) and daily_ind.volatility_percentile >= D("90"))
            or (not is_unknown(s_to_atr) and s_to_atr >= D("0.12"))
        )

        # --- 3. التقويم الاقتصادي ---------------------------------------
        calendar = run_calendar_gate(
            snapshot, self.registry,
            now=now, currencies=self.currencies, conditions_abnormal=conditions_abnormal,
        )
        record(Stage.ECONOMIC_CALENDAR, calendar.passed, calendar.reason_ar, calendar.as_dict())
        if not calendar.passed:
            return reject("HIGH_IMPACT_BLACKOUT", calendar.reason_ar)

        # --- 4. النظام الكلي والأساسي -----------------------------------
        fundamentals = assess_fundamentals(
            snapshot.fundamentals, provider_configured=self.registry.macro.configured
        )
        record(
            Stage.MACRO_REGIME,
            True,   # مُدخَل لا بوابة: لا يعتمد صفقة ولا يمنعها وحده
            f"انحياز EUR/USD: {fundamentals.relative_bias.value} · "
            f"اكتمال {fundamentals.completeness:.0%} · صالح للاستعمال: {fundamentals.usable}.",
            fundamentals.as_dict(),
        )

        # --- 5. الأخبار المُتحقَّق منها -----------------------------------
        news = run_news_gate(snapshot, self.registry, now=now, currencies=self.currencies)
        record(Stage.VERIFIED_NEWS, news.passed, news.reason_ar, news.as_dict())
        if not news.passed:
            return reject("NEWS_BLOCK", news.reason_ar, fundamentals=fundamentals)

        # --- 6. تحليل متعدد الأطر ---------------------------------------
        view = analyse_all(dict(snapshot.series), min_bars=self.required_bars)
        record(
            Stage.MULTI_TIMEFRAME,
            not view.incomplete_timeframes(),
            f"D1 {view.primary_regime_trend.value} · H4 {view.structural_trend.value} · "
            f"M15 {view.entry_trend.value}.",
            view.as_dict(),
        )

        # --- 7. بنية السوق + تصنيف النظام -------------------------------
        regime = classify_regime(
            view,
            spread_to_atr=s_to_atr,
            in_event_window=False,     # الحجب فُحص في المرحلة 3 وسبق أن مرّ
        )
        record(Stage.MARKET_STRUCTURE, regime.tradable, regime.reason_ar, regime.as_dict())

        # --- 8-ب. التقلب والسيولة (تسجيل) --------------------------------
        record(
            Stage.VOLATILITY_LIQUIDITY,
            not is_unknown(s_to_atr),
            (
                f"السبريد/ATR = {s_to_atr:.4f} · المئين التقلبي "
                f"{daily_ind.volatility_percentile}."
                if not is_unknown(s_to_atr)
                else "نسبة السبريد إلى ATR غير معلومة."
            ),
            {"spread_to_atr": str(s_to_atr), "indicators": daily_ind.as_dict()},
        )

        # --- 9. مطابقة الاستراتيجية -------------------------------------
        strategy = match_strategy(self.strategies, regime.regime)
        record(Stage.STRATEGY_MATCH, strategy.has_match, strategy.reason_ar, strategy.as_dict())
        if not strategy.has_match:
            return reject(
                "NO_STRATEGY_FOR_REGIME", strategy.reason_ar,
                regime=regime, view=view, fundamentals=fundamentals, strategy=strategy,
            )
        definition = strategy.matched
        assert definition is not None

        # --- 10. إعداد الدخول -------------------------------------------
        setup = build_setup(view, regime, definition)
        if setup is None:
            record(Stage.ENTRY_SETUP, False, "لا إعداد دخول صالح وفق قواعد الاستراتيجية.")
            return reject(
                "NO_VALID_SETUP", "قواعد الاستراتيجية لم تتحقق على هذه اللقطة.",
                regime=regime, view=view, fundamentals=fundamentals, strategy=strategy,
            )
        record(
            Stage.ENTRY_SETUP, setup.confirmed, setup.rationale_ar,
            {
                "side": setup.side.value,
                "entry": str(setup.entry_price),
                "stop": str(setup.stop_price),
                "take_profit": str(setup.take_profit_price),
                "confirmed": setup.confirmed,
                "natural_stop_ar": setup.natural_stop_ar,
            },
        )

        # --- 11-12. التكلفة والسبريد + بناء المركز ------------------------
        position = construct_position(setup, snapshot)
        if position is None:
            record(Stage.COST_SPREAD, False, "تعذّر حساب اقتصاديات الصفقة.")
            record(Stage.POSITION_CONSTRUCTION, False, "لا مركز.")
            return reject(
                "COST_MODEL_UNAVAILABLE", "لا يمكن حساب التكلفة — لا قرار على أرقام مجهولة.",
                regime=regime, view=view, fundamentals=fundamentals, strategy=strategy, setup=setup,
            )
        record(
            Stage.COST_SPREAD, True,
            f"سبريد {position.spread} · تعرّض {position.notional:.2f} · "
            f"هامش {position.margin:.2f} · خسارة كلية {position.all_in_risk:.2f}.",
            {
                "notional": f"{position.notional:.2f}",
                "margin": f"{position.margin:.2f}",
                "all_in_risk": f"{position.all_in_risk:.2f}",
                "net_reward_risk": f"{position.net_reward_risk:.2f}",
            },
        )
        record(
            Stage.POSITION_CONSTRUCTION,
            position.respects_broker_minimum and position.stop_was_not_tightened,
            (
                f"كمية {position.size} · وقف {position.stop_pips:.1f} نقطة. "
                + ("الوقف الطبيعي لم يُضيَّق." if position.stop_was_not_tightened
                   else "⚠️ الوقف ضُيِّق — ممنوع.")
            ),
            {
                "size": str(position.size),
                "stop_pips": f"{position.stop_pips:.1f}",
                "respects_broker_minimum": position.respects_broker_minimum,
                "stop_was_not_tightened": position.stop_was_not_tightened,
            },
        )
        if not position.stop_was_not_tightened:
            return reject(
                "STOP_TIGHTENED_TO_FIT_RISK",
                "الوقف الصحيح فنياً لا يُضيَّق لجعل الصفقة تناسب حد المخاطرة.",
                regime=regime, view=view, fundamentals=fundamentals,
                strategy=strategy, setup=setup, position=position,
            )
        if not position.respects_broker_minimum:
            return reject(
                "MINIMUM_SIZE_EXCEEDS_PROFILE_RISK",
                (
                    f"الكمية الدنيا للوسيط تُنتج خسارة {position.all_in_risk:.2f} دولار "
                    f"تتجاوز حد الملف {limits.max_risk_per_trade:.2f} دولار. "
                    "لا يمكن تصغير الكمية ولا تضييق الوقف."
                ),
                regime=regime, view=view, fundamentals=fundamentals,
                strategy=strategy, setup=setup, position=position,
            )

        # --- التناقضات (تُحسب قبل الدرجة لأنها تدخل فيها) -----------------
        next_event_minutes: Optional[int] = None
        if calendar.upcoming:
            from .snapshot import ImpactLevel
            highs = [e for e in calendar.upcoming if e.impact is ImpactLevel.HIGH]
            if highs:
                delta = (highs[0].scheduled_utc - now).total_seconds() / 60
                next_event_minutes = int(delta)

        oldest_candle_age = None
        m15 = snapshot.series.get(Timeframe.M15)
        if m15 and m15.candles:
            oldest_candle_age = (now - m15.candles[-1].start_utc).total_seconds()

        direction = TrendDirection.UP if setup.side is Side.BUY else TrendDirection.DOWN
        contradictions = detect_contradictions(ContradictionInputs(
            intended_direction=direction,
            view=view,
            regime=regime,
            fundamentals=fundamentals,
            strategy_declares_regime_compatible=definition.accepts(regime.regime),
            strategy_key=definition.key,
            spread_to_atr=s_to_atr,
            gross_reward_risk=position.gross_reward_risk,
            net_reward_risk=position.net_reward_risk,
            required_reward_risk=limits.min_net_reward_risk,
            minutes_to_next_high_impact_event=next_event_minutes,
            quote_age_seconds=snapshot.bid.age_seconds(now),
            oldest_candle_age_seconds=oldest_candle_age,
        ))

        # --- الدرجة الحتمية ----------------------------------------------
        score = evaluate_quality(ScoreInputs(
            data_health_passed=health.live_eligible,
            data_unknown_count=len(snapshot.unknown_critical_fields()),
            calendar_passed=calendar.passed,
            news_passed=news.passed,
            regime=regime,
            view=view,
            strategy_matched=True,
            strategy_approved=definition.is_live_eligible,
            strategy_regime_compatible=definition.accepts(regime.regime),
            entry_confirmed=setup.confirmed,
            fundamentals=fundamentals,
            intended_direction=direction,
            volatility_percentile=daily_ind.volatility_percentile,
            spread_to_atr=s_to_atr,
            stop_valid=position.stop_pips > 0,
            stop_respects_broker_minimum=position.respects_broker_minimum,
            net_reward_risk=position.net_reward_risk,
            required_reward_risk=limits.min_net_reward_risk,
            contradiction_penalty=contradictions.total_penalty,
            unresolved_material_contradiction=contradictions.has_unresolved_material,
        ))

        # فشل إلزامي: يُفحص **قبل** النظر إلى الرقم، ولا يُعوَّض بأي درجة.
        if score.has_mandatory_failure:
            codes = "، ".join(MANDATORY_FAILURE_AR[f] for f in score.mandatory_failures)
            return reject(
                score.mandatory_failures[0].value,
                f"فشل إلزامي لا يُعوَّض بدرجة الجودة ({score.total}/100): {codes}",
                score=score, contradictions=contradictions, regime=regime, view=view,
                fundamentals=fundamentals, strategy=strategy, setup=setup, position=position,
            )

        if not score.meets(limits.min_quality_score):
            return reject(
                "QUALITY_BELOW_PROFILE_THRESHOLD",
                f"درجة الجودة {score.total} دون عتبة الملف {limits.min_quality_score}.",
                score=score, contradictions=contradictions, regime=regime, view=view,
                fundamentals=fundamentals, strategy=strategy, setup=setup, position=position,
            )

        # --- 13. نقض محرك المخاطر ----------------------------------------
        veto = risk_veto(position, setup)
        record(Stage.RISK_ENGINE_VETO, veto.approved, veto.reason_ar,
               {"reason_code": veto.reason_code})
        if not veto.approved:
            return reject(
                veto.reason_code or "RISK_ENGINE_VETO", veto.reason_ar,
                score=score, contradictions=contradictions, regime=regime, view=view,
                fundamentals=fundamentals, strategy=strategy, setup=setup, position=position,
            )

        # --- 14. المراجعة المستقلة ---------------------------------------
        proposal = TradeProposal(
            snapshot_id=snapshot.snapshot_id,
            instrument=self.instrument,
            side=setup.side,
            size=position.size,
            entry_reference=setup.entry_price,
            stop_price=setup.stop_price,
            take_profit_price=setup.take_profit_price,
            stop_kind=setup.stop_kind,
            claimed_spread=position.spread,
            claimed_pip_value=position.pip_value,
            claimed_notional=position.notional,
            claimed_margin=position.margin,
            claimed_price_risk=position.price_risk,
            claimed_fees=position.fees,
            claimed_slippage_reserve=position.slippage_reserve,
            claimed_all_in_risk=position.all_in_risk,
            claimed_reward_risk=position.net_reward_risk,
            profile_max_risk=limits.max_risk_per_trade,
            profile_min_reward_risk=limits.min_net_reward_risk,
            remaining_daily_budget=veto.remaining_daily,
            remaining_weekly_budget=veto.remaining_weekly,
        )
        verification = self.verifier.verify(
            proposal, snapshot,
            now=now, in_blackout=calendar.in_blackout,
            max_quote_age_seconds=self.max_quote_age_seconds,
        )
        record(
            Stage.INDEPENDENT_VERIFICATION, verification.passed,
            verification.reason_ar, verification.as_dict(),
        )
        if not verification.passed:
            return reject(
                "VERIFICATION_MISMATCH", verification.reason_ar,
                score=score, contradictions=contradictions, verification=verification,
                regime=regime, view=view, fundamentals=fundamentals,
                strategy=strategy, setup=setup, position=position,
            )

        # --- 15. القرار النهائي -------------------------------------------
        # الاستراتيجية غير المعتمدة لا تصل هنا (فشل إلزامي أعلاه)، لكن الفحص
        # مكرَّر عمداً: طبقتان أرخص من صفقة واحدة خاطئة.
        if not definition.is_live_eligible:
            record(Stage.FINAL_DECISION, False, "الاستراتيجية ليست معتمدة.")
            return reject(
                "STRATEGY_NOT_APPROVED",
                f"{definition.key} في حالة {definition.state.value} — "
                "لا صفقة مهما كانت جودة الإشارة.",
                score=score, contradictions=contradictions, verification=verification,
                regime=regime, view=view, fundamentals=fundamentals,
                strategy=strategy, setup=setup, position=position,
            )

        record(
            Stage.FINAL_DECISION, True,
            f"كل البوابات اجتازت · الدرجة {score.total}/{limits.min_quality_score} · "
            f"R:R صافٍ {position.net_reward_risk:.2f}.",
        )
        return PipelineResult(
            decision=Decision.TRADE,
            reason_code="APPROVED",
            reason_ar=(
                f"كل المراحل السبع عشرة اجتازت على اللقطة {snapshot.snapshot_id[:12]}. "
                f"الخسارة الكلية {position.all_in_risk:.2f} دولار ضمن حد الملف "
                f"{limits.max_risk_per_trade:.2f} دولار."
            ),
            snapshot_id=snapshot.snapshot_id,
            profile=profile,
            stages=tuple(stages),
            score=score,
            contradictions=contradictions,
            verification=verification,
            regime=regime,
            view=view,
            fundamentals=fundamentals,
            strategy=strategy,
            position=position,
            setup=setup,
            missing_providers=missing_providers,
            missing_data=snapshot.unknown_critical_fields(),
            decided_at_utc=now,
        )


__all__ = [
    "Stage",
    "STAGE_ORDER",
    "STAGE_NAME_AR",
    "MANDATORY_GATES",
    "StageRecord",
    "EntrySetup",
    "ConstructedPosition",
    "RiskVeto",
    "PipelineResult",
    "MarketIntelligencePipeline",
]
