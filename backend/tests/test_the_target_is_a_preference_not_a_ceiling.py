"""
هدفٌ يُرفض به — فيصير سقفاً لم يعتمده أحد.

## القرار المكتوب

* `Target Risk` = 10.00$ — **المخاطرة المفضّلة**.
* `Hard Maximum` = 12.00$ — **السقف الذي لا يُتجاوَز**.

(كانا 0.75 و1.50 حتى ١١ سبتمبر ٢٠٢٦، ثم رفعتهما المالكة في التجريبي
وحده. **والقاعدة التي يحرسها هذا الملف لم تتغيّر**: الهدف يُختار به
الحجم ولا يُرفض به. تغيّرت الأرقامُ وحدها.)

ونصُّ المالكة: «لا تعامل 0.75 USD كسقف رفض مطلقاً. إذا كان أصغر حجم قابل
للتنفيذ يعرض 1.00 USD للخسارة، وكان الحد الصلب 1.50 ولم تُخالف بقية
الحدود، فلا ترفض الصفقة لمجرد تجاوز الهدف بـ0.25.»

## وما كان في الكود

    budget = min(target_risk, effective_max, remaining_day, remaining_week, ...)
    cap    = min(budget, effective_max)
    if economics.all_in_risk > cap: reject

فـ`cap` لا يتجاوز الهدف أبداً. أي أن ١٫٥٠ **لم تكن بوابة قط**؛ البوابة
الفعلية كانت ٠٫٧٥. وسقفٌ مكتوبٌ لا يُقرأ هو العيب الحاكم في المشروع:
قيمةٌ تُعلَن ولا تُقرأ في موضع تنفيذها.

## وما لا يجوز أن ينكسر

الحدود الأخرى تبقى بوابات: ما تبقّى من اليوم والأسبوع والإجمالي، والحدّ
الصلب نفسه. السلّم يبحث عن حجمٍ **تحت** السقف، ولا يرفعه.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.contracts import Broker, Decision, Side, Signal, StopKind

from .conftest import make_balances
from app.money import D
from app.risk.capital_costs import (
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
)
from app.risk.constitution import RiskLimits, RiskMode
from app.risk.engine import RiskEngine, SessionRiskState
from app.risk.size_ladder import (
    BROKER_MIN_QUANTITY_RISK_EXCEEDED,
    POSITION_SIZE_ROUNDED_TO_ZERO,
    build_ladder,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

#: EUR/USD كما قِيس من حساب Demo في 2026-09-03 — الكمية الدنيا ١٠٠،
#: ودرجة الزيادة ١٠٠، والحدّ ٠٫٠١٪.
EURUSD = InstrumentEconomics(
    epic="EURUSD", pip_size=D("0.0001"), lot_size=D("1"),
    min_deal_size=D("100"), size_increment=D("100"),
    margin_factor=D("3.333333"), margin_factor_unit="PERCENTAGE",
    min_stop_distance=D("0.01"), min_stop_distance_unit="PERCENTAGE",
    min_guaranteed_stop_distance=D("0.25"),
    min_guaranteed_stop_distance_unit="PERCENTAGE",
    guaranteed_stop_available=True, quote_currency="USD",
    overnight_fee_rate_daily=None, provenance=ValueProvenance.BROKER_DISCOVERY,
)

ASSUMPTIONS = CfdCostAssumptions(
    spread_price=D("0.00007"), slippage_reserve_pips=D("1.0"),
    guaranteed_stop_premium_pips=None, currency_conversion_pct=D("0"),
    nights_held=0, spread_provenance=ValueProvenance.BROKER_DISCOVERY,
)


def model() -> CapitalComCostModel:
    return CapitalComCostModel(economics=EURUSD, assumptions=ASSUMPTIONS)


def limits(baseline: str = "300") -> RiskLimits:
    return RiskLimits.for_mode(RiskMode.VALIDATION, D(baseline), Broker.CAPITAL_COM)


def state(baseline: str = "300", day_loss: str = "0", week_loss: str = "0") -> SessionRiskState:
    return SessionRiskState(
        baseline_equity=D(baseline), current_equity=D(baseline),
        realized_pnl_today=-D(day_loss), realized_pnl_week=-D(week_loss),
        unrealized_pnl=D("0"), open_positions=0, entry_orders_today=0,
        consecutive_losses=0,
    )


def signal(*, entry="1.16000", stop="1.15000", target="1.18000", side=Side.BUY) -> Signal:
    return Signal(
        strategy_name="LADDER_TEST", strategy_version="1.0.0", symbol="EURUSD",
        side=side, entry_price=D(entry), stop_price=D(stop),
        take_profit_price=D(target), generated_at_utc=NOW,
        rationale_ar="فحص", invalidation_ar="—", inputs_digest="t",
    )


def decide(sig: Signal, *, st: SessionRiskState | None = None, cash: str = "300"):
    engine = RiskEngine(limits())
    st = st or state()
    pip = EURUSD.pip_size
    return engine.evaluate_cfd(
        signal=sig, state=st,
        balances=make_balances(cash, at=NOW),
        cost_model=model(),
        stop_distance_pips=abs(sig.entry_price - sig.stop_price) / pip,
        take_profit_distance_pips=abs(sig.take_profit_price - sig.entry_price) / pip,
        stop_kind=StopKind.NORMAL,
        kill_switch_active=False, now=NOW,
    )


# ---------------------------------------------------------------------------
# ١ · الحدود كما اعتمدتها المالكة
# ---------------------------------------------------------------------------

def test_the_two_numbers_are_what_the_owner_approved():
    lim = limits()
    assert lim.target_risk_per_trade == D("5.00")
    assert lim.max_risk_per_trade == D("10.00")
    assert lim.daily_loss == D("24.00")
    assert lim.weekly_loss == D("48.00")
    assert lim.hard_total_loss == D("72.00")
    assert lim.max_open_positions == 2


def test_the_ceiling_and_the_preference_are_two_different_numbers():
    engine = RiskEngine(limits())
    st = state()
    assert engine.target_risk_for_next_trade(st) == D("5.00")
    assert engine.hard_risk_ceiling(st) == D("10.00")


# ---------------------------------------------------------------------------
# ٢ · الحالات الخمس المطلوبة
# ---------------------------------------------------------------------------

def test_risk_below_the_target_is_accepted():
    """وقفٌ قصير ⇒ خسارةٌ دون الهدف. تُقبل، ويُختار أقرب حجمٍ إلى الهدف."""
    d = decide(signal(entry="1.16000", stop="1.15800", target="1.16600"))
    assert d.approved, d.reason_ar
    # يُقرأ من الحدود لا يُكتب رقماً: رقمٌ مثبَّتٌ هنا يمرّ لو غُيّر الحدّ
    # في الدستور وفي الاختبار معاً — وتلك طريقةُ إلغاء حدٍّ بصمت.
    assert d.expected_risk_usd <= limits().max_risk_per_trade


def test_risk_between_the_target_and_the_hard_cap_is_accepted():
    """
    **الحالة التي كانت تُرفض.** أرخص كميةٍ (١٠٠ وحدة) بوقف ٥٠٠ نقطة تخسر
    نحو ٥٫٠٢ دولار — فوق الهدف ٥٫٠٠ ودون السقف ٦٫٠٠. ولا حجمَ أصغر: الكمية
    الدنيا عند الوسيط ١٠٠.

    (كانت ١٠٠ نقطة تكفي حين كان الهدف ٠٫٧٥؛ وبعد الرفع صارت تلك الحالة
    **دون** الهدف، فأُعيد اشتقاق المسافة من الحدود الجديدة لا من ذاكرة
    الأرقام القديمة.)
    """
    # الهدفُ ٨٠٠ نقطة لا ٧٥٠: النسبةُ المشروطة **صافيةٌ بعد التكاليف**،
    # و٧٥٠ تعطي 1.49 فتُرفض عند حدّ 1.5. التكلفةُ تُحسب لا تُهمَل.
    d = decide(signal(entry="1.16000", stop="1.11000", target="1.24000"))
    assert d.approved, d.reason_ar
    lim = limits()
    assert lim.target_risk_per_trade < d.expected_risk_usd <= lim.max_risk_per_trade, (
        d.expected_risk_usd
    )
    assert d.reason_code is None


def test_the_reason_says_it_passed_the_target_and_why_that_is_allowed():
    d = decide(signal(entry="1.16000", stop="1.15000", target="1.18000"))
    text = " ".join(msg for _, _, msg in d.checks)
    assert "تفضيلٌ لا سقف" in text, text


def test_risk_exactly_at_the_hard_cap_is_accepted():
    """السقف حدٌّ شامل: المساواة تمرّ، والتجاوز يُرفض."""
    ladder = build_ladder(
        cost_model=model(), entry_price=D("1.16000"),
        stop_distance_pips=D("100"), take_profit_distance_pips=D("200"),
        stop_kind=StopKind.NORMAL, target_risk=D("0.75"),
        hard_ceiling=D("1.02"), available_margin=D("300"),
    )
    assert ladder.approved
    assert ladder.chosen.all_in_risk == D("1.02")


def test_risk_above_the_hard_cap_is_refused_by_its_own_name():
    # ٧٠٠ نقطة على الكمية الدنيا ⇒ نحو ٧٫٠٢ دولار، فوق السقف ٦٫٠٠.
    d = decide(signal(entry="1.16000", stop="1.03000", target="1.39000"))
    assert d.decision is Decision.NO_TRADE
    assert d.reason_code == BROKER_MIN_QUANTITY_RISK_EXCEEDED, d.reason_ar
    assert "السقف الصلب" in d.reason_ar
    assert "الهدف" in d.reason_ar and "ليس سبب الرفض" in d.reason_ar


# ---------------------------------------------------------------------------
# ٣ · السلّم يختار، ولا يرفع سقفاً
# ---------------------------------------------------------------------------

def test_the_ladder_uses_the_brokers_increment_not_a_free_number():
    ladder = build_ladder(
        cost_model=model(), entry_price=D("1.16000"),
        stop_distance_pips=D("20"), take_profit_distance_pips=D("60"),
        stop_kind=StopKind.NORMAL, target_risk=D("0.75"),
        hard_ceiling=D("1.50"), available_margin=D("300"),
    )
    assert ladder.approved
    assert ladder.chosen.size % D("100") == 0
    assert ladder.chosen.size >= D("100")


def test_the_ladder_picks_the_step_closest_to_the_target():
    ladder = build_ladder(
        cost_model=model(), entry_price=D("1.16000"),
        stop_distance_pips=D("20"), take_profit_distance_pips=D("60"),
        stop_kind=StopKind.NORMAL, target_risk=D("0.75"),
        hard_ceiling=D("1.50"), available_margin=D("300"),
    )
    gaps = [(abs(c.all_in_risk - D("0.75")), c.size) for c in ladder.candidates if c.feasible]
    assert ladder.chosen.size == min(gaps)[1]


def test_the_ladder_never_returns_a_step_above_the_ceiling():
    for ceiling in ("0.30", "0.60", "0.90", "1.20", "1.50"):
        ladder = build_ladder(
            cost_model=model(), entry_price=D("1.16000"),
            stop_distance_pips=D("20"), take_profit_distance_pips=D("60"),
            stop_kind=StopKind.NORMAL, target_risk=D("0.75"),
            hard_ceiling=D(ceiling), available_margin=D("300"),
        )
        if ladder.approved:
            assert ladder.chosen.all_in_risk <= D(ceiling)


def test_the_trace_names_every_size_it_tried():
    """رفضٌ بلا أثرٍ لا يُراجَع. الأحجام المجرَّبة وخسارةُ كلٍّ منها تُقال."""
    ladder = build_ladder(
        cost_model=model(), entry_price=D("1.16000"),
        stop_distance_pips=D("300"), take_profit_distance_pips=D("600"),
        stop_kind=StopKind.NORMAL, target_risk=D("0.75"),
        hard_ceiling=D("1.50"), available_margin=D("300"),
    )
    assert not ladder.approved
    assert ladder.reason_code == BROKER_MIN_QUANTITY_RISK_EXCEEDED
    assert "الأحجام المجرَّبة" in ladder.trace_ar()
    assert "100" in ladder.trace_ar()


# ---------------------------------------------------------------------------
# ٤ · الحدود الأخرى تبقى بوابات
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "day_loss,week_loss,expected_ceiling",
    [("0", "0", "10.00"), ("16.00", "16.00", "8.00"), ("0", "43.50", "4.50")],
)
def test_the_ceiling_shrinks_with_what_is_left_of_the_day_and_week(
    day_loss, week_loss, expected_ceiling
):
    engine = RiskEngine(limits())
    st = state(day_loss=day_loss, week_loss=week_loss)
    assert engine.hard_risk_ceiling(st) == D(expected_ceiling)


def test_a_spent_day_refuses_even_a_cheap_trade():
    st = state(day_loss="24.00", week_loss="24.00")
    d = decide(signal(entry="1.16000", stop="1.15800", target="1.16600"), st=st)
    assert d.decision is Decision.NO_TRADE
    assert d.reason_code is not None


def test_margin_still_binds():
    d = decide(signal(entry="1.16000", stop="1.15800", target="1.16600"), cash="0.50")
    assert d.decision is Decision.NO_TRADE


def test_a_zero_increment_does_not_produce_a_zero_size():
    """درجةٌ صفرية مواصفةٌ ناقصة، لا «حجمٌ واحد ممكن»."""
    econ = EURUSD.__class__(**{**EURUSD.__dict__, "min_deal_size": D("0")})
    ladder = build_ladder(
        cost_model=CapitalComCostModel(economics=econ, assumptions=ASSUMPTIONS),
        entry_price=D("1.16000"), stop_distance_pips=D("20"),
        take_profit_distance_pips=D("60"), stop_kind=StopKind.NORMAL,
        target_risk=D("0.75"), hard_ceiling=D("1.50"), available_margin=D("300"),
    )
    assert not ladder.approved
    assert ladder.reason_code == POSITION_SIZE_ROUNDED_TO_ZERO
