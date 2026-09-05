"""
حالةُ المخاطرة تُقرأ من الدفتر الذي نكتبه — لا من جدولٍ لم يدخله صفٌّ قط.

يوم 2026-09-05 كان `load_session_state` يبني أربعةَ عدّاداتٍ من جدول `trades`:
`realized_pnl_today` و`realized_pnl_week` و`consecutive_losses` و
`entry_orders_today`. ولا سطرَ في المستودع كلّه ينشئ `TradeRow`. فكانت أربعتُها
صفراً دائماً، وكان حدُّ الخسارة اليومي والأسبوعي وتهدئةُ الخسارتين المتتاليتين
وسقفُ الدخول اليومي **عاجزةً عن العمل بنيوياً**.

وهذه الاختبارات تُثبت أنّ الخسارة تصل الآن إلى العدّاد الذي يوقف التداول،
وأنّ ما لا نعرفه يُعَدّ جهلاً ولا يُطرَح صفراً.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clock import now_utc, trading_day_bounds_utc
from app.db.models import Base, PositionBookRow
from app.risk import session_state as ss

BASELINE = Decimal("300")


@pytest.fixture()
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _closed(session, deal_id, pnl, *, when=None, symbol="EURUSD"):
    """صفٌّ مغلقٌ بنتيجةٍ — أو بلا نتيجة إن كانت `pnl` هي `None`."""
    day_start, _ = trading_day_bounds_utc(now_utc())
    at = when or (day_start + timedelta(hours=1))
    row = PositionBookRow(
        broker_deal_id=deal_id,
        symbol=symbol,
        quantity=Decimal("1"),
        state="CLOSED",
        first_seen_utc=at,
        last_seen_utc=at,
        opened_at_utc=at,
        closed_at_utc=at,
        realised_pnl=pnl,
    )
    session.add(row)
    session.commit()
    return row


def _open(session, deal_id, *, symbol="EURUSD"):
    day_start, _ = trading_day_bounds_utc(now_utc())
    at = day_start + timedelta(hours=1)
    row = PositionBookRow(
        broker_deal_id=deal_id,
        symbol=symbol,
        quantity=Decimal("1"),
        state="OPEN",
        first_seen_utc=at,
        last_seen_utc=at,
        opened_at_utc=at,
    )
    session.add(row)
    session.commit()
    return row


def _state(session):
    return ss.load_session_state(session, baseline_equity=BASELINE)


class TestTheSourceIsTheBookWeWrite:
    def test_the_dead_table_is_no_longer_read(self):
        """
        `TradeRow` لا يُستعمَل في بناء حالة المخاطرة.

        والفحص بالشجرة النحوية لا بالبحث النصّي: التوثيق هنا **يذكر** الجدول
        الميّت عمداً ليشرح ما جرى، وبحثٌ نصّيٌّ ساذج يقرأ الشرح استعمالاً
        فيفشل على تعليقٍ صادق. الشجرة ترى الأسماء المستعملة وحدها.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(ss))
        used = {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        } | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert "TradeRow" not in used, (
            "حالةُ المخاطرة عادت تقرأ من `trades` — وهو جدولٌ لا يُكتَب فيه. "
            "المصدر هو `position_book`."
        )
        assert "PositionBookRow" in used

    def test_a_loss_today_reaches_the_day_counter(self, session):
        """خسارةٌ مغلقةٌ اليوم تصل إلى العدّاد الذي يوقف التداول."""
        _closed(session, "d1", Decimal("-12.50"))
        state = _state(session)
        assert state.realized_pnl_today == Decimal("-12.50")
        assert state.day_loss == Decimal("12.50")
        assert state.current_equity == BASELINE - Decimal("12.50")

    def test_an_open_row_is_counted_as_exposure(self, session):
        _open(session, "d2", symbol="GBPUSD")
        state = _state(session)
        assert state.open_positions == 1
        assert state.open_symbols == ("GBPUSD",)

    def test_entries_today_counts_what_opened_today(self, session):
        _open(session, "d3")
        _closed(session, "d4", Decimal("1"))
        state = _state(session)
        assert state.entry_orders_today == 2


class TestTheStreakStopsAtWhatWeKnow:
    def test_two_losses_in_a_row_are_two(self, session):
        base, _ = trading_day_bounds_utc(now_utc())
        _closed(session, "a", Decimal("-3"), when=base + timedelta(hours=1))
        _closed(session, "b", Decimal("-4"), when=base + timedelta(hours=2))
        assert _state(session).consecutive_losses == 2

    def test_a_win_breaks_the_streak(self, session):
        base, _ = trading_day_bounds_utc(now_utc())
        _closed(session, "a", Decimal("-3"), when=base + timedelta(hours=1))
        _closed(session, "b", Decimal("5"), when=base + timedelta(hours=2))
        _closed(session, "c", Decimal("-4"), when=base + timedelta(hours=3))
        assert _state(session).consecutive_losses == 1

    def test_an_unknown_result_stops_the_count_without_claiming_a_win(self, session):
        """
        صفقةٌ لا نعرف نتيجتها لا تُعَدّ خسارةً ولا تُعَدّ ربحاً يقطع السلسلة.

        فيقف العدّاد عندها على آخر ما نعرفه يقيناً — ولا يُبالَغ في التهدئة
        ولا يُهوَّن منها.
        """
        base, _ = trading_day_bounds_utc(now_utc())
        _closed(session, "a", Decimal("-3"), when=base + timedelta(hours=1))
        _closed(session, "b", None, when=base + timedelta(hours=2))
        _closed(session, "c", Decimal("-4"), when=base + timedelta(hours=3))
        assert _state(session).consecutive_losses == 1


class TestIgnoranceIsCountedNotSubtracted:
    def test_a_close_without_a_result_is_not_a_zero(self, session):
        """`None` ليست ربحاً صفراً — تُعَدّ جهلاً معلَناً."""
        _closed(session, "a", Decimal("-10"))
        _closed(session, "b", None)
        state = _state(session)
        assert state.realized_pnl_today == Decimal("-10")
        assert state.unknown_realised_closes == 1

    def test_a_complete_book_declares_no_ignorance(self, session):
        _closed(session, "a", Decimal("-10"))
        _closed(session, "b", Decimal("2"))
        assert _state(session).unknown_realised_closes == 0

    def test_an_empty_book_is_not_ignorance(self, session):
        """لا صفقةَ مغلقة ≠ صفقةٌ مجهولة. الفراغُ الصادقُ ليس جهلاً."""
        state = _state(session)
        assert state.unknown_realised_closes == 0
        assert state.realized_pnl_today == Decimal("0")
        assert state.current_equity == BASELINE


class TestTheGateRefusesToTradeOverIgnorance:
    def test_the_heartbeat_has_a_reason_code_for_it(self):
        from app.runtime import heartbeat

        assert heartbeat.REALISED_PNL_INCOMPLETE == "REALISED_PNL_INCOMPLETE"

    def test_the_gate_is_wired_after_the_state_is_read(self):
        """البوابة تُقرأ بعد الحالة لا قبلها — وإلا حكمت على حالةٍ لم تُبنَ."""
        import inspect

        from app.runtime import heartbeat

        source = inspect.getsource(heartbeat)
        load_at = source.index("session_state = load_session_state(")
        gate_at = source.index("unknown_realised_closes")
        assert load_at < gate_at
