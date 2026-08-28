"""
FastAPI application. الواجهة تقرأ من هنا فقط.

مبدأ: لا يوجد endpoint واحد يستطيع تعديل دستور المخاطر أو تفعيل التداول الحقيقي.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .audit.log import Actor, AuditAction, verify_chain
from .api.state import SystemState, build_system
from .clock import format_riyadh, now_utc, us_market_status
from .config import get_settings
from .eligibility.allowlist import ALLOWLIST, EXPLICIT_DENYLIST
from .killswitch.engine import TRIGGER_LABELS_AR, KillSwitchTrigger
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

app = FastAPI(title="Maather Autonomous Trader", version="0.3.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"], allow_headers=["*"],
)

_SYSTEM: Optional[SystemState] = None


def system() -> SystemState:
    global _SYSTEM
    if _SYSTEM is None:
        _SYSTEM = build_system()
    return _SYSTEM


def _money(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


# ---------------------------------------------------------------------------

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
    market = us_market_status()
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
        "trading_allowed": sys.kill_switch.allows_new_entries() and market.is_open,
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

@app.get("/api/broker")
def broker_state(sys: SystemState = Depends(system)):
    """
    كل ما تحتاج المالكة رؤيته عن الوسيط — بلا أي سرّ ولا معرّف حساب كامل.
    """
    limits = sys.limits
    ks_event = sys.kill_switch.state.current_event
    return {
        "broker": limits.broker.value,
        "environment": sys.settings.risk_mode and "demo",
        "is_demo": True,
        "live_api_enabled_in_source": LIVE_API_ENABLED,
        "base_url": DEMO_BASE_URL,
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
        "discovery_allowlist": list(DISCOVERY_EPICS),
        "execution_allowlist": list(EXECUTION_EPICS),
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
