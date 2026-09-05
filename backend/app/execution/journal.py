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
import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import select

from ..clock import now_utc
from ..contracts import ExecutionUncertainty, OrderIntent, OrderStatus
from ..db.models import (
    BrokerOrderRow,
    ExecutionAttempt,
    ExecutionRow,
    OrderIntentRow,
    RiskDecisionRow,
)
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


def _checks_json(decision) -> str:
    """فحوصُ القرار نصّاً — وبها يُعرَف **أيُّ شرطٍ سقط**، لا أنّ شرطاً سقط."""
    checks = getattr(decision, "checks", ()) or ()
    try:
        return json.dumps(
            [
                {"name": c[0], "passed": bool(c[1]), "detail_ar": c[2]}
                for c in checks
                if len(c) >= 3
            ],
            ensure_ascii=False,
        )
    except Exception:  # noqa: BLE001
        return "[]"


@dataclass
class ExecutionJournal:
    """
    يكتب النيّة والمحاولة قبل الإرسال، وأمرَ الوسيط بعده.

    بلا `session_factory` يصير الأثرُ معطَّلاً صراحةً — وهو ما تحتاجه
    الاختبارات الوحدوية للتنفيذ بلا قاعدة. أمّا الخدمة فتُمرّره دائماً،
    ويحرس ذلك اختبارٌ مستقل.
    """

    session_factory: Optional[Callable[[], object]] = None
    #: ربطُ النيّة بقرارها — يعيش لحظاتٍ بين `decided()` و`opened()` في
    #: العملية نفسها. وغيابُه يترك `risk_decision_id` فارغاً **ولا يُخمَّن**:
    #: رابطٌ خاطئ أسوأ من رابطٍ غائب، لأنه يُقرأ على أنه معرفة.
    _decisions: dict = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.session_factory is not None

    # -- قرارُ المخاطر ------------------------------------------------------

    def decided(
        self,
        decision,
        *,
        symbol: str,
        intent_key: Optional[str] = None,
    ) -> Optional[int]:
        """
        يكتب قرارَ المخاطر صفّاً — **الموافقةَ والرفضَ معاً**.

        الرفضُ ليس عدماً: تشخيصُ «لماذا لا يتداول النظام» يحتاج عدَّ الرفض
        بأسبابه ومراحله، لا قراءتَه جملةً في سجلّ التدقيق. وقد كان هذا
        الجدول فارغاً منذ بُني، فكان كلُّ سؤالٍ عن الرفض يُجاب بالنصّ لا
        بالعدد.

        ولا يرفع شيئاً: قرارٌ لم يُسجَّل لا يمنع تسجيلَ ما بعده، والإرسالُ
        نفسه محروسٌ بـ`opened()` التي **تمنع** عند فشلها.
        """
        if not self.enabled:
            return None
        try:
            with self.session_factory() as session:  # type: ignore[misc]
                row = RiskDecisionRow(
                    symbol=symbol or "",
                    approved=bool(getattr(decision, "approved", False)),
                    reason_code=(getattr(decision, "reason_code", None) or "")[:64],
                    reason_ar=getattr(decision, "reason_ar", "") or "",
                    checks_json=_checks_json(decision),
                    quantity=getattr(decision, "quantity", 0) or 0,
                    expected_risk_usd=getattr(decision, "expected_risk_usd", 0) or 0,
                    expected_costs_usd=getattr(decision, "expected_costs_usd", 0) or 0,
                    risk_budget_usd=getattr(decision, "risk_budget_usd", 0) or 0,
                    constitution_fingerprint=(
                        getattr(decision, "constitution_fingerprint", "") or ""
                    ),
                    decided_at_utc=getattr(decision, "decided_at_utc", None) or now_utc(),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                if intent_key:
                    self._decisions[intent_key] = row.id
                return row.id
        except Exception as exc:  # noqa: BLE001
            _LOG.error("تعذّر تسجيل قرار المخاطر: %s", type(exc).__name__)
            return None

    # -- التنفيذات ---------------------------------------------------------

    def executed(self, result, *, broker=None, account_id: str = "") -> int:
        """
        يحفظ التنفيذات كما يقولها الوسيط — **وهي وحدها تُعرِّف الانزلاق**.

        `broker_orders` تحمل ما طُلب وما تأكّد؛ و`executions` تحمل **ما وقع
        فعلاً**: السعر المنفَّذ والكمية والرسوم لكلّ تعبئة. وبلا هذه لا يُعرف
        الفرقُ بين السعر المتوقَّع والمنفَّذ — أي لا تُقاس جودةُ التنفيذ، وهي
        نصفُ `E3`.

        والمحوّل يملك `get_executions` منذ بُني، **ولم يكن أحدٌ يحفظ ما تعيده**.

        ولا يرفع شيئاً: التنفيذ وقع، وفشلُ تسجيله لا يُنكره.
        """
        if not self.enabled or broker is None:
            return 0
        order = getattr(result, "order", None)
        broker_order_id = str(getattr(order, "broker_order_id", "") or "")
        if not broker_order_id:
            return 0
        try:
            fills = list(broker.get_executions(account_id) or [])
        except Exception as exc:  # noqa: BLE001
            _LOG.error("تعذّرت قراءة التنفيذات من الوسيط: %s", type(exc).__name__)
            return 0

        saved = 0
        try:
            with self.session_factory() as session:  # type: ignore[misc]
                for fill in fills:
                    if str(getattr(fill, "broker_order_id", "")) != broker_order_id:
                        continue
                    key = str(getattr(fill, "execution_id", "") or "")
                    if not key:
                        continue
                    existing = session.execute(
                        select(ExecutionRow).where(ExecutionRow.execution_id == key)
                    ).scalar_one_or_none()
                    if existing is not None:
                        continue
                    session.add(
                        ExecutionRow(
                            execution_id=key,
                            broker_order_id=broker_order_id,
                            symbol=getattr(fill, "symbol", "") or "",
                            side=getattr(
                                getattr(fill, "side", None), "value", str(getattr(fill, "side", ""))
                            ),
                            quantity=getattr(fill, "quantity", 0) or 0,
                            price=getattr(fill, "price", 0) or 0,
                            commission=getattr(fill, "commission", 0) or 0,
                            executed_at_utc=getattr(fill, "executed_at_utc", None) or now_utc(),
                        )
                    )
                    saved += 1
                if saved:
                    session.commit()
        except Exception as exc:  # noqa: BLE001
            _LOG.error("تعذّر حفظ التنفيذات: %s", type(exc).__name__)
            return 0
        return saved

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
                    row = _intent_row(intent, broker=broker, environment=environment)
                    # الرابطُ يُقرأ من الذاكرة لا يُخمَّن؛ وغيابُه يتركه فارغاً.
                    row.risk_decision_id = self._decisions.pop(
                        intent.idempotency_key, None
                    )
                    session.add(row)
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
