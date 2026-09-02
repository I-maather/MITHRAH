"""
**لا رقم من عمولات IBKR يقدر أن يغيّر قراراً على كابيتال.**

## السؤال الذي يجيبه هذا الملف

سألت المالكة: «تأكّدي لي النظام كامل يشتغل على عمولات كابيتال فقط، ولا
يخلط بينها وبين IBKR؟» — وكانت قد سألت السؤال نفسه قبل أسبوع، فأُجيبت
«نعم» بعد إصلاح طبقة **الأهلية** وحدها. وبقيت طبقة **المخاطرة والتحجيم**
تستدعي `risk.evaluate` — مسار أسهم IBKR — على كل صفقة.

⇒ الجواب «نعم» لا يساوي شيئاً ما لم يُثبَت. والفرق بين إثباتين:

  * فحصٌ يُثبت أن CFD **يذهب** إلى نموذج كابيتال — وهذا موجود في
    `test_the_pipeline_prices_with_the_right_broker.py`. يُثبت وجود الطريق.
  * فحصٌ يُثبت أنه **لا طريق آخر** — وهو هذا الملف. ويُثبت بالطريقة
    الوحيدة التي لا تُخدع: **يُفسَد جدول IBKR إفساداً فاضحاً**، ثم يُنظر
    هل تحرّك قرارُ كابيتال بمقدار سنت.

إن لم يتحرّك، فالجدول لا يُقرأ في هذا المسار — وهذا برهان، لا وصف.

## ولماذا الإفساد لا التحقّق من الاستدعاء

فحصٌ يقول «`evaluate_cfd` استُدعيت» يمرّ حتى لو استُدعيت الاثنتان وأُخذ
أسوأهما. وفحصٌ يقارن رقماً برقمٍ يمرّ بالمصادفة إن تقاربا. أمّا عمولةٌ
بألف دولار للأمر: لو دخلت الحساب بأي وزنٍ لظهرت. فالإفساد هو المِحَكّ.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timezone
from decimal import Decimal

import pytest

from app.audit.log import AuditLog, InMemoryAuditStore
from app.brokers.mock import MockBehaviour, make_quote
from app.contracts import Broker, DataSource, Decision
from app.execution.orders import ExecutionService, IdempotencyGuard
from app.killswitch.engine import KillSwitch
from app.money import D
from app.pipeline.runner import BlackoutCalendar, MacroAssessment, Pipeline
from app.risk.constitution import RiskLimits, RiskMode
from app.risk.costs import IBKR_PRO_TIERED_US_STOCK, CommissionSchedule, CostAssumptions
from app.risk.engine import RiskEngine, SessionRiskState
from app.risk.instrument_registry import InstrumentRegistry
from tests.conftest import (
    MID_SESSION, make_balances, make_permissions, uptrend_bars,
)
from tests.test_the_pipeline_prices_with_the_right_broker import (
    MEASURED, CapitalLikeBroker, FixedSignal, capital_permissions,
)

UTC = timezone.utc
NO_MACRO = MacroAssessment(blocks_trading=False, reason_ar="لا مانع كلي.")


def absurd_schedule() -> CommissionSchedule:
    """
    جدول عمولاتٍ فاضح الفساد. **لو دخل الحساب بأي وزنٍ لظهر.**

    القيم تُبنى بـ`replace` من الجدول الحقيقي كي يبقى الشكل صالحاً مهما
    تغيّرت حقول `CommissionSchedule` — فحصٌ يُكسَر عند إضافة حقل ليس حارساً.
    """
    schedule = IBKR_PRO_TIERED_US_STOCK
    changes = {}
    for field, value in vars(schedule).items():
        if isinstance(value, Decimal):
            changes[field] = D("1000")
    return replace(schedule, **changes)


def absurd_assumptions() -> CostAssumptions:
    base = CostAssumptions.default()
    changes = {
        field: D("1000")
        for field, value in vars(base).items()
        if isinstance(value, Decimal)
    }
    return replace(base, **changes)


def build(*, schedule, assumptions, symbol="GOLD", now=MID_SESSION):
    """
    السهم يحتاج صلاحيات سهم ووسيط IBKR ورأس مالٍ يتّسع له. وأوّل كتابةٍ
    لهذا الملف مرّرت صلاحيات كابيتال إلى `SPY`، فسقط عند
    `PERMISSIONS_INSUFFICIENT` **قبل أن يبلغ نموذج التكلفة** — فبدا أن
    الإفساد لم يصل إلى مسار الأسهم، وهو لم يبلغه أصلاً.
    وهذا بالضبط ما جاء فحص الضبط ليمسكه، فمسكه في نفسه.
    """
    is_cfd_symbol = symbol in CapitalLikeBroker.CLASSES
    broker = CapitalLikeBroker(behaviour=MockBehaviour(stop_on_fractional_supported=True))
    broker.connect()
    broker.balances = make_balances("300" if is_cfd_symbol else "5000", at=now)
    broker.permissions = (
        capital_permissions(now) if is_cfd_symbol else make_permissions(at=now)
    )
    bid, ask = ("3299.5", "3300.0") if is_cfd_symbol else ("639.99", "640.00")
    broker.set_quote(make_quote(symbol, bid, ask, at=now, source=DataSource.REALTIME))
    audit = AuditLog(InMemoryAuditStore())
    pipeline = Pipeline(
        broker=broker,
        risk_engine=RiskEngine(
            RiskLimits.for_mode(RiskMode.VALIDATION, D("300"), Broker.CAPITAL_COM)
            if is_cfd_symbol
            else RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("5000"), Broker.IBKR)
        ),
        kill_switch=KillSwitch(), audit=audit,
        execution=ExecutionService(broker=broker, audit=audit, guard=IdempotencyGuard()),
        strategies=[
            FixedSignal(entry="3300.0", stop="3280.0", target="3360.0")
            if is_cfd_symbol
            else FixedSignal(entry="640.00", stop="630.00", target="660.00")
        ],
        schedule=schedule, assumptions=assumptions,
        blackouts=BlackoutCalendar(entries=[], confirmed_for={now.date()}),
        instruments=InstrumentRegistry.from_dict(MEASURED),
    )
    equity = D("300") if is_cfd_symbol else D("5000")
    state = SessionRiskState(
        baseline_equity=equity, current_equity=equity,
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )
    return pipeline.run(
        symbol=symbol, bars=uptrend_bars(), state=state, macro=NO_MACRO, now=now
    )


@pytest.fixture(scope="module")
def honest():
    return build(
        schedule=IBKR_PRO_TIERED_US_STOCK,
        assumptions=CostAssumptions(D("0.01"), D("0.0005"), D("0")),
    )


@pytest.fixture(scope="module")
def poisoned():
    return build(schedule=absurd_schedule(), assumptions=absurd_assumptions())


def test_the_poison_is_actually_poisonous():
    """
    **حارسٌ للحارس.** لو لم تتغيّر قيمةٌ واحدة في الجدول المفسَد، لصار
    الفحص التالي يقارن الشيء بنفسه ويمرّ أبداً — وهو أسوأ من غيابه.
    """
    original, poison = IBKR_PRO_TIERED_US_STOCK, absurd_schedule()
    changed = [
        field
        for field, value in vars(original).items()
        if isinstance(value, Decimal) and getattr(poison, field) != value
    ]
    assert changed, "لم يُفسَد شيء — الفحص التالي بلا معنى."


def test_the_honest_gold_run_actually_reached_the_capital_model(honest):
    """
    **حارسٌ ثالث — وقد كُتب لأن الفحص التالي كان فارغاً بدونه.**

    قُلبت طفرةٌ تُلغي التوجيه (`if is_cfd(details)` ⇐ `if False`)، فمرّ
    الفحص التالي كما هو. والسبب: الذهب على مسار الأسهم يُرفض مبكّراً —
    قيمةٌ اسمية 3300 دولاراً على نقدٍ 300 — فيتساوى الجدولان في الرفض
    نفسه، ويُقارَن رفضٌ برفض فيُقال «لم يتحرّك شيء».

    أي أن الفحص كان يقارن فشلين ويسمّي تطابقهما برهاناً. وهو العيب الحاكم
    في الفحوص نفسها: نتيجةٌ تُقرأ من غير الموضع الذي تدّعي قراءته.

    فيُشترَط أوّلاً أن يكون القرار **موافِقاً وبالكمية الدنيا للوسيط** —
    أي أنه بلغ `evaluate_cfd` فعلاً — ثم يُقارَن.
    """
    assert honest.risk_decision is not None, honest.reason_ar
    assert honest.risk_decision.approved, (
        f"القرار الأمين ليس موافِقاً ({honest.reason_code}: {honest.reason_ar}) — "
        "فالمقارنة التالية تقارن فشلاً بفشل."
    )
    assert honest.risk_decision.quantity == D("0.01"), (
        "الكمية ليست الكمية الدنيا للوسيط — أي أن مسار الأسهم هو الذي سعّر."
    )


def test_a_gold_decision_does_not_move_by_one_cent(honest, poisoned):
    """
    **البرهان.** عمولة ألف دولار للأمر، وانزلاقٌ بألف، وسبريدٌ بألف — ولا
    يتحرّك قرار الذهب. أي أن الجدول لا يُقرأ في هذا المسار أصلاً.
    """
    assert honest.risk_decision is not None, honest.reason_ar
    assert poisoned.risk_decision is not None, poisoned.reason_ar
    for field in ("approved", "quantity", "expected_risk_usd",
                  "expected_costs_usd", "notional", "risk_budget_usd"):
        assert getattr(honest.risk_decision, field) == getattr(
            poisoned.risk_decision, field
        ), (
            f"«{field}» تغيّر حين أُفسد جدول IBKR — فهو يُقرأ في مسار كابيتال."
        )
    assert honest.decision is poisoned.decision
    assert honest.reason_code == poisoned.reason_code


def test_the_stock_path_does_still_read_it():
    """
    **الوجه الآخر من البرهان.** لو لم يتحرّك قرار الأسهم أيضاً، لكان عدم
    تحرّك الذهب دليلاً على أن الإفساد لم يقع — لا على أنه لم يُقرأ.

    فيُشغَّل السهم نفسه بالجدولين، ويجب أن **يختلف**.
    """
    honest_stock = build(
        symbol="SPY", schedule=IBKR_PRO_TIERED_US_STOCK,
        assumptions=CostAssumptions(D("0.01"), D("0.0005"), D("0")),
    )
    poisoned_stock = build(
        symbol="SPY", schedule=absurd_schedule(), assumptions=absurd_assumptions(),
    )
    honest_risk = getattr(honest_stock.risk_decision, "expected_risk_usd", None)
    poisoned_risk = getattr(poisoned_stock.risk_decision, "expected_risk_usd", None)
    assert (honest_stock.reason_code != poisoned_stock.reason_code) or (
        honest_risk != poisoned_risk
    ), (
        "لم يتحرّك قرار الأسهم أيضاً — فالإفساد لم يصل إلى أي مسار، "
        "والفحص أعلاه لا يُثبت شيئاً."
    )
