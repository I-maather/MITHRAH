"""
الدفترُ ينجو إعادةَ التشغيل — وما لم يُرَ لا يُكتَب أنه أُغلق.

## ما الذي يحرسه هذا الملف

قراءةُ الوسيط كلَّ دورة (C2) أصلحت سقفَ العدد، لكنها لا تنجو من إعادة تشغيل:
ما لا يُكتَب لا يُقارَن بعد الإقلاع. فلا يُعرَف مركزٌ **فُتح بيننا** من مركزٍ
وجدناه، ولا يُكشَف مركزٌ اختفى بلا صفقةٍ تقابله، ولا يُعرَف أيُّ استراتيجيةٍ
بأيّ إصدار تحمل أيَّ مركز.

والمفتاح `broker_deal_id` لا الرمز: كابيتال يسمح بعدّة مراكز على الأداة
الواحدة — وكان على GBPUSD ثلاثة في يومٍ واحد — فمفتاحٌ بالرمز يُسقط أحدها
على الآخر ويقول «مطابَق».
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, BrokerOrderRow, OrderIntentRow, PositionBookRow
from app.money import D
from app.portfolio.book import (
    KIND_COMMISSIONING,
    KIND_STRATEGY,
    KIND_UNATTRIBUTED,
    OpenPosition,
    PortfolioSnapshot,
    unavailable,
    PORTFOLIO_BROKER_UNREACHABLE,
)
from app.portfolio.ledger import (
    ATTRIBUTION_LINKED,
    ATTRIBUTION_UNLINKED,
    STATE_CLOSED,
    STATE_OPEN,
    exposure,
    mark_restart,
    open_rows,
    sync,
)

NOW = datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=5)


def _utc(value: datetime) -> datetime:
    """
    SQLite لا يحفظ المنطقة الزمنية، فيعود التاريخ ساذجاً.

    القيمة **مكتوبةٌ بـUTC دائماً** — لا يوجد مسارٌ يكتب غيرها — فالمقارنة
    تُسوّى هنا بدل أن يُحشَر تحويلٌ في كل قراءة. ولو تغيّر ذلك يوماً، فهذا
    السطر هو الذي يجب أن يسقط أوّلاً.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        yield s


def _position(deal_id: str, symbol: str, quantity: str, *, stop=None, reference=None):
    return OpenPosition(
        symbol=symbol,
        quantity=D(quantity),
        entry_price=D("1.35"),
        stop_price=D(stop) if stop is not None else None,
        deal_id=deal_id,
        deal_reference=reference,
    )


def _snapshot(*positions, at=NOW, ok=True):
    return PortfolioSnapshot(
        as_of_utc=at, ok=ok, account_id="acct", open_positions=tuple(positions)
    )


def _linked_order(session, *, deal_id, reference, client_order_id, strategy, version):
    session.add(
        BrokerOrderRow(
            broker_order_id=f"bo-{deal_id}",
            deal_reference=reference,
            broker_deal_id=deal_id,
            client_order_id=client_order_id,
            symbol="GBPUSD", side="SELL", order_type="MARKET",
            quantity=D("200"), filled_quantity=D("200"),
            status="FILLED", updated_at_utc=NOW,
        )
    )
    session.add(
        OrderIntentRow(
            idempotency_key=f"idem-{client_order_id}",
            client_order_id=client_order_id,
            strategy_name=strategy, strategy_version=version,
            symbol="GBPUSD", side="SELL", order_type="MARKET",
            quantity=D("200"), expected_fill_price=D("1.35"),
            max_slippage_abs=D("0.0005"), exit_plan_ar="—",
            instrument_snapshot_json="{}", created_at_utc=NOW,
        )
    )
    session.commit()


# --- ١ · المركز ينجو إعادة التشغيل -----------------------------------------


def test_an_open_position_is_still_in_the_book_after_a_restart(session):
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200")))

    # إعادة تشغيل: عمليةٌ جديدة تقرأ الجدول نفسه.
    assert mark_restart(session) == 1
    rows = open_rows(session)
    assert [r.broker_deal_id for r in rows] == ["d-1"]
    assert rows[0].seen_after_restart is False, "قبل أوّل قراءة لا يُدّعى أنه رُئي"

    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200"), at=LATER))
    assert open_rows(session)[0].seen_after_restart is True


# --- ٢ · لقطةٌ فاشلة لا تُغلق شيئاً ----------------------------------------


def test_a_failed_read_never_closes_the_book(session):
    """**العطل الأخطر الممكن هنا**: تحويلُ عجزٍ عن القراءة إلى إغلاقٍ مكتوب."""
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200")))

    result = sync(
        session,
        unavailable(at=LATER, reason_code=PORTFOLIO_BROKER_UNREACHABLE, error_ar="سقطت الشبكة"),
    )

    assert result is None
    assert [r.broker_deal_id for r in open_rows(session)] == ["d-1"]


# --- ٣ · الإغلاق يُكتَب حين يُرى فعلاً ------------------------------------


def test_a_position_that_left_the_broker_is_marked_closed(session):
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200")))
    result = sync(session, _snapshot(at=LATER))

    assert result is not None and result.closed == ("d-1",)
    assert open_rows(session) == []
    row = session.query(PositionBookRow).one()
    assert row.state == STATE_CLOSED and _utc(row.closed_at_utc) == LATER


def test_a_position_that_returns_is_reopened_not_duplicated(session):
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200")))
    sync(session, _snapshot(at=LATER))
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200"), at=LATER + timedelta(minutes=1)))

    assert session.query(PositionBookRow).count() == 1
    assert session.query(PositionBookRow).one().state == STATE_OPEN


# --- ٤ · عدّة مراكز على أداة واحدة -----------------------------------------


def test_three_positions_on_one_symbol_are_three_rows(session):
    sync(session, _snapshot(
        _position("d-1", "GBPUSD", "-200"),
        _position("d-2", "GBPUSD", "-200"),
        _position("d-3", "GBPUSD", "-200"),
    ))

    rows = open_rows(session)
    assert len(rows) == 3
    assert exposure(rows) == {"GBPUSD": D("-600")}


# --- ٥ · النسب ---------------------------------------------------------------


def test_a_position_is_linked_to_the_strategy_that_opened_it(session):
    _linked_order(
        session, deal_id="d-1", reference="ref-1",
        client_order_id="coid-1", strategy="SHORT_SYMMETRY", version="v3",
    )
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200", reference="ref-1")))

    row = open_rows(session)[0]
    assert row.attribution == ATTRIBUTION_LINKED
    assert row.kind == KIND_STRATEGY
    assert (row.strategy_name, row.strategy_version) == ("SHORT_SYMMETRY", "v3")
    assert row.client_order_id == "coid-1"


def test_a_commissioning_position_is_named_commissioning(session):
    _linked_order(
        session, deal_id="d-9", reference="ref-9",
        client_order_id="coid-9", strategy="COMMISSIONING", version="v1",
    )
    sync(session, _snapshot(_position("d-9", "EURUSD", "100", reference="ref-9")))
    assert open_rows(session)[0].kind == KIND_COMMISSIONING


def test_an_unknown_position_is_named_unattributed_not_guessed(session):
    """
    مركزٌ لا أمرَ لنا يحمل هويّته لا يُنسَب بالرمز والتوقيت: مركزان على
    الأداة نفسها في الدقيقة نفسها يُنسبان خطأً، ونسبةٌ خاطئة تُقرأ معرفةً.
    """
    result = sync(session, _snapshot(_position("d-ghost", "GOLD", "-0.01")))

    row = open_rows(session)[0]
    assert row.attribution == ATTRIBUTION_UNLINKED
    assert row.kind == KIND_UNATTRIBUTED
    assert row.strategy_name == ""
    assert result is not None and result.unattributed == ("d-ghost",)


def test_attribution_falls_back_to_the_deal_reference(session):
    """الوسيط يعطي المرجع أوّلاً والهويّة بعد التأكيد — فكلاهما مقبول."""
    session.add(
        BrokerOrderRow(
            broker_order_id="bo-x", deal_reference="ref-x", broker_deal_id=None,
            client_order_id="coid-x", symbol="EURUSD", side="BUY", order_type="MARKET",
            quantity=D("300"), filled_quantity=D("300"), status="FILLED", updated_at_utc=NOW,
        )
    )
    session.add(
        OrderIntentRow(
            idempotency_key="idem-x", client_order_id="coid-x",
            strategy_name="MOMENTUM", strategy_version="v2",
            symbol="EURUSD", side="BUY", order_type="MARKET", quantity=D("300"),
            expected_fill_price=D("1.16"), max_slippage_abs=D("0.0005"),
            exit_plan_ar="—", instrument_snapshot_json="{}", created_at_utc=NOW,
        )
    )
    session.commit()

    sync(session, _snapshot(_position("d-x", "EURUSD", "300", reference="ref-x")))
    row = open_rows(session)[0]
    assert row.attribution == ATTRIBUTION_LINKED
    assert row.strategy_version == "v2"


# --- ٦ · التغيّر يُسجَّل ------------------------------------------------------


def test_a_moved_stop_is_recorded_as_a_change(session):
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200", stop="1.3555")))
    result = sync(
        session,
        _snapshot(_position("d-1", "GBPUSD", "-200", stop="1.3520"), at=LATER),
    )

    assert result is not None and result.changed == ("d-1",)
    assert open_rows(session)[0].stop_price == D("1.3520")


def test_an_unchanged_position_is_not_reported_as_changed(session):
    sync(session, _snapshot(_position("d-1", "GBPUSD", "-200", stop="1.3555")))
    result = sync(
        session,
        _snapshot(_position("d-1", "GBPUSD", "-200", stop="1.3555"), at=LATER),
    )
    assert result is not None and result.changed == ()


# --- ٧ · مركزٌ بلا هويّة ------------------------------------------------------


def test_a_position_without_a_broker_identity_is_not_invented(session):
    """
    مفتاحٌ مخترَع يُنشئ مركزاً جديداً كلَّ دورة، فينتفخ الدفتر بأشباح تُقرأ
    على أنها تعرّض حقيقيّ.
    """
    result = sync(session, _snapshot(OpenPosition(symbol="GOLD", quantity=D("-0.01"))))

    assert open_rows(session) == []
    assert result is not None and any("بلا هويّة" in n for n in result.notes_ar)


# --- ٨ · أوّل مزامنة ---------------------------------------------------------


def test_the_first_sighting_is_reported_as_opened(session):
    result = sync(session, _snapshot(_position("d-1", "GBPUSD", "-200")))
    assert result is not None
    assert result.opened == ("d-1",) and result.closed == ()
    assert _utc(open_rows(session)[0].first_seen_utc) == NOW
