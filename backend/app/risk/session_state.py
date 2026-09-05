"""
بناء حالة المخاطرة — **لكلّ مؤشّرٍ مصدرُه، ولا مصدرَ يُستبدل بصفر.**

## ما كان، وما ظهر

كانت `realized_pnl_today` و`realized_pnl_week` مثبَّتتين على صفرٍ في
`api/state.py`، فلا يستطيع حدُّ الخسارة اليومي ولا الأسبوعي أن يُفعَّل. فكُتب
هذا الملف ليقرأهما من جدول `trades`.

ثم تبيّن يوم 2026-09-05 أنّ **`trades` لا يُكتَب فيه قط**: لا سطرَ واحد ينشئ
`TradeRow` في التطبيق ولا في الاختبارات، وعلى الخادم الحيّ صفر صف. فكان
الإصلاح قد نقل الصفرَ من ثابتٍ مكتوبٍ إلى استعلامٍ على جدولٍ فارغ — والثاني
أسوأ، لأنه **يبدو** كأنه يقرأ. أربعُ بوّاباتٍ كانت عاجزةً بنيوياً.

## المصادر — بقرار المالكة 2026-09-05

| المؤشّر | المصدر | عند التعذّر |
|---|---|---|
| `current_equity` | **الحصّة المخصَّصة + المحقَّق المؤكَّد + غير المحقَّق من لقطة الوسيط** | `equity_known=False` ⇒ حجب الدخول |
| `broker_equity` | `net_liquidation` حيّاً — للكفاية والهامش وكشف الانحراف | `None` ⇒ حجب |
| `realized_pnl_today` · `_week` | إغلاقاتُ `position_book` **المؤكَّدة** وحدها | مجهولٌ يُعَدّ ولا يُطرَح صفراً ⇒ حجب |
| `consecutive_losses` | الإغلاقات المؤكَّدة بترتيب `closed_at_utc` | تقف عند أوّل مجهولٍ كما تقف عند أوّل ربح |
| `entry_orders_today` | **`order_intents`** — محاولةُ الدخول تُكتَب قبل الإرسال | تعذّر القراءة ⇒ حجب |
| `open_positions` · `open_symbols` | `position_book`، ويصحّحها `heartbeat` باتحادها مع اللقطة | اللقطة غير `ok` ⇒ حجب |

### ولماذا الحصّة المخصَّصة لا رصيدُ الحساب

الرصيدُ الخام يكسر الحاجز الذي يُفترض أن يحميه. `total_loss` تُحسب
`baseline − current_equity`؛ وعلى حسابٍ تجريبيّ رصيده تسعون ألفاً والحصّةُ
المخصَّصة ثلاثمئة، تصير:

    total_loss = max(0, 300 − 90,000) = 0     ← أبداً، مهما خسرنا

فحاجزُ التراجع التشغيلي **لا يستطيع أن يعمل**. والفارقُ هنا تصميمٌ لا انحراف:
النتائج تُقاس كما لو كان الحساب ثلاثمئة كي تنتقل التجربة إلى الحساب الحقيقي.

فالمقياسُ هو **حصّةُ الاستراتيجية**: المخصَّص + ما تحقّق مؤكَّداً + ما لم
يتحقّق بعدُ من مراكزنا المفتوحة. وعلى حسابٍ حقيقيٍّ رصيده ثلاثمئة يتطابق
القياسان تماماً؛ ويبقى `broker_equity` مقروءاً حيّاً للكفاية والهامش وكشف
الانحراف، ولا يحلّ محلّ المخصَّص.

### ولماذا `order_intents` لا `position_book` لعدّ الدخول

السقفُ يحرس **المحاولات** لا النجاحات: أمرٌ رفضه الوسيط استهلك محاولةً ولم
يترك مركزاً. وعدُّه من الدفتر يجعل النظام يُعيد المحاولة بلا حدٍّ ما دامت
كلّها تُرفض.

## والجهل يُعَدّ ولا يُطرَح

صفٌّ مغلقٌ بلا `realised_pnl` ليس ربحاً صفراً؛ جمعُه كصفرٍ يُنقص خسارةً حقيقية
من العدّاد الذي يحمي رأس المال. ولا يُبطَل الإقلاع عند أيٍّ من هذه: القراءةُ
والمراقبةُ تبقيان، والممنوعُ **مخاطرةٌ جديدة**.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now_utc, trading_day_bounds_utc, trading_week_bounds_utc
from ..db.models import OrderIntentRow, PositionBookRow
from ..money import D
from ..portfolio.ledger import RECON_CONFIRMED, STATE_CLOSED, STATE_OPEN
from .engine import SessionRiskState

#: بعدها تُعَدّ لقطةُ الحساب قديمة. دورةُ القرار ٦٠ ثانية، فالضِّعف يحتمل
#: دورةً فائتةً واحدة ولا يحتمل انقطاعاً. (قرار المالكة 2026-09-05)
EQUITY_STALE_AFTER = timedelta(seconds=120)


@dataclass(frozen=True)
class EquityReading:
    """
    ما يُقرأ من الوسيط لبناء حقوق الملكية — **بزمنه وبحالته**.

    `ok=False` تعني «لا أعرف»، لا «صفر» ولا «كما كان». وحينها لا يُبنى على
    الرقم قرار: `equity_known` تحملها إلى `SessionRiskState`، و`heartbeat`
    يحجب بها الدخول.

    و`unrealised` **ناقصةٌ تعني مجهولة**: مركزٌ واحدٌ بلا ربحٍ غير محقَّق
    يجعل المجموع كلَّه غيرَ معروف، لأنّ حذفه منه يُصغّر الخسارة.
    """

    broker_equity: Optional[Decimal]
    unrealised: Optional[Decimal]
    as_of_utc: Optional[datetime]
    ok: bool
    reason_ar: str

    def is_stale(self, at: Optional[datetime] = None) -> bool:
        if not self.ok or self.as_of_utc is None:
            return True
        return (at or now_utc()) - self.as_of_utc > EQUITY_STALE_AFTER


def _unrealised_of(snapshot) -> tuple[Optional[Decimal], str]:
    """
    مجموعُ غير المحقَّق من لقطة المراكز — أو `None` مع سببٍ مكتوب.

    لا مركزَ مفتوح ⇒ **صفرٌ صادق**، وهو معلومٌ لا مجهول. وذلك يختلف عن
    لقطةٍ لم تُقرأ: الأولى تقول «لا شيء»، والثانية تقول «لا أعرف».
    """
    if snapshot is None or not getattr(snapshot, "ok", False):
        return None, "لم تُقرأ لقطةُ المراكز — لا يُعرَف غيرُ المحقَّق."
    total = D(0)
    for position in getattr(snapshot, "open_positions", ()) or ():
        value = getattr(position, "unrealised_pnl", None)
        if value is None:
            value = getattr(position, "unrealized_pnl", None)
        if value is None:
            return None, (
                f"مركز {getattr(position, 'symbol', '?')} بلا ربحٍ غير محقَّق — "
                "وحذفُه من المجموع يُصغّر الخسارة."
            )
        total += D(value)
    return total, "غيرُ المحقَّق مقروءٌ من كلّ مركزٍ مفتوح."


def read_equity(broker, account_id: str = "", *, snapshot=None) -> EquityReading:
    """
    يقرأ رصيدَ الحساب وغيرَ المحقَّق — ولا يخترع رقماً عند الفشل.

    `net_liquidation` هي الرصيد **زائد ربح المراكز المفتوحة**؛ وعند كابيتال
    تُبنى من `balance + profit_loss` في المحوّل. والنقدُ المسوّى وحده يُنقص ما
    في السوق فيبدو الحساب أصغر مما هو — ولذلك لا يُستعمل بديلاً صامتاً.
    """
    unrealised, note = _unrealised_of(snapshot)

    # **`get_accounts` ليست في العقد المجرَّد.** `get_balances(account_id)` هي
    # الموجودة في `BrokerAdapter`، فيملكها كلُّ وسيطٍ بالضرورة؛ أمّا الأولى
    # فيملكها بعضُهم. واشتراطُها هنا كان يحوّل وسيطاً سليماً إلى
    # `EQUITY_UNKNOWN` عبر `AttributeError` تُبتلَع في `except` أدناه — وهو
    # نفسُ عطل `get_account_snapshot` الذي كلّفنا يومين: **اسمٌ كُتب من
    # الذاكرة لا من العقد**. فتُجرَّب إن وُجدت، ويُمضى بلا حسابٍ إن غابت.
    if not account_id:
        getter = getattr(broker, "get_accounts", None)
        if callable(getter):
            try:
                accounts = list(getter() or [])
                account_id = accounts[0] if accounts else ""
            except Exception:  # noqa: BLE001
                account_id = ""

    try:
        balances = broker.get_balances(account_id)
        equity = getattr(balances, "net_liquidation", None)
        as_of = getattr(balances, "as_of_utc", None) or now_utc()
    except Exception as exc:  # noqa: BLE001
        return EquityReading(
            None, unrealised, None, False,
            f"تعذّرت قراءة الرصيد من الوسيط ({type(exc).__name__}) — لا حكم.",
        )

    if equity is None:
        return EquityReading(
            None, unrealised, as_of, False,
            "الوسيط لم يُعِد صافي التصفية — لا يُستبدَل بالنقد المسوّى.",
        )
    if unrealised is None:
        return EquityReading(D(str(equity)), None, as_of, False, note)
    return EquityReading(
        D(str(equity)), unrealised, as_of, True,
        "رصيدٌ حيّ من الوسيط، وغيرُ محقَّقٍ مقروءٌ من كلّ مركز.",
    )


def _closed_confirmed(session: Session, start: datetime, end: datetime):
    """
    الإغلاقاتُ **المؤكَّدة** ضمن نافذة.

    `reconciliation != CONFIRMED` يعني أنّ الإغلاق نفسه لم يُثبَت بدليلٍ
    مستقلّ من دفتر معاملات الوسيط — ونتيجةٌ غيرُ مؤكَّدة لا تدخل عدّاداً
    يوقف التداول.
    """
    return session.execute(
        select(PositionBookRow.broker_deal_id, PositionBookRow.realised_pnl).where(
            PositionBookRow.state == STATE_CLOSED,
            PositionBookRow.reconciliation == RECON_CONFIRMED,
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
    ولا تُعَدّ ربحاً يقطع السلسلة.

    **ولا تستبعد شيئاً بحسب التصنيف** (قرار المالكة 2026-09-05): هذا عدّادُ
    تهدئةِ مخاطر، ورأسُ المال لا يسأل عن سبب الخسارة. والاستبعادُ موضعُه
    إحصاءُ أداء الاستراتيجية، وهو عدّادٌ آخر.
    """
    rows = session.execute(
        select(PositionBookRow.realised_pnl)
        .where(
            PositionBookRow.state == STATE_CLOSED,
            PositionBookRow.reconciliation == RECON_CONFIRMED,
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
    equity: Optional[EquityReading] = None,
) -> SessionRiskState:
    """
    يبني `SessionRiskState`.

    `equity` قراءةٌ تُمرَّر من المستدعي — يبقى هذا الملف نقيَّ القاعدة، وتبقى
    مكالمةُ الشبكة حيث تُرى وتُقاس. وبلا قراءةٍ صالحة تُعلَن الحالة
    `equity_known=False`، ويُملأ الحقل بأفضل تقديرٍ **موسوماً** كي لا ينهار
    قارئٌ لا يقرأ العَلَم — والقرار يُحجَب عند البوّابة لا هنا.
    """
    at = at or now_utc()
    day_start, day_end = trading_day_bounds_utc(at)
    week_start, week_end = trading_week_bounds_utc(at)

    realized_today, unknown_today = _sum_realised(
        _closed_confirmed(session, day_start, day_end)
    )
    realized_week, unknown_week = _sum_realised(
        _closed_confirmed(session, week_start, week_end)
    )

    all_closed = session.execute(
        select(PositionBookRow.broker_deal_id, PositionBookRow.realised_pnl).where(
            PositionBookRow.state == STATE_CLOSED,
            PositionBookRow.reconciliation == RECON_CONFIRMED,
            PositionBookRow.closed_at_utc.is_not(None),
        )
    ).all()
    realized_total, unknown_total = _sum_realised(all_closed)

    # الأسماءُ لا العددُ وحده: بوابةُ مصدر التعرّض تحتاج أن تعرف **ماذا** فُتح
    # لا **كم**. ويصحّحها `heartbeat` باتحادها مع لقطة الوسيط.
    open_symbols = tuple(
        session.execute(
            select(PositionBookRow.symbol).where(PositionBookRow.state == STATE_OPEN)
        ).scalars().all()
    )

    # **محاولاتُ الدخول لا المراكزُ الناتجة.**
    entries_today = len(
        session.execute(
            select(OrderIntentRow.id).where(
                OrderIntentRow.created_at_utc >= day_start,
                OrderIntentRow.created_at_utc < day_end,
            )
        ).scalars().all()
    )

    baseline = D(baseline_equity)
    known = bool(equity and equity.ok and equity.unrealised is not None)
    unrealised = equity.unrealised if known else D(0)

    return SessionRiskState(
        baseline_equity=baseline,
        # **حصّةُ الاستراتيجية، لا رصيدُ الحساب.** رصيدٌ تجريبيٌّ ضخمٌ يجعل
        # `total_loss` صفراً أبداً فيُعطَّل حاجزُ التراجع.
        current_equity=baseline + realized_total + unrealised,
        realized_pnl_today=realized_today,
        realized_pnl_week=realized_week,
        unrealized_pnl=unrealised,
        open_positions=len(open_symbols),
        entry_orders_today=entries_today,
        consecutive_losses=_consecutive_losses(session),
        open_symbols=open_symbols,
        unknown_realised_closes=max(unknown_today, unknown_week, unknown_total),
        equity_known=known,
        broker_equity=(equity.broker_equity if equity else None),
        equity_as_of_utc=(equity.as_of_utc if equity else None),
        equity_stale=(equity.is_stale(at) if equity else True),
        equity_reason_ar=(
            equity.reason_ar if equity else "لم تُطلَب قراءةُ رصيدٍ من الوسيط."
        ),
    )


__all__ = ["EquityReading", "read_equity", "load_session_state", "EQUITY_STALE_AFTER"]


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
