"""
التأكيد يُطلب بمرجع الوسيط، لا بالمعرّف الذي ولّدناه.

كابيتال لا يعرف `client_order_id` الذي نصنعه؛ إيصاله الوحيد `dealReference`
يعود في استجابة الإرسال ويضعه المحوّل في `order.client_order_id`. وسؤالُه
بمعرّفنا يعود دائماً بـ«لا أعرف» — فيُعلَن أمرٌ نُفِّذ وحُمِي مجهولَ المصير،
ويُرفع فوقه قاطع الطوارئ، ويتوقّف النظام عن التداول بسبب سؤالٍ خاطئ لا
بسبب حالةٍ خطرة.

وقع هذا يوم 2026-09-04 على أول صفقة استراتيجية كاملة: GBPUSD قصير بحجم ٢٠٠
عند 1.34997 بوقفٍ عند 1.35364 — مطابقٌ لما وافقت عليه المخاطر — والنظام
سمّاه «تعذّر تأكيد الأمر».
"""
from __future__ import annotations

from app.contracts import BrokerOrder, OrderStatus, OrderType, Side
from app.execution.orders import ExecutionService, IdempotencyGuard, SubmissionOutcome
from app.money import D
from tests.conftest import MID_SESSION
from tests.test_execution import an_intent, fresh_broker

BROKER_REFERENCE = "o_98f1c0b2-deal-reference"


def _unknown(client_order_id: str) -> BrokerOrder:
    return BrokerOrder(
        broker_order_id="",
        client_order_id=client_order_id,
        symbol="",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=D("0"),
        filled_quantity=D("0"),
        average_fill_price=None,
        status=OrderStatus.UNKNOWN,
        updated_at_utc=MID_SESSION,
    )


def _broker_that_only_knows_its_own_reference(**kw):
    """وسيطٌ ينفّذ الأمر ويعيد مرجعه هو، ولا يجيب عن معرّفنا — كسلوك كابيتال."""
    broker = fresh_broker(**kw)
    original_place = broker.place_order
    filled: dict[str, BrokerOrder] = {}

    def place_order(intent):
        order = original_place(intent).model_copy(
            update={"client_order_id": BROKER_REFERENCE}
        )
        filled[BROKER_REFERENCE] = order
        return order

    def confirm_order(client_order_id: str) -> BrokerOrder:
        if client_order_id in filled:
            return filled[client_order_id]
        return _unknown(client_order_id)

    broker.place_order = place_order       # type: ignore[method-assign]
    broker.confirm_order = confirm_order   # type: ignore[method-assign]
    return broker


def test_an_order_the_broker_filled_is_not_called_unknown(audit):
    broker = _broker_that_only_knows_its_own_reference()
    service = ExecutionService(broker=broker, audit=audit, guard=IdempotencyGuard())

    result = service.submit(an_intent())

    assert result.outcome is SubmissionOutcome.FILLED
    assert result.requires_kill_switch is False


def test_an_order_with_no_proof_anywhere_is_still_unknown(audit):
    """الإصلاح لا يُرخّي الشرط: بلا تنفيذٍ مُثبَتٍ يبقى المصير مجهولاً."""
    broker = _broker_that_only_knows_its_own_reference()
    original_place = broker.place_order

    def place_order(intent):
        return original_place(intent).model_copy(
            update={"status": OrderStatus.UNKNOWN, "filled_quantity": D("0")}
        )

    broker.place_order = place_order          # type: ignore[method-assign]
    broker.confirm_order = _unknown           # type: ignore[method-assign]
    service = ExecutionService(broker=broker, audit=audit, guard=IdempotencyGuard())

    result = service.submit(an_intent())

    assert result.outcome is SubmissionOutcome.UNCONFIRMED
    assert result.requires_kill_switch is True
