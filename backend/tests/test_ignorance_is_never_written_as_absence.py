"""الجهل بمركزٍ ليس غيابَه.

يوم أُثبت الدفتر الدائم ظهر أنّ إعادة التشغيل تُطفئ علماً ثنائياً ثم تعيده
خلال أقلّ من ثانية. والعلمُ الثنائي هو المشكلة: «لم أقرأ بعد» و«قرأتُ ولم
أجده» ليسا درجتين من شيءٍ واحد — أحدهما جهلٌ والآخر علم. وما بُني عليهما:

* لقطةٌ **ناجحةٌ وفارغة** كانت تُغلق الدفتر كلَّه فوراً وبصمت؛
* والتعرّض كان يُقرأ من لقطة الوسيط وحدها، فمركزٌ لم يظهر يسقط من السقف —
  أي أنّ الجهل بمركزٍ قائم يُقرأ «لا مركز»، فيُفتَح فوقه.

فصارت الحالة صريحة: `CONFIRMED` أو `STALE`، والإغلاق يحتاج تأكيداً متكرّراً،
والمراكز غيرُ المؤكَّدة تبقى مفتوحةً وتُعدّ.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.models import Base, PositionBookRow
from app.portfolio.book import OpenPosition, PortfolioSnapshot
from app.portfolio.ledger import (
    CLOSE_CONFIRMATIONS,
    RECON_CONFIRMED,
    RECON_STALE,
    STATE_OPEN,
    exposure,
    mark_restart,
    open_rows,
    stale_rows,
    sync,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as handle:
        yield handle


def _pos(deal_id: str, symbol: str = "EURUSD", qty: str = "100") -> OpenPosition:
    return OpenPosition(
        symbol=symbol,
        quantity=Decimal(qty),
        entry_price=Decimal("1.1"),
        stop_price=Decimal("1.0"),
        deal_id=deal_id,
        opened_utc=NOW,
    )


def _snap(*positions: OpenPosition, ok: bool = True, at: datetime = NOW) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        ok=ok, account_id="acct", as_of_utc=at, open_positions=list(positions)
    )


def _seed(session: Session) -> None:
    sync(session, _snap(_pos("d-1"), _pos("d-2", "GBPUSD", "-200")))


# ١ — الوسيط متاح: لا نافذةَ صفر، ولا فقدانَ تأكيد


def test_a_successful_snapshot_confirms_without_any_zero_window(session):
    _seed(session)
    rows = open_rows(session)
    assert len(rows) == 2
    assert {r.reconciliation for r in rows} == {RECON_CONFIRMED}
    assert all(r.last_confirmed_utc is not None for r in rows)
    assert stale_rows(session) == []


def test_a_restart_keeps_every_row_and_only_lowers_confidence(session):
    _seed(session)
    before = {r.broker_deal_id: (r.state, r.quantity, r.stop_price) for r in open_rows(session)}

    count = mark_restart(session)

    assert count == 2
    after = {r.broker_deal_id: (r.state, r.quantity, r.stop_price) for r in open_rows(session)}
    assert after == before, "الإقلاع غيّر ما نعرفه عن المركز، لا ثقتَنا فيه فقط"
    assert {r.reconciliation for r in open_rows(session)} == {RECON_STALE}
    assert len(stale_rows(session)) == 2
    # وتُعَدّ في التعرّض وهي غير مؤكَّدة
    assert exposure(open_rows(session)) == {
        "EURUSD": Decimal("100"),
        "GBPUSD": Decimal("-200"),
    }


# ٢ — الوسيط غير متاح


def test_a_failed_read_writes_nothing_at_all(session):
    _seed(session)
    mark_restart(session)
    before = [
        (r.broker_deal_id, r.state, r.reconciliation, r.absent_confirmations)
        for r in open_rows(session)
    ]

    assert sync(session, _snap(ok=False, at=LATER)) is None

    after = [
        (r.broker_deal_id, r.state, r.reconciliation, r.absent_confirmations)
        for r in open_rows(session)
    ]
    assert after == before
    assert len(stale_rows(session)) == 2, "الجهل لا يُقرأ تأكيداً"


# ٣ — لقطةٌ ناجحةٌ فارغة: إغلاقٌ بسياسةٍ مؤكَّدة، لا محوٌ صامت


def test_one_empty_but_successful_snapshot_closes_nothing(session):
    _seed(session)
    result = sync(session, _snap(at=LATER))

    assert result is not None
    assert result.closed == ()
    assert sorted(result.stale) == ["d-1", "d-2"]
    assert len(open_rows(session)) == 2
    assert {r.state for r in open_rows(session)} == {STATE_OPEN}
    assert len(result.notes_ar) >= 2, "غيابٌ بلا ملاحظة هو المحو الصامت نفسه"


def test_the_close_arrives_only_after_the_threshold(session):
    _seed(session)
    for _ in range(CLOSE_CONFIRMATIONS - 1):
        assert sync(session, _snap(at=LATER)).closed == ()
    final = sync(session, _snap(at=LATER))
    assert sorted(final.closed) == ["d-1", "d-2"]
    assert open_rows(session) == []
    assert any("مغلقاً" in note for note in final.notes_ar)


# ٥ — لا تكرار ولا تبدُّل هويّة


def test_no_row_is_duplicated_and_no_identity_changes(session):
    _seed(session)
    identity = sorted(r.broker_deal_id for r in open_rows(session))
    ids = sorted(r.id for r in open_rows(session))

    for _ in range(4):
        mark_restart(session)
        sync(session, _snap(_pos("d-1"), _pos("d-2", "GBPUSD", "-200"), at=LATER))

    rows = session.query(PositionBookRow).all()
    assert len(rows) == 2, "تكرّرت الصفوف عبر إعادات التشغيل"
    assert sorted(r.broker_deal_id for r in rows) == identity
    assert sorted(r.id for r in rows) == ids, "تبدّل مفتاحُ الصف"
    assert {r.reconciliation for r in rows} == {RECON_CONFIRMED}


def test_a_confirmed_close_is_labelled_confirmed(session):
    """صفٌّ كُتب مغلقاً بتأكيدٍ متكرّر ليس «غيرَ مؤكَّد».

    `reconciliation` تصف الثقة في `state`. فصفٌّ بقي `STALE` بعد الإغلاق
    يُقرأ «لا نعرف أمُغلقٌ هو» — وهو عكس ما جرى.
    """
    _seed(session)
    for _ in range(CLOSE_CONFIRMATIONS):
        sync(session, _snap(at=LATER))
    rows = session.query(PositionBookRow).all()
    assert {r.state for r in rows} == {"CLOSED"}
    assert {r.reconciliation for r in rows} == {RECON_CONFIRMED}, (
        "الإغلاق المؤكَّد وُسم غيرَ مؤكَّد"
    )
