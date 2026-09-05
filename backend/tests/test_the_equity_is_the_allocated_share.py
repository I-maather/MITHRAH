"""
حقوقُ الملكية = **حصّةُ الاستراتيجية**، لا رصيدُ الحساب.

`total_loss = baseline − current_equity`. وعلى حسابٍ تجريبيّ رصيده تسعون ألفاً
والحصّةُ المخصَّصة ثلاثمئة، لو أُخذ الرصيدُ الخام لصارت:

    total_loss = max(0, 300 − 90,000) = 0     ← أبداً، مهما خسرنا

فحاجزُ التراجع التشغيلي يُعطَّل بنيوياً — وهو الحاجزُ نفسه الذي كنّا نُصلحه.
والفارقُ هنا تصميمٌ لا انحراف: النتائج تُقاس كما لو كان الحساب ثلاثمئة.

فالمقياس: **المخصَّص + المحقَّق المؤكَّد + غير المحقَّق من لقطة الوسيط**.
ويبقى `broker_equity` مقروءاً حيّاً للكفاية والهامش وكشف الانحراف.
(قرار المالكة 2026-09-05)
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clock import now_utc
from app.db.models import Base, PositionBookRow
from app.risk import session_state as ss

ALLOCATED = Decimal("300")
DEMO_BALANCE = Decimal("90000")


@pytest.fixture()
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _broker(net_liquidation=DEMO_BALANCE, *, raises=False):
    class B:
        def get_accounts(self):
            return ["acct"]

        def get_balances(self, account_id=""):
            if raises:
                raise RuntimeError("مفصول")
            return SimpleNamespace(
                account_id=account_id,
                net_liquidation=net_liquidation,
                as_of_utc=now_utc(),
            )

    return B()


def _snapshot(*positions, ok=True):
    return SimpleNamespace(ok=ok, open_positions=tuple(positions))


def _position(symbol="EURUSD", upl=Decimal("0")):
    return SimpleNamespace(symbol=symbol, unrealised_pnl=upl)


def _closed(session, deal_id, pnl):
    at = now_utc() - timedelta(hours=1)
    session.add(PositionBookRow(
        broker_deal_id=deal_id, symbol="EURUSD", quantity=Decimal("1"),
        state="CLOSED", reconciliation="CONFIRMED",
        first_seen_utc=at, last_seen_utc=at, closed_at_utc=at, realised_pnl=pnl,
    ))
    session.commit()


class TestTheMeasureIsTheAllocatedShare:
    def test_a_huge_demo_balance_does_not_become_our_equity(self, session):
        reading = ss.read_equity(_broker(), snapshot=_snapshot())
        state = ss.load_session_state(
            session, baseline_equity=ALLOCATED, equity=reading
        )
        assert state.current_equity == ALLOCATED, (
            "رصيدُ الحساب صار حقوقَ الملكية — وبه يُعطَّل حاجزُ التراجع."
        )
        assert state.broker_equity == DEMO_BALANCE
        assert state.equity_known is True

    def test_the_drawdown_guard_can_actually_fire(self, session):
        """الاختبارُ الذي يهمّ: هل تصل الخسارةُ إلى `total_loss`؟"""
        _closed(session, "a", Decimal("-6.50"))
        reading = ss.read_equity(_broker(), snapshot=_snapshot())
        state = ss.load_session_state(
            session, baseline_equity=ALLOCATED, equity=reading
        )
        assert state.current_equity == Decimal("293.50")
        assert state.total_loss == Decimal("6.50")

    def test_an_unrealised_loss_lowers_the_equity_now(self, session):
        """المركزُ الغارقُ يُنقص حقوقَ الملكية الآن، لا عند إغلاقه."""
        reading = ss.read_equity(
            _broker(), snapshot=_snapshot(_position(upl=Decimal("-4")))
        )
        state = ss.load_session_state(
            session, baseline_equity=ALLOCATED, equity=reading
        )
        assert state.unrealized_pnl == Decimal("-4")
        assert state.current_equity == Decimal("296")
        assert state.total_loss == Decimal("4")


class TestIgnoranceBlocksInsteadOfDefaulting:
    def test_a_disconnected_broker_is_not_a_known_equity(self, session):
        reading = ss.read_equity(_broker(raises=True), snapshot=_snapshot())
        state = ss.load_session_state(
            session, baseline_equity=ALLOCATED, equity=reading
        )
        assert state.equity_known is False
        assert state.broker_equity is None
        assert "تعذّرت" in state.equity_reason_ar

    def test_a_missing_net_liquidation_is_not_replaced_by_cash(self, session):
        reading = ss.read_equity(_broker(net_liquidation=None), snapshot=_snapshot())
        assert reading.ok is False
        assert "صافي التصفية" in reading.reason_ar

    def test_one_position_without_a_pnl_makes_the_whole_sum_unknown(self, session):
        """حذفُ مركزٍ من المجموع يُصغّر الخسارة — فالنقصُ جهلٌ لا صفر."""
        reading = ss.read_equity(
            _broker(),
            snapshot=_snapshot(
                _position("EURUSD", Decimal("-3")), _position("GOLD", None)
            ),
        )
        assert reading.ok is False
        assert reading.unrealised is None
        state = ss.load_session_state(
            session, baseline_equity=ALLOCATED, equity=reading
        )
        assert state.equity_known is False

    def test_an_unread_snapshot_is_not_zero_positions(self, session):
        reading = ss.read_equity(_broker(), snapshot=_snapshot(ok=False))
        assert reading.ok is False

    def test_no_open_positions_is_an_honest_zero(self, session):
        """لا مركزَ مفتوح ≠ لم أقرأ. الأولى معلومةٌ والثانية مجهولة."""
        reading = ss.read_equity(_broker(), snapshot=_snapshot())
        assert reading.ok is True
        assert reading.unrealised == Decimal("0")

    def test_no_reading_at_all_is_unknown_and_stale(self, session):
        state = ss.load_session_state(session, baseline_equity=ALLOCATED)
        assert state.equity_known is False
        assert state.equity_stale is True


class TestStaleness:
    def test_a_fresh_reading_is_not_stale(self):
        reading = ss.read_equity(_broker(), snapshot=_snapshot())
        assert reading.is_stale() is False

    def test_a_reading_older_than_the_threshold_is_stale(self):
        old = ss.EquityReading(
            broker_equity=Decimal("300"),
            unrealised=Decimal("0"),
            as_of_utc=now_utc() - ss.EQUITY_STALE_AFTER - timedelta(seconds=1),
            ok=True,
            reason_ar="",
        )
        assert old.is_stale() is True

    def test_the_threshold_is_the_one_the_owner_chose(self):
        assert ss.EQUITY_STALE_AFTER == timedelta(seconds=120)


class TestTheGatesExist:
    def test_the_heartbeat_carries_both_reason_codes(self):
        from app.runtime import heartbeat

        assert heartbeat.EQUITY_UNKNOWN == "EQUITY_UNKNOWN"
        assert heartbeat.RISK_STATE_STALE == "RISK_STATE_STALE"

    def test_the_equity_is_read_after_the_snapshot_not_before(self):
        """
        غيرُ المحقَّق جزءٌ من حقوق الملكية ولا يُعرَف إلا من المراكز.
        فقياسُه قبل قراءتها قياسٌ على نصف الحقيقة.
        """
        import inspect

        from app.runtime import heartbeat

        source = inspect.getsource(heartbeat)
        snapshot_at = source.index('snapshot = getattr(state, "portfolio", None)')
        equity_at = source.index("equity = read_equity(")
        assert snapshot_at < equity_at


class TestTheContractIsWhatWeMayAssume:
    """
    `get_accounts` ليست في `BrokerAdapter` — و`get_balances(account_id)` هي.

    اشتراطُ الأولى حوّل وسيطاً سليماً إلى `EQUITY_UNKNOWN` عبر `AttributeError`
    تُبتلَع في `except`. وهو نفسُ عطل `get_account_snapshot`: **اسمٌ كُتب من
    الذاكرة لا من العقد**، في مسارٍ لا يُنفَّذ حتى يُنفَّذ.
    """

    def test_a_broker_without_get_accounts_still_gives_its_equity(self):
        class Minimal:
            def get_balances(self, account_id=""):
                return SimpleNamespace(
                    net_liquidation=Decimal("300"), as_of_utc=now_utc()
                )

        reading = ss.read_equity(Minimal(), snapshot=_snapshot())
        assert reading.ok is True, (
            "وسيطٌ يملك ما يوجبه العقد رُفض لأنه لا يملك ما لا يوجبه."
        )
        assert reading.broker_equity == Decimal("300")

    def test_a_failing_get_accounts_does_not_block_the_reading(self):
        class Grumpy:
            def get_accounts(self):
                raise RuntimeError("لا قائمة حسابات")

            def get_balances(self, account_id=""):
                return SimpleNamespace(
                    net_liquidation=Decimal("300"), as_of_utc=now_utc()
                )

        assert ss.read_equity(Grumpy(), snapshot=_snapshot()).ok is True
