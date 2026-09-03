"""
هدفُ المشاركة اليومية — **صفقةٌ استراتيجية مكتملة واحدة على الأقل في كل
يوم تداولٍ مؤهَّل.**

## ما هو اليوم المؤهَّل

يومٌ اجتمع فيه أربعة:

1. **السوق مفتوح** فيه ولو جزئياً (يُقاس من محاولات المسح لا من تقويم).
2. **الوسيط والبيانات والتكاملات سليمة** — دارت الحلقة وبلغت أهليةً
   واحدة على الأقل.
3. **لم تُبلَغ حدود الخسارة ولا التراجع** — لا قاطع طوارئ مفعَّل.
4. **لم توقفه المالكة** بقرارها.

والرابع ليس عيباً في النظام، ولذلك يُخرَج من المقام ويُقال بالاسم بدل أن
يُحسَب فشلاً في المشاركة.

## ما لا يُحسَب صفقةً استراتيجية

صفقات التشغيل (`Commissioning`)، والاختبارات، والصفقات اليدوية. وهي
تُميَّز باسم الاستراتيجية: ما ليس له اسم استراتيجيةٍ مسجَّلة ليس صفقةً
استراتيجية.

## وما لا يعد به هذا الملف

**لا يَعِد بصفقةٍ كل يوم.** يقيس ما وقع، ويقيس ما تستطيعه الاستراتيجيات
(من مسح التاريخ)، ويقول الفجوة بينهما. والوعد قبل الدليل هو ما جعل
المشروع يبني بنيةَ إطلاقٍ فوق حافّةٍ غير مقيسة.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from .funnel import (
    OWNER_LABEL_AR,
    STAGE_LABEL_AR,
    DayFunnel,
    days_present,
    funnel_for_day,
)


@dataclass(frozen=True)
class DayOutcome:
    funnel: DayFunnel
    eligible: bool
    not_eligible_because: str
    strategy_trades_filled: int
    strategy_trades_closed: int
    #: صافي الصفقات **المغلقة وحدها**. ربحٌ غير محقَّق ليس نتيجة.
    closed_net_pnl: Decimal

    @property
    def participated(self) -> bool:
        return self.strategy_trades_filled > 0

    def as_dict(self) -> dict:
        return {
            **self.funnel.as_dict(),
            "eligible": self.eligible,
            "not_eligible_because": self.not_eligible_because,
            "strategy_trades_filled": self.strategy_trades_filled,
            "strategy_trades_closed": self.strategy_trades_closed,
            "closed_net_pnl": str(self.closed_net_pnl),
            "participated": self.participated,
        }


def _eligibility(funnel: DayFunnel) -> tuple[bool, str]:
    if funnel.counts.get("scans", 0) == 0:
        return False, "NO_DECISION_CYCLE_RAN"
    if funnel.owner_paused:
        return False, "OWNER_PAUSED"
    if funnel.kill_switch_active:
        return False, "KILL_SWITCH_ACTIVE"
    if funnel.counts.get("eligible", 0) == 0:
        # لا أداة مؤهَّلة طوال اليوم: سوقٌ مغلق أو بياناتٌ معطّلة.
        reasons = funnel.rejections.get("eligible", {})
        if reasons.get("MARKET_CLOSED"):
            return False, "MARKET_CLOSED"
        return False, "NO_ELIGIBLE_INSTRUMENT"
    return True, ""


def build_day(
    events: Iterable,
    trading_day: str,
    *,
    trades: Sequence = (),
) -> DayOutcome:
    """
    يبني نتيجة يومٍ واحد.

    `trades` صفوفُ `TradeRow` لذلك اليوم — تُمرَّر من الاستدعاء كي يبقى
    هذا الملف بلا اعتماد على قاعدة البيانات، فيُختبَر بلا خادم.
    """
    funnel = funnel_for_day(events, trading_day)
    eligible, because = _eligibility(funnel)
    strategy_rows = [t for t in trades if _is_strategy_trade(t)]
    filled = len(strategy_rows)
    closed_rows = [t for t in strategy_rows if getattr(t, "closed_at_utc", None)]
    closed = len(closed_rows)
    net = sum(
        (Decimal(str(getattr(t, "net_pnl", 0) or 0)) for t in closed_rows), Decimal("0")
    )
    return DayOutcome(
        funnel=funnel,
        eligible=eligible,
        not_eligible_because=because,
        strategy_trades_filled=filled,
        strategy_trades_closed=closed,
        closed_net_pnl=net,
    )


#: أسماءٌ تدلّ على أن الصفقة **ليست** استراتيجية.
NON_STRATEGY_MARKERS = ("COMMISSION", "MANUAL", "TEST", "SMOKE", "DIAGNOSTIC")


def _is_strategy_trade(trade) -> bool:
    name = (getattr(trade, "strategy_name", "") or "").upper()
    if not name:
        return False
    return not any(marker in name for marker in NON_STRATEGY_MARKERS)


@dataclass(frozen=True)
class ParticipationReport:
    days: tuple[DayOutcome, ...]

    # ------------------------------------------------------------------
    @property
    def eligible_days(self) -> tuple[DayOutcome, ...]:
        return tuple(d for d in self.days if d.eligible)

    @property
    def eligible_trading_days(self) -> int:
        return len(self.eligible_days)

    @property
    def days_with_strategy_trades(self) -> int:
        return len([d for d in self.eligible_days if d.participated])

    @property
    def daily_participation_rate(self) -> Optional[float]:
        if not self.eligible_days:
            return None
        return self.days_with_strategy_trades / len(self.eligible_days)

    @property
    def avg_qualified_signals_per_day(self) -> Optional[float]:
        if not self.eligible_days:
            return None
        total = sum(d.funnel.counts.get("signals", 0) for d in self.eligible_days)
        return total / len(self.eligible_days)

    @property
    def filled_strategy_trades_per_day(self) -> Optional[float]:
        if not self.eligible_days:
            return None
        total = sum(d.strategy_trades_filled for d in self.eligible_days)
        return total / len(self.eligible_days)

    @property
    def closed_strategy_trades(self) -> int:
        return sum(d.strategy_trades_closed for d in self.days)

    @property
    def net_expectancy_after_costs(self) -> Optional[Decimal]:
        """
        **صافي التوقّع لكل صفقة مغلقة** — بعد كل التكاليف، لأن `net_pnl`
        محسوبٌ بعدها. ولا يُحسَب من صفقاتٍ مفتوحة: ربحٌ غير محقَّق ليس نتيجة.

        و`None` حين لا صفقة مغلقة — لا صفر. الصفر رقمٌ يُقرأ «لا ربح ولا
        خسارة»، والحقيقة «لا عيّنة».
        """
        count = self.closed_strategy_trades
        if count == 0:
            return None
        total = sum((d.closed_net_pnl for d in self.days), Decimal("0"))
        return total / Decimal(count)

    def rejection_funnel(self) -> dict[str, dict[str, int]]:
        merged: dict[str, dict[str, int]] = {}
        for day in self.days:
            for stage, reasons in day.funnel.rejections.items():
                bucket = merged.setdefault(stage, {})
                for code, count in reasons.items():
                    bucket[code] = bucket.get(code, 0) + count
        return merged

    def no_trade_reasons(self) -> dict[str, int]:
        """توزيعُ سبب كل يومٍ مؤهَّل انتهى بلا صفقة — سببٌ واحد لكل يوم."""
        out: dict[str, int] = {}
        for day in self.eligible_days:
            if day.participated:
                continue
            key = day.funnel.blamed_on
            out[key] = out.get(key, 0) + 1
        return out

    def stage_totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for day in self.days:
            for stage, value in day.funnel.counts.items():
                out[stage] = out.get(stage, 0) + value
        return out

    def as_dict(self) -> dict:
        rate = self.daily_participation_rate
        return {
            "eligible_trading_days": self.eligible_trading_days,
            "days_with_strategy_trades": self.days_with_strategy_trades,
            "daily_participation_rate": None if rate is None else round(rate, 4),
            "avg_qualified_signals_per_day": (
                None if self.avg_qualified_signals_per_day is None
                else round(self.avg_qualified_signals_per_day, 3)
            ),
            "filled_strategy_trades_per_day": (
                None if self.filled_strategy_trades_per_day is None
                else round(self.filled_strategy_trades_per_day, 3)
            ),
            "closed_strategy_trades": self.closed_strategy_trades,
            "net_expectancy_after_costs": (
                None if self.net_expectancy_after_costs is None
                else str(self.net_expectancy_after_costs.quantize(Decimal("0.0001")))
            ),
            "no_trade_reasons": self.no_trade_reasons(),
            "rejection_funnel": self.rejection_funnel(),
            "stage_totals": self.stage_totals(),
            "days": [d.as_dict() for d in self.days],
            "excluded_days": [
                {"trading_day": d.funnel.trading_day, "because": d.not_eligible_because}
                for d in self.days if not d.eligible
            ],
        }


def build_report(events: Iterable, *, trades_by_day=None) -> ParticipationReport:
    events = list(events)
    trades_by_day = trades_by_day or {}
    days = tuple(
        build_day(events, day, trades=trades_by_day.get(day, ()))
        for day in days_present(events)
    )
    return ParticipationReport(days=days)


# ---------------------------------------------------------------------------
# تقرير يومٍ مؤهَّل انتهى بلا صفقة
# ---------------------------------------------------------------------------

def daily_no_trade_report(day: DayOutcome) -> str:
    """
    `DAILY-NO-TRADE-REPORT` — يثبت بالأرقام أين توقّف المسار ولماذا.

    ولا يُكتب ليومٍ غير مؤهَّل: يومٌ مغلقُ السوق ليس إخفاقاً في المشاركة،
    وكتابةُ تقرير إخفاقٍ عنه تُغرق الإشارة بالضجيج.
    """
    f = day.funnel
    lines: list[str] = []
    lines.append(f"# DAILY-NO-TRADE-REPORT — {f.trading_day}")
    lines.append("")
    if not day.eligible:
        lines.append(
            f"**اليوم غير مؤهَّل**: {f.trading_day} — {day.not_eligible_because}. "
            "لا يُحسَب في مقام معدّل المشاركة."
        )
        return "\n".join(lines)

    lines.append("## المسار بالأرقام")
    lines.append("")
    lines.append("| المرحلة | العدد |")
    lines.append("|---|---|")
    from .funnel import STAGES

    for stage in STAGES:
        lines.append(f"| {STAGE_LABEL_AR.get(stage, stage)} | {f.counts.get(stage, 0)} |")
    lines.append("")

    stage = f.collapse_stage
    lines.append("## أين توقّف")
    lines.append("")
    if stage is None:
        lines.append("لم ينهر المسار عند مرحلةٍ بعينها، ولم تقع صفقة — يُراجَع يدوياً.")
    else:
        lines.append(
            f"أوّل مرحلةٍ نزل عندها العدد إلى صفر: **{STAGE_LABEL_AR.get(stage, stage)}**."
        )
        lines.append("")
        lines.append(f"**الجهة المسؤولة:** {OWNER_LABEL_AR.get(f.blamed_on, f.blamed_on)}")
    lines.append("")

    if f.rejections:
        lines.append("## أسباب الرفض بالتكرار")
        lines.append("")
        lines.append("| المرحلة | الرمز | العدد |")
        lines.append("|---|---|---|")
        for st, reasons in f.rejections.items():
            for code, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
                lines.append(f"| {STAGE_LABEL_AR.get(st, st)} | `{code}` | {count} |")
        lines.append("")

    if f.isolated_instruments:
        lines.append("## أدواتٌ معزولة (عزلٌ لا توقّف)")
        lines.append("")
        for symbol, code in sorted(f.isolated_instruments.items()):
            lines.append(f"* `{symbol}` — `{code}`")
        lines.append("")

    lines.append("## القراءة")
    lines.append("")
    lines.append(
        "تكرارُ الرفض في بوابةٍ واحدة يستوجب تشخيص السياسة أو الإعداد أو "
        "بيانات الوسيط أو نسخة النشر — لا افتراض غياب الفرص. "
        "وتكرارُ أيامٍ مؤهَّلة بلا صفقة مؤشّرٌ على أن **تغطية الاستراتيجيات "
        "غير كافية**، وتُعاد إلى البحث؛ وليس مبرّراً لخفض معايير الجودة."
    )
    return "\n".join(lines)


__all__ = [
    "DayOutcome",
    "ParticipationReport",
    "build_day",
    "build_report",
    "daily_no_trade_report",
]
