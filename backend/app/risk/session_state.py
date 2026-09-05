"""
بناء حالة المخاطرة من **الدفتر الذي نكتبه فعلاً**.

## ما كان قبل هذا الملف، وما ظهر بعده

قبله كانت `realized_pnl_today` و`realized_pnl_week` مثبَّتتين على صفر في
`api/state.py`، فلا يستطيع حدُّ الخسارة اليومي ولا الأسبوعي أن يُفعَّل. فكُتب
هذا الملف ليقرأهما من جدول `trades`.

ثم تبيّن يوم 2026-09-05 أنّ **جدول `trades` لا يُكتَب فيه قط**: لا سطرٌ واحد
ينشئ `TradeRow` في التطبيق ولا في الاختبارات، ولا `INSERT INTO trades`، وعلى
الخادم الحيّ صفر صف بينما `position_book` يحمل خمسة. فكان الإصلاح قد نقل
الصفرَ من موضعٍ إلى موضع: من ثابتٍ مكتوبٍ إلى استعلامٍ على جدولٍ فارغ.
والثاني أسوأ من الأول، لأنه **يبدو** كأنه يقرأ.

والأثر مقيسٌ على أربع بوّابات:

| ما تحسبه | كانت قيمته دائماً |
|---|---|
| `realized_pnl_today` · `realized_pnl_week` | صفر |
| `current_equity` | الأساس، بلا نقصانٍ أبداً |
| `consecutive_losses` | صفر |
| `entry_orders_today` | صفر |

⇒ حدُّ الخسارة اليومي، وحدُّ الخسارة الأسبوعي، وتهدئةُ الخسارتين المتتاليتين،
وسقفُ الدخول اليومي — أربعتُها كانت **عاجزةً عن العمل بنيوياً**؛ لا معطّلةً
بقرارٍ يمكن مراجعته، بل تقرأ من فراغ.

## المصدر الآن

`position_book`: الدفتر الذي يكتبه `ledger.sync()` من لقطة الوسيط، ويُغلق
صفوفَه **بدليلٍ مستقلّ** من دفتر معاملات الوسيط لا بغياب اللقطات. مصدرٌ واحدٌ
للحقيقة، والذي يُقرَأ منه هو الذي يُكتَب فيه.

## والجهل يُعَدّ ولا يُطرَح

صفٌّ مغلقٌ بلا `realised_pnl` ليس ربحاً صفراً. وجمعُه كصفرٍ يُنقص خسارةً
حقيقية من العدّاد الذي يحمي رأس المال — وهو العطل نفسه بلباسٍ آخر. فتُعَدّ
هذه الصفوف في `unknown_realised_closes`، ويُحجَب بها فتحُ صفقاتٍ جديدة في
`heartbeat` حتى تُعرَف. ولا يُبطَل الإقلاع: القراءةُ والمراقبةُ تبقيان،
والممنوعُ هو **المخاطرة الجديدة** — فالفشل مغلقٌ عند القرار، لا عند التشغيل.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clock import now_utc, trading_day_bounds_utc, trading_week_bounds_utc
from ..db.models import PositionBookRow
from ..money import D
from ..portfolio.ledger import STATE_CLOSED, STATE_OPEN
from .engine import SessionRiskState


def _closed_in_window(session: Session, start: datetime, end: datetime):
    """صفوفُ الدفتر المغلقةُ ضمن نافذة — بنتيجتها كما هي، `None` منها."""
    return session.execute(
        select(PositionBookRow.broker_deal_id, PositionBookRow.realised_pnl).where(
            PositionBookRow.state == STATE_CLOSED,
            PositionBookRow.closed_at_utc.is_not(None),
            PositionBookRow.closed_at_utc >= start,
            PositionBookRow.closed_at_utc < end,
        )
    ).all()


def _sum_realised(rows) -> tuple[Decimal, int]:
    """يجمع المعلوم ويعدّ المجهول. **لا يُحوّل `None` إلى صفر.**"""
    total = D(0)
    unknown = 0
    for _deal_id, value in rows:
        if value is None:
            unknown += 1
            continue
        total += D(value)
    return total, unknown


def _consecutive_losses(session: Session) -> int:
    """
    الخسائرُ المتتالية في ذيل الدفتر — تتوقّف عند أوّل ربح.

    وتتوقّف أيضاً عند أوّل **مجهول**: صفقةٌ لا نعرف نتيجتها لا تُعَدّ خسارةً
    ولا تُعَدّ ربحاً يقطع السلسلة. والوقوف عندها يُبقي العدّاد على آخر ما
    نعرفه يقيناً، فلا يُبالغ في التهدئة ولا يُهوّن منها.
    """
    rows = session.execute(
        select(PositionBookRow.realised_pnl)
        .where(
            PositionBookRow.state == STATE_CLOSED,
            PositionBookRow.closed_at_utc.is_not(None),
        )
        .order_by(PositionBookRow.closed_at_utc.desc())
        .limit(50)
    ).scalars().all()
    count = 0
    for value in rows:
        if value is None:
            break
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
    يبني `SessionRiskState` من `position_book`.

    `current_equity` = رأس المال المرجعي + كلُّ ما تحقّق **وعُرف**. لا يُقرأ
    من الوسيط هنا عمداً: حالةُ المخاطرة يجب أن تُبنى حتى لو كان الوسيط
    مفصولاً، وإلا صار انقطاعُ الشبكة سبباً في إقلاعٍ بحدودٍ صفرية.
    """
    at = at or now_utc()
    day_start, day_end = trading_day_bounds_utc(at)
    week_start, week_end = trading_week_bounds_utc(at)

    realized_today, unknown_today = _sum_realised(
        _closed_in_window(session, day_start, day_end)
    )
    realized_week, unknown_week = _sum_realised(
        _closed_in_window(session, week_start, week_end)
    )

    all_closed = session.execute(
        select(PositionBookRow.broker_deal_id, PositionBookRow.realised_pnl).where(
            PositionBookRow.state == STATE_CLOSED,
            PositionBookRow.closed_at_utc.is_not(None),
        )
    ).all()
    realized_total, unknown_total = _sum_realised(all_closed)

    # الأسماءُ لا العددُ وحده: بوابةُ مصدر التعرّض تحتاج أن تعرف **ماذا** فُتح
    # لا **كم**. وعدُّ ثلاثة مراكز لا يقول إنّ ثلاثتها على الدولار نفسه.
    #
    # ويصحّحها `heartbeat` من لقطة الوسيط قبل سؤال المحرّك: الدفتر يعبر
    # إعادةَ التشغيل، لكنّ حارسَ اللحظة يجب أن يرى اللحظة.
    open_symbols = tuple(
        session.execute(
            select(PositionBookRow.symbol).where(PositionBookRow.state == STATE_OPEN)
        ).scalars().all()
    )
    open_positions = len(open_symbols)

    # `opened_at_utc` وقتُ الوسيط، وقد يغيب. و`first_seen_utc` أوّلُ دورةٍ
    # رأيناه فيها — وهي لمركزٍ فتحناه نحن تبعد ثوانيَ عن الفتح. البديلُ
    # معلَنٌ لا صامت، ولا يُترك العدّاد ناقصاً فيُفتَح فوق السقف.
    opened_at = func.coalesce(
        PositionBookRow.opened_at_utc, PositionBookRow.first_seen_utc
    )
    entries_today = len(
        session.execute(
            select(PositionBookRow.id).where(
                opened_at >= day_start,
                opened_at < day_end,
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
        open_symbols=open_symbols,
        unknown_realised_closes=max(unknown_today, unknown_week, unknown_total),
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


def check_baseline_against_broker(
    broker, baseline: Decimal, *, simulated_capital: bool = False
) -> BaselineDrift:
    """
    يقارن رأس المال المرجعي بالرصيد الفعلي لدى الوسيط.

    **لا يصحّح ولا يوقف.** المرجع قرارٌ للمالكة لا قيمةٌ تُستنتج؛ ومهمّة هذا
    الفحص أن يجعل الانحراف **مرئياً** بدل أن يبقى صامتاً — كما بقي ١٥٠ مقابل
    ١٤٠ حتى انكشف بالمصادفة عند أول اتصال حقيقي.

    وفشل القراءة ليس انحرافاً: وسيطٌ مفصول لا يُثبت شيئاً عن الرصيد، فتُعاد
    `diverged=False` مع سبب صريح — ولا يُختلق رقم.

    ## `simulated_capital` — ولماذا هو ضروري لا تخفيف

    على حساب تجريبي رصيده ٩١ ألفاً بينما المرجع ٣٠٠ **عمداً**، تكون المقارنة
    بلا معنى: الفارق ليس انحرافاً بل **تصميماً**. وإنذارٌ دائم يشتعل بلا سبب
    يُدرَّب على تجاهله، فيصمت في اليوم الذي يهمّ.

    والسؤال الصحيح هنا يختلف: ليس «أيطابق الرصيدُ المرجع؟» بل **«أيكفي
    الرصيد للمرجع؟»** — لأن رصيداً أقلّ من المرجع يعني حدوداً محسوبة على
    مالٍ غير موجود، وذلك خطرٌ حقيقي في الحالتين.
    """
    # ## الميثود التي لا وجود لها
    #
    # كان هنا `broker.get_account_snapshot()` — **وهي غير موجودة على أي
    # وسيط في المشروع**. لا في `BrokerAdapter`، ولا في محوّل كابيتال، ولا
    # في الوهمي. فكان النداء يرفع `AttributeError` في كل مرّة، ويُبتلَع في
    # `except` أدناه، فيُعاد «تعذّرت القراءة» **دائماً**.
    #
    # ولم يُكشَف لأن هذه الدالة كُتبت ولم تُوصَل بشيء يومين. ثم وُصلت أمس
    # بشاشة المحفظة، فظهر أثرها للمالكة: «غير متاح» ورصيدٌ لا يصل أبداً
    # مهما كان الوسيط متصلاً.
    #
    # نفس عائلة `UNRELIABLE` و`observed_at_utc` و`app.backtest.runner`:
    # **اسمٌ كُتب من الذاكرة لا من العقد**، في مسارٍ لا يُنفَّذ.
    #
    # والصحيح `get_balances(account_id)` — وهي في العقد المجرَّد، فيملكها
    # كل وسيط بالضرورة.
    try:
        accounts = list(broker.get_accounts() or [])
        balances = broker.get_balances(accounts[0] if accounts else "")
        # **صافي التصفية** هو حقوق الملكية: الرصيد زائد ربح المراكز المفتوحة.
        # والنقد المسوّى وحده يُنقص ما في السوق، فيبدو الحساب أصغر مما هو.
        equity = D(str(
            getattr(balances, "net_liquidation", None)
            or getattr(balances, "total_cash", None)
            or getattr(balances, "settled_cash", 0)
        ))
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

    if simulated_capital:
        # رأس مالٍ محاكى: يُطلَب أن **يكفي** الرصيد لا أن يطابقه.
        if equity < baseline:
            return BaselineDrift(
                baseline=baseline, broker_equity=equity, diverged=True,
                reason_ar=(
                    f"⚠️ رأس المال المحاكى {baseline} أكبر من الرصيد الفعلي "
                    f"{equity} — الحدود تُحسب على مالٍ غير موجود."
                ),
            )
        return BaselineDrift(
            baseline=baseline, broker_equity=equity, diverged=False,
            reason_ar=(
                f"رأس مال محاكى {baseline} على حسابٍ رصيده {equity}. "
                f"الفارق مقصود: النتائج تُقاس كما لو كان الحساب {baseline}، "
                f"كي تنتقل التجربة إلى الحساب الحقيقي."
            ),
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
