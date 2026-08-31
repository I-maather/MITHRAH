"""
Runtime state container. One process, one system — تُبنى مرة عند الإقلاع.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..audit.log import Actor, AuditAction, AuditLog, verify_chain
from ..audit.sqlstore import SqlAuditStore
from ..brokers.base import BrokerAdapter
from ..brokers.factory import build_broker
from ..clock import now_utc, forex_market_status
from ..config import REPO_ROOT, Settings, get_settings
from ..contracts import HealthReport
from ..db.session import get_session, init_db
from ..execution.orders import ExecutionService, IdempotencyGuard
from ..killswitch.engine import KillSwitch
from ..killswitch.store import load_kill_switch_state, record_trigger
from ..money import D
from ..pipeline.runner import BlackoutCalendar, MacroAssessment, Pipeline, PipelineResult
from ..risk.constitution import RiskLimits, RiskMode
from ..risk.costs import IBKR_PRO_TIERED_US_STOCK, CostAssumptions
from ..risk.engine import RiskEngine, SessionRiskState
from ..risk.session_state import load_session_state
from ..strategies.base import StrategyRegistry
from ..strategies.registry import StrategyDefinitionRegistry
from ..intelligence.providers import ProviderRegistry
from ..intelligence.pipeline import PipelineResult as IntelligenceResult
from ..profiles import DEFAULT_PROFILE
from ..profiles.manager import ProfileManager
from ..strategies.trend_pullback_v1 import TrendPullbackV1
from ..brokers.capital.safety import LIVE_API_ENABLED, ExecutionLock
from ..contracts import Broker, StopKind
from ..notifications import InMemoryNotifier
from ..risk.capital_costs import PROVISIONAL_EURUSD, CapitalComCostModel
from ..scheduling import SafeScheduler
from ..secretstore.provider import REQUIRED_CAPITAL_SECRETS, build_secret_provider
from ..secretstore.redaction import install_redacting_filter


@dataclass
class SystemState:
    settings: Settings
    broker: BrokerAdapter
    audit: AuditLog
    kill_switch: KillSwitch
    risk_engine: RiskEngine
    execution: ExecutionService
    registry: StrategyRegistry
    pipeline: Pipeline
    blackouts: BlackoutCalendar
    limits: RiskLimits
    session_state: SessionRiskState
    cost_model: CapitalComCostModel
    execution_lock: ExecutionLock
    notifier: InMemoryNotifier
    scheduler: SafeScheduler
    secret_presence: list
    #: مدير ملفات التداول. لا يملك مرجعاً إلى أي عدّاد — يقرأ لقطة حراسات فقط.
    profiles: ProfileManager
    #: سجل تعريفات الاستراتيجيات المُصدَّرة (غير سجل الاستراتيجيات القابلة للتنفيذ).
    strategy_definitions: StrategyDefinitionRegistry
    #: مزوّدو البيانات. الافتراضي **غير مُعدّ** لكل واحد — بلا اختراع مزوّد.
    providers: ProviderRegistry
    #: قفل محلي يوقفه المالكة من الواجهة. لا يفتح شيئاً — يوقف فقط.
    locally_paused: bool = True
    #: جلسة قاعدة البيانات — تلزم لتثبيت إطفاء قاطع الطوارئ بموافقة مكتوبة (C2).
    db_session: object = None
    last_result: Optional[PipelineResult] = None
    last_intelligence: Optional[IntelligenceResult] = None

    def health(self) -> HealthReport:
        details: list[str] = []
        try:
            broker_ok = self.broker.health_check()
        except Exception as exc:  # noqa: BLE001
            broker_ok = False
            details.append(f"الوسيط: {exc}")
        if not broker_ok:
            details.append("الوسيط غير متصل.")

        try:
            db_ok = True
            with get_session() as s:
                s.execute.__self__  # touch
        except Exception as exc:  # noqa: BLE001
            db_ok = False
            details.append(f"قاعدة البيانات: {exc}")

        try:
            chain = verify_chain(self.audit.events())
            chain_ok = chain.ok
            if not chain_ok:
                details.append(chain.problem_ar or "سلسلة التدقيق مكسورة.")
        except Exception as exc:  # noqa: BLE001
            chain_ok = False
            details.append(f"سجل التدقيق: {exc}")

        market = forex_market_status()
        details.append(f"حالة السوق: {market.reason_ar}")

        return HealthReport(
            broker_connected=broker_ok,
            market_data_ok=broker_ok and market.is_open,
            database_ok=db_ok,
            scheduler_ok=True,
            clock_ok=True,
            audit_chain_ok=chain_ok,
            kill_switch_active=self.kill_switch.is_active,
            details_ar=tuple(details),
            checked_at_utc=now_utc(),
        )


def build_system(settings: Settings | None = None) -> SystemState:
    settings = settings or get_settings()
    init_db()

    session = get_session()
    audit = AuditLog(SqlAuditStore(session))

    broker = build_broker(settings)
    try:
        broker.connect()
    except Exception:  # noqa: BLE001
        pass

    install_redacting_filter()
    settings.assert_mode_allowed()
    limits = RiskLimits.for_mode(RiskMode(settings.risk_mode), D(settings.baseline_equity_usd))
    # C2: الحالة تُستعاد من السجل، والتفعيل يُكتَب فوراً.
    # قاطع الطوارئ لا يُطفَأ بإعادة تشغيل — بموافقة إنسان مكتوبة فقط.
    kill_switch = KillSwitch(
        state=load_kill_switch_state(session),
        notifier=lambda event: record_trigger(session, event),
    )
    risk_engine = RiskEngine(limits)
    execution = ExecutionService(broker=broker, audit=audit, guard=IdempotencyGuard())

    registry = StrategyRegistry()
    registry.register(TrendPullbackV1())

    blackouts = BlackoutCalendar()
    pipeline = Pipeline(
        broker=broker, risk_engine=risk_engine, kill_switch=kill_switch, audit=audit,
        execution=execution, strategies=registry.all(),
        schedule=IBKR_PRO_TIERED_US_STOCK, assumptions=CostAssumptions.default(),
        blackouts=blackouts, allow_live_submission=False,
    )

    # C1: حالة المخاطرة تُقرأ من جدول الصفقات، لا تُثبَّت على صفر.
    # قبل هذا كانت realized_pnl_today/week صفراً دائماً، فحدود الخسارة
    # اليومية والأسبوعية وحاجز التراجع **لا يمكن أن تُفعَّل**.
    state = load_session_state(session, baseline_equity=limits.baseline_equity)

    audit.record(
        actor=Actor.SYSTEM, action=AuditAction.SYSTEM_START,
        decision=f"BROKER={broker.name} LIVE={settings.live_trading} MODE={limits.mode.value}",
        reason_ar=(
            f"إقلاع النظام برأس مال مرجعي {limits.baseline_equity} دولار "
            f"في وضع مخاطرة {limits.mode.value}."
        ),
        source="build_system",
    )

    # على الماك تُقرأ الأسرار من سلسلة المفاتيح؛ وعلى الخادم لا سلسلة مفاتيح،
    # فالملف هو المصدر الوحيد. المسار من الإعدادات لا مثبَّتاً هنا — لأن تثبيته
    # كان يجعل مفتاحاً كُتب على الخادم في ملف آخر «موجوداً وغير مقروء».
    secret_provider = build_secret_provider(
        env_file=settings.secrets_file, allow_process_env=False
    )
    return SystemState(
        settings=settings, broker=broker, audit=audit, kill_switch=kill_switch,
        risk_engine=risk_engine, execution=execution, registry=registry, pipeline=pipeline,
        blackouts=blackouts, limits=limits, session_state=state,
        cost_model=CapitalComCostModel(PROVISIONAL_EURUSD),
        execution_lock=ExecutionLock.locked(),
        notifier=InMemoryNotifier(),
        scheduler=SafeScheduler(),
        secret_presence=[p.as_dict() for p in secret_provider.presence(REQUIRED_CAPITAL_SECRETS)],
        profiles=ProfileManager(DEFAULT_PROFILE),
        db_session=session,
        strategy_definitions=StrategyDefinitionRegistry(),
        # لا مزوّد مُعدّ بعد: التقويم والأخبار والكلي وبيانات السوق كلها ناقصة،
        # وهذا يظهر باسمه الدقيق في `/api/intelligence` ويمنع الأهلية الحقيقية.
        providers=ProviderRegistry(),
        locally_paused=True,
    )
