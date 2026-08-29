"""
مصدر الحالة للجوال — يحوّل `SystemState` إلى الأقسام التي تقرأها الشاشات.

## قاعدة هذا الملف

**قسمٌ غير موصول يقول ذلك صراحةً**، ولا يعيد `{}`.

القاموس الفارغ يُقرأ في الواجهة «لا يوجد شيء»، وهو ادّعاء لا نملكه: الفرق
بين «لا صفقات» و«لم نسأل عن الصفقات» هو الفرق بين معلومة وجهل. فكل قسم غير
جاهز يحمل `available: false` وسبباً بالعربية تعرضه الشاشة كما هو.

وهذا امتداد للقاعدة نفسها في طبقة المزوّدين: قائمة فارغة لا تعني «لا
أحداث» إلا عند `FRESH`.

## ولا سرّ يمرّ

`assert_response_is_clean` تفحص كل استجابة قبل خروجها، لكن الحارس الحقيقي
هنا: لا يُقرأ من `SystemState` سوى حقول مُسمّاة صراحةً أدناه. لا تمرير
كائنٍ كامل، ولا `__dict__`، ولا `vars()`.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..clock import format_riyadh, now_utc, us_market_status


def _money(value: Decimal | None) -> str | None:
    return f"{value:.2f}" if value is not None else None


def _not_wired(reason_ar: str) -> dict[str, Any]:
    """قسم لم يُوصَل بعد. يقول ذلك بدل أن يتظاهر بالفراغ."""
    return {"available": False, "reason_ar": reason_ar}


def build_mobile_state(sys: Any) -> dict[str, Any]:
    """
    يُستدعى عند كل طلب قراءة. رخيص عمداً: لا شبكة ولا وسيط.

    `sys` هو `SystemState`؛ النوع غير مُصرَّح كي لا تستورد طبقة الجوال
    وحدات التنفيذ — ويوجد اختبار AST يفحص أن هذه الحزمة لا تستوردها.
    """
    market = us_market_status()
    health = sys.health()
    limits = sys.limits
    session = sys.session_state
    kill = sys.kill_switch

    status = {
        "available": True,
        "server_time_riyadh": format_riyadh(now_utc()),
        "market_open": market.is_open,
        "market_reason_ar": market.reason_ar,
        "broker_connected": health.broker_connected,
        "broker_name": sys.broker.name,
        "broker_is_live": sys.broker.is_live,
        "database_ok": health.database_ok,
        "audit_chain_ok": health.audit_chain_ok,
        "kill_switch_active": kill.is_active,
        "locally_paused": sys.locally_paused,
        # الثابت الذي تفحصه الواجهة عند كل استجابة.
        "authorises_execution": False,
    }

    risk = {
        "available": True,
        "kill_switch_active": kill.is_active,
        "max_risk_per_trade_usd": _money(limits.max_risk_per_trade),
        "daily_loss_limit_usd": _money(limits.daily_loss),
        "weekly_loss_limit_usd": _money(limits.weekly_loss),
        "hard_total_loss_usd": _money(limits.hard_total_loss),
        "daily_loss_used_usd": _money(session.day_loss),
        "weekly_loss_used_usd": _money(session.week_loss),
        "total_loss_used_usd": _money(session.total_loss),
        "note_ar": "الحدود تُفرَض على الخادم. الجوال يعرضها ولا يغيّرها.",
    }

    manager = sys.profiles
    pending = manager.pending_upgrade
    remaining = manager.cooling_remaining()
    profiles = {
        "available": True,
        "effective": manager.effective_profile.value,
        "selected": manager.selected_profile.value,
        # الترقية المعلَّقة تُعرَض ولا تُفعَّل من الجوال: التفعيل قرار منفصل
        # بعد انقضاء التبريد وإعادة فحص الشروط، والفحص على الخادم.
        "pending_upgrade": pending.target.value if pending else None,
        "cooling_remaining_seconds": (
            int(remaining.total_seconds()) if remaining is not None else None
        ),
        "changeable_from_mobile": False,
        "note_ar": (
            "الملف يغيّر الحجم والتواتر فقط. لا يخفّف بوابة تحليل واحدة، "
            "ولا يعيد ضبط أي عدّاد."
        ),
    }

    return {
        "status": status,
        "risk": risk,
        "profiles": profiles,
        "decision": _not_wired(
            "لا قرار بعد: لا استراتيجية معتمدة، والخط يتوقف عند "
            "STRATEGY_NOT_APPROVED."
        ),
        "intelligence": _not_wired(
            "خط الاستخبارات لم يُشغَّل في هذه الجلسة."
        ),
        "position": _not_wired("لا تتبّع مراكز — الحساب غير مموَّل ولا صفقة."),
        "trades": [],
        "performance": _not_wired(
            "لا أداء يُعرض قبل Backtest وShadow Mode. الفراغ هنا ليس صفراً."
        ),
        "providers": _not_wired(
            "عقود المزوّدين غير مُتحقَّقة بعد (CONTRACT_VERIFIED = False)."
        ),
        "notifications": [],
    }


__all__ = ["build_mobile_state"]
