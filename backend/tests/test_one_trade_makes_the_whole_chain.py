"""
سلسلةُ الأمر كاملةً — من قرار المخاطر إلى إغلاقٍ مؤكَّد يبلغ عدّاد الخسارة.

هذا الاختبار هو البرهان الذي طُلب: **صفقةٌ واحدة تُنتج السلسلة كلَّها**.

    risk_decision → order_intent → execution_attempt → broker_order
                  → execution → position_book(OPEN)
                  → إغلاقٌ بدليلٍ مستقلّ → CLOSED/CONFIRMED
                  → الخسارة تبلغ `realized_pnl_today` و`day_loss`

وكلُّ حلقةٍ منها كانت مفقودةً أو فارغةً يوم 2026-09-05: الجداول الستّة كانت
صفراً على الخادم الحيّ، وأربعُ بوّاباتِ مخاطرةٍ تقرأ من فراغ.

ويُشغَّل على `MockBrokerAdapter` — وسيطِ المشروع نفسه — لا على وسيطٍ مكتوبٍ
لأجل الاختبار. فالوسيطُ المصنوعُ في الاختبار يوافق ما يظنّه كاتبُه صحيحاً،
وهذا بعينه ما يُخفي عيبَ عدمِ التركيب: عقودُ `OrderPreview` و`BrokerOrder`
و`Execution` هنا هي عقودُ الإنتاج، ومعرّفاتُ الوسيط تُقرأ منه لا تُملى عليه.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.audit.log import AuditLog, InMemoryAuditStore
from app.brokers.mock import DEFAULT_ACCOUNT, MockBehaviour, MockBrokerAdapter
from app.clock import now_utc
from app.contracts import OrderIntent, OrderType, Side
from app.db.models import (
    Base,
    BrokerOrderRow,
    ExecutionAttempt,
    ExecutionRow,
    OrderIntentRow,
    PositionBookRow,
    RiskDecisionRow,
)
from app.execution.journal import ExecutionJournal
from app.execution.orders import ExecutionService, IdempotencyGuard
from app.portfolio import ledger
from app.portfolio.book import ClosedTrade, OpenPosition, PortfolioSnapshot
from app.risk.session_state import load_session_state

ALLOCATED = Decimal("300")

#: انزلاقٌ صغيرٌ مقصود: سعرُ التنفيذ يجب أن يأتي من الوسيط لا من النيّة.
SLIPPAGE = Decimal("0.0001")
COMMISSION = Decimal("0.02")
EXPECTED = Decimal("1.16")
FILLED_AT = EXPECTED + SLIPPAGE


@pytest.fixture()
def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture()
def broker() -> MockBrokerAdapter:
    b = MockBrokerAdapter(behaviour=MockBehaviour(slippage=SLIPPAGE))
    b.connect()
    return b


class _Decision:
    """قرارُ مخاطرةٍ موافِق — بأقلّ ما يحتاجه العقد."""

    approved = True
    reason_code = None
    reason_ar = "مرّت البوّابات الإحدى عشرة."
    checks = (("حدّ الخسارة اليومي", True, "لم يُبلَغ"),)
    quantity = Decimal("1")
    expected_risk_usd = Decimal("0.73")
    expected_costs_usd = COMMISSION
    risk_budget_usd = Decimal("1.50")
    constitution_fingerprint = "fp-test"
    decided_at_utc = now_utc()


class _Rejected(_Decision):
    approved = False
    reason_code = "DAILY_LOSS_REACHED"
    reason_ar = "بلغت خسارةُ اليوم حدَّها."


def _intent(key="k-1") -> OrderIntent:
    return OrderIntent(
        idempotency_key=key,
        client_order_id="MAT-" + key,
        symbol="EURUSD",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        limit_price=None,
        stop_price=Decimal("1.1527"),
        expected_fill_price=EXPECTED,
        max_slippage_abs=Decimal("0.001"),
        strategy_name="T",
        strategy_version="1",
        risk_amount_usd=Decimal("0.73"),
        commission_estimate_usd=COMMISSION,
        exit_plan_ar="وقفٌ وهدف.",
        instrument_snapshot={},
        created_at_utc=now_utc(),
    )


def _service(factory, broker) -> ExecutionService:
    return ExecutionService(
        broker=broker,
        audit=AuditLog(InMemoryAuditStore()),
        guard=IdempotencyGuard(session_factory=factory),
        journal=ExecutionJournal(session_factory=factory),
    )


class TestOneTradeProducesTheWholeChain:
    def test_every_link_is_written(self, factory, broker):
        service = _service(factory, broker)
        intent = _intent()

        # ١) قرارُ المخاطر — يُكتَب قبل النيّة ويحمل مفتاحها.
        decision_id = service.journal.decided(
            _Decision(), symbol="EURUSD", intent_key=intent.idempotency_key
        )
        assert decision_id is not None

        # ٢) الإرسال — والجريدة تكتب ما قبله وما بعده.
        result = service.submit(intent)
        assert result.outcome.value in {"FILLED", "PARTIALLY_FILLED"}

        with factory() as session:
            decisions = list(session.execute(select(RiskDecisionRow)).scalars())
            intents = list(session.execute(select(OrderIntentRow)).scalars())
            attempts = list(session.execute(select(ExecutionAttempt)).scalars())
            orders = list(session.execute(select(BrokerOrderRow)).scalars())
            fills = list(session.execute(select(ExecutionRow)).scalars())

        assert len(decisions) == 1, "قرارُ المخاطر لم يُكتَب"
        assert decisions[0].symbol == "EURUSD"
        assert len(intents) == 1, "النيّة لم تُكتَب"
        assert len(attempts) == 1, "المحاولة لم تُكتَب"
        assert len(orders) == 1, "أمرُ الوسيط لم يُكتَب"
        assert len(fills) == 1, "التنفيذ لم يُحفَظ — ولا يُعرَف الانزلاق بدونه"

        # ٣) الرابط — النيّة تشير إلى قرارها بعينه، لا إلى أقربِ قرارٍ زمنياً.
        assert intents[0].risk_decision_id == decision_id

        # ٤) المعرّفات معرّفاتُ الوسيط، تُقرأ منه ولا تُخترع.
        broker_order = broker.confirm_order(intent.client_order_id)
        assert orders[0].broker_deal_id == broker_order.broker_order_id
        assert orders[0].deal_reference == intent.client_order_id

        # ٥) التنفيذ يحمل السعر الحقيقي — بانزلاقه — والرسوم.
        assert fills[0].price == FILLED_AT, "سعرُ النيّة كُتب مكان سعرِ التنفيذ"
        assert fills[0].commission == COMMISSION
        assert fills[0].execution_id == broker.get_executions(DEFAULT_ACCOUNT)[0].execution_id

    def test_a_rejected_decision_is_a_row_not_only_a_sentence(self, factory, broker):
        service = _service(factory, broker)
        assert service.journal.decided(_Rejected(), symbol="GOLD") is not None
        with factory() as session:
            rows = list(session.execute(select(RiskDecisionRow)).scalars())
        assert len(rows) == 1
        assert rows[0].approved is False
        assert rows[0].reason_code == "DAILY_LOSS_REACHED"
        assert rows[0].symbol == "GOLD"

    def test_an_unlinked_intent_keeps_a_null_link_not_a_guess(self, factory, broker):
        """رابطٌ خاطئ أسوأ من رابطٍ غائب — لأنه يُقرأ على أنه معرفة."""
        service = _service(factory, broker)
        service.journal.decided(_Decision(), symbol="EURUSD")  # بلا مفتاح
        service.submit(_intent("k-nolink"))
        with factory() as session:
            row = session.execute(select(OrderIntentRow)).scalars().one()
        assert row.risk_decision_id is None


class TestTheGuardSurvivesARestart:
    def test_the_same_key_is_refused_by_a_fresh_guard(self, factory, broker):
        service = _service(factory, broker)
        service.submit(_intent("k-restart"))

        # حارسٌ جديد بذاكرةٍ فارغة — كأنّ العملية أُقلعت من جديد.
        fresh = IdempotencyGuard(session_factory=factory)
        assert fresh.seen("k-restart") is True, (
            "المنعُ ضاع مع إعادة التشغيل — وهو السيناريو الذي يضيع فيه المال."
        )

    def test_an_unknown_key_passes(self, factory):
        assert IdempotencyGuard(session_factory=factory).seen("k-never") is False

    def test_an_unreadable_database_blocks_rather_than_allows(self):
        def broken():
            raise RuntimeError("لا قاعدة")

        assert IdempotencyGuard(session_factory=broken).seen("k") is True

    def test_without_a_database_the_guard_is_memory_only(self):
        guard = IdempotencyGuard()
        assert guard.seen("k") is False
        guard.remember("k")
        assert guard.seen("k") is True


class TestTheLossReachesTheCounterThatStopsTrading:
    def test_from_open_to_confirmed_close_to_day_loss(self, factory, broker):
        service = _service(factory, broker)
        intent = _intent("k-full")
        service.journal.decided(
            _Decision(), symbol="EURUSD", intent_key=intent.idempotency_key
        )
        service.submit(intent)

        with factory() as session:
            order_row = session.execute(select(BrokerOrderRow)).scalars().one()
            deal_id = order_row.broker_deal_id
            reference = order_row.deal_reference

        opened = now_utc() - timedelta(hours=2)
        with factory() as session:
            # ٦) الدفتر يرى المركز عند الوسيط.
            ledger.sync(
                session,
                PortfolioSnapshot(
                    as_of_utc=opened,
                    ok=True,
                    account_id=DEFAULT_ACCOUNT,
                    open_positions=(
                        OpenPosition(
                            symbol="EURUSD",
                            quantity=Decimal("1"),
                            entry_price=FILLED_AT,
                            deal_id=deal_id,
                            deal_reference=reference,
                            unrealised_pnl=Decimal("0"),
                            opened_utc=opened,
                        ),
                    ),
                ),
            )
            row = session.execute(select(PositionBookRow)).scalars().one()
            assert row.state == "OPEN"

            # ٧) لقطتان فارغتان + دليلٌ مستقلّ ⇒ إغلاقٌ مؤكَّد.
            closed_at = now_utc() - timedelta(minutes=5)
            evidence = ClosedTrade(
                deal_id=deal_id,
                reference=reference,
                symbol="EURUSD",
                closed_utc=closed_at,
                realised_pnl=Decimal("-0.79"),
            )
            for _ in range(2):
                ledger.sync(
                    session,
                    PortfolioSnapshot(
                        as_of_utc=closed_at,
                        ok=True,
                        account_id=DEFAULT_ACCOUNT,
                        open_positions=(),
                        closed_trades=(evidence,),
                    ),
                )

            row = session.execute(select(PositionBookRow)).scalars().one()
            assert row.state == "CLOSED"
            assert row.reconciliation == "CONFIRMED"
            assert row.realised_pnl == Decimal("-0.79")

            # ٨) والخسارة تبلغ العدّاد الذي يوقف التداول.
            state = load_session_state(session, baseline_equity=ALLOCATED)
            assert state.realized_pnl_today == Decimal("-0.79")
            assert state.day_loss == Decimal("0.79")
            assert state.consecutive_losses == 1
            assert state.entry_orders_today == 1, "النيّة لم تُعَدّ محاولةَ دخول"
