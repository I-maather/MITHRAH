"""
Execution — دورة الأمر الكاملة.

Signal → Risk Approval → Order Intent → Preview → Submission → Confirmation → Reconciliation

قاعدة صارمة: استجابة الـAPI الأولى ليست تنفيذاً. لا نعتبر أي أمر منفذاً
حتى نستخرج تأكيداً من الوسيط بحالة FILLED/PARTIALLY_FILLED وكمية وسعر.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..audit.log import Actor, AuditAction, AuditLog, canonical_json
from ..brokers.base import BrokerAdapter, BrokerRejected, BrokerTimeout
from ..contracts import (
    BrokerOrder,
    OrderIntent,
    OrderStatus,
    OrderType,
    Position,
    ReconciliationResult,
    RiskDecision,
    Side,
    Signal,
)
from ..money import D, money


class SubmissionOutcome(str, Enum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    UNCONFIRMED = "UNCONFIRMED"     # أرسلنا ولم نستلم تأكيداً — الحالة الأخطر
    DUPLICATE_BLOCKED = "DUPLICATE_BLOCKED"
    PREVIEW_REJECTED = "PREVIEW_REJECTED"
    SLIPPAGE_EXCEEDED = "SLIPPAGE_EXCEEDED"
    SIZE_MISMATCH = "SIZE_MISMATCH"


@dataclass(frozen=True)
class SubmissionResult:
    outcome: SubmissionOutcome
    reason_ar: str
    intent: OrderIntent
    order: Optional[BrokerOrder]
    requires_kill_switch: bool = False


def build_idempotency_key(
    *, signal: Signal, decision: RiskDecision, trading_day: str
) -> str:
    """
    مفتاح فريد لنية أمر واحدة. نفس (الاستراتيجية، الإصدار، الرمز، اليوم،
    بصمة المدخلات، الكمية) => نفس المفتاح => لا يمكن إرسال الأمر مرتين.
    """
    payload = {
        "strategy": signal.strategy_name,
        "version": signal.strategy_version,
        "symbol": signal.symbol,
        "side": signal.side,
        "trading_day": trading_day,
        "inputs_digest": signal.inputs_digest,
        "quantity": decision.quantity,
        "entry": signal.entry_price,
        "stop": signal.stop_price,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()[:40]


def _price(value: Decimal) -> str:
    """
    السعر **بدقّته هو**، لا بمنزلتين دائماً.

    كان `f"{price:.2f}"`. وهو صحيحٌ للذهب (4389.12) وللين (146.82)، ويهدم
    اليورو: وقفٌ عند 1.14523 يُسجَّل «1.15» — بعيدٌ عن الوقف الحقيقي 47.7
    نقطة، أي نحو نصف أدنى مسافةٍ يقبلها الوسيط.

    وهذا النصّ يُكتب في **خط التدقيق** سبباً لـ`ORDER_INTENT_CREATED`: أي
    أنه السجلّ البشري لما أُمر به من حماية. فرقمٌ مقرَّبٌ فيه ليس تجميلاً.

    والدقّة تُشتقّ من القيمة نفسها: `Decimal` يحفظ منازل مصدره، فيُطبع
    بها بلا جدولٍ يُصان. ولا تُستعمل `normalize()` — تقصّ الأصفار فتكتب
    وقف «1.10000» على أنه «1.1»، وهي القيمة ذاتها لكنها تُقرأ أقلّ دقّةً
    في سجلٍّ غايتُه الدقّة.
    """
    return format(value, "f")


def build_order_intent(
    *,
    signal: Signal,
    decision: RiskDecision,
    trading_day: str,
    instrument_snapshot: dict,
    max_slippage_abs: Decimal,
    now: datetime,
) -> OrderIntent:
    if not decision.approved:
        raise ValueError("لا يمكن بناء نية أمر من قرار مخاطرة غير موافِق")
    key = build_idempotency_key(signal=signal, decision=decision, trading_day=trading_day)
    return OrderIntent(
        idempotency_key=key,
        client_order_id=f"MAT-{key[:16]}",
        symbol=signal.symbol,
        side=signal.side,
        order_type=OrderType.LIMIT,
        quantity=decision.quantity,
        limit_price=signal.entry_price,
        stop_price=signal.stop_price,
        take_profit_price=signal.take_profit_price,
        expected_fill_price=signal.entry_price,
        max_slippage_abs=max_slippage_abs,
        strategy_name=signal.strategy_name,
        strategy_version=signal.strategy_version,
        risk_amount_usd=decision.expected_risk_usd,
        commission_estimate_usd=decision.expected_costs_usd,
        exit_plan_ar=(
            f"وقف عند {_price(signal.stop_price)} وهدف عند "
            f"{_price(signal.take_profit_price)}. إبطال: {signal.invalidation_ar}"
        ),
        instrument_snapshot=instrument_snapshot,
        created_at_utc=now,
    )


class IdempotencyGuard:
    """يمنع إرسال نفس النية مرتين، حتى بعد إعادة تشغيل العملية (يُدعم بجدول DB)."""

    def __init__(self, seen: Optional[set[str]] = None) -> None:
        self._seen: set[str] = set(seen or ())

    def seen(self, key: str) -> bool:
        return key in self._seen

    def remember(self, key: str) -> None:
        self._seen.add(key)


@dataclass
class ExecutionService:
    broker: BrokerAdapter
    audit: AuditLog
    guard: IdempotencyGuard = field(default_factory=IdempotencyGuard)

    def submit(self, intent: OrderIntent) -> SubmissionResult:
        # 1) حماية من التكرار
        if self.guard.seen(intent.idempotency_key):
            self.audit.record(
                actor=Actor.SYSTEM, action=AuditAction.ORDER_REJECTED,
                decision="DUPLICATE_BLOCKED",
                reason_ar="نية أمر مكررة — نفس مفتاح الـidempotency أُرسل مسبقاً.",
                source="ExecutionService", related_id=intent.client_order_id,
            )
            return SubmissionResult(
                SubmissionOutcome.DUPLICATE_BLOCKED,
                "أمر مكرر — مُنع الإرسال.",
                intent, None, requires_kill_switch=True,
            )

        # 2) Preview إلزامي قبل أي إرسال
        preview = self.broker.preview_order(intent)
        self.audit.record(
            actor=Actor.BROKER, action=AuditAction.ORDER_PREVIEWED,
            decision="ACCEPTED" if preview.accepted_by_broker else "REJECTED",
            reason_ar=preview.broker_message, source=self.broker.name,
            after=preview.model_dump(mode="json"), related_id=intent.client_order_id,
        )
        if not preview.accepted_by_broker:
            return SubmissionResult(
                SubmissionOutcome.PREVIEW_REJECTED,
                f"الوسيط رفض المعاينة: {preview.broker_message}",
                intent, None,
            )

        # 3) الإرسال. نسجّل المفتاح *قبل* الإرسال: إن ضاع الرد، لا نعيد الإرسال أبداً.
        self.guard.remember(intent.idempotency_key)
        self.audit.record(
            actor=Actor.SYSTEM, action=AuditAction.ORDER_SUBMITTED,
            decision="SUBMITTED", reason_ar="إرسال الأمر بعد موافقة المخاطر والمعاينة.",
            source="ExecutionService", after=intent.model_dump(mode="json"),
            related_id=intent.client_order_id,
        )

        try:
            order = self.broker.place_order(intent)
        except BrokerRejected as exc:
            self.audit.record(
                actor=Actor.BROKER, action=AuditAction.ORDER_REJECTED,
                decision="REJECTED", reason_ar=f"رفض الوسيط: {exc}",
                source=self.broker.name, related_id=intent.client_order_id,
            )
            return SubmissionResult(SubmissionOutcome.REJECTED, f"رفض الوسيط: {exc}", intent, None)
        except BrokerTimeout as exc:
            # لا نعيد المحاولة. نحاول *القراءة* فقط لمعرفة الحقيقة.
            self.audit.record(
                actor=Actor.BROKER, action=AuditAction.ORDER_TIMEOUT,
                decision="UNCONFIRMED", reason_ar=f"انقطاع/مهلة أثناء الإرسال: {exc}",
                source=self.broker.name, related_id=intent.client_order_id,
            )
            recovered = self._try_recover(intent)
            if recovered is not None and recovered.status in (
                OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED
            ):
                return self._verify_fill(intent, recovered)
            return SubmissionResult(
                SubmissionOutcome.UNCONFIRMED,
                "أُرسل الأمر ولم يصل تأكيد. النظام لن يعيد الإرسال — يتطلب فحصاً بشرياً.",
                intent, recovered, requires_kill_switch=True,
            )

        except Exception as exc:  # noqa: BLE001
            # ---------------------------------------------------------------
            # **لا إرسالَ يموت صامتاً.**
            #
            # كانت هذه الدالة تلتقط `BrokerRejected` و`BrokerTimeout` وحدهما.
            # وكل ما عداهما — `ExecutionLocked` مثلاً — يمرّ من فوقها فيقتل
            # المهمة المجدولة، **بعد** أن سُجِّل `ORDER_SUBMITTED` في خط
            # التدقيق وقبل أن يُسجَّل شيءٌ عن مصيره.
            #
            # ووقع ذلك فعلاً في 2026-09-03: ثلاث دورات متتالية تُسجّل
            # «أُرسل» ولا تُسجّل شيئاً بعده، والسجلّ الوحيد سطرٌ في
            # journalctl: «فشل المهمة المجدولة decision-loop: ExecutionLocked».
            # فبدا في خط التدقيق أن ثلاثة أوامر خرجت إلى الوسيط ولم تعد —
            # وهي **لم تخرج أصلاً**.
            #
            # والفرق بين «أُرسل ولا نعرف» و«لم يُرسَل» هو الفرق بين حالة
            # طوارئ وحالة إعداد. وخط تدقيقٍ لا يفرّق بينهما يضلّل في اللحظة
            # التي يُقرأ فيها.
            #
            # ⇒ يُسجَّل الفشل باسم صنفه، ويُطلَب قاطع الطوارئ: مصيرُ أمرٍ
            # مجهولٌ حتى يُقرأ من الوسيط.
            # ---------------------------------------------------------------
            self.audit.record(
                actor=Actor.SYSTEM, action=AuditAction.ORDER_REJECTED,
                decision=f"SUBMIT_FAILED_{type(exc).__name__}",
                reason_ar=(
                    f"تعذّر الإرسال بعد تسجيله: {type(exc).__name__}. "
                    "لم يصل تأكيدٌ ولم يُقرأ مركز — يُعامَل مجهولَ المصير "
                    "حتى تُقرأ حالة الوسيط."
                ),
                source=self.broker.name, related_id=intent.client_order_id,
            )
            recovered = self._try_recover(intent)
            if recovered is not None and recovered.status in (
                OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED
            ):
                return self._verify_fill(intent, recovered)
            return SubmissionResult(
                SubmissionOutcome.UNCONFIRMED,
                f"تعذّر الإرسال ({type(exc).__name__}) ولم يُقرأ أثرٌ عند الوسيط.",
                intent, recovered, requires_kill_switch=True,
            )
        # 4) التأكيد من الوسيط — لا نثق بالاستجابة الأولى وحدها.
        #
        # **والمرجع الذي نسأل به مرجعُ الوسيط لا مرجعُنا.** كان السؤال
        # يُطرح بـ`intent.client_order_id` — وهو معرّفٌ نولّده نحن ولا
        # يعرفه كابيتال؛ إيصاله الوحيد `dealReference` الذي يعيده الإرسال،
        # ويضعه المحوّل في `order.client_order_id`. فكان الجواب «لا أعرف»
        # في كل مرّة، فيُعلَن أمرٌ مؤكَّدٌ محميٌّ مجهولَ المصير ويُرفع فوقه
        # قاطع الطوارئ.
        #
        # وقع ذلك في 2026-09-04 على **أول صفقة استراتيجية كاملة**: مركز
        # GBPUSD قصير بحجم ٢٠٠ فُتح فعلاً عند 1.34997 بوقفٍ عند 1.35364 —
        # أي بالضبط ما وافقت عليه المخاطر — ثم أوقف النظام نفسه عنه
        # وسمّاه «مجهولاً». وأسوأ ما في الخطأ أنه يقع **بعد** نجاح كل شيء.
        reference = (order.client_order_id or "").strip() or intent.client_order_id
        confirmed = self.broker.confirm_order(reference)
        if confirmed.status is OrderStatus.UNKNOWN:
            # `place_order` في هذا المحوّل لا يعود إلا بعد أن يقرأ تأكيداً
            # من الوسيط ويتحقّق من الوقف عنده. فإن كان بين أيدينا تنفيذٌ
            # مُثبَت، فالجهل هنا جهلُ السؤال لا جهلُ الحال — ولا يجوز أن
            # يُترجَم إلى حالة طوارئ.
            if order is not None and order.status in (
                OrderStatus.FILLED,
                OrderStatus.PARTIALLY_FILLED,
            ):
                confirmed = order
            else:
                return SubmissionResult(
                    SubmissionOutcome.UNCONFIRMED,
                    "تعذر تأكيد الأمر من الوسيط بعد الإرسال.",
                    intent, order, requires_kill_switch=True,
                )
        return self._verify_fill(intent, confirmed)

    def _try_recover(self, intent: OrderIntent) -> Optional[BrokerOrder]:
        try:
            found = self.broker.confirm_order(intent.client_order_id)
            return None if found.status is OrderStatus.UNKNOWN else found
        except Exception:
            return None

    def _verify_fill(self, intent: OrderIntent, order: BrokerOrder) -> SubmissionResult:
        if order.filled_quantity > intent.quantity:
            self.audit.record(
                actor=Actor.SYSTEM, action=AuditAction.ORDER_CONFIRMED,
                decision="SIZE_MISMATCH",
                reason_ar=f"الكمية المنفذة {order.filled_quantity} تتجاوز المطلوبة {intent.quantity}.",
                source=self.broker.name, related_id=intent.client_order_id,
            )
            return SubmissionResult(
                SubmissionOutcome.SIZE_MISMATCH,
                "الكمية المنفذة تتجاوز المطلوبة — خطر جسيم.",
                intent, order, requires_kill_switch=True,
            )

        if order.average_fill_price is not None and intent.max_slippage_abs >= 0:
            slip = abs(order.average_fill_price - intent.expected_fill_price)
            if slip > intent.max_slippage_abs:
                self.audit.record(
                    actor=Actor.SYSTEM, action=AuditAction.ORDER_CONFIRMED,
                    decision="SLIPPAGE_EXCEEDED",
                    reason_ar=f"انزلاق {slip:.4f} يتجاوز الحد {intent.max_slippage_abs:.4f}.",
                    source=self.broker.name, related_id=intent.client_order_id,
                )
                return SubmissionResult(
                    SubmissionOutcome.SLIPPAGE_EXCEEDED,
                    f"انزلاق {slip:.4f} تجاوز الحد المسموح.",
                    intent, order, requires_kill_switch=True,
                )

        outcome = (
            SubmissionOutcome.FILLED
            if order.status is OrderStatus.FILLED
            else SubmissionOutcome.PARTIALLY_FILLED
        )
        self.audit.record(
            actor=Actor.BROKER, action=AuditAction.ORDER_CONFIRMED,
            decision=outcome.value,
            reason_ar=f"تأكيد الوسيط: كمية {order.filled_quantity} بسعر {order.average_fill_price}.",
            source=self.broker.name, after=order.model_dump(mode="json"),
            related_id=intent.client_order_id,
        )
        return SubmissionResult(outcome, "تم التأكيد من الوسيط.", intent, order)


def reconcile(
    *,
    local_positions: list[Position],
    broker_positions: list[Position],
    tolerance: Decimal = Decimal("0.0001"),
    now: datetime,
) -> ReconciliationResult:
    """مطابقة سجلاتنا مع الوسيط. أي اختلاف = مشكلة، لا 'تقريب'."""
    problems: list[str] = []

    # **الأداة تحتمل أكثر من مركز، فتُجمع كمياتها لا يمحو أحدُها الآخر.**
    #
    # كان الجانبان يُبنيان قاموساً مفتاحه الرمز، فيُسقط المركزُ الثاني على
    # الأداة نفسها الأولَ ويبقى واحدٌ يُقارَن. وكابيتال يسمح بعدّة مراكز
    # على الأداة الواحدة: يوم 2026-09-04 كان على GBPUSD مركزان بـ٢٠٠ لكلٍّ
    # منهما، فقرأ المطابِق ‎-200‎ على الجانبين وقال «مطابَق» — وفي الحساب
    # ‎-400‎. أي أن الخطأ كان يُخفي فارقاً حقيقياً لا يخترعه.
    def _totals(positions: list[Position]) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for position in positions:
            totals[position.symbol] = totals.get(position.symbol, Decimal("0")) + position.quantity
        return totals

    local_map = _totals(local_positions)
    broker_map = _totals(broker_positions)

    for symbol in sorted(set(local_map) | set(broker_map)):
        local = local_map.get(symbol)
        remote = broker_map.get(symbol)
        if local is None:
            problems.append(f"مركز غير معروف لدينا موجود في حساب الوسيط: {symbol} كمية {remote}.")
        elif remote is None:
            problems.append(f"مركز مسجّل لدينا وغير موجود لدى الوسيط: {symbol} كمية {local}.")
        elif abs(local - remote) > tolerance:
            problems.append(
                f"اختلاف كمية {symbol}: لدينا {local} ولدى الوسيط {remote}."
            )

    return ReconciliationResult(
        matched=not problems,
        checked_at_utc=now,
        local_positions=tuple(local_positions),
        broker_positions=tuple(broker_positions),
        discrepancies_ar=tuple(problems),
    )
