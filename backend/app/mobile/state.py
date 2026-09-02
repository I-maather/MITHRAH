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


def _price(value: Any) -> str | None:
    """
    سعرٌ لا مبلغ — **بكامل خاناته**.

    `_money` يقرّب إلى منزلتين لأنه للمبالغ بالدولار. واستعمالُه على سعر صرف
    يحوّل `1.10105` إلى `"1.10"`: خمس خانات تصير اثنتين، فتُرسم الشموع كلها
    على مستوىً واحد ويختفي التحرّك تماماً.

    وهو نفس صنف الخطأ الذي طاردناه اليوم في `stopDistance`: **مقياسٌ صحيح في
    مكانه، مستعملٌ في غير مكانه.**
    """
    if value is None:
        return None
    return format(value, "f") if isinstance(value, Decimal) else str(value)


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
        # ---------------------------------------------------------------
        # **حالةُ السوق تُقرأ من الوسيط لكل أداة — لا ساعاتُ الفوركس للكلّ.**
        #
        # أُصلح هذا في بوّابة الأهلية، ولم يُصلَح في **الشاشة التي تنظر
        # إليها المالكة**. فبينما يرفض المحرّك الذهب بـ`MARKET_CLOSED`
        # لأن الوسيط يقول `CLOSED`، تقول اللوحة «سوق الفوركس مفتوح».
        #
        # وقد وقع ذلك فعلاً: 21:21 UTC أربعاء — الفوركس مفتوح والذهب في
        # استراحته اليومية عند إقفال شيكاغو.
        #
        # فتُذكر ساعاتُ الفوركس بوصفها ما هي، وتُذكر معها حالةُ كل أداةٍ
        # كما أعلنها الوسيط. والشاشة تعرض الاثنتين ولا تخلطهما.
        # ---------------------------------------------------------------
        "market": {
            "is_open": market.is_open,
            "reason_ar": market.reason_ar,
            "scope_ar": "ساعات الفوركس — ولكل أداةٍ حالتُها أدناه.",
            "per_instrument": _instrument_market_status(sys),
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


def _instrument_market_status(sys: Any) -> list[dict[str, Any]]:
    """
    حالةُ كل أداةٍ **كما أعلنها الوسيط**، لا كما تستنتجها ساعاتنا.

    وما لم يُعلنه الوسيط يُقال «غير معلومة» — لا يُملأ بحالة الفوركس، لأن
    ملأه بها هو العطب نفسه في صورةٍ أهدأ.
    """
    rows: list[dict[str, Any]] = []
    for symbol in sorted(getattr(sys.limits, "allowed_instruments", ()) or ()):
        declared = None
        try:
            details = sys.broker.get_instrument_details(symbol)
            declared = getattr(details, "market_status", None)
        except Exception:  # noqa: BLE001
            declared = None
        rows.append({
            "symbol": symbol,
            "status": declared,
            "tradable": None if declared is None else declared.upper() == "TRADEABLE",
            "reason_ar": (
                "الوسيط لم يُعلن حالتها — لا تُملأ بحالة الفوركس."
                if declared is None
                else f"الوسيط يقول: {declared}"
            ),
        })
    return rows


def _risk(sys: Any) -> dict[str, Any]:
    from ..profiles import ProfileLimits

    session = sys.session_state
    profile = sys.profiles.effective_profile
    spec = ProfileLimits.for_profile(profile, session.current_equity)

    # ---------------------------------------------------------------------
    # **الأرقام المعروضة هي التي يُنفّذها المحرّك.**
    #
    # كانت هذه الشاشة تعرض حدود **الملف** (`ProfileLimits`)، والمحرّك ينفّذ
    # حدود **الدستور** (`sys.limits`) — و`ProfileLimits` لا تُستدعى في مسار
    # القرار إطلاقاً، فقط هنا وفي التحليل. فكان المعروض عند مرجع 300 دولار:
    # 0.75 لليوم، والمُنفَّذ 6.00 — **أشدّ ثماني مرّاتٍ مما يُنفَّذ**.
    #
    # وشاشةٌ تعد بحدٍّ أشدّ من الحدّ العامل ليست تحفّظاً، هي طمأنينةٌ كاذبة:
    # تُقرأ فيُظنّ أن خسارةً واحدة تُنهي اليوم، والمحرّك يسمح بثمانٍ. وهو
    # الشكل العاشر من العيب الحاكم: قيمةٌ تُعرَض لم تُقرأ من مصدر تنفيذها.
    #
    # فالمصدر الآن هو `sys.limits` وحده، ويُرافقه `profile_binding_ar` يقول
    # صراحةً أيّ الحدّين يعمل. وسريانُ حدود الملف قرارٌ معلّق عند المالكة —
    # ولا يُدّعى قبل أن يقع.
    # ---------------------------------------------------------------------
    limits = sys.limits
    equity = session.current_equity
    enforced_per_trade = limits.effective_max_risk(equity)
    enforced_daily = limits.daily_loss
    enforced_weekly = limits.weekly_loss
    enforced_boundary = limits.hard_total_loss

    remaining_day = max(Decimal("0"), enforced_daily - session.day_loss)
    remaining_week = max(Decimal("0"), enforced_weekly - session.week_loss)
    to_boundary = max(Decimal("0"), enforced_boundary - session.total_loss)

    profile_is_tighter = (
        spec.max_risk_per_trade < enforced_per_trade
        or spec.max_daily_loss < enforced_daily
        or spec.max_weekly_loss < enforced_weekly
    )
    profile_binding_ar = (
        f"الأرقام هنا هي التي ينفّذها المحرّك. حدود ملفك «{spec.name_ar}» أشدّ "
        f"({spec.max_risk_per_trade:.2f} للصفقة و{spec.max_daily_loss:.2f} لليوم) "
        "ولا تُنفَّذ بعد — سريانها قرارٌ معلّق."
        if profile_is_tighter
        else f"الأرقام هنا هي التي ينفّذها المحرّك، وحدود ملفك «{spec.name_ar}» ليست أشدّ منها."
    )

    return {
        "profile": profile.value,
        "profile_name_ar": spec.name_ar,
        "currency": "USD",
        "profile_binding_ar": profile_binding_ar,
        "equity_used": _money(equity),
        "risk_used_today": _money(session.day_loss),
        "risk_remaining_today": _money(remaining_day),
        "risk_used_week": _money(session.week_loss),
        "risk_remaining_week": _money(remaining_week),
        "max_risk_per_trade": _money(enforced_per_trade),
        "max_daily_loss": _money(enforced_daily),
        "max_weekly_loss": _money(enforced_weekly),
        "operational_drawdown_stop": _money(limits.effective_drawdown_stop()),
        "absolute_loss_boundary": _money(enforced_boundary),
        "distance_to_kill_switch": _money(to_boundary),
        "open_positions": session.open_positions,
        "max_open_positions": limits.max_open_positions,
        "entry_orders_today": session.entry_orders_today,
        "max_entry_orders_per_day": limits.max_entry_orders_per_day,
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

#: أسبابٌ مصدرها عطلٌ عندنا لا حالةُ سوق. تُميَّز في العرض لأن الأولى
#: تحتاج يداً والثانية عملُ النظام الطبيعي — وخلطهما يرسل المالكة إلى
#: المكان الخطأ تماماً.
_NEEDS_A_HAND = frozenset({
    "INSUFFICIENT_BARS", "BROKER_UNREACHABLE", "MARKET_DATA_STALE",
    "CALENDAR_UNCONFIRMED", "NO_INSTRUMENT",
})


def _scan(sys: Any) -> dict[str, Any]:
    """
    **ماذا رأى النظام في السوق كلّه** — لا ماذا قرّر في أداة واحدة.

    ## لماذا هذه الشاشة أهمّ ما في التطبيق

    بحث المنافسين في هذا المشروع وجد الفراغ الوظيفي بنفسه: لا شاشة في ٦٩
    لقطة تقول «لماذا لم أتداول». ثم بنينا تطبيقاً يقول «لا تداول: رمزٌ ما»
    — وهي حقيقة، وليست جواباً.

    الجواب: أيّ أداة نُظِرت، وماذا وُجد فيها، وأيّها اقترب. وذلك محفوظٌ في
    `last_scan` منذ صار المسح يمرّ على الأدوات كلّها — **ولم تكن أي شاشة
    تعرضه**. أثمنُ ما في النظام موجودٌ في الذاكرة ولا يصل إلى صاحبته.

    ولا يُختلق ترتيبٌ ولا «قُرب»: تُعرض النتائج كما وقعت، ويُفصل ما يحتاج
    يداً عمّا هو عملٌ طبيعي.
    """
    scan = list(getattr(sys, "last_scan", []) or [])
    instruments = []
    for symbol, result in scan:
        code = getattr(result, "reason_code", None)
        instruments.append({
            "symbol": symbol,
            "decision": getattr(getattr(result, "decision", None), "value", None),
            "reason_code": code,
            "reason_ar": getattr(result, "reason_ar", "") or None,
            "stage": getattr(result, "stage", None),
            "needs_a_hand": bool(code and code in _NEEDS_A_HAND),
            # **الشروط بالأرقام.** كان السبب جملةً واحدة («لا فرصة مطابقة»)
            # هي نفسها سواء كان ADX عند 24.9 أو عند 8. وهذه القائمة هي
            # الفرق بين «انتظري» و«الاستراتيجية لا تناسب هذا السوق».
            "strategies": [
                {
                    "key": key,
                    "summary_ar": getattr(a, "summary_ar", ""),
                    "checks": [
                        {
                            "name_ar": c.name_ar,
                            "passed": bool(c.passed),
                            "detail_ar": c.detail_ar,
                        }
                        for c in getattr(a, "checks", ()) or ()
                    ],
                }
                for key, a in (getattr(result, "assessments", ()) or ())
            ],
        })
    faults = [i for i in instruments if i["needs_a_hand"]]
    return {
        "instruments": instruments,
        "scanned": len(instruments),
        "faults": len(faults),
        # جملةٌ واحدة تُقرأ في ثانية. وتُبنى من العدّ لا من التفسير.
        "summary_ar": (
            "لم تبدأ دورة مسحٍ بعد."
            if not instruments
            else (
                f"نُظِر في {len(instruments)} أداة، "
                + (f"و{len(faults)} منها لم تُقرأ بياناتها."
                   if faults else "ولم تكتمل شروط الدخول في أيٍّ منها.")
            )
        ),
    }


#: ترتيب الأطر من الأطول إلى الأقصر — للعرض، كي لا يختلف ترتيبها بين نداءٍ
#: وآخر بحسب ما جُلب أوّلاً.
CHART_RESOLUTION_ORDER: tuple[str, ...] = (
    "DAY", "HOUR_4", "HOUR", "MINUTE_30", "MINUTE_15",
)


def _candles(sys: Any) -> dict[str, Any]:
    """
    الشموع كما رآها النظام — **من الذاكرة لا من الشبكة**.

    ## لماذا من الذاكرة

    بناء حالة الجوال يُستدعى عند **كل طلب قراءة**. وجلبُ شموعٍ فيه يحوّل
    تصفّحاً عادياً إلى عشرات النداءات على الوسيط، فتُستهلَك حدوده ويُحرَم
    منها القرار نفسه. فالشموع تُحفَظ في دورة المسح وتُقرأ هنا.

    ⇒ وهذا يعني أن ما تراه المالكة هو **الصورة التي رآها النظام حين قرّر**،
    لا صورةً أحدث منها. وذلك أصدق: شمعةٌ أحدث من القرار تجعل السبب المكتوب
    يبدو خاطئاً وهو صحيح على بياناته.

    ## وما لا يُرسَل

    لا مؤشرات محسوبة: حسابُها هنا يعني تنفيذاً ثانياً لمنطق الاستراتيجية،
    فتختلف الشاشة عن القرار في العدد نفسه. والشاشة ترسم السعر ومستويات
    المركز، والباقي يأتي من `scan/latest` بنصّه.
    """
    def rows_of(bars) -> list[dict[str, Any]]:
        return [
            {
                "t": _iso(getattr(bar, "start_utc", None)),
                "o": _price(getattr(bar, "open", None)),
                "h": _price(getattr(bar, "high", None)),
                "l": _price(getattr(bar, "low", None)),
                "c": _price(getattr(bar, "close", None)),
            }
            for bar in bars
        ]

    decision_resolution = str(getattr(sys, "candle_resolution", "DAY"))
    charts = dict(getattr(sys, "chart_bars", {}) or {})
    decided = dict(getattr(sys, "last_bars", {}) or {})

    instruments: dict[str, Any] = {}
    for symbol in sorted(set(charts) | set(decided)):
        per_resolution: dict[str, Any] = {}
        for resolution, bars in (charts.get(symbol) or {}).items():
            per_resolution[str(resolution)] = rows_of(bars)
        # إطار القرار يُضاف من `last_bars` إن لم يكن قد جُلب للرسم بعد:
        # الرسم يتحدّث كل عشر دقائق، والقرار كل دقيقة — فأوّل دقائق التشغيل
        # يكون إطار القرار وحده موجوداً، ولا يصحّ أن تُرى الشاشة فارغة.
        if decision_resolution not in per_resolution and symbol in decided:
            per_resolution[decision_resolution] = rows_of(decided[symbol])
        if per_resolution:
            instruments[symbol] = per_resolution

    resolutions = sorted(
        {r for per in instruments.values() for r in per},
        key=lambda r: CHART_RESOLUTION_ORDER.index(r) if r in CHART_RESOLUTION_ORDER else 99,
    )

    position = _position(sys)
    return {
        "instruments": instruments,
        "symbols": sorted(instruments),
        "resolutions": resolutions,
        # الإطار الذي يُقاس عليه القرار — يُميَّز في الشاشة عن أطر العرض.
        "decision_resolution": decision_resolution,
        "levels": {
            # مستويات المركز المفتوح — تُرسَم على السعر. و`None` تعني
            # «لا مركز»، لا «صفر».
            "symbol": position.get("instrument"),
            "entry": position.get("entry_price"),
            "stop": position.get("stop_price"),
            "target": position.get("take_profit_price"),
        },
        "note_ar": (
            "لم تُقرأ شموعٌ بعد — دورة المسح لم تكتمل."
            if not instruments
            else (
                "الشموع كما رآها النظام، لا أحدث منها. "
                f"والقرار يُقاس على إطار {decision_resolution} وحده — "
                "وقيدُ الوسيط يمنع التداول على ما دونه."
            )
        ),
    }


class _LazySections(dict):
    """
    أقسام الحالة **تُبنى عند الطلب لا كلّها في كل نداء**.

    ## لماذا

    `build_mobile_state` يُستدعى عند **كل** طلب قراءة، وكان يبني الأقسام
    الاثني عشر كلّها ثم يُرمى أحد عشر منها. وكان ذلك محتملاً حين كان قسم
    الشموع إطاراً واحداً؛ ولمّا صار خمسة أطر لثلاث أدوات، صار كل استعلام
    عن الحالة يحمل مئات الشموع التي لم تُطلَب.

    وهذا القاموس يحفظ **دوالّ** لا قيماً، ويستدعي الدالّة عند أوّل قراءةٍ
    لمفتاحها ويحفظ ناتجها. فالسلوك من الخارج قاموسٌ عادي (`.get`, `[]`,
    `in`) — ولا تتغيّر طبقة الـAPI حرفاً.
    """

    def __init__(self, builders: dict[str, Any]) -> None:
        super().__init__()
        self._builders = builders
        self._built: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        if key not in self._built:
            if key not in self._builders:
                raise KeyError(key)
            self._built[key] = self._builders[key]()
        return self._built[key]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        return key in self._builders

    def keys(self):  # noqa: D102
        return self._builders.keys()

    def __iter__(self):
        return iter(self._builders)

    def __len__(self) -> int:
        return len(self._builders)

    def materialise(self) -> dict[str, Any]:
        """كل الأقسام مبنيّة — للعقد والاختبارات، لا لمسار الطلب."""
        return {key: self[key] for key in self._builders}


def build_mobile_state(sys: Any) -> Any:
    """
    يُستدعى عند كل طلب قراءة. رخيص عمداً: لا شبكة ولا وسيط.

    والأقسام **كسولة**: يُبنى منها ما يُقرأ فقط. انظري `_LazySections`.

    `sys` هو `SystemState`؛ النوع غير مُصرَّح كي لا تستورد طبقة الجوال
    وحدات التنفيذ — ويوجد اختبار AST يفحص أن هذه الحزمة لا تستوردها.
    """
    return _LazySections({
        "status": lambda: _status(sys),
        "risk": lambda: _risk(sys),
        "profiles": lambda: _profiles(sys),
        "decision": lambda: _decision(sys),
        "intelligence": lambda: _intelligence(sys),
        "position": lambda: _position(sys),
        # قائمة فارغة صادقة هنا: لم يُرسَل أمرٌ قط، فلا صفقة أُغفلت.
        "trades": lambda: [],
        "performance": lambda: _performance(sys),
        "providers": lambda: _providers(sys),
        "scan": lambda: _scan(sys),
        "candles": lambda: _candles(sys),
        "notifications": lambda: _notifications(sys),
    })


__all__ = ["build_mobile_state"]
