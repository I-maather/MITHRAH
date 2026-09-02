"""
Runtime state container. One process, one system — تُبنى مرة عند الإقلاع.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
from ..strategies.trend_pullback_v2 import TrendPullbackV2
from ..strategies.range_mean_reversion import RangeMeanReversion
from ..strategies.breakout_retest import BreakoutRetest
from ..runtime.demo_trial import demo_trial_for, read_demo_trial
from ..risk.instrument_registry import InstrumentRegistry
from ..brokers.capital.safety import LIVE_API_ENABLED, ExecutionLock
from ..contracts import Broker, StopKind
from ..notifications import InMemoryNotifier
from ..risk.capital_costs import PROVISIONAL_EURUSD, CapitalComCostModel
from ..scheduling import SafeScheduler
from ..secretstore.provider import REQUIRED_CAPITAL_SECRETS, build_secret_provider
from ..secretstore.redaction import install_redacting_filter

logger = logging.getLogger(__name__)



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
    #: سببُ انقطاع الوسيط بالنصّ. «غير متصل» وحدها ترسل المالكة تبحث.
    broker_note_ar: str = ""
    last_result: Optional[PipelineResult] = None
    #: آخر مسحٍ كامل — نتيجةٌ لكل أداة مسموحة، بالترتيب الذي مُسحت به.
    #: `last_result` واحدةٌ منها مختارة للعرض؛ وهذه هي الصورة الكاملة التي
    #: تجيب «ماذا رأى النظام في السوق كلّه»، لا «ماذا قرّر في أداة واحدة».
    last_scan: list[tuple[str, PipelineResult]] = field(default_factory=list)
    #: آخر الشموع لكل أداة، كما وصلت من الوسيط في دورة المسح.
    #:
    #: تُحفَظ هنا كي تخدم شاشة الشموع **بلا نداء شبكة**: بناء حالة الجوال
    #: يُستدعى عند كل طلب قراءة، وجلبُ شموعٍ فيه يحوّل تصفّحاً عادياً إلى
    #: عشرات النداءات على الوسيط — وحدودُه تُستهلَك فيُحرَم القرار منها.
    last_bars: dict = field(default_factory=dict)
    #: شموع الرسم لكل أداة **ولكل إطار**: `{symbol: {resolution: [Bar]}}`.
    #: منفصلةٌ عن `last_bars` عمداً: تلك ما رآه القرار، وهذه ما تتصفّحه
    #: المالكة. وخلطُهما يجعل تغييرَ إطارِ العرض يغيّر ما يُقاس عليه القرار.
    chart_bars: dict = field(default_factory=dict)
    last_intelligence: Optional[IntelligenceResult] = None
    #: دقّة الشموع التي تقرأها حلقة القرار. `DAY` افتراضاً، ولا تُغيَّر إلا
    #: عبر تجربة التجريبي (`app/runtime/demo_trial.py`).
    candle_resolution: str = "DAY"
    #: وصفُ التجربة بالنصّ — يُعرض ويُسجَّل، فلا يبقى الفرق بين «مطفأة» و«مُلغاة
    #: لأن الوسيط حقيقي» في الذاكرة وحدها.
    demo_trial_note_ar: str = "تجربة التجريبي مطفأة."
    #: اقتصاديات الأدوات المقيسة. فارغٌ يعني «لا قياس»، لا «لا أدوات».
    instruments: object = None
    instruments_note_ar: str = ""

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

        if not broker_ok and self.broker_note_ar:
            details.append(f"سبب انقطاع الوسيط: {self.broker_note_ar}")

        # **`scheduler_ok` كان مثبَّتاً على `True`.** أي أنه يقول «المجدول
        # سليم» عن مجدولٍ فارغ لم يُسجَّل فيه شيء، وعن مهامٍّ تُخفق في كل
        # نبضة. وهذا هو صنف العطل الحاكم: حقلٌ يُعرَض ولا يُقاس من مصدره.
        #
        # وقد كلّفنا ذلك الآن بالضبط: الوسيط «غير متصل»، والمجدول «سليم»،
        # ولا سبيل لمعرفة أسُجِّلت مهمّة إبقاء الجلسة أصلاً أم لا.
        jobs = self.scheduler.status()
        scheduler_ok = bool(jobs) and all(j.get("last_error") is None for j in jobs)
        if not jobs:
            details.append("المجدول فارغ — لم تُسجَّل أي مهمة. النبض لم يبدأ.")
        for job in jobs:
            if job.get("last_error"):
                details.append(
                    f"المهمة «{job['name']}» أخفقت: {job['last_error']} "
                    f"({job.get('failures', 0)} إخفاقاً من {job.get('runs', 0)} تشغيلاً)."
                )
            elif job.get("runs", 0) == 0:
                details.append(f"المهمة «{job['name']}» مسجَّلة ولم تُشغَّل بعد.")

        return HealthReport(
            broker_connected=broker_ok,
            market_data_ok=broker_ok and market.is_open,
            database_ok=db_ok,
            scheduler_ok=scheduler_ok,
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
    except Exception as exc:  # noqa: BLE001
        # **لا يُبتلع صامتاً.** كان `pass` هنا يجعل إخفاق وصلٍ عابر عند
        # الإقلاع انقطاعاً دائماً بلا سبب معروض: المحوّل يبقى غير موصول،
        # و`_require_connection` ترفض كل قراءة، فلا قراءةٌ تُصلح الجلسة.
        # التعافي الآن مهمّة `broker-keepalive`، والسبب يُكتب ليُقرأ.
        logging.getLogger(__name__).warning(
            "تعذّر وصل الوسيط عند الإقلاع: %s", type(exc).__name__
        )
        boot_note = f"تعذّر الوصل عند الإقلاع ({type(exc).__name__}) — يُعاد كل ٤ دقائق."
    else:
        boot_note = ""

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
    # الثلاث الجديدة تُسجَّل — والتسجيل **لا يعتمد**: الخط يصفّي بالحالة،
    # وحالتهنّ `RESEARCH`. وكنّ غير مسجَّلات أصلاً، فكان المسح يقول «لا
    # استراتيجية معتمدة» عن استراتيجياتٍ لم تكن في السجلّ من الأساس.
    registry.register(TrendPullbackV2())
    registry.register(RangeMeanReversion())
    registry.register(BreakoutRetest())

    # اقتصاديات الأدوات — المقيسة من الوسيط وحدها تُنفَّذ عليها.
    #
    # ## ولماذا لا يُطفَأ التنفيذ حين لا قياس
    #
    # القاعدة «المقيس وحده» صحيحة، وتطبيقُها الحرفي عند غياب الملف يُطفئ
    # التداول كلّه بلا أن تطلب المالكة ذلك — وهي مفاجأةٌ بقدر مفاجأة
    # التنفيذ على افتراض. فيبقى الافتراضي القديم عند الغياب، **ويُقال
    # بصراحة إنه مفترض** في سجل التدقيق وفي شاشة الوسيط. الصمت وحده ممنوع.
    instruments = InstrumentRegistry.load()
    measured_execution = instruments.executable_epics(
        within=getattr(broker, "discovery_allowlist", None)
    )
    if measured_execution:
        try:
            broker.execution_allowlist = measured_execution
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("الوسيط لا يقبل ضبط قائمة التنفيذ.")
        instruments_note = (
            "قائمة التنفيذ من قياسٍ للوسيط: " + "، ".join(sorted(measured_execution))
        )
    else:
        instruments_note = (
            "لا قياس لاقتصاديات أي أداة — التنفيذ يجري على اقتصادياتٍ **مفترضة**. "
            "شغّلي scripts/discover_instrument_economics.py."
        )
    audit.record(
        actor=Actor.SYSTEM, action=AuditAction.CONFIG_CHANGE,
        decision="INSTRUMENT_ECONOMICS",
        reason_ar=instruments_note, source="build_system",
    )

    # التجربة تُقرأ من البيئة ثم **تُصفّى بالوسيط**. حقيقيٌّ ⇒ تُلغى كاملةً.
    trial = demo_trial_for(broker, read_demo_trial())

    blackouts = BlackoutCalendar()
    pipeline = Pipeline(
        broker=broker, risk_engine=risk_engine, kill_switch=kill_switch, audit=audit,
        execution=execution, strategies=registry.all(),
        # جدول IBKR يبقى **لمسار الأسهم وحده**؛ وصفقات كابيتال تُسعَّر من
        # `instruments` أدناه. وقبل هذا كان الجدول يُطبَّق على الاثنين.
        schedule=IBKR_PRO_TIERED_US_STOCK, assumptions=CostAssumptions.default(),
        blackouts=blackouts, allow_live_submission=False,
        trial_strategies=trial.strategies,
        instruments=instruments,
    )

    # قفل التنفيذ: مغلقٌ إلا في تجربةٍ تجريبيةٍ صريحة بمرجع موافقة مكتوب.
    #
    # ولا يُفتَح من متغيّر بيئةٍ وحده: `authorise` تشترط مرجعاً وسبباً، والتجربة
    # لا تكون فعّالة أصلاً إلا بعد أن يقول الوسيط إنه تجريبي. ثلاثة شروط
    # مجتمعة، وأيّ واحدٍ ناقص ⇒ يبقى مغلقاً.
    trial_lock = ExecutionLock.locked()
    if trial.active:
        trial_lock = trial_lock.authorise(
            owner_authorization_reference=trial.approval_reference,
            reason_ar=(
                "تجربة الحساب التجريبي — تشغيل استراتيجيات البحث على مالٍ وهمي "
                "لجمع إشاراتٍ أمامية. لا يمسّ الحساب الحقيقي."
            ),
            at=now_utc(),
        )
        # القفل يُركَّب على المحوّل نفسه: الخط يسأل المحوّل لا الحالة.
        try:
            broker.execution_lock = trial_lock
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "الوسيط لا يقبل قفل تنفيذ — التجربة لن تنفّذ."
            )
    # **اسمٌ لا يطابق شيئاً يُقال، لا يُبتلَع.**
    #
    # كُتب في الإعداد `TREND_PULLBACK_V2` وهو لا يطابق أي استراتيجية
    # (اسمها `TREND_PULLBACK` وإصدارها `2.0.0`). فلم تُشغَّل الاستراتيجية
    # الرئيسية إطلاقاً — بصمت، ولأيامٍ لو لم يظهر التشخيص على الشاشة.
    from ..pipeline.runner import strategy_key

    known = {strategy_key(s) for s in registry.all()}
    unmatched = sorted(trial.strategies - known)
    trial_note = trial.note_ar
    if unmatched:
        trial_note = (
            f"{trial.note_ar} ⚠️ أسماءٌ في الإعداد لا تطابق أي استراتيجية: "
            f"{'، '.join(unmatched)}. المتاح: {'، '.join(sorted(known))}."
        )
    audit.record(
        actor=Actor.OWNER, action=AuditAction.CONFIG_CHANGE,
        decision=(
            "DEMO_TRIAL_PARTIAL" if (trial.active and unmatched)
            else "DEMO_TRIAL_ACTIVE" if trial.active else "DEMO_TRIAL_OFF"
        ),
        reason_ar=trial_note, source="build_system",
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
        candle_resolution=trial.resolution, demo_trial_note_ar=trial_note,
        instruments=instruments, instruments_note_ar=instruments_note,
        cost_model=CapitalComCostModel(PROVISIONAL_EURUSD),
        execution_lock=trial_lock,
        notifier=InMemoryNotifier(),
        scheduler=SafeScheduler(),
        secret_presence=[p.as_dict() for p in secret_provider.presence(REQUIRED_CAPITAL_SECRETS)],
        profiles=ProfileManager(DEFAULT_PROFILE),
        db_session=session,
        strategy_definitions=StrategyDefinitionRegistry(),
        # يُبنى من المفاتيح المتاحة. مفتاحٌ غائب ⇒ مزوّدٌ غير مُعدّ يظهر
        # باسمه في «ما هو ناقص» — لا مزوّدٌ يُخفق بصمت عند أول نداء.
        providers=build_provider_registry(secret_provider, broker),
        locally_paused=True,
        broker_note_ar=boot_note,
    )


# ---------------------------------------------------------------------------
# بناء سجلّ المزوّدين من الأسرار
# ---------------------------------------------------------------------------


def build_provider_registry(secrets, broker=None) -> ProviderRegistry:
    """
    يبني سجلّ المزوّدين من المفاتيح المتاحة.

    ## لماذا لم يكن موجوداً

    المزوّدون الأربعة مكتوبون ومُختبَرون منذ أشهر، ولم يكن في المشروع كلّه
    سطرٌ واحد يبنيهم: `build_system` كانت تُمرّر `ProviderRegistry()` فارغاً،
    فيقول النظام «اكتمال البيانات ٠٪» — **وهو صادق**: لا مزوّد مُعدّ.
    وحدةٌ سليمة وغير موصولة، ولا اختبار يكشف الفرق. نفس درس ركوب مسارات
    الجوال في ٠٫٥٫٦.

    ## القاعدة هنا

    **مفتاحٌ غائب ⇒ مزوّدٌ غير مُعدّ، لا مزوّدٌ يُخفق بصمت.** لا يُبنى مزوّد
    بمفتاح فارغ ليفشل عند أول نداء؛ يُترك موضعه فارغاً فيتولّاه البديل
    `Unconfigured…`، ويظهر باسمه في «ما هو ناقص» أمام المالكة.

    والبيانات الكلّية لها مساران: FRED إن وُجد مفتاحه، وإلا ECB — وهو **عام
    بلا مفتاح**، فلا يبقى هذا المزوّد ناقصاً لمجرّد غياب مفتاح أمريكي.

    وبيانات السوق تأتي من الوسيط نفسه لا من طرف ثالث: هو مصدر السعر الذي
    سنُنفّذ عليه، فقياسٌ من مصدرٍ آخر يُدخل فرقاً لا يُفسَّر.
    """
    from ..live_readonly.capital_bridge import CapitalReadOnlyBridge
    from ..live_readonly.market_data import LiveReadOnlyMarketDataProvider
    from ..providers.ecb_macro import EcbMacroDataProvider
    from ..providers.faireconomy_calendar import FairEconomyCalendarProvider
    from ..providers.finnhub_news import FinnhubForexNewsProvider
    from ..providers.fred_macro import FredMacroDataProvider

    def key(name: str) -> Optional[str]:
        try:
            value = secrets.get_optional(name)
        except Exception:  # noqa: BLE001
            return None
        return value or None

    finnhub = key("FINNHUB_API_KEY")
    fred = key("FRED_API_KEY")

    # التقويم: التغذية المجانية وحدها.
    #
    # أثبت المسبار أن تقويم FMP **خارج الخطة المجانية** — يعيد صفر أحداث بلا
    # خطأ. فلا يصلح بديلاً: بديلٌ يعيد صفراً بلا شكوى ليس بديلاً بل تمويه،
    # وهو بالضبط ما جعلنا نظنّ التقويم عاملاً أسابيع.
    #
    # ولا يُجلب هنا. الجلب عند بناء النظام يعني أمرين سيّئين: إقلاعٌ يتعلّق
    # بشبكةٍ خارجية، وانقطاعٌ عابر لحظةَ الإقلاع يُعطّل الحارس **لعمر
    # العملية كلها** لأن لا أحد يعيد المحاولة. فالجلب مهمّةٌ مجدولة
    # (`calendar-refresh`) تعمل عند أول نبضة وكل ساعة، فيتعافى النظام وحده.
    calendar = FairEconomyCalendarProvider()
    news = FinnhubForexNewsProvider(api_key=finnhub) if finnhub else None
    macro = FredMacroDataProvider(api_key=fred) if fred else EcbMacroDataProvider()

    # جلسة الوسيط تُمرَّر عبر جسرٍ لا مباشرةً: المزوّد كُتب لواجهة
    # `LiveSession` (`authenticated` و`get`)، وجلسة كابيتال واجهتها أخرى.
    # وتمريرها مباشرةً كان ينفجر بـAttributeError عند أوّل استعلام —
    # ولم يمسكه اختبار لأن الوسيط الوهمي بلا جلسة أصلاً.
    market_data = None
    session = getattr(broker, "session", None)
    if session is not None:
        try:
            market_data = LiveReadOnlyMarketDataProvider(CapitalReadOnlyBridge(session))
        except Exception as exc:  # noqa: BLE001
            logger.warning("تعذّر بناء مزوّد بيانات السوق: %s", type(exc).__name__)

    return ProviderRegistry(
        calendar=calendar,
        macro=macro,
        news=news,
        market_data=market_data,
    )
