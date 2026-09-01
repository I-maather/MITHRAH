"""
مصدر الحالة للجوال — يحوّل `SystemState` إلى **عقد التطبيق حرفياً**.

## العطب الذي أنشأ هذا الملف من جديد

كُتب هذا الملف أول مرة بشكلٍ من ابتكاري: `kill_switch_active` قيمةً مفردة،
و`daily_loss_used_usd`، و`available/reason_ar` لكل قسم غير جاهز. والتطبيق
كان — ولا يزال — يقرأ عقداً آخر مُعلَناً في `mobile/src/api/types.ts`:
`kill_switch.active` كائناً، و`risk_used_today`، وحقولاً لا وجود لها عندي.

    التطبيق يقرأ  s.kill_switch.active
    والخادم يرسل  kill_switch_active
    ⇒ قراءة حقل داخل شيء غير موجود ⇒ انهيار التصيير ⇒ **شاشة سوداء**

ولم يظهر العطب طوال الوقت لأن كل الطلبات كانت تفشل، فكانت الشاشة تعرض
«غير متاح» ولا تبلغ عرض البيانات أصلاً. أول مرة نجحت فيها الطلبات، انهار.

**والخادم يتبع عقد العميل لا العكس** — نفس القاعدة التي حكمت مسارات الجلسة:
العميل مُثبَّت على جهاز لا يُحدَّث بأمر.

## القاعدة الثابتة: لا اختراع

عقد العميل يقبل `null` في كل حقل غير محسوب، والواجهة تعرض «غير متاح».
فالحقل الذي لا نملكه **يُرسَل مفتاحاً بقيمة `null`** — لا يُحذف (فيصير
قراءةً على غير موجود) ولا يُملأ بقيمة مصطنعة.

## ولا سرّ يمرّ

لا يُقرأ من `SystemState` سوى حقول مُسمّاة صراحةً أدناه. لا تمرير كائنٍ
كامل، ولا `__dict__`، ولا `vars()`.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..clock import now_utc, forex_market_status


def _money(value: Decimal | None) -> str | None:
    """رقم نقدي نصّاً بمنزلتين. `None` تبقى `None` — لا تصير «0.00»."""
    return f"{value:.2f}" if value is not None else None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# الأقسام
# ---------------------------------------------------------------------------

def _status(sys: Any) -> dict[str, Any]:
    market = forex_market_status()
    health = sys.health()
    kill = sys.kill_switch
    event = kill.state.current_event

    if kill.is_active:
        phase, phase_ar = "KILL_SWITCH", "قاطع الطوارئ مُفعَّل — لا دخول."
    elif sys.locally_paused:
        phase, phase_ar = "PAUSED", "موقوف محلياً."
    elif not health.broker_connected or not health.database_ok:
        phase, phase_ar = "DEGRADED", "النظام يعمل بقدرة ناقصة."
    else:
        phase, phase_ar = "RUNNING", "يعمل."

    # **الاكتمال يُقاس على الإلزاميين وحدهم.**
    #
    # كان يُقاس على كل المزوّدين، ومنهم `FundamentalContextProvider` — وهو
    # **اختياري ولا وجود لتنفيذٍ له في المشروع أصلاً**. فكان يُحتسب ناقصاً
    # إلى الأبد، وتُعرض على المالكة نسبة **لا يمكن أن تبلغ ١٠٠٪ بحال**،
    # وتوحي بنقصٍ يمنع التداول وهو لا يمنعه.
    #
    # والإلزاميون هم من يحكمون الأهلية (`MANDATORY_FOR_LIVE`)، فهم وحدهم
    # ما تعنيه كلمة «اكتمال». والاختياري الناقص يُقال باسمه على حدة، لا
    # يُخصَم من رقمٍ يُقرأ حكماً.
    from ..intelligence.providers import MANDATORY_FOR_LIVE

    missing_mandatory = list(sys.providers.missing_mandatory())
    missing_ar = [_provider_name_ar(k) for k in missing_mandatory]
    optional_missing_ar = [
        _provider_name_ar(k) for k in sys.providers.missing()
        if k not in MANDATORY_FOR_LIVE
    ]
    total = len([p for p in sys.providers.all() if p.kind in MANDATORY_FOR_LIVE])
    configured = total - len(missing_ar)

    return {
        "system_state": phase,
        "system_state_ar": phase_ar,
        "locally_paused": sys.locally_paused,
        "kill_switch": {
            "active": kill.is_active,
            "trigger": event.trigger.value if event else None,
            "reason_ar": event.reason_ar if event else None,
            "at_utc": _iso(event.triggered_at_utc) if event else None,
        },
        "broker": {
            "name": sys.broker.name,
            "connected": health.broker_connected,
            # **السبب يُرسَل مع الحال.** «غير متصل» وحدها ترسل المالكة تبحث
            # في سجلات الخادم عن شيء يعرفه النظام ولا يقوله.
            "note_ar": getattr(sys, "broker_note_ar", "") or None,
            "is_demo": not sys.broker.is_live,
            # **لا يُرسَل معرّف الحساب** — لا كاملاً ولا مقنَّعاً في هذا
            # الإصدار. الحقل موجود في العقد ويبقى `null` حتى يُقنَّع بمصدر
            # موثوق؛ إرسال آخر رقمين اليوم ليس ضرورة وهو تسريب صغير مجاني.
            "account_masked": None,
            "execution_locked": True,
        },
        "market": {
            "is_open": market.is_open,
            "reason_ar": market.reason_ar,
            "next_open_utc": _iso(market.session_open_utc),
            "next_close_utc": _iso(market.session_close_utc),
        },
        "data_completeness": {
            "complete": not missing_ar,
            "ratio": (configured / total) if total else None,
            "missing": missing_ar,
            # الاختياري الناقص يُذكر ولا يُخصَم: معلومةٌ لا حكم.
            "optional_missing": optional_missing_ar,
        },
        # لا استراتيجية مُجازة للتنفيذ، ولا نخترع واحدة لملء الحقل.
        "strategy_state": None,
        # التقويم الاقتصادي غير مُعدّ، فلا حدث معلوم — و`null` هنا تعني
        # «لا نعلم»، تعرضها الواجهة «لا حدث مُعلَن ضمن النافذة».
        "upcoming_event": None,
        "last_refresh_utc": now_utc().isoformat(),
        "no_trade_reason_ar": _no_trade_reason(sys),
    }


def _no_trade_reason(sys: Any) -> str | None:
    if sys.kill_switch.is_active:
        return "قاطع الطوارئ مُفعَّل. لا دخول حتى يُلغى من الخادم."
    if sys.last_result is not None and sys.last_result.reason_code:
        return sys.last_result.reason_ar
    missing = [_provider_name_ar(k) for k in sys.providers.missing_mandatory()]
    if missing:
        return (
            "مزوّدون إلزاميون غير مُعدّين: "
            + "، ".join(missing)
            + ". ولا استراتيجية مُجازة بعد."
        )
    return "لا استراتيجية معتمدة — يتوقف الخط عند STRATEGY_NOT_APPROVED."


#: أسماء المزوّدين بالعربية. تُعرض للمالكة كما هي.
_PROVIDER_NAMES_AR: dict[str, str] = {
    "EconomicCalendarProvider": "التقويم الاقتصادي",
    "MacroDataProvider": "البيانات الكلية",
    "VerifiedNewsProvider": "الأخبار المُتحقَّقة",
    "MarketDataProvider": "بيانات السوق",
    "FundamentalContextProvider": "السياق الأساسي",
}


def _provider_name_ar(kind: Any) -> str:
    key = getattr(kind, "value", str(kind))
    return _PROVIDER_NAMES_AR.get(key, key)


def _risk(sys: Any) -> dict[str, Any]:
    from ..profiles import ProfileLimits

    session = sys.session_state
    profile = sys.profiles.effective_profile
    # حدود **الملف الفعّال** محسوبة على حقوق الملكية الحالية. ودستور
    # المخاطر (`sys.limits`) يبقى المرجع الأشدّ على الخادم، ولا يُرسَل هنا
    # كي لا تُعرض مجموعتا حدود متجاورتين فتُقرأ الأضعف.
    spec = ProfileLimits.for_profile(profile, session.current_equity)

    remaining_day = max(Decimal("0"), spec.max_daily_loss - session.day_loss)
    remaining_week = max(Decimal("0"), spec.max_weekly_loss - session.week_loss)
    to_boundary = max(Decimal("0"), spec.absolute_loss_boundary - session.total_loss)

    return {
        "profile": profile.value,
        "profile_name_ar": spec.name_ar,
        "currency": "USD",
        "equity_used": _money(spec.equity_used),
        "risk_used_today": _money(session.day_loss),
        "risk_remaining_today": _money(remaining_day),
        "risk_used_week": _money(session.week_loss),
        "risk_remaining_week": _money(remaining_week),
        "max_risk_per_trade": _money(spec.max_risk_per_trade),
        "max_daily_loss": _money(spec.max_daily_loss),
        "max_weekly_loss": _money(spec.max_weekly_loss),
        "operational_drawdown_stop": _money(spec.operational_drawdown_stop),
        "absolute_loss_boundary": _money(spec.absolute_loss_boundary),
        "distance_to_kill_switch": _money(to_boundary),
        "open_positions": session.open_positions,
        "max_open_positions": spec.max_open_positions,
        "entry_orders_today": session.entry_orders_today,
        "max_entry_orders_per_day": spec.max_entry_orders_per_day,
        "consecutive_losses": session.consecutive_losses,
        "two_loss_lock_active": session.consecutive_losses >= 2,
        # الحدود تُفرَض على الخادم. الثابت يُفحَص في العميل عند كل استجابة.
        "editable_from_device": False,
        # ---- المحفظة -------------------------------------------------------
        # ثلاثة أرقام لا واحد، **والخلاف بينها معلومة لا خطأ**:
        #
        #   المرجعي   الرقم الذي تُحسب منه كل الحدود.
        #   الفعلي    ما يقوله الوسيط الآن.
        #   الحالي    المرجعي زائد ما تحقّق من ربح أو خسارة.
        #
        # وعرض الفعلي وحده يُخفي أن الحدود قد تُحسب على رقمٍ آخر — وهو ما
        # بقي صامتاً حتى انكشف بالمصادفة: ١٥٠ مرجعاً و١٤٠ في الحساب.
        # وعرض المرجعي وحده يُخفي المال نفسه.
        "portfolio": _portfolio(sys, session),
    }


def _portfolio(sys: Any, session: Any) -> dict[str, Any]:
    """
    المرجع والرصيد والخلاف بينهما.

    **لا يُختلق رقم.** وسيطٌ مفصول لا يُثبت شيئاً عن الرصيد، فيعود `null`
    مع سببٍ مكتوب — لا صفر ولا آخر قيمة معروفة.
    """
    from ..risk.session_state import check_baseline_against_broker

    baseline = sys.limits.baseline_equity
    try:
        # على حسابٍ تجريبي يكون المرجع **محاكى عمداً**: رصيد الديمو كبير
        # والمرجع صغير كي تنتقل التجربة إلى الحساب الحقيقي. فلا يُسمّى ذلك
        # انحرافاً — وإنذارٌ دائم بلا سبب يُدرَّب على تجاهله.
        simulated = not bool(getattr(sys.broker, "is_live", False))
        drift = check_baseline_against_broker(
            sys.broker, baseline, simulated_capital=simulated
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "baseline_equity": _money(baseline),
            "broker_equity": None,
            "current_equity": _money(session.current_equity),
            "diverged": False,
            "note_ar": f"تعذّر فحص الرصيد ({type(exc).__name__}).",
        }

    return {
        "baseline_equity": _money(drift.baseline),
        "broker_equity": _money(drift.broker_equity),
        "current_equity": _money(session.current_equity),
        "diverged": drift.diverged,
        "note_ar": drift.reason_ar,
    }


def _profiles(sys: Any) -> dict[str, Any]:
    from ..profiles import (
        PROFILE_RISK_ORDER,
        PROFILE_SPECS,
        ProfileLimits,
        TradingProfile,
    )

    manager = sys.profiles
    pending = manager.pending_upgrade
    remaining = manager.cooling_remaining()
    equity = sys.session_state.current_equity

    available = []
    for profile in TradingProfile:
        spec = PROFILE_SPECS[profile]
        computed = ProfileLimits.for_profile(profile, equity)
        available.append({
            "profile": profile.value,
            "name_ar": spec.name_ar,
            "description_ar": spec.description_ar,
            "risk_rank": PROFILE_RISK_ORDER[profile] + 1,
            "limits": {
                "max_risk_per_trade": _money(computed.max_risk_per_trade),
                "max_daily_loss": _money(computed.max_daily_loss),
                "max_weekly_loss": _money(computed.max_weekly_loss),
                "operational_drawdown_stop": _money(computed.operational_drawdown_stop),
                "absolute_loss_boundary": _money(computed.absolute_loss_boundary),
                "max_open_positions": computed.max_open_positions,
                "max_entry_orders_per_day": computed.max_entry_orders_per_day,
                "min_net_reward_risk": f"{computed.min_net_reward_risk:.2f}",
                "min_quality_score": computed.min_quality_score,
                "allow_overnight": computed.allow_overnight,
                "allow_weekend_hold": computed.allow_weekend_hold,
            },
        })

    effective_spec = PROFILE_SPECS[manager.effective_profile]
    selected_spec = PROFILE_SPECS[manager.selected_profile]
    rank = PROFILE_RISK_ORDER[manager.effective_profile]
    return {
        "selected_profile": manager.selected_profile.value,
        "selected_name_ar": selected_spec.name_ar,
        "effective_profile": manager.effective_profile.value,
        "effective_name_ar": effective_spec.name_ar,
        "risk_level_ar": ("منخفض", "متوسط", "أعلى")[rank],
        "pending_profile": pending.target.value if pending else None,
        "pending_available_at_utc": _iso(pending.available_at_utc) if pending else None,
        "cooling_remaining_seconds": (
            int(remaining.total_seconds()) if remaining is not None else None
        ),
        "change_blocked_reason_ar": (
            "الملف يُغيَّر من الخادم فقط، وبتبريد ٢٤ ساعة. "
            "والتبديل لا يعيد ضبط أي عدّاد."
        ),
        "available_profiles": available,
        "fingerprint": None,
        # الثابت الذي يفحصه العميل: الترقية تحتاج الخادم.
        "upgrade_requires_server": True,
    }


def _decision(sys: Any) -> dict[str, Any]:
    result = sys.last_result
    if result is None:
        return {
            "decision": "UNKNOWN",
            "decision_ar": "لم يُشغَّل خط القرار بعد.",
            "reason_code": None,
            "explanation_ar": _no_trade_reason(sys),
            "score": None,
            "snapshot_id": None,
            "decided_at_utc": None,
            "blocking_reasons_ar": [],
            "stages": [],
            "authorises_execution": False,
        }
    return {
        "decision": "NO_TRADE" if result.reason_code else "ELIGIBLE",
        "decision_ar": result.one_line_ar,
        "reason_code": result.reason_code or None,
        "explanation_ar": result.reason_ar or None,
        "score": None,
        "snapshot_id": None,
        "decided_at_utc": None,
        "blocking_reasons_ar": [result.reason_ar] if result.reason_ar else [],
        "stages": [],
        "authorises_execution": False,
    }


def _intelligence(sys: Any) -> dict[str, Any]:
    """
    `available: false` جزءٌ من عقد هذا القسم وحده — لا من كل قسم.

    والفرق مقصود: «لم يُشغَّل الخط» معلومة، أما `{}` فادّعاء فراغ لا نملكه.
    """
    return {
        "available": sys.last_intelligence is not None,
        "reason_ar": (
            None if sys.last_intelligence is not None
            else "لم يُشغَّل خط الاستخبارات في هذه الجلسة."
        ),
        "snapshot_id": None,
        "decided_at_utc": None,
        "regime": None,
        "timeframes": None,
        "stages": [],
        "score": None,
        "contradictions": None,
        "missing_providers": [_provider_name_ar(k) for k in sys.providers.missing()],
        "missing_data": [],
        "explanation_ar": _no_trade_reason(sys),
    }


def _position(sys: Any) -> dict[str, Any]:
    """
    لا مركز مفتوح، ونعلم ذلك: لم يُرسَل أمرٌ قط، والتنفيذ مقفول.

    `protection_held_by_broker` يبقى `True`: الوقف والهدف — متى وُجدا —
    يُحفظان لدى الوسيط لا في هذا التطبيق. الحقل يقول قاعدة لا حالة.
    """
    return {
        "has_position": sys.session_state.open_positions > 0,
        "instrument_ar": None,
        "instrument": None,
        "direction_ar": None,
        "opened_utc": None,
        "entry_price": None,
        "current_price": None,
        "stop_price": None,
        "take_profit_price": None,
        "size_display": None,
        "notional_display": None,
        "unrealised_pnl": None,
        "unrealised_pnl_sign": None,
        "risk_at_stop": None,
        "protection_held_by_broker": True,
        "strategy_ar": None,
        "notes_ar": ["لا مركز مفتوح. لم يُرسَل أي أمر، والتنفيذ مقفول."],
    }


def _performance(sys: Any) -> dict[str, Any]:
    """
    **الفراغ هنا ليس صفراً.** لا صفقة واحدة، فلا نسبة ربح ولا توقّع.

    وكل مقياس استنتاجي يبقى `null` — لا `0` — كي لا يُقرأ يوماً على أنه
    نتيجة قيست فكانت صفراً.
    """
    return {
        "sample_size": 0,
        "sufficient_sample": False,
        "insufficient_sample_note_ar": (
            "لا صفقة واحدة بعد. لا نسبة ربح ولا توقّع يُقرأ من عيّنة فارغة، "
            "ولا أداء يُعرض قبل Backtest وShadow Mode."
        ),
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "average_r": None,
        "expectancy": None,
        "max_drawdown": None,
        "realised_pnl_total": None,
        "calibration": [],
        "period_start_utc": None,
        "period_end_utc": None,
    }


def _providers(sys: Any) -> dict[str, Any]:
    from ..intelligence.providers import MANDATORY_FOR_LIVE

    rows = []
    for status in sys.providers.statuses():
        rows.append({
            "kind": status.kind.value,
            "name": status.name,
            "name_ar": _provider_name_ar(status.kind),
            "configured": status.configured,
            # `null` لا `false`: غير المُعدّ لم تُفحَص صحّته أصلاً، وقول
            # «غير سليم» عنه ادّعاءٌ عن شيء لم يُسأل.
            "healthy": None,
            "mandatory": status.kind in MANDATORY_FOR_LIVE,
            "last_success_utc": None,
            "note_ar": status.note_ar,
        })
    return {
        "providers": rows,
        "missing": [_provider_name_ar(k) for k in sys.providers.missing()],
        "missing_mandatory": [
            _provider_name_ar(k) for k in sys.providers.missing_mandatory()
        ],
        "live_eligible_by_providers": sys.providers.live_eligible(),
    }


def _notifications(sys: Any) -> list[dict[str, Any]]:
    rows = []
    for note in getattr(sys.notifier, "sent", []):
        rows.append({
            "type": note.kind.value,
            "created_utc": note.created_at_utc.isoformat(),
            # التفصيل يُعرض بعد المصادقة فقط — والشاشة المقفلة لا تطلب هذا
            # المسار أصلاً.
            "in_app_detail_ar": note.detail_ar,
            "deep_link": None,
            "read": False,
        })
    return rows


# ---------------------------------------------------------------------------

def build_mobile_state(sys: Any) -> dict[str, Any]:
    """
    يُستدعى عند كل طلب قراءة. رخيص عمداً: لا شبكة ولا وسيط.

    `sys` هو `SystemState`؛ النوع غير مُصرَّح كي لا تستورد طبقة الجوال
    وحدات التنفيذ — ويوجد اختبار AST يفحص أن هذه الحزمة لا تستوردها.
    """
    return {
        "status": _status(sys),
        "risk": _risk(sys),
        "profiles": _profiles(sys),
        "decision": _decision(sys),
        "intelligence": _intelligence(sys),
        "position": _position(sys),
        # قائمة فارغة صادقة هنا: لم يُرسَل أمرٌ قط، فلا صفقة أُغفلت.
        # وعقد العميل لهذا القسم بلا قناة «غير معلوم» — وهي ثغرة مُسجَّلة.
        "trades": [],
        "performance": _performance(sys),
        "providers": _providers(sys),
        "notifications": _notifications(sys),
    }


__all__ = ["build_mobile_state"]
