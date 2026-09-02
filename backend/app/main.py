"""
FastAPI application. الواجهة تقرأ من هنا فقط.

مبدأ: لا يوجد endpoint واحد يستطيع تعديل دستور المخاطر أو تفعيل التداول الحقيقي.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .audit.log import Actor, AuditAction, verify_chain
from .api.state import SystemState, build_system
from .clock import format_riyadh, now_utc, forex_market_status
from .config import get_settings
from .eligibility.allowlist import ALLOWLIST, EXPLICIT_DENYLIST
from .killswitch.engine import TRIGGER_LABELS_AR, KillSwitchTrigger
from contextlib import asynccontextmanager
import logging

from .killswitch.store import record_reset
from .runtime import Heartbeat, register_runtime_jobs
from .money import D
from .risk.constitution import (
    CONSTITUTION_VERSION,
    MODE_SPECS,
    RiskMode,
    constitution_fingerprint,
)
from .brokers.capital.endpoints import DEMO_BASE_URL
from .brokers.capital.safety import LIVE_API_ENABLED
from .contracts import Broker, StopKind
from .discovery.capital_discovery import DISCOVERY_EPICS, EXECUTION_EPICS
from .intelligence.pipeline import STAGE_NAME_AR, STAGE_ORDER
from .mobile.routes import (
    MobileRuntime,
    router as mobile_router,
    session_router as mobile_session_router,
    MobileActions,
    set_runtime,
)
from .mobile.api import MobileApiError
from .mobile.security import MobileSecurityService
from .mobile.state import build_mobile_state
from .mobile.store import MobileStateStore
from .profiles import (
    GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD,
    GLOBAL_GAP_SLIPPAGE_RESERVE_USD,
    GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD,
    NEVER_WEAKENED_BY_PROFILE,
    PROFILE_RISK_ORDER,
    PROFILE_SPECS,
    PROFILE_UPGRADE_COOLING_HOURS,
    ProfileLimits,
    TradingProfile,
)
from .profiles.manager import SystemGuardState

def _read_boot_commit() -> str:
    """كوميت رأس المستودع لحظةَ إقلاع هذه العملية. يُقرأ مرّة ولا يُعاد."""
    try:
        head = Path(__file__).resolve().parents[2] / ".git" / "HEAD"
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            target = head.parent / ref[5:]
            return target.read_text(encoding="utf-8").strip()[:40]
        return ref[:40]
    except Exception:  # noqa: BLE001
        return "unknown"


_BOOT_COMMIT = _read_boot_commit()
_BOOT_TIME = datetime.now(timezone.utc)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """
    النبض يبدأ مع الخادم ويتوقف معه.

    **لا يُسقط الإقلاع.** فشل بدء النبض يُسجَّل ويستمرّ الخادم: واجهةٌ حيّة
    بلا نبض أفضل من خادمٍ لا يُقلع — لأن الأولى تُظهر العطل، والثانية تخفيه.
    """
    beat = None
    try:
        state = system()
        register_runtime_jobs(state)
        beat = Heartbeat(state)
        beat.start()
        _app.state.heartbeat = beat
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("تعذّر بدء النبض: %s", type(exc).__name__)
    try:
        yield
    finally:
        if beat is not None:
            await beat.stop()


app = FastAPI(title="Maather Autonomous Trader", version="0.7.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"], allow_headers=["*"],
)

_SYSTEM: Optional[SystemState] = None

#: قفل البناء — **ليس تحسيناً، بل تصحيحاً.**
#:
#: المسارات المتزامنة تعمل في خيوط منفصلة عند uvicorn. واللوحة الرئيسية في
#: الجوال تطلب خمسة مسارات في اللحظة نفسها، فرأى كلٌّ منها `_SYSTEM is None`
#: وبدأ يبني النظام — فتسابقت الخيوط على `create_all`:
#:
#:     sqlite3.OperationalError: table accounts already exists
#:
#: و`checkfirst` لا يحمي من ذلك: بين الفحص والإنشاء فجوة. والبناء نفسه ثقيل
#: (يفتح اتصالاً بالوسيط)، فتكراره خطأ حتى لو نجح.
_SYSTEM_LOCK = Lock()


def system() -> SystemState:
    global _SYSTEM
    if _SYSTEM is not None:
        return _SYSTEM
    with _SYSTEM_LOCK:
        # يُعاد الفحص **داخل القفل**: خيطٌ آخر ربما بناه أثناء الانتظار.
        if _SYSTEM is None:
            _SYSTEM = build_system()
    return _SYSTEM


# ---------------------------------------------------------------------------
# مجال الجوال — الوصلة التي كانت مفقودة
# ---------------------------------------------------------------------------
#
# `app/mobile/` كُتبت واختُبرت في 0.4.0 ثم **لم تُركَّب**. فلم يكن تحت
# `/api/mobile/v1/` مسارٌ واحد، وكان التطبيق يعرض «لا جهاز مسجَّل» بحقّ.
#
# الحالة تُحفَظ على القرص لا في الذاكرة: خادم يُعاد تشغيله عند كل تحديث،
# وحالةٌ في الذاكرة تعني إعادة مسح رمز QR بعد كل إعادة تشغيل.

_MOBILE_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "mobile-state.json"

def _mobile_pause(reason_ar: str) -> None:
    """يوقف التداول محلياً **فعلاً**. كان الزرّ يسجّل ولا يوقف."""
    sys_state = system()
    sys_state.locally_paused = True
    sys_state.audit.record(
        actor=Actor.OWNER, action=AuditAction.CONFIG_CHANGE, decision="LOCAL_PAUSE",
        reason_ar=reason_ar, source="mobile",
    )


def _mobile_resume(reason_ar: str) -> None:
    """
    يرفع الإيقاف المحلي **وحده**.

    ## لماذا يُرفض ما دام القاطع مفعّلاً

    الإيقاف المحلي قرارٌ («لا أريد التداول الآن»)، وقاطع الطوارئ **حكمٌ**
    («وقع ما يستدعي التوقف»). ورفعُ الإيقاف بينما القاطع مفعّل يخلط بينهما:
    يبدو أن التداول عاد، والقاطع ما زال يمنع كل دخول — فتظنّ المالكة أن
    النظام يعمل وهو لا يعمل.

    والرفض هنا **من عند المصدر** لا من عند الواجهة: لو حُرس في الواجهة وحدها
    لمرّ أي نداءٍ آخر من حوله.
    """
    sys_state = system()
    if sys_state.kill_switch.is_active:
        event = sys_state.kill_switch.state.current_event
        raise MobileApiError(
            "قاطع الطوارئ مفعّل"
            + (f" ({event.reason_ar})" if event else "")
            + " — الاستئناف لا يرفعه، ورفعه إجراء يزيد المخاطرة ويحتاج الخادم.",
            status=409,
        )
    sys_state.locally_paused = False
    sys_state.audit.record(
        actor=Actor.OWNER, action=AuditAction.CONFIG_CHANGE, decision="LOCAL_RESUME",
        reason_ar=reason_ar, source="mobile",
    )


def _mobile_switch_environment(target: str) -> dict:
    """
    يبدّل حساب الوسيط المقروء منه — **ولا يفتح تداولاً**.

    ## ما يتغيّر وما لا يتغيّر

    يتغيّر: الحساب الذي تُقرأ منه الأسعار والرصيد والمراكز.

    ولا يتغيّر: `LIVE_TRADING` في بيئة الخادم · قفل التنفيذ · رفض `is_live`
    داخل `place_order`. ثلاثة أقفال مستقلّة، ولا يمسّها هذا المسار.

    ⇒ جهازٌ مسروق يبدّل إلى الحقيقي ولا يرسل أمراً واحداً.

    ## ويفشل مغلقاً

    الوسيط الجديد يُبنى ويُوصَل **قبل** أن يحلّ محلّ القديم. فإن أخفق الوصل
    بقيت البيئة كما هي وأُبلغ السبب — بدل نظامٍ بلا وسيطٍ أصلاً، وهو أسوأ
    من نظامٍ على الحساب الخطأ.
    """
    from .brokers.capital.endpoints import CapitalEnvironment
    from .brokers.factory import build_capital_adapter
    from .secretstore.provider import build_secret_provider

    sys_state = system()
    environment = (
        CapitalEnvironment.LIVE if target == "LIVE" else CapitalEnvironment.DEMO
    )
    try:
        secrets = build_secret_provider(
            env_file=sys_state.settings.secrets_file, allow_process_env=False
        )
        candidate = build_capital_adapter(environment, secrets=secrets)
        candidate.connect()
    except Exception as exc:  # noqa: BLE001
        raise MobileApiError(
            f"تعذّر الوصل بحساب {target}: {type(exc).__name__}. "
            "لم تتغيّر البيئة — ما زال النظام على الحساب السابق.",
            status=502,
        ) from exc

    sys_state.broker = candidate
    sys_state.broker_note_ar = ""
    sys_state.audit.record(
        actor=Actor.OWNER, action=AuditAction.CONFIG_CHANGE,
        decision=f"BROKER_ENVIRONMENT_{target}",
        reason_ar=f"بُدِّل حساب الوسيط إلى {target} من الجوال. لا يفتح تداولاً.",
        source="mobile",
    )
    return {
        "environment": target,
        "is_demo": not candidate.is_live,
        "broker_name": candidate.name,
    }


def _mobile_kill(reason_ar: str) -> None:
    """يفعّل قاطع الطوارئ **فعلاً**. كان الزرّ يسجّل ولا يفعّل."""
    sys_state = system()
    sys_state.kill_switch.trigger(KillSwitchTrigger.MANUAL, reason_ar=reason_ar)


mobile_runtime = MobileRuntime(
    security=MobileSecurityService(store=MobileStateStore(_MOBILE_STATE_PATH)),
    state_source=lambda: build_mobile_state(system()),
    actions=MobileActions(
        pause=_mobile_pause,
        activate_kill_switch=_mobile_kill,
        resume=_mobile_resume,
        switch_environment=_mobile_switch_environment,
    ),
)
set_runtime(mobile_runtime)
# مجال الجلسة أولاً: مساراته صريحة، ومجال البيانات ينتهي بمُلتقِط عام.
app.include_router(mobile_session_router)
app.include_router(mobile_router)


def _money(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


# ---------------------------------------------------------------------------

@app.get("/api/version")
def version():
    """
    أي كوميتٍ **يعمل الآن في هذه العملية** — لا أيّه على القرص.

    ## لماذا وُجد هذا المسار

    كانت النشرة تنقل الكود ثم تنادي `systemctl enable --now`. و`--now`
    يشغّل الخدمة إن لم تكن تعمل **ولا يعيد تشغيلها إن كانت تعمل**. فبقيت
    عملية واحدة تخدم من 21:52 حتى الصباح، والكود الجديد على القرص لا يُقرأ.

    وأخفاه فحصُ الجاهزية: يسأل «هل يردّ أحدٌ على 8000؟» — والعملية القديمة
    تردّ. فحصُ حياة لا فحصُ إصدار.

    وكلّف ذلك ليلة: كل إصلاح يُنشر ولا يعمل، بينما المسابر — عمليات منفصلة
    تقرأ من القرص — تعمل بالكود الجديد. فبدا النظام يناقض نفسه.

    فيُقرأ الكوميت **من رأس المستودع وقت الإقلاع**، ويُثبَّت في ثابتٍ يُقرأ
    مرّة: قراءته عند كل طلب تجعله يتبع القرص لا الذاكرة — وهو نفس الخداع.
    """
    return {"commit": _BOOT_COMMIT, "started_utc": _BOOT_TIME.isoformat()}


@app.get("/api/health")
def health(sys: SystemState = Depends(system)):
    report = sys.health()
    return {
        "broker_connected": report.broker_connected,
        "broker_name": sys.broker.name,
        "broker_is_live": sys.broker.is_live,
        "market_data_ok": report.market_data_ok,
        "database_ok": report.database_ok,
        "scheduler_ok": report.scheduler_ok,
        "clock_ok": report.clock_ok,
        "audit_chain_ok": report.audit_chain_ok,
        "kill_switch_active": report.kill_switch_active,
        "details_ar": list(report.details_ar),
        "checked_at_riyadh": format_riyadh(report.checked_at_utc),
    }


@app.get("/api/today")
def today(sys: SystemState = Depends(system)):
    market = forex_market_status()
    st = sys.session_state
    limits = sys.limits
    ks_event = sys.kill_switch.state.current_event

    remaining_total = max(Decimal("0"), limits.hard_total_loss - st.total_loss)
    verdict = (
        sys.last_result.one_line_ar
        if sys.last_result
        else "لم يُشغَّل خط القرار بعد اليوم."
    )

    return {
        "now_riyadh": format_riyadh(now_utc()),
        "market": {
            "is_open": market.is_open,
            "reason_ar": market.reason_ar,
            "open_riyadh": format_riyadh(market.session_open_utc) if market.session_open_utc else None,
            "close_riyadh": format_riyadh(market.session_close_utc) if market.session_close_utc else None,
        },
        # **كل البوابات، لا اثنتين منها.**
        #
        # كان: `kill_switch.allows_new_entries() and market.is_open` — يفحص
        # قفلين ويتجاهل أربعة، فيقول «مسموح» بينما التداول مستحيل. حقلٌ اسمه
        # أوسع مما يفحص هو كذبٌ بالتسمية.
        #
        # ومعه `blocked_by`: لا يكفي أن نقول «ممنوع»، بل **أيّ بوابة** منعت —
        # وإلا صار على المالكة أن تخمّن أو تسألني في كل مرة.
        **_trading_gates(sys, market),
        "broker": {"name": sys.broker.name, "connected": sys.broker.health_check(), "is_live": sys.broker.is_live},
        "live_trading_enabled": sys.settings.live_trading,
        "risk_mode": limits.mode.value,
        "risk_mode_purpose_ar": MODE_SPECS[limits.mode].purpose_ar,
        "equity": {
            "baseline": _money(limits.baseline_equity),
            "current": _money(st.current_equity),
        },
        "losses": {
            "today": _money(st.day_loss),
            "week": _money(st.week_loss),
            "total": _money(st.total_loss),
        },
        "limits": {
            "daily": _money(limits.daily_loss),
            "weekly": _money(limits.weekly_loss),
            "total": _money(limits.hard_total_loss),
            "target_risk_per_trade": _money(limits.target_risk_per_trade),
            "max_risk_per_trade": _money(limits.max_risk_per_trade),
        },
        "distance_to_kill_switch": _money(remaining_total),
        "open_positions": st.open_positions,
        "verdict_ar": verdict,
        "no_trade_reason_ar": (
            sys.last_result.reason_ar
            if sys.last_result and sys.last_result.reason_code
            else None
        ),
        "kill_switch": {
            "active": sys.kill_switch.is_active,
            "trigger": ks_event.trigger.value if ks_event else None,
            "reason_ar": ks_event.reason_ar if ks_event else None,
            "at_riyadh": format_riyadh(ks_event.triggered_at_utc) if ks_event else None,
        },
    }


@app.get("/api/risk")
def risk(sys: SystemState = Depends(system)):
    limits = sys.limits
    st = sys.session_state
    return {
        "constitution_fingerprint": constitution_fingerprint(limits.mode),
        "risk_mode": limits.mode.value,
        "risk_mode_purpose_ar": MODE_SPECS[limits.mode].purpose_ar,
        "economic_guards_enforced": limits.enforce_economic_viability,
        "editable_from_ui": False,
        "modes": {
            m.value: {
                "purpose_ar": spec.purpose_ar,
                "max_risk_pct": str(spec.max_risk_pct * 100),
                "daily_loss_pct": str(spec.daily_loss_pct * 100),
                "weekly_loss_pct": str(spec.weekly_loss_pct * 100),
                "hard_total_loss_pct": str(spec.hard_total_loss_pct * 100),
                "max_lifetime_entry_orders": spec.max_lifetime_entry_orders,
                "requires_per_order_approval": spec.requires_per_order_approval,
                "enforce_economic_viability": spec.enforce_economic_viability,
            }
            for m, spec in MODE_SPECS.items()
        },
        "limits": {k: str(v) for k, v in limits.as_dict().items()},
        "usage": {
            "day_loss": _money(st.day_loss),
            "week_loss": _money(st.week_loss),
            "total_loss": _money(st.total_loss),
            "open_positions": st.open_positions,
            "entry_orders_today": st.entry_orders_today,
            "consecutive_losses": st.consecutive_losses,
        },
        "triggers": [
            {"code": t.value, "label_ar": TRIGGER_LABELS_AR[t]} for t in KillSwitchTrigger
        ],
        "history": [
            {
                "trigger": e.trigger.value,
                "reason_ar": e.reason_ar,
                "policy": e.policy.value,
                "at_riyadh": format_riyadh(e.triggered_at_utc),
            }
            for e in sys.kill_switch.state.events
        ],
    }


class KillRequest(BaseModel):
    reason_ar: str = Field(min_length=10)
    confirm_phrase: str


KILL_PHRASE = "أوقف التداول الآن"
RESET_PHRASE = "أعد تفعيل النظام بعد المراجعة"


@app.post("/api/risk/kill-switch")
def trigger_kill(req: KillRequest, sys: SystemState = Depends(system)):
    if req.confirm_phrase.strip() != KILL_PHRASE:
        raise HTTPException(400, f"عبارة التأكيد غير مطابقة. المطلوب: «{KILL_PHRASE}»")
    ev = sys.kill_switch.trigger(KillSwitchTrigger.MANUAL, reason_ar=req.reason_ar)
    sys.audit.record(
        actor=Actor.OWNER, action=AuditAction.KILL_SWITCH_TRIGGERED, decision=ev.trigger.value,
        reason_ar=ev.reason_ar, source="ui",
    )
    return {"active": True, "reason_ar": ev.reason_ar}


class ResetRequest(BaseModel):
    approved_by: str = Field(min_length=2)
    reason_ar: str = Field(min_length=10)
    confirm_phrase: str
    acknowledged_review: bool


@app.post("/api/risk/kill-switch/reset")
def reset_kill(req: ResetRequest, sys: SystemState = Depends(system)):
    if not req.acknowledged_review:
        raise HTTPException(400, "يجب تأكيد مراجعة سبب التفعيل أولاً.")
    if req.confirm_phrase.strip() != RESET_PHRASE:
        raise HTTPException(400, f"عبارة التأكيد غير مطابقة. المطلوب: «{RESET_PHRASE}»")
    try:
        approval = sys.kill_switch.reset(approved_by=req.approved_by, reason_ar=req.reason_ar)
        # C2: يُثبَّت الإطفاء في السجل، وإلا عاد القاطع مفعّلاً بعد إعادة التشغيل.
        if sys.db_session is not None:
            record_reset(sys.db_session, approval)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    sys.audit.record(
        actor=Actor.OWNER, action=AuditAction.KILL_SWITCH_RESET, decision="RESET",
        reason_ar=approval.reason_ar, source="ui",
    )
    return {"active": False, "approved_by": approval.approved_by}


@app.get("/api/opportunities")
def opportunities(sys: SystemState = Depends(system)):
    """
    لا تُعرض هنا 'دعوة شراء'. كل صف يشرح لماذا قُبل أو رُفض.
    """
    rows = []
    for symbol, entry in ALLOWLIST.items():
        rows.append({
            "symbol": symbol,
            "name_ar": entry.name_ar,
            "enabled": entry.enabled,
            "rationale_ar": entry.rationale_ar,
            "strategy": "TREND_PULLBACK 1.0.0",
            "status_ar": "الاستراتيجية في حالة بحث — لا تُنتج أوامر.",
        })
    denied = [{"symbol": s, "reason_ar": r} for s, r in EXPLICIT_DENYLIST.items()]
    return {"allowlist": rows, "denylist": denied}


@app.get("/api/strategies")
def strategies(sys: SystemState = Depends(system)):
    out = []
    for s in sys.registry.all():
        m = s.metadata
        out.append({
            "name": m.name, "version": m.version, "state": m.state.value,
            "hypothesis_ar": m.hypothesis_ar, "markets": list(m.markets), "timeframe": m.timeframe,
            "entry_conditions_ar": list(m.entry_conditions_ar),
            "exit_conditions_ar": list(m.exit_conditions_ar),
            "invalidations_ar": list(m.invalidations_ar),
            "no_trade_conditions_ar": list(m.no_trade_conditions_ar),
            "assumed_costs_ar": m.assumed_costs_ar,
            "backtest_evidence_ar": m.backtest_evidence_ar,
            "walkforward_evidence_ar": m.walkforward_evidence_ar,
            "changelog_ar": list(m.changelog_ar),
        })
    return {"strategies": out, "active_count": len(sys.registry.active())}


@app.get("/api/audit")
def audit(limit: int = 200, action: str | None = None, sys: SystemState = Depends(system)):
    events = sys.audit.events()
    if action:
        events = [e for e in events if e.action == action]
    chain = verify_chain(sys.audit.events())
    return {
        "chain_ok": chain.ok,
        "chain_problem_ar": chain.problem_ar,
        "checked": chain.checked,
        "events": [
            {
                "sequence": e.sequence,
                "at_riyadh": format_riyadh(e.timestamp_utc),
                "actor": e.actor, "action": e.action, "decision": e.decision,
                "reason_ar": e.reason_ar, "source": e.source,
                "related_id": e.related_id, "entry_hash": e.entry_hash[:16],
            }
            for e in events[-limit:]
        ],
    }


@app.get("/api/trades")
def trades(sys: SystemState = Depends(system)):
    try:
        account = sys.broker.get_accounts()[0]
        positions = [p.model_dump(mode="json") for p in sys.broker.get_positions(account)]
        orders = [o.model_dump(mode="json") for o in sys.broker.get_orders(account)]
        executions = [x.model_dump(mode="json") for x in sys.broker.get_executions(account)]
    except Exception as exc:  # noqa: BLE001
        return {"error_ar": f"تعذر جلب البيانات من الوسيط: {exc}",
                "positions": [], "orders": [], "executions": []}
    return {"positions": positions, "orders": orders, "executions": executions}


@app.get("/api/settings")
def settings_view(sys: SystemState = Depends(system)):
    s = get_settings()
    return {
        "mode": "LIVE" if s.live_trading else "PAPER/MOCK",
        "broker_mode": s.broker_mode,
        "live_trading": s.live_trading,
        "display_timezone": s.display_timezone,
        "baseline_equity_usd": s.baseline_equity_usd,
        "risk_mode": sys.limits.mode.value,
        "risk_mode_changeable_from_ui": False,
        "risk_constitution_editable": False,
        "allowlist": list(ALLOWLIST.keys()),
        "blackout_days_confirmed": [d.isoformat() for d in sorted(sys.blackouts.confirmed_for)],
    }


# ---------------------------------------------------------------------------
# Capital.com — الوسيط والاعتمادات والتشغيل التجريبي
# ---------------------------------------------------------------------------

def _trading_gates(sys: SystemState, market) -> dict:
    """
    البوابات التي يجب أن تُفتح جميعاً قبل أي دخول جديد.

    لكل بوابة صيغتان: **الشرط** حين تكون مفتوحة، و**سبب المنع** حين تكون
    مغلقة. ولا تُشتقّ الثانية بنفي الأولى: أول نسخة أدرجت الشرط نفسه في
    `blocked_by`، فقرأتها المالكة «ممنوع بسبب: التشغيل غير موقوف محلياً» —
    عكس المعنى تماماً. والنفي اللغوي ليس نفياً منطقياً في العربية ولا في
    غيرها، فتُكتب الصيغتان صراحةً.
    """
    from .brokers.capital.adapter import STOP_DISTANCE_UNIT

    #: (مفتوحة؟, سبب المنع حين تكون مغلقة)
    gates = [
        (sys.kill_switch.allows_new_entries(), "قاطع الطوارئ مُفعَّل"),
        (market.is_open, "السوق مغلق"),
        (not sys.locally_paused, "التشغيل موقوف محلياً"),
        (sys.settings.live_trading, "التداول الحقيقي مُعطَّل"),
        (sys.execution_lock.unlocked, "قفل التنفيذ مغلق"),
        # الوحدة صارت مقيسة (2026-09-01) ولم تعد بوابة. وحلّ محلّها تحقّقٌ
        # **بعد كل تنفيذ** من وقف المركز عند الوسيط — وهو لا يُعرَض هنا
        # لأنه ليس بوابةً قبلية بل رفضٌ بعديّ.
        (STOP_DISTANCE_UNIT == "PRICE", "وحدة مسافة الوقف غير معروفة"),
    ]
    blocked = [reason for ok, reason in gates if not ok]
    return {"trading_allowed": not blocked, "blocked_by": blocked}


def _broker_environment(broker) -> str:
    """بيئة الوسيط كما يقولها هو. الوسطاء بلا جلسة (الوهمي) يُعلنون أنفسهم."""
    session = getattr(broker, "session", None)
    env = getattr(session, "environment", None)
    if env is not None:
        return getattr(env, "value", str(env))
    return getattr(broker, "name", "unknown").lower()


@app.get("/api/broker")
def broker_state(sys: SystemState = Depends(system)):
    """
    كل ما تحتاج المالكة رؤيته عن الوسيط — بلا أي سرّ ولا معرّف حساب كامل.
    """
    limits = sys.limits
    ks_event = sys.kill_switch.state.current_event
    return {
        "broker": limits.broker.value,
        # **تُقرأ من المحوّل القائم، لا تُثبَّت.**
        #
        # كانت `is_demo` و`base_url` قيمتين ثابتتين، و`environment` تعبيراً
        # يبدو ديناميكياً (`risk_mode and "demo"`) ويُنتج "demo" دائماً. فلمّا
        # صار الوسيط حقيقياً ظلّت الواجهة تقول «تجريبي» بينما `adapter_name`
        # يقول `CAPITAL_COM_LIVE` — تناقضٌ في الاستجابة نفسها.
        #
        # وشاشةٌ تكذب عن بيئة الوسيط أخطر من قفلٍ مفتوح: القفل يُرى ويُغلق،
        # والكذب يُصدَّق ويُبنى عليه قرار.
        "environment": _broker_environment(sys.broker),
        "is_demo": not getattr(sys.broker, "is_live", False),
        "live_api_enabled_in_source": LIVE_API_ENABLED,
        "base_url": getattr(getattr(sys.broker, "session", None), "base_url", None),
        "adapter_name": sys.broker.name,
        "connected": _safe_health(sys),
        "account_masked": None,
        "local_trading_paused": sys.locally_paused,
        "execution_lock": sys.execution_lock.as_dict(),
        "risk_mode": limits.mode.value,
        "risk_constitution_version": CONSTITUTION_VERSION,
        "kill_switch": {
            "active": sys.kill_switch.is_active,
            "trigger": ks_event.trigger.value if ks_event else None,
            "reason_ar": ks_event.reason_ar if ks_event else None,
        },
        "credentials": sys.secret_presence,
        # **تُقرأ من المحوّل العامل، لا من ثابتٍ في ملف.**
        #
        # كانت هذه السطور تطبع `DISCOVERY_EPICS` و`EXECUTION_EPICS` — وهما
        # ثابتان في `discovery/capital_discovery.py` لا علاقة لهما بما يعمل
        # به المحوّل. فلمّا وُسّعت قائمة التنفيذ من القياس إلى أربع أدوات،
        # بقيت الشاشة تقول «EURUSD» وحدها. قيمةٌ تُعرَض ولا تُقرأ من مصدرها،
        # للمرّة السابعة في هذا المشروع.
        "discovery_allowlist": sorted(
            getattr(sys.broker, "discovery_allowlist", None) or DISCOVERY_EPICS
        ),
        "execution_allowlist": sorted(
            getattr(sys.broker, "execution_allowlist", None) or EXECUTION_EPICS
        ),
        "instruments_note_ar": getattr(sys, "instruments_note_ar", ""),
        "api_key_pause_instructions_ar": [
            "افتحي حسابك على Capital.com ← Settings ← API.",
            "أوقفي أو احذفي المفتاح المستخدم هنا لإيقاف كل وصول برمجي فوراً.",
            "إيقاف المفتاح من الوسيط أقوى من أي زر في هذه الواجهة، لأنه لا يعتمد على تشغيل هذا النظام.",
        ],
    }


def _safe_health(sys: SystemState) -> bool:
    try:
        return bool(sys.broker.health_check())
    except Exception:  # noqa: BLE001
        return False


class PauseRequest(BaseModel):
    reason_ar: str = Field(min_length=3)


@app.post("/api/trading/pause")
def pause_trading(req: PauseRequest, sys: SystemState = Depends(system)):
    """إيقاف محلي فوري. لا يحتاج عبارة تأكيد لأن الإيقاف دائماً آمن."""
    sys.locally_paused = True
    sys.audit.record(
        actor=Actor.OWNER, action=AuditAction.CONFIG_CHANGE, decision="LOCAL_PAUSE",
        reason_ar=req.reason_ar, source="ui",
    )
    return {"local_trading_paused": True, "reason_ar": req.reason_ar}


class ResumeRequest(BaseModel):
    reason_ar: str = Field(min_length=10)
    confirm_phrase: str


RESUME_PHRASE = "ارفع الإيقاف المحلي"


@app.post("/api/trading/resume")
def resume_trading(req: ResumeRequest, sys: SystemState = Depends(system)):
    """
    رفع الإيقاف المحلي **لا يفعّل التداول الحقيقي**.
    التداول الحقيقي يبقى مقفلاً بأقفال البيئة وملف الموافقة وقفل الكود.
    """
    if req.confirm_phrase.strip() != RESUME_PHRASE:
        raise HTTPException(400, f"عبارة التأكيد غير مطابقة. المطلوب: «{RESUME_PHRASE}»")
    if sys.kill_switch.is_active:
        raise HTTPException(400, "Kill Switch مفعّل — لا يمكن رفع الإيقاف المحلي قبل إعادة تفعيله.")
    sys.locally_paused = False
    sys.audit.record(
        actor=Actor.OWNER, action=AuditAction.CONFIG_CHANGE, decision="LOCAL_RESUME",
        reason_ar=req.reason_ar, source="ui",
    )
    return {
        "local_trading_paused": False,
        "live_trading_enabled": sys.settings.live_trading,
        "note_ar": "رُفع الإيقاف المحلي فقط. التداول الحقيقي ما زال مقفلاً.",
    }


@app.get("/api/cfd-preview")
def cfd_preview(
    stop_pips: float = 25.0,
    take_profit_pips: float = 50.0,
    guaranteed: bool = False,
    sys: SystemState = Depends(system),
):
    """
    بطاقة معاينة CFD. تعرض **التعرّض والهامش والخسارة منفصلة** كما يفرض
    نموذج التكلفة، ولا تصف الأمر أبداً بأنه «أمر بـ5–10 دولارات».
    """
    model = sys.cost_model
    entry = D("1.08546")
    try:
        economics = model.estimate(
            size=model.economics.min_deal_size,
            entry_price=entry,
            stop_distance_pips=D(str(stop_pips)),
            take_profit_distance_pips=D(str(take_profit_pips)),
            stop_kind=StopKind.GUARANTEED if guaranteed else StopKind.NORMAL,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    limits = sys.limits
    return {
        "epic": economics.epic,
        "provisional": economics.provisional,
        "provisional_note_ar": (
            "قيم مبدئية من الموقع العام — لم تُكتشف بعد من حساب Demo. "
            "لا يُبنى عليها قرار تنفيذ."
            if economics.provisional
            else "قيم مُكتشَفة من الوسيط."
        ),
        "display": economics.as_display_dict(),
        "caps": {
            "preferred_max_risk": f"{limits.target_risk_per_trade:.2f}",
            "absolute_max_risk": f"{limits.max_risk_per_trade:.2f}",
            "within_preferred": economics.all_in_risk <= limits.target_risk_per_trade,
            "within_absolute": economics.all_in_risk <= limits.max_risk_per_trade,
        },
        "warnings_ar": list(economics.provenance_notes),
        "submitted": False,
        "execution_locked": not sys.execution_lock.unlocked,
    }


# ---------------------------------------------------------------------------
# ملفات التداول (0.3.0)
# ---------------------------------------------------------------------------

def _guard_state(sys: SystemState) -> SystemGuardState:
    """
    لقطة الحراسات **للقراءة فقط**. مدير الملفات يستقبلها ولا يكتب فيها،
    ولذلك لا يستطيع تبديل الملف أن يعيد ضبط أي عدّاد.
    """
    st = sys.session_state
    return SystemGuardState(
        open_positions=st.open_positions,
        pending_orders=0,
        unknown_executions=0,
        risk_engine_healthy=_safe_health(sys),
        loss_lock_active=st.consecutive_losses >= sys.limits.consecutive_losses_pause,
        kill_switch_active=sys.kill_switch.is_active,
        daily_loss=st.day_loss,
        weekly_loss=st.week_loss,
        total_drawdown=st.total_loss,
        consecutive_losses=st.consecutive_losses,
        open_risk=D("0"),
        strategy_validation_history_len=len(sys.registry.all())
        if hasattr(sys.registry, "all") else 0,
    )


@app.get("/api/profiles")
def profiles_state(sys: SystemState = Depends(system)):
    """
    الملف المختار · الفعّال · المعلّق · المتبقي من التهدئة · سبب المنع ·
    وحدود الملفات الثلاثة كاملة للمقارنة.
    """
    guards = _guard_state(sys)
    state = sys.profiles.state_for_display(guards, sys.session_state.current_equity)
    state["available_profiles"] = [
        {
            "profile": p.value,
            "name_ar": PROFILE_SPECS[p].name_ar,
            "description_ar": PROFILE_SPECS[p].description_ar,
            "risk_rank": PROFILE_RISK_ORDER[p],
            "limits": ProfileLimits.for_profile(
                p, sys.session_state.current_equity
            ).as_display_dict(),
        }
        for p in sorted(TradingProfile, key=lambda x: PROFILE_RISK_ORDER[x])
    ]
    state["global_loss_constitution"] = {
        "operational_drawdown_stop": _money(GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD),
        "gap_slippage_reserve": _money(GLOBAL_GAP_SLIPPAGE_RESERVE_USD),
        "absolute_loss_boundary": _money(GLOBAL_ABSOLUTE_LOSS_BOUNDARY_USD),
        "cooling_hours": PROFILE_UPGRADE_COOLING_HOURS,
        "note_ar": (
            "هذه الحدود تسري على كل الملفات، ولا يُعاد ضبطها بتبديل الملف. "
            "الوقف العادي لا يضمن الحاجز عند الفجوة."
        ),
    }
    state["never_weakened_by_profile"] = list(NEVER_WEAKENED_BY_PROFILE)
    return state


class ProfileChangeRequestBody(BaseModel):
    profile: str
    owner_confirmed: bool = False
    owner_reference: str = ""


@app.post("/api/profiles/select")
def select_profile(req: ProfileChangeRequestBody, sys: SystemState = Depends(system)):
    """
    اختيار ملف. الخفض فوري؛ الرفع يبدأ تهدئة 24 ساعة ويحتاج تأكيداً صريحاً.
    **لا يفتح هذا المسار التداول الحقيقي بحال، ولا يعيد ضبط أي عدّاد.**
    """
    try:
        target = TradingProfile(req.profile)
    except ValueError:
        raise HTTPException(400, "ملف غير معروف.")

    guards = _guard_state(sys)
    result = sys.profiles.request_change(
        target, guards,
        owner_confirmed=req.owner_confirmed,
        owner_reference=req.owner_reference,
    )
    if result.record is not None:
        sys.audit.record(
            actor=Actor.OWNER,
            action=AuditAction.CONFIG_CHANGE,
            decision="PROFILE_CHANGE",
            reason_ar=result.message_ar,
            source="ui",
            after=result.record.as_audit_payload(),
        )
    return {
        "accepted": result.accepted,
        "effective_profile": result.effective_profile.value,
        "pending_profile": result.pending.target.value if result.pending else None,
        "refusal": result.refusal.value if result.refusal else None,
        "message_ar": result.message_ar,
        "live_trading_enabled": sys.settings.live_trading,
        "note_ar": "تبديل الملف لا يفتح التداول الحقيقي ولا يعيد ضبط أي عدّاد.",
    }


@app.post("/api/profiles/confirm-upgrade")
def confirm_profile_upgrade(
    req: ProfileChangeRequestBody, sys: SystemState = Depends(system)
):
    guards = _guard_state(sys)
    result = sys.profiles.confirm_pending_upgrade(guards, owner_reference=req.owner_reference)
    if result.record is not None:
        sys.audit.record(
            actor=Actor.OWNER,
            action=AuditAction.CONFIG_CHANGE,
            decision="PROFILE_UPGRADE_CONFIRMED",
            reason_ar=result.message_ar,
            source="ui",
            after=result.record.as_audit_payload(),
        )
    return {
        "accepted": result.accepted,
        "effective_profile": result.effective_profile.value,
        "refusal": result.refusal.value if result.refusal else None,
        "message_ar": result.message_ar,
    }


@app.get("/api/intelligence")
def intelligence(sys: SystemState = Depends(system)):
    """
    آخر قرار من خط الاستخبارات، بكل مراحله ودرجته وتناقضاته ومراجعته المستقلة.

    الغرض أن يكون `NO_TRADE` **مفهوماً لا معطّلاً**: كل مرحلة تُعرض بحالتها
    وسببها، والبيانات الناقصة والمزوّدون الناقصون بأسمائهم الدقيقة.
    """
    result = sys.last_intelligence
    providers = sys.providers.as_display_dict()
    if result is None:
        return {
            "available": False,
            "reason_ar": (
                "لم تُشغَّل دورة تحليل بعد. المزوّدون الناقصون تمنع التشغيل الحقيقي."
            ),
            "providers": providers,
            "stages": [
                {"stage": s.value, "name_ar": STAGE_NAME_AR[s], "passed": None}
                for s in STAGE_ORDER
            ],
            "strategies": sys.strategy_definitions.as_dict(),
        }
    payload = result.as_dict()
    payload["available"] = True
    payload["providers"] = providers
    payload["strategies"] = sys.strategy_definitions.as_dict()
    return payload
