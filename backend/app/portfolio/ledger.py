"""
الدفتر الدائم — ما رآه الوسيط يُكتَب، فينجو إعادةَ التشغيل.

## المسألة

`read_portfolio` (C2) جعل المحرّك يقرأ الوسيط كلَّ دورة، فلم يعد سقفُ العدد
يقرأ جدولاً فارغاً. لكن القراءة لا تُخزَّن، ومعنى ذلك أنّ إعادة تشغيلٍ تمحو
كلَّ ما نعرفه عن المراكز: لا يُعرَف مركزٌ **فُتح بيننا** من مركزٍ وجدناه، ولا
تُقارَن لقطةُ اليوم بلقطة أمس، ولا يُكشَف مركزٌ اختفى بلا صفقةٍ تقابله.

## القاعدة

المفتاح `broker_deal_id` لا الرمز. كابيتال يسمح بعدّة مراكز على الأداة
الواحدة — وكان على GBPUSD ثلاثة في يومٍ واحد — فمفتاحٌ بالرمز يُسقط أحدَها
على الآخر ويقول «مطابَق».

## النسب

`broker_deal_id` → `broker_orders.broker_deal_id` → `client_order_id` →
`order_intents` → الاستراتيجية وإصدارها وقرار المخاطر. وما لا يُنسَب يُسمّى
`UNATTRIBUTED` صراحةً؛ لا يُخمَّن ولا يُنسَب بالرمز والتوقيت.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import BrokerOrderRow, OrderIntentRow, PositionBookRow
from .book import KIND_COMMISSIONING, KIND_STRATEGY, KIND_UNATTRIBUTED, PortfolioSnapshot

STATE_OPEN = "OPEN"
STATE_CLOSED = "CLOSED"
#: مركزٌ في الدفتر مفتوحاً ولم يعد لدى الوسيط، ولا صفقةَ إغلاقٍ تقابله بعد.
STATE_ORPHANED = "ORPHANED"

ATTRIBUTION_LINKED = "LINKED"
ATTRIBUTION_UNLINKED = "UNLINKED"

#: حالةُ المعرفة — لا حالةُ المركز.
RECON_CONFIRMED = "CONFIRMED"
RECON_STALE = "STALE"

#: كم لقطةً **ناجحة** متتاليةً يجب أن يغيب فيها المركز قبل أن يُكتَب مغلقاً.
#:
#: الواحدة لا تكفي. ردُّ وسيطٍ بحالة 200 وقائمةٍ فارغة يبدو ناجحاً تماماً،
#: وقد يقع لأسبابٍ لا علاقة لها بإغلاق المراكز: حسابٌ خطأ في الطلب، ترحيلٌ
#: عند الوسيط، نافذةٌ بين إغلاق جلسةٍ وفتح أخرى. وكتابةُ الإغلاق فعلٌ لا
#: يُستعاد: يُمحى بها ما نعرفه عن خمسة مراكز حيّة. فيُشترط تكرارٌ.
CLOSE_CONFIRMATIONS = 2


@dataclass(frozen=True)
class LedgerSync:
    """نتيجةُ مزامنةٍ واحدة — تُقرأ في السجل وفي الشاشة."""

    at_utc: datetime
    #: مراكز رأيناها لأول مرة في هذه المزامنة.
    opened: tuple[str, ...] = ()
    #: مراكز كانت في الدفتر واختفت من الوسيط.
    closed: tuple[str, ...] = ()
    #: مراكز تغيّرت كميّتها أو حمايتها.
    changed: tuple[str, ...] = ()
    #: مراكز لم يُعرَف أيُّ قرارٍ فتحها.
    unattributed: tuple[str, ...] = ()
    #: مراكز في الدفتر لم تظهر في هذه اللقطة — **تبقى مفتوحةً وتُعدّ**.
    stale: tuple[str, ...] = ()
    #: مراكز غابت ولم تبلغ عتبةَ التأكيد بعد — إغلاقٌ مؤجَّلٌ لا صامت.
    pending_close: tuple[str, ...] = ()
    notes_ar: tuple[str, ...] = ()

    @property
    def touched(self) -> int:
        return len(self.opened) + len(self.closed) + len(self.changed)


@dataclass
class _Attribution:
    kind: str = KIND_UNATTRIBUTED
    attribution: str = ATTRIBUTION_UNLINKED
    client_order_id: Optional[str] = None
    deal_reference: Optional[str] = None
    risk_decision_id: Optional[int] = None
    strategy_name: str = ""
    strategy_version: str = ""
    notes: list[str] = field(default_factory=list)


def _attribute(session: Session, *, deal_id: str, deal_reference: Optional[str]) -> _Attribution:
    """
    ينسب مركزاً إلى الأمر الذي فتحه — **بالهويّة وحدها**.

    البحث بـ`broker_deal_id` أوّلاً، ثم بـ`deal_reference`. ولا بحث بالرمز
    ولا بالتوقيت: مركزان على الأداة نفسها في الدقيقة نفسها ينسبان خطأً،
    ونسبةٌ خاطئة أسوأ من `UNATTRIBUTED` — لأنها تُقرأ على أنها معرفة.
    """
    order = session.execute(
        select(BrokerOrderRow).where(BrokerOrderRow.broker_deal_id == deal_id)
    ).scalar_one_or_none()

    if order is None and deal_reference:
        order = session.execute(
            select(BrokerOrderRow).where(BrokerOrderRow.deal_reference == deal_reference)
        ).scalar_one_or_none()

    if order is None:
        return _Attribution(
            notes=[f"لا أمرَ لدينا يحمل هويّة المركز {deal_id} — لا يُنسَب."]
        )

    intent = session.execute(
        select(OrderIntentRow).where(OrderIntentRow.client_order_id == order.client_order_id)
    ).scalar_one_or_none()

    if intent is None:
        return _Attribution(
            attribution=ATTRIBUTION_UNLINKED,
            client_order_id=order.client_order_id,
            deal_reference=order.deal_reference,
            notes=[f"أمرٌ بلا نيّة مسجَّلة: {order.client_order_id}."],
        )

    kind = KIND_COMMISSIONING if intent.strategy_name == "COMMISSIONING" else KIND_STRATEGY
    return _Attribution(
        kind=kind,
        attribution=ATTRIBUTION_LINKED,
        client_order_id=order.client_order_id,
        deal_reference=order.deal_reference,
        risk_decision_id=intent.risk_decision_id,
        strategy_name=intent.strategy_name,
        strategy_version=intent.strategy_version,
    )


def open_rows(session: Session) -> list[PositionBookRow]:
    """المراكز التي يقول الدفتر إنها مفتوحة — تُقرأ عند الإقلاع."""
    return list(
        session.execute(
            select(PositionBookRow).where(PositionBookRow.state == STATE_OPEN)
        ).scalars()
    )


def sync(session: Session, snapshot: PortfolioSnapshot) -> Optional[LedgerSync]:
    """
    يكتب لقطةَ الوسيط في الدفتر.

    **لقطةٌ فاشلة لا تُكتَب إطلاقاً.** `ok=False` تعني «لم أرَ»، وكتابتها
    تعني إغلاق كلِّ مركزٍ في الدفتر لأنه «لم يظهر» — وهو بالضبط الخطأ الذي
    يحوّل عجزاً عن القراءة إلى حقيقةٍ مكتوبة. فتُعاد `None` ويبقى الدفتر
    على آخر ما رآه.
    """
    if not snapshot.ok:
        return None

    now = snapshot.as_of_utc
    opened: list[str] = []
    changed: list[str] = []
    unattributed: list[str] = []
    notes: list[str] = []

    seen: set[str] = set()

    for position in snapshot.open_positions:
        deal_id = (position.deal_id or "").strip()
        if not deal_id:
            # بلا هويّة لا مكان في الدفتر: مفتاحٌ مخترَع يُنشئ مركزاً جديداً
            # كلَّ دورة، فينتفخ الدفتر بأشباح.
            notes.append(f"مركز {position.symbol} بلا هويّة لدى الوسيط — لم يُكتَب.")
            continue
        seen.add(deal_id)

        row = session.execute(
            select(PositionBookRow).where(PositionBookRow.broker_deal_id == deal_id)
        ).scalar_one_or_none()

        if row is None:
            attribution = _attribute(
                session, deal_id=deal_id, deal_reference=position.deal_reference
            )
            notes.extend(attribution.notes)
            row = PositionBookRow(
                broker_deal_id=deal_id,
                account_id=snapshot.account_id or "",
                symbol=position.symbol,
                quantity=position.quantity,
                entry_price=position.entry_price,
                stop_price=position.stop_price,
                take_profit_price=position.take_profit_price,
                currency=position.currency or "",
                state=STATE_OPEN,
                kind=attribution.kind,
                attribution=attribution.attribution,
                deal_reference=attribution.deal_reference or position.deal_reference,
                client_order_id=attribution.client_order_id,
                risk_decision_id=attribution.risk_decision_id,
                strategy_name=attribution.strategy_name,
                strategy_version=attribution.strategy_version,
                opened_at_utc=position.opened_utc,
                first_seen_utc=now,
                last_seen_utc=now,
                seen_after_restart=True,
                reconciliation=RECON_CONFIRMED,
                last_confirmed_utc=now,
                absent_confirmations=0,
            )
            session.add(row)
            opened.append(deal_id)
            if attribution.attribution != ATTRIBUTION_LINKED:
                unattributed.append(deal_id)
            continue

        moved = (
            row.quantity != position.quantity
            or row.stop_price != position.stop_price
            or row.take_profit_price != position.take_profit_price
        )
        row.quantity = position.quantity
        row.stop_price = position.stop_price
        row.take_profit_price = position.take_profit_price
        row.last_seen_utc = now
        row.seen_after_restart = True
        row.reconciliation = RECON_CONFIRMED
        row.last_confirmed_utc = now
        row.absent_confirmations = 0
        if row.state != STATE_OPEN:
            # عاد بعد أن ظننّاه مغلقاً: الوسيط هو الحقيقة، والدفتر يتبعه.
            row.state = STATE_OPEN
            row.closed_at_utc = None
            notes.append(f"مركز {deal_id} عاد إلى الوسيط بعد أن غاب — أُعيد فتحه في الدفتر.")
            moved = True
        if moved:
            changed.append(deal_id)
        if row.attribution != ATTRIBUTION_LINKED:
            unattributed.append(deal_id)

    # **الغياب ليس إغلاقاً — لا في اللقطة الأولى.**
    #
    # كان كلُّ صفٍّ لم يظهر يُكتَب `CLOSED` فوراً وبلا ملاحظة. فلقطةٌ واحدة
    # ناجحةٌ وفارغة — وهي حالةٌ ممكنةٌ لأسبابٍ لا تعني إغلاقاً — تمحو حقيقةَ
    # الدفتر كلِّه بصمت. صار الغياب يُعَدّ: يبقى المركز مفتوحاً ويُعلَّم
    # `STALE` ويستمرّ في التعرّض والمخاطر، ولا يُكتَب مغلقاً إلا بعد
    # `CLOSE_CONFIRMATIONS` لقطةً ناجحةً متتاليةً غاب فيها — ومع ملاحظةٍ
    # تقول لماذا.
    closed: list[str] = []
    stale: list[str] = []
    pending: list[str] = []
    for row in open_rows(session):
        if row.broker_deal_id in seen:
            continue
        row.absent_confirmations = int(row.absent_confirmations or 0) + 1
        row.reconciliation = RECON_STALE
        if row.absent_confirmations >= CLOSE_CONFIRMATIONS:
            row.state = STATE_CLOSED
            row.closed_at_utc = now
            # **الإغلاق نفسه مؤكَّد.** `reconciliation` تصف الثقة في
            # `state` لا في وجود المركز: صفٌّ بقي `STALE` بعد أن كُتب
            # مغلقاً يُقرأ «لا نعرف أمُغلقٌ هو» — وهو عكسُ ما جرى، فقد
            # تأكّد غيابُه من لقطاتٍ ناجحةٍ متتالية. و`last_confirmed_utc`
            # يبقى آخرَ لحظةٍ رُئي فيها **مفتوحاً**، وذلك معناه.
            row.reconciliation = RECON_CONFIRMED
            closed.append(row.broker_deal_id)
            notes.append(
                f"مركز {row.broker_deal_id} غاب عن {row.absent_confirmations} "
                "لقطةً ناجحةً متتالية — كُتب مغلقاً."
            )
        else:
            stale.append(row.broker_deal_id)
            pending.append(row.broker_deal_id)
            notes.append(
                f"مركز {row.broker_deal_id} لم يظهر في هذه اللقطة "
                f"({row.absent_confirmations}/{CLOSE_CONFIRMATIONS}) — يبقى "
                "مفتوحاً ويُعدّ في التعرّض حتى يتأكّد."
            )

    session.commit()

    return LedgerSync(
        at_utc=now,
        opened=tuple(opened),
        closed=tuple(closed),
        changed=tuple(changed),
        unattributed=tuple(dict.fromkeys(unattributed)),
        stale=tuple(stale),
        pending_close=tuple(pending),
        notes_ar=tuple(notes),
    )


def mark_restart(session: Session) -> int:
    """
    يُعلِّم كلَّ مركزٍ مفتوح `STALE` عند الإقلاع — **ولا يمحو شيئاً**.

    ما نعرفه عن المركز يبقى كما هو: الكمية والوقف والنسبة وآخر تأكيد. الذي
    يتغيّر هو **ثقتُنا** فيه: من «مؤكَّد» إلى «آخرُ حقيقةٍ معروفة». فالإقلاع
    لا يُنقص علماً، إنما يُعلن أنّ العلم لم يُجدَّد بعد.

    ولذلك لا يُنشئ هذا نافذةً يبدو فيها الدفتر فارغاً: الصفوف تبقى `OPEN`،
    فتُعَدّ في التعرّض والمخاطر، ويُعرَض للمستخدم آخرُ ما نعرفه موسوماً بأنه
    غيرُ مؤكَّد — لا صفرٌ، ولا سكوت.
    """
    rows = open_rows(session)
    for row in rows:
        row.seen_after_restart = False
        row.reconciliation = RECON_STALE
    session.commit()
    return len(rows)


def stale_rows(session: Session) -> list[PositionBookRow]:
    """المراكز المفتوحة التي لم تُؤكَّد بعد — يُحجب الدخول ما دامت."""
    return [r for r in open_rows(session) if r.reconciliation != RECON_CONFIRMED]


def as_positions(rows: list[PositionBookRow]) -> list[dict]:
    """تمثيلٌ خفيف للمطابقة والعرض."""
    return [
        {
            "deal_id": row.broker_deal_id,
            "symbol": row.symbol,
            "quantity": row.quantity,
            "strategy": row.strategy_name,
            "strategy_version": row.strategy_version,
            "kind": row.kind,
            "attribution": row.attribution,
            "state": row.state,
            "reconciliation": row.reconciliation or RECON_STALE,
            "last_confirmed_utc": (
                row.last_confirmed_utc.isoformat() if row.last_confirmed_utc else None
            ),
            "absent_confirmations": int(row.absent_confirmations or 0),
        }
        for row in rows
    ]


def exposure(rows: list[PositionBookRow]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        totals[row.symbol] = totals.get(row.symbol, Decimal("0")) + row.quantity
    return totals
