"""
لا أمرَ يخرج بلا أثرٍ مكتوبٍ قبله.

## ما وجدناه يوم 2026-09-04

بعد يومٍ كاملٍ من التشغيل الحقيقي على الحساب التجريبي — صفقةُ استراتيجيةٍ
كاملة، وصفقةُ تشغيل، وخمسةُ مراكز مفتوحة — كان في القاعدة:

    broker_orders 0 · order_intents 0 · risk_decisions 0 · execution_attempts 0

الجداول مُصمَّمة ومُختبَرة، ولا سطرَ في `app/` ينشئ صفاً في أيٍّ منها.
و`record_attempt` و`resolve_attempt` مكتوبتان ولا تُستدعيان من أيّ مكان.

وأخطر ما فيه أنّ حارس الإقلاع الذي يبحث عن **محاولات تنفيذٍ غير محسومة** كان
يقرأ جدولاً لا يُكتَب فيه شيء، فيمرّ دائماً: الحماية من السيناريو الوحيد الذي
يضيع فيه المال صامتاً — انقطاعٌ بين «أُرسل» و«وصل التأكيد» — شكلٌ بلا مضمون.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.audit.log import AuditLog, InMemoryAuditStore
from app.clock import now_utc
from app.contracts import BrokerOrder, OrderIntent, OrderPreview, OrderStatus, OrderType, Side
from app.db.models import Base, BrokerOrderRow, ExecutionAttempt, OrderIntentRow
from app.db.recovery import unresolved_attempts
from app.execution.journal import ExecutionJournal
from app.execution.orders import ExecutionService, SubmissionOutcome
from app.money import D


@pytest.fixture()
def factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)


def _intent(key="idem-1", coid="coid-1") -> OrderIntent:
    return OrderIntent(
        idempotency_key=key, client_order_id=coid,
        symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
        quantity=D("100"), limit_price=None, stop_price=D("1.15"),
        expected_fill_price=D("1.16"), max_slippage_abs=D("0.0010"),
        strategy_name="COMMISSIONING", strategy_version="v1",
        risk_amount_usd=D("0.75"), commission_estimate_usd=D("0"),
        exit_plan_ar="وقف عند 1.15", instrument_snapshot={},
        created_at_utc=now_utc(),
    )


def _order(status=OrderStatus.FILLED, filled="100", price="1.16") -> BrokerOrder:
    return BrokerOrder(
        broker_order_id="deal-77", client_order_id="ref-77",
        symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
        quantity=D("100"), filled_quantity=D(filled),
        average_fill_price=D(price) if price else None, status=status,
        updated_at_utc=now_utc(),
    )


class _Broker:
    name = "TEST"
    environment = "demo"

    def __init__(self, *, order=None, raises=None):
        self._order = order if order is not None else _order()
        self._raises = raises
        self.sent = 0

    def preview_order(self, intent):
        return OrderPreview(
            intent_key=intent.idempotency_key,
            accepted_by_broker=True, broker_message="مقبول",
            estimated_commission=D("0"), estimated_price=D("1.16"),
            previewed_at_utc=now_utc(),
        )

    def place_order(self, intent):
        self.sent += 1
        if self._raises is not None:
            raise self._raises
        return self._order

    def confirm_order(self, reference):
        if self._raises is not None:
            return BrokerOrder(
                broker_order_id="", client_order_id=reference, symbol="EURUSD",
                side=Side.BUY, order_type=OrderType.MARKET, quantity=D("100"),
                filled_quantity=D("0"), average_fill_price=None,
                status=OrderStatus.UNKNOWN, updated_at_utc=now_utc(),
            )
        return self._order


def _service(factory, broker):
    return ExecutionService(
        broker=broker, audit=AuditLog(InMemoryAuditStore()),
        journal=ExecutionJournal(session_factory=factory),
    )


# --- ١ · الأثر يُكتَب --------------------------------------------------------


def test_a_successful_send_writes_intent_order_and_resolves_the_attempt(factory):
    broker = _Broker()
    result = _service(factory, broker).submit(_intent())

    assert result.outcome is SubmissionOutcome.FILLED
    with factory() as session:
        assert session.execute(select(OrderIntentRow)).scalars().all()
        order_row = session.execute(select(BrokerOrderRow)).scalar_one()
        assert order_row.broker_deal_id == "deal-77"
        assert order_row.deal_reference == "ref-77", "المرجع مرجعُ الوسيط لا معرّفنا"
        assert order_row.client_order_id == "coid-1"
        assert order_row.filled_quantity == Decimal("100")
        assert unresolved_attempts(session) == []


def test_the_attempt_exists_before_the_order_is_sent(factory):
    """
    الترتيب هو الضمانة كلّها: لو كُتب الأثر بعد الإرسال، لضاع كلُّ انقطاعٍ
    يقع بينهما — وهو بالضبط الانقطاع الذي يضيع فيه المال.
    """
    seen: list[int] = []

    class _Watching(_Broker):
        def place_order(self, intent):
            with factory() as session:
                seen.append(len(session.execute(select(ExecutionAttempt)).scalars().all()))
            return super().place_order(intent)

    _service(factory, _Watching()).submit(_intent())
    assert seen == [1], "المحاولة لم تكن مكتوبةً لحظةَ الإرسال"


# --- ٢ · الغموض يبقى غموضاً ---------------------------------------------------


def test_an_unconfirmed_send_leaves_the_attempt_unresolved(factory):
    """
    وهذا ما يجعل حارسَ الإقلاع حقيقياً: انقطاعٌ بعد الإرسال يترك أثراً غير
    محسوم، فيُقفَل الدخول عند الإقلاع القادم حتى تُقرأ حالة الوسيط.
    """
    from app.brokers.base import BrokerTimeout

    broker = _Broker(raises=BrokerTimeout("انقطاع"))
    result = _service(factory, broker).submit(_intent())

    assert result.outcome is SubmissionOutcome.UNCONFIRMED
    with factory() as session:
        pending = unresolved_attempts(session)
        assert [a.idempotency_key for a in pending] == ["idem-1"]


def test_a_rejected_send_is_resolved_not_left_hanging(factory):
    from app.brokers.base import BrokerRejected

    broker = _Broker(raises=BrokerRejected("رفض"))
    service = _service(factory, broker)
    result = service.submit(_intent())

    assert result.outcome is SubmissionOutcome.REJECTED
    with factory() as session:
        assert unresolved_attempts(session) == []


# --- ٣ · لا إرسالَ بلا أثر ----------------------------------------------------


def test_a_failing_journal_stops_the_send_entirely(factory):
    """إرسالٌ بلا أثر أسوأ من عدم الإرسال، لأنّ عدم الإرسال معلوم."""

    def _broken():
        raise RuntimeError("القاعدة مقفلة")

    broker = _Broker()
    service = ExecutionService(
        broker=broker, audit=AuditLog(InMemoryAuditStore()),
        journal=ExecutionJournal(session_factory=_broken),
    )
    result = service.submit(_intent())

    assert result.outcome is SubmissionOutcome.REJECTED
    assert broker.sent == 0, "أُرسل أمرٌ بلا أثر"


# --- ٤ · التكرار --------------------------------------------------------------


def test_the_same_intent_does_not_duplicate_rows(factory):
    broker = _Broker()
    service = _service(factory, broker)
    service.submit(_intent())
    second = service.submit(_intent())

    assert second.outcome is SubmissionOutcome.DUPLICATE_BLOCKED
    assert broker.sent == 1
    with factory() as session:
        assert len(session.execute(select(OrderIntentRow)).scalars().all()) == 1
        assert len(session.execute(select(ExecutionAttempt)).scalars().all()) == 1


# --- ٥ · التركيب --------------------------------------------------------------


def test_the_running_service_is_built_with_a_journal():
    """
    اختبارُ الوحدة يثبت أن القطعة صحيحة، ولا يثبت أنها مركَّبة. وهذا العيب
    بعينه: أربعةُ جداولٍ سليمةٍ وفارغةٍ لأنّ أحداً لم يوصلها.
    """
    import inspect

    import app.api.state as state_module

    source = inspect.getsource(state_module)
    assert "ExecutionJournal(session_factory=" in source
