# -*- coding: utf-8 -*-
"""
عدّادُ الخسائر **ينسى** — وهذا ما يفكّ الحلقة المغلقة.

## العطل المقيس (٨ سبتمبر ٢٠٢٦)

كان `_consecutive_losses` يقرأ ذيلَ الدفتر بلا نافذةٍ زمنية إطلاقاً. وثلاثةُ
إغلاقاتٍ خاسرة — كلُّها GBPUSD بيعاً، وكلُّها من فكرةٍ واحدةٍ نُفِّذت ثلاث
مرّات يوم ٤ سبتمبر — أوقفت النظام، ولا شيء في الكود يفكّ الوقف: العدّاد لا
ينزل إلا بإغلاقٍ رابح، والرابحُ يحتاج صفقةً، والصفقةُ ممنوعةٌ بالعدّاد.

فالحارسُ لم يكن تهدئةً بل قفلاً أبديّاً. وقاعدةُ المشروع تقول عكسه بنصّها:
«لا تجعل خسارتين متتاليتين سببًا لإيقاف النظام إلى أجل غير محدد».

هذه الحزمة تحرس أن النسيان **يقع فعلاً**، وأنه **لا يُنسي ما يجب أن يُعَدّ**.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, PositionBookRow
from app.risk.session_state import CONSECUTIVE_LOSS_WINDOW_HOURS, _consecutive_losses

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _close(s: Session, *, hours_ago: float, pnl, symbol: str = "GBPUSD",
           recon: str = "CONFIRMED", state: str = "CLOSED") -> None:
    n = len(s.execute(__import__("sqlalchemy").select(PositionBookRow.id)).all())
    s.add(PositionBookRow(
        broker_deal_id=f"deal-{n}-{hours_ago}",
        account_id="****2590",
        symbol=symbol,
        quantity=Decimal("-200"),
        entry_price=Decimal("1.35"),
        stop_price=Decimal("1.355"),
        take_profit_price=Decimal("1.344"),
        currency="USD",
        state=state,
        reconciliation=recon,
        # `first_seen_utc` و`last_seen_utc` إلزاميّان في المخطّط: الدفتر يسجّل
        # متى رأى المركز أوّل مرّة وآخر مرّة، ولا يقبل صفّاً بلا ذلك.
        first_seen_utc=(NOW - timedelta(hours=hours_ago + 48)).replace(tzinfo=None),
        last_seen_utc=(NOW - timedelta(hours=hours_ago)).replace(tzinfo=None),
        closed_at_utc=(NOW - timedelta(hours=hours_ago)).replace(tzinfo=None),
        realised_pnl=None if pnl is None else Decimal(str(pnl)),
    ))
    s.flush()


class TestTheWindowForgets:
    def test_three_losses_inside_the_window_are_all_counted(self, session: Session) -> None:
        for h in (1, 5, 10):
            _close(session, hours_ago=h, pnl="-0.73")
        assert _consecutive_losses(session, at=NOW) == 3

    def test_a_loss_older_than_the_window_is_not_counted(self, session: Session) -> None:
        """الحافّة **تتجاهل** ولا **توقف**: القديمُ يسقط من الاستعلام أصلاً."""
        _close(session, hours_ago=1, pnl="-0.73")
        _close(session, hours_ago=CONSECUTIVE_LOSS_WINDOW_HOURS + 1, pnl="-0.69")
        assert _consecutive_losses(session, at=NOW) == 1

    def test_everything_outside_the_window_means_zero(self, session: Session) -> None:
        """وهذا هو فكُّ الحلقة: الوقتُ وحده يُنهي التهدئة."""
        for h in (30, 40, 50):
            _close(session, hours_ago=h, pnl="-0.73")
        assert _consecutive_losses(session, at=NOW) == 0

    def test_the_boundary_is_inclusive_and_does_not_drift(self, session: Session) -> None:
        _close(session, hours_ago=CONSECUTIVE_LOSS_WINDOW_HOURS - 0.01, pnl="-0.73")
        assert _consecutive_losses(session, at=NOW) == 1


class TestWhatMustStillStopTheCount:
    def test_a_win_stops_the_chain(self, session: Session) -> None:
        _close(session, hours_ago=1, pnl="-0.73")
        _close(session, hours_ago=2, pnl="0.90")
        _close(session, hours_ago=3, pnl="-0.69")
        assert _consecutive_losses(session, at=NOW) == 1

    def test_an_unknown_stops_the_chain_and_is_not_a_win(self, session: Session) -> None:
        """صفقةٌ لا نعرف نتيجتها لا تُعَدّ خسارةً ولا تُعَدّ ربحاً يقطع بأمان."""
        _close(session, hours_ago=1, pnl="-0.73")
        _close(session, hours_ago=2, pnl=None)
        _close(session, hours_ago=3, pnl="-0.69")
        assert _consecutive_losses(session, at=NOW) == 1

    def test_an_open_position_is_not_counted(self, session: Session) -> None:
        _close(session, hours_ago=1, pnl="-0.73", state="OPEN")
        _close(session, hours_ago=2, pnl="-0.69")
        assert _consecutive_losses(session, at=NOW) == 1

    def test_an_unconfirmed_close_is_not_counted(self, session: Session) -> None:
        """المطابقةُ شرط: رقمٌ لم يؤكّده الوسيط لا يُوقف التداول."""
        _close(session, hours_ago=1, pnl="-0.73", recon="STALE")
        _close(session, hours_ago=2, pnl="-0.69")
        assert _consecutive_losses(session, at=NOW) == 1

    def test_zero_is_not_a_loss(self, session: Session) -> None:
        _close(session, hours_ago=1, pnl="0")
        assert _consecutive_losses(session, at=NOW) == 0


class TestTheDeadlockIsGone:
    def test_the_pause_expires_by_time_alone(self, session: Session) -> None:
        """
        الاختبارُ الذي يمثّل العطل نفسه: خسارتان تُقفلان، ثم يمضي الوقت
        **بلا صفقةٍ رابحة** — وتنفكّ التهدئة. هذا مستحيلٌ في الكود القديم.
        """
        _close(session, hours_ago=0, pnl="-0.73")
        _close(session, hours_ago=1, pnl="-0.69")
        assert _consecutive_losses(session, at=NOW) == 2

        later = NOW + timedelta(hours=CONSECUTIVE_LOSS_WINDOW_HOURS + 1)
        assert _consecutive_losses(session, at=later) == 0
