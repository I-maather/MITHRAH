"""
قمعُ الفرص — من المسح إلى المطابقة، **بالأرقام لا بالجملة**.

## السؤال الذي يجيبه

«لماذا لم يتداول اليوم؟» — وهو سؤالٌ لم يكن في النظام ما يجيبه إلا بجملة
واحدة: «لا فرصة مطابقة». وهي نفسها سواء كان السبب أن السوق مغلق، أو أن
الاستراتيجية لم تُشِر، أو أن كل إشاراتها رُفضت عند حدٍّ خاطئ.

وقد كلّف ذلك أربعة أيام: كان النظام يولّد ٤٨٦ إشارة ويرفضها كلّها عند
بوابةٍ واحدة، والشاشة تقول «لا فرصة». والفرق بين «لا فرصة» و«٤٨٦ فرصة
رُفضت كلها في بوابةٍ واحدة» هو الفرق بين انتظارٍ وعطل.

## من أين تُقرأ الأرقام

**من سجلّ التدقيق نفسه، لا من عدّادات موازية.**

عدّادٌ ثانٍ للحقيقة نفسها هو العيب الحاكم في المشروع: طرفان يوافق كلٌّ
منهما نفسه ويختلفان بصمت. والسجلّ مسلسلٌ ومربوطٌ بالتجزئة، فهو المصدر
الوحيد — والقمع **اشتقاقٌ منه** لا سجلٌّ موازٍ.

## المراحل بالترتيب

    مسح ← أهلية ← إعداد ← إشارة ← اقتصاديات الأداة ← بوابة المخاطر
        ← نيّة ← إرسال ← تأكيد الوسيط ← تنفيذ ← حماية ← إغلاق ← مطابقة

وكلُّ سقوطٍ بين مرحلتين يُنسَب إلى **رمزه** لا إلى «لا صفقة».
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Iterable, Optional, Sequence

#: المراحل بالترتيب الذي يمرّ به الخط. الترتيب جزءٌ من المعنى: أوّل مرحلةٍ
#: ينهار عندها العدد هي موضع التشخيص.
STAGES: tuple[str, ...] = (
    "scans",
    "eligible",
    "assessed",
    "signals",
    "instrument_economics_ok",
    "risk_approved",
    "intents",
    "submitted",
    "acknowledged",
    "filled",
    "reconciled",
)

#: **مرحلتان لا تُشتقّان من السجلّ**: الحماية والإغلاق يُقرآن من جدول
#: الصفقات والمراكز، لا من الأحداث. وإدراجُهما هنا بصفر كان يجعل يوماً
#: نُفِّذت فيه صفقةٌ يبدو منهاراً عند «مراكز محميّة» — صفرٌ لأنه لم يُقَس،
#: لا لأنه وقع صفراً. والفرق بينهما هو الفرق بين تشخيصٍ وتضليل.
STAGES_FROM_TRADES: tuple[str, ...] = ("protected", "closed")

#: تصنيفُ موضع الانهيار إلى الجهة المسؤولة — وهو ما تطلبه المالكة صراحةً:
#: «هل الخلل في السوق أو الاستراتيجية أو المخاطر أو البيانات أو التنفيذ؟»
STAGE_OWNER: dict[str, str] = {
    "scans": "MARKET",
    "eligible": "DATA",
    "assessed": "STRATEGY",
    "signals": "STRATEGY",
    "instrument_economics_ok": "DATA",
    "risk_approved": "RISK",
    "intents": "EXECUTION",
    "submitted": "EXECUTION",
    "acknowledged": "EXECUTION",
    "filled": "EXECUTION",
    "reconciled": "EXECUTION",
}

STAGE_LABEL_AR: dict[str, str] = {
    "scans": "مسح",
    "eligible": "أدوات مؤهَّلة",
    "assessed": "استراتيجيات شُغّلت",
    "signals": "إشارات",
    "instrument_economics_ok": "اقتصاديات الأداة",
    "risk_approved": "موافقات المخاطر",
    "intents": "نيّات أوامر",
    "submitted": "أوامر مُرسَلة",
    "acknowledged": "تأكيدات الوسيط",
    "filled": "تنفيذات",
    "protected": "مراكز محميّة",
    "closed": "مراكز مغلقة",
    "reconciled": "مطابقات",
}

OWNER_LABEL_AR: dict[str, str] = {
    "MARKET": "السوق",
    "DATA": "البيانات أو مواصفات الأداة",
    "STRATEGY": "الاستراتيجية",
    "RISK": "سياسة المخاطر",
    "EXECUTION": "التنفيذ أو الوسيط",
    "OWNER": "قرار المالكة",
    "NONE": "لا انهيار — وقعت صفقة",
}


def _day_of(event) -> str:
    ts = getattr(event, "timestamp_utc", None)
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc).date().isoformat()
    return ""


@dataclass(frozen=True)
class DayFunnel:
    """قمعُ يومٍ واحد. كل عددٍ مشتقٌّ من أحداث السجلّ لذلك اليوم."""

    trading_day: str
    counts: dict[str, int]
    #: أسباب السقوط عند كل مرحلة: {المرحلة: {الرمز: العدد}}
    rejections: dict[str, dict[str, int]]
    #: أدواتٌ رُفضت لسببٍ يخصّها وحدها (عزلٌ لا توقّف).
    isolated_instruments: dict[str, str]
    owner_paused: bool
    kill_switch_active: bool
    market_closed_events: int

    # ------------------------------------------------------------------
    @property
    def strategy_trades(self) -> int:
        """الصفقات التي بلغت التنفيذ. لا تُحسب صفقات التشغيل هنا."""
        return self.counts.get("filled", 0)

    @property
    def collapse_stage(self) -> Optional[str]:
        """
        **أوّل مرحلةٍ نزل عندها العدد إلى صفر بعد أن كان موجباً قبلها.**

        وهي موضع التشخيص. ولو لم ينهر شيء (وقعت صفقة) تعود `None`.
        """
        previous = None
        for stage in STAGES:
            value = self.counts.get(stage, 0)
            if value == 0 and previous is not None and previous > 0:
                return stage
            if value > 0:
                previous = value
        return None

    @property
    def blamed_on(self) -> str:
        if self.owner_paused:
            return "OWNER"
        stage = self.collapse_stage
        if stage is None:
            return "NONE"
        return STAGE_OWNER.get(stage, "EXECUTION")

    def top_reasons(self, limit: int = 5) -> list[tuple[str, int]]:
        merged: Counter = Counter()
        for stage_reasons in self.rejections.values():
            merged.update(stage_reasons)
        return merged.most_common(limit)

    def as_dict(self) -> dict:
        return {
            "trading_day": self.trading_day,
            "counts": dict(self.counts),
            "rejections": {k: dict(v) for k, v in self.rejections.items()},
            "isolated_instruments": dict(self.isolated_instruments),
            "owner_paused": self.owner_paused,
            "kill_switch_active": self.kill_switch_active,
            "market_closed_events": self.market_closed_events,
            "collapse_stage": self.collapse_stage,
            "blamed_on": self.blamed_on,
            "blamed_on_ar": OWNER_LABEL_AR.get(self.blamed_on, self.blamed_on),
            "strategy_trades": self.strategy_trades,
        }


#: رموزٌ تعني «هذه الأداة وحدها» لا «النظام». عزلُ أداةٍ ليس توقّف نظام —
#: وخلطُهما جعل عطل تحويل عملة الين يُقرأ توقّفاً عاماً.
INSTRUMENT_SCOPED = {
    "CONVERSION_COST_UNMEASURED",
    "INSTRUMENT_ECONOMICS_UNMEASURED",
    "INSTRUMENT_SPEC_UNRESOLVED",
    "STOP_DISTANCE_UNKNOWN",
    "DATA_NOT_TRADABLE",
    "NOT_IN_CFD_ALLOWLIST",
    "EXPLICITLY_DENIED",
    "NOT_IN_ALLOWLIST",
}


def funnel_for_day(events: Iterable, trading_day: str) -> DayFunnel:
    """يبني قمع يومٍ واحد من أحداث السجلّ."""
    counts: Counter = Counter()
    rejections: dict[str, Counter] = {stage: Counter() for stage in STAGES}
    isolated: dict[str, str] = {}
    owner_paused = False
    kill_active = False
    market_closed = 0

    for event in events:
        if _day_of(event) != trading_day:
            continue
        action = getattr(event, "action", "")
        decision = getattr(event, "decision", "") or ""
        source = getattr(event, "source", "") or ""
        reason = getattr(event, "reason_ar", "") or ""

        if action == "PIPELINE_RUN":
            counts["scans"] += 1
        elif action == "ELIGIBILITY_DECISION":
            if decision == "ELIGIBLE":
                counts["eligible"] += 1
            else:
                rejections["eligible"][decision] += 1
                if decision == "MARKET_CLOSED":
                    market_closed += 1
                if decision in INSTRUMENT_SCOPED:
                    symbol = reason.split(":")[0].strip().split(" ")[0]
                    if symbol:
                        isolated.setdefault(symbol, decision)
        elif action == "SIGNAL_GENERATED":
            counts["signals"] += 1
            counts["assessed"] += 1
        elif action == "NO_TRADE":
            if source == "strategy":
                counts["assessed"] += 1
                rejections["signals"][decision or "NO_SETUP"] += 1
            elif source.startswith("Pipeline.cfd_review"):
                rejections["instrument_economics_ok"][decision or "CFD_ECONOMICS"] += 1
            else:
                rejections["risk_approved"][decision or "NO_TRADE"] += 1
        elif action == "RISK_DECISION":
            if decision == "TRADE":
                counts["risk_approved"] += 1
                counts["instrument_economics_ok"] += 1
            else:
                rejections["risk_approved"][decision or "REJECTED"] += 1
        elif action == "ORDER_INTENT_CREATED":
            counts["intents"] += 1
        elif action == "ORDER_SUBMITTED":
            counts["submitted"] += 1
        elif action == "ORDER_CONFIRMED":
            counts["acknowledged"] += 1
        elif action in {"ORDER_REJECTED", "ORDER_TIMEOUT"}:
            rejections["acknowledged"][decision or action] += 1
        elif action == "EXECUTION_RECORDED":
            counts["filled"] += 1
        elif action == "RECONCILIATION":
            if decision and decision.upper().startswith("MISMATCH"):
                rejections["reconciled"][decision] += 1
            else:
                counts["reconciled"] += 1
        elif action == "KILL_SWITCH_TRIGGERED":
            kill_active = True
        elif action == "CONFIG_CHANGE":
            if decision in {"LOCAL_PAUSE", "LOCAL_PAUSE_RESTORED"}:
                owner_paused = True
            elif decision in {"LOCAL_RESUME", "LOCAL_RESUME_RESTORED"}:
                owner_paused = False
            elif decision == "TIMEFRAME_MISMATCH":
                rejections["assessed"]["TIMEFRAME_MISMATCH"] += 1

    return DayFunnel(
        trading_day=trading_day,
        counts=dict(counts),
        rejections={k: dict(v) for k, v in rejections.items() if v},
        isolated_instruments=isolated,
        owner_paused=owner_paused,
        kill_switch_active=kill_active,
        market_closed_events=market_closed,
    )


def days_present(events: Iterable) -> list[str]:
    """أيامُ السجلّ بالترتيب."""
    seen: dict[str, None] = {}
    for event in events:
        day = _day_of(event)
        if day:
            seen.setdefault(day, None)
    return sorted(seen)


__all__ = [
    "STAGES",
    "STAGE_OWNER",
    "STAGE_LABEL_AR",
    "OWNER_LABEL_AR",
    "INSTRUMENT_SCOPED",
    "DayFunnel",
    "funnel_for_day",
    "days_present",
]
