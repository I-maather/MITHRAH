"""
أثرُ الأمر في القاعدة — الجداول التي كانت موجودةً وفارغةً دائماً.

## ما وجدناه يوم 2026-09-04

بعد يومٍ كاملٍ من التشغيل الحقيقي على الحساب التجريبي — صفقةُ استراتيجيةٍ
كاملة، وصفقةُ تشغيل، وخمسةُ مراكز مفتوحة — كان في القاعدة:

    broker_orders 0 · order_intents 0 · risk_decisions 0 · execution_attempts 0

الجداول مُصمَّمة ومُختبَرة، ولا سطرَ في `app/` ينشئ صفاً في أيٍّ منها.
و`record_attempt` و`resolve_attempt` مكتوبتان ولا تُستدعيان.

وأخطر ما في ذلك أنّ حارس الإقلاع الذي يبحث عن **محاولات تنفيذٍ غير محسومة**
كان يقرأ جدولاً لا يُكتَب فيه شيء، فيمرّ دائماً. أي أنّ الحماية من السيناريو
الوحيد الذي يضيع فيه المال صامتاً — انقطاعٌ بين «أُرسل الأمر» و«وصل التأكيد»
— كانت شكلاً بلا مضمون.

## القاعدة

**لا إرسالَ بلا أثرٍ مكتوبٍ قبله.** إن تعذّرت كتابة المحاولة، لا يُرسَل الأمر:
إرسالٌ بلا أثر أسوأ من عدم الإرسال، لأنّ عدم الإرسال معلوم.

وإن تعذّرت كتابة **الحسم** بعد التنفيذ، فالتنفيذ لا يُنكَر: تبقى المحاولة غير
محسومة فيقفل الإقلاع القادم على الدخول حتى تُقرأ حالة الوسيط. الجهلُ المعلَن
أأمن من نجاحٍ مُدَّعى.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from sqlalchemy import select

from ..clock import now_utc
from ..contracts import ExecutionUncertainty, OrderIntent, OrderStatus
from ..db.models import BrokerOrderRow, ExecutionAttempt, OrderIntentRow
from ..db.recovery import record_attempt, resolve_attempt

_LOG = logging.getLogger(__name__)


class JournalUnavailable(RuntimeError):
    """تعذّرت كتابة الأثر — ولا يُرسَل أمرٌ بلا أثر."""


#: كيف يُترجَم مآلُ الإرسال إلى حسمٍ للمحاولة.
#:
#: ما ليس هنا **لا يُحسَم**: الغموض يبقى غموضاً حتى تُقرأ حالة الوسيط.
_RESOLUTION = {
    "FILLED": (ExecutionUncertainty.RESOLVED_FILLED, "تنفيذٌ مؤكَّد من الوسيط."),
    "PARTIALLY_FILLED": (
        ExecutionUncertainty.RESOLVED_FILLED,
        "تنفيذٌ جزئيّ مؤكَّد من الوسيط.",
    ),
    "REJECTED": (ExecutionUncertainty.RESOLVED_REJECTED, "رفضٌ صريح من الوسيط."),
    "PREVIEW_REJECTED": (
        ExecutionUncertainty.RESOLVED_ABSENT,
        "رُفضت المعاينة — لم يخرج أمرٌ إلى الوسيط.",
    ),
    "SIZE_MISMATCH": (
        ExecutionUncertainty.RESOLVED_FILLED,
        "نُفِّذ بكميةٍ تتجاوز المطلوبة — منفَّذ ومُبلَّغ عنه.",
    ),
    "SLIPPAGE_EXCEEDED": (
        ExecutionUncertainty.RESOLVED_FILLED,
        "نُفِّذ بانزلاقٍ فوق الحدّ — منفَّذ ومُبلَّغ عنه.",
    ),
}


@dataclass
class ExecutionJournal:
    """
    يكتب النيّة والمحاولة قبل الإرسال، وأمرَ الوسيط بعده.

    بلا `session_factory` يصير الأثرُ معطَّلاً صراحةً — وهو ما تحتاجه
    الاختبارات الوحدوية للتنفيذ بلا قاعدة. أمّا الخدمة فتُمرّره دائماً،
    ويحرس ذلك اختبارٌ مستقل.
    """

    session_factory: Optional[Callable[[], object]] = None

    @property
    def enabled(self) -> bool:
        return self.session_factory is not None

    # -- قبل الإرسال ---------------------------------------------------------

    def opened(self, intent: OrderIntent, *, broker: str, environment: str) -> None:
        """
        يكتب `order_intents` و`execution_attempts` **قبل** أن يُرسَل شيء.

        يرفع `JournalUnavailable` عند الفشل، ومعناه: لا تُرسِل.
        """
        if not self.enabled:
            return
        try:
            with self.session_factory() as session:  # type: ignore[misc]
                existing = session.execute(
                    select(OrderIntentRow).where(
                        OrderIntentRow.idempotency_key == intent.idempotency_key
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(_intent_row(intent, broker=broker, environment=environment))
                    session.commit()

                attempt = session.execute(
                    select(ExecutionAttempt).where(
                        ExecutionAttempt.idempotency_key == intent.idempotency_key
                    )
                ).scalar_one_or_none()
                if attempt is None:
                    record_attempt(
                        session,
                        idempotency_key=intent.idempotency_key,
                        broker=broker,
                        broker_environment=environment,
                        epic=intent.symbol,
                        at=now_utc(),
                    )
        except Exception as exc:  # noqa: BLE001
            _LOG.error("تعذّرت كتابة أثر الأمر قبل الإرسال: %s", type(exc).__name__)
            raise JournalUnavailable(
                f"تعذّرت كتابة أثر الأمر ({type(exc).__name__}) — لا يُرسَل أمرٌ بلا أثر."
            ) from exc

    # -- بعد الإرسال ---------------------------------------------------------

    def settled(self, intent: OrderIntent, result) -> None:
        """
        يكتب أمرَ الوسيط ويحسم المحاولة.

        **لا يرفع شيئاً.** التنفيذ وقع، وفشلُ الكتابة بعده لا يُنكره؛ تبقى
        المحاولة غير محسومة فيقفل الإقلاع القادم حتى تُقرأ حالة الوسيط.
        """
        if not self.enabled:
            return
        try:
            with self.session_factory() as session:  # type: ignore[misc]
                order = getattr(result, "order", None)
                if order is not None:
                    _upsert_broker_order(session, intent, order)

                attempt = session.execute(
                    select(ExecutionAttempt).where(
                        ExecutionAttempt.idempotency_key == intent.idempotency_key
                    )
                ).scalar_one_or_none()
                if attempt is None:
                    return

                outcome = getattr(getattr(result, "outcome", None), "value", "")
                mapped = _RESOLUTION.get(outcome)
                deal_id = getattr(order, "broker_order_id", None) if order else None
                if mapped is None:
                    # غامضٌ يبقى غامضاً: `UNCONFIRMED` و`DUPLICATE_BLOCKED`
                    # وكلُّ ما لم يُصرَّح به. تُحدَّث الملاحظة ولا تُحسَم.
                    attempt.uncertainty = ExecutionUncertainty.PENDING_CONFIRMATION.value
                    attempt.resolution_note_ar = (
                        f"مآلٌ غير حاسم ({outcome or 'غير معروف'}) — يُقرأ من الوسيط."
                    )
                    attempt.broker_deal_id = deal_id
                    session.commit()
                    return

                uncertainty, note = mapped
                resolve_attempt(
                    session, attempt,
                    uncertainty=uncertainty, note_ar=note,
                    broker_deal_id=deal_id, at=now_utc(),
                )
        except Exception as exc:  # noqa: BLE001
            _LOG.error(
                "تعذّرت كتابة حسم الأمر بعد التنفيذ: %s — تبقى المحاولة غير محسومة",
                type(exc).__name__,
            )


def _intent_row(intent: OrderIntent, *, broker: str, environment: str) -> OrderIntentRow:
    return OrderIntentRow(
        idempotency_key=intent.idempotency_key,
        client_order_id=intent.client_order_id,
        broker=broker,
        broker_environment=environment,
        epic=intent.symbol,
        strategy_name=getattr(intent, "strategy_name", "") or "",
        strategy_version=getattr(intent, "strategy_version", "") or "",
        symbol=intent.symbol,
        side=getattr(intent.side, "value", str(intent.side)),
        order_type=getattr(intent.order_type, "value", str(intent.order_type)),
        quantity=intent.quantity,
        limit_price=getattr(intent, "limit_price", None),
        stop_price=getattr(intent, "stop_price", None),
        expected_fill_price=intent.expected_fill_price,
        max_slippage_abs=intent.max_slippage_abs,
        exit_plan_ar=getattr(intent, "exit_plan_ar", "") or "",
        instrument_snapshot_json="{}",
        created_at_utc=now_utc(),
    )


def _upsert_broker_order(session, intent: OrderIntent, order) -> None:
    """
    مفتاحُ الصف `broker_order_id` — هويّة الوسيط.

    و`deal_reference` يُقرأ من `order.client_order_id`: المحوّل يضع فيه
    إيصالَ كابيتال لا معرّفنا، وهو الفرق الذي عطّل تأكيد أوّل صفقةٍ كاملة.
    """
    broker_order_id = str(getattr(order, "broker_order_id", "") or "")
    if not broker_order_id:
        return
    row = session.execute(
        select(BrokerOrderRow).where(BrokerOrderRow.broker_order_id == broker_order_id)
    ).scalar_one_or_none()
    reference = (getattr(order, "client_order_id", "") or "").strip() or None
    status = getattr(order.status, "value", str(order.status))
    filled = getattr(order, "filled_quantity", 0) or 0

    if row is None:
        row = BrokerOrderRow(
            broker_order_id=broker_order_id,
            deal_reference=reference,
            broker_deal_id=broker_order_id,
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=getattr(intent.side, "value", str(intent.side)),
            order_type=getattr(intent.order_type, "value", str(intent.order_type)),
            quantity=intent.quantity,
            filled_quantity=filled,
            average_fill_price=getattr(order, "average_fill_price", None),
            status=status,
            updated_at_utc=now_utc(),
        )
        session.add(row)
    else:
        row.deal_reference = reference or row.deal_reference
        row.broker_deal_id = broker_order_id
        row.filled_quantity = filled
        row.average_fill_price = getattr(order, "average_fill_price", None)
        row.status = status
        row.updated_at_utc = now_utc()

    row.broker_confirmation_state = (
        "CONFIRMED"
        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        else "PENDING"
    )
    session.commit()
