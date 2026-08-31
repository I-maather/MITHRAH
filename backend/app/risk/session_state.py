"""
بناء حالة المخاطرة من قاعدة البيانات — إصلاح C1.

قبل هذا الملف كانت `realized_pnl_today` و`realized_pnl_week` **مثبَّتتين على
صفر** عند بناء النظام (`api/state.py`)، ولا مسار يحدّثهما. وأثر ذلك أن حدّ
الخسارة اليومي والأسبوعي وحاجز التراجع التشغيلي **لا يمكن أن تُفعَّل أبداً**:
`day_loss` و`week_loss` تُشتقّان من هذين الحقلين.

المبدأ هنا: **لا قيمة مُختلَقة.** الحالة تُقرأ من جدول `trades` أو لا تُبنى.
فشل القراءة يُرفَع استثناءً ولا يُبتلَع — نظامٌ يُقلع بحالة مخاطرة كاذبة
أخطر من نظام لا يُقلع.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now_utc, trading_day_bounds_utc, trading_week_bounds_utc
from ..db.models import TradeRow
from ..money import D
from .engine import SessionRiskState


def _sum_net_pnl(session: Session, start: datetime, end: datetime) -> Decimal:
    """صافي أرباح/خسائر الصفقات **المغلقة** ضمن نافذة زمنية."""
    rows = session.execute(
        select(TradeRow.net_pnl).where(
            TradeRow.closed_at_utc.is_not(None),
            TradeRow.closed_at_utc >= start,
            TradeRow.closed_at_utc < end,
        )
    ).scalars().all()
    return sum((D(v) for v in rows), D(0))


def _consecutive_losses(session: Session) -> int:
    """عدد الخسائر المتتالية في ذيل السجل — يتوقّف عند أول ربح."""
    rows = session.execute(
        select(TradeRow.net_pnl)
        .where(TradeRow.closed_at_utc.is_not(None))
        .order_by(TradeRow.closed_at_utc.desc())
        .limit(50)
    ).scalars().all()
    count = 0
    for value in rows:
        if D(value) < 0:
            count += 1
        else:
            break
    return count


def load_session_state(
    session: Session,
    *,
    baseline_equity: Decimal,
    at: Optional[datetime] = None,
) -> SessionRiskState:
    """
    يبني `SessionRiskState` من قاعدة البيانات.

    `current_equity` = رأس المال المرجعي + كل الأرباح المحقّقة. لا يُقرأ من
    الوسيط هنا عمداً: حالة المخاطرة يجب أن تُبنى حتى لو كان الوسيط مفصولاً،
    وإلا صار انقطاعُ الشبكة سبباً في إقلاع بحدود صفرية.
    """
    at = at or now_utc()
    day_start, day_end = trading_day_bounds_utc(at)
    week_start, week_end = trading_week_bounds_utc(at)

    realized_today = _sum_net_pnl(session, day_start, day_end)
    realized_week = _sum_net_pnl(session, week_start, week_end)

    all_time = session.execute(
        select(TradeRow.net_pnl).where(TradeRow.closed_at_utc.is_not(None))
    ).scalars().all()
    realized_total = sum((D(v) for v in all_time), D(0))

    open_positions = len(
        session.execute(
            select(TradeRow.id).where(TradeRow.closed_at_utc.is_(None))
        ).scalars().all()
    )

    entries_today = len(
        session.execute(
            select(TradeRow.id).where(
                TradeRow.opened_at_utc >= day_start,
                TradeRow.opened_at_utc < day_end,
            )
        ).scalars().all()
    )

    baseline = D(baseline_equity)
    return SessionRiskState(
        baseline_equity=baseline,
        current_equity=baseline + realized_total,
        realized_pnl_today=realized_today,
        realized_pnl_week=realized_week,
        unrealized_pnl=D(0),          # يُحدَّث من الوسيط في مسار التشغيل، لا عند الإقلاع
        open_positions=open_positions,
        entry_orders_today=entries_today,
        consecutive_losses=_consecutive_losses(session),
    )


__all__ = ["load_session_state"]


# ---------------------------------------------------------------------------
# انحراف رأس المال المرجعي عن الرصيد الفعلي
# ---------------------------------------------------------------------------

#: نسبة الانحراف المقبولة قبل التحذير. الخسائر والأرباح تُبعد الرصيد عن
#: المرجع بطبيعتها، فالتحذير عند فارقٍ لا يفسّره تداولٌ عادي.
BASELINE_DRIFT_TOLERANCE = D("0.10")   # ١٠٪


@dataclass(frozen=True)
class BaselineDrift:
    """نتيجة مقارنة المرجع بالرصيد. `broker_equity=None` يعني تعذّرت القراءة."""

    baseline: Decimal
    broker_equity: Optional[Decimal]
    diverged: bool
    reason_ar: str

    def as_dict(self) -> dict:
        return {
            "baseline": str(self.baseline),
            "broker_equity": None if self.broker_equity is None else str(self.broker_equity),
            "diverged": self.diverged,
            "reason_ar": self.reason_ar,
        }


def check_baseline_against_broker(broker, baseline: Decimal) -> BaselineDrift:
    """
    يقارن رأس المال المرجعي بالرصيد الفعلي لدى الوسيط.

    **لا يصحّح ولا يوقف.** المرجع قرارٌ للمالكة لا قيمةٌ تُستنتج؛ ومهمّة هذا
    الفحص أن يجعل الانحراف **مرئياً** بدل أن يبقى صامتاً — كما بقي ١٥٠ مقابل
    ١٤٠ حتى انكشف بالمصادفة عند أول اتصال حقيقي.

    وفشل القراءة ليس انحرافاً: وسيطٌ مفصول لا يُثبت شيئاً عن الرصيد، فتُعاد
    `diverged=False` مع سبب صريح — ولا يُختلق رقم.
    """
    try:
        snapshot = broker.get_account_snapshot()
        equity = D(str(getattr(snapshot, "settled_cash", None)
                       or getattr(snapshot, "equity", 0)))
    except Exception as exc:  # noqa: BLE001
        return BaselineDrift(
            baseline=baseline,
            broker_equity=None,
            diverged=False,
            reason_ar=f"تعذّرت قراءة الرصيد من الوسيط ({type(exc).__name__}) — لا حكم.",
        )

    if equity <= 0:
        return BaselineDrift(
            baseline=baseline, broker_equity=equity, diverged=False,
            reason_ar="الوسيط أعاد رصيداً غير موجب — لا حكم.",
        )

    gap = abs(equity - baseline) / baseline
    if gap <= BASELINE_DRIFT_TOLERANCE:
        return BaselineDrift(
            baseline=baseline, broker_equity=equity, diverged=False,
            reason_ar=f"المرجع {baseline} والرصيد {equity} — ضمن المدى.",
        )
    return BaselineDrift(
        baseline=baseline, broker_equity=equity, diverged=True,
        reason_ar=(
            f"⚠️ رأس المال المرجعي {baseline} والرصيد الفعلي {equity} — "
            f"انحراف {gap:.0%}. كل الحدود تُحسب من المرجع، فراجعيه: "
            f"BASELINE_EQUITY_USD في بيئة الخادم."
        ),
    )
