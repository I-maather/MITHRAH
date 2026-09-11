"""
حسابٌ تجريبي برصيد ٩١ ألفاً — ورأس مالٍ مخصَّص قدره ٣٠٠.

## السؤال الذي يجيبه هذا الملف

سؤالٌ من فريق الاختراق: **هل يستطيع النظام تجاوز رأس المال المخصَّص لأن
رصيد الحساب التجريبي كبير؟**

وكان الجواب نعم في موضعٍ واحد: فحص الهامش يقارن بـ
`balances.available_for_new_trade` — وهو رصيد الوسيط. فنظامٌ «يتداول ٣٠٠»
يستطيع أن يحجز آلافاً لأن الرصيد يسمح.

وأثرُه ليس نظرياً: بعد تصحيح وحدة أدنى مسافة الوقف صار التداول داخل اليوم
ممكناً، وأوقافُه أضيق — فيختار سلّمُ الأحجام كمياتٍ أكبر لبلوغ الهدف
نفسه. وعند وقفٍ بستّ نقاط على اليورو تبلغ الكمية تسعمئة وحدة وتعرّضها
ألف دولار: ثلاثة أضعاف المخصَّص كلّه، في صفقةٍ واحدة.

وذلك يُبطل معنى التخصيص: تجربةٌ ناجحة على ٩١ ألفاً **لا تنتقل** إلى ٣٠٠،
لأن قيد الكمية الدنيا غير مُلزم هناك ومُلزمٌ في كل صفقة هنا.

## القاعدة

سقف الهامش لمركزٍ واحد = **المخصَّص ÷ أقصى عدد مراكز متزامنة**. فمجموع
الهوامش لا يتجاوز المخصَّص مهما بلغ الرصيد. وهو حجزٌ لا خسارة، والخسارة
يحكمها سقفها هي — قيدان مستقلّان لا يغني أحدهما عن الآخر.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.contracts import Broker, Decision, Side, Signal, StopKind
from app.money import D
from app.risk.capital_costs import (
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
)
from app.risk.constitution import RiskLimits, RiskMode
from app.risk.engine import MARGIN_EXCEEDS_AVAILABLE, RiskEngine, SessionRiskState

from .conftest import make_balances

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

EURUSD = InstrumentEconomics(
    epic="EURUSD", pip_size=D("0.0001"), lot_size=D("1"),
    min_deal_size=D("100"), size_increment=D("100"),
    margin_factor=D("3.333333"), margin_factor_unit="PERCENTAGE",
    min_stop_distance=D("0.01"), min_stop_distance_unit="PERCENTAGE",
    min_guaranteed_stop_distance=None, guaranteed_stop_available=True,
    quote_currency="USD", overnight_fee_rate_daily=None,
    provenance=ValueProvenance.BROKER_DISCOVERY,
)
ASSUMPTIONS = CfdCostAssumptions(
    spread_price=D("0.00007"), slippage_reserve_pips=D("1.0"),
    guaranteed_stop_premium_pips=None, currency_conversion_pct=D("0"),
    nights_held=0, spread_provenance=ValueProvenance.BROKER_DISCOVERY,
)


def limits() -> RiskLimits:
    return RiskLimits.for_mode(RiskMode.VALIDATION, D("300"), Broker.CAPITAL_COM)


def decide(*, stop_pips: str, broker_cash: str):
    """وقفٌ ضيّق يدفع السلّم إلى كمياتٍ كبيرة — وهو موضع الخطر."""
    engine = RiskEngine(limits())
    state = SessionRiskState(
        baseline_equity=D("300"), current_equity=D("300"),
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )
    stop = D("1.16000") - D(stop_pips) * D("0.0001")
    target = D("1.16000") + D(stop_pips) * D("0.0001") * D("3")
    signal = Signal(
        strategy_name="X", strategy_version="1.0.0", symbol="EURUSD", side=Side.BUY,
        entry_price=D("1.16000"), stop_price=stop, take_profit_price=target,
        generated_at_utc=NOW, rationale_ar="فحص", invalidation_ar="—", inputs_digest="t",
    )
    return engine.evaluate_cfd(
        signal=signal, state=state, balances=make_balances(broker_cash, at=NOW),
        cost_model=CapitalComCostModel(economics=EURUSD, assumptions=ASSUMPTIONS),
        stop_distance_pips=D(stop_pips),
        take_profit_distance_pips=D(stop_pips) * D("3"),
        stop_kind=StopKind.NORMAL, kill_switch_active=False, now=NOW,
    )


def test_the_ceiling_is_the_allocation_divided_by_the_positions():
    lim = limits()
    assert lim.baseline_equity == D("300")
    assert lim.max_open_positions == 2
    # ٣٠٠ ÷ ٢ = ١٥٠. صار مركزان بعد رفع المخاطرة (١١ سبتمبر): سقفٌ صلبٌ
    # ٦٫٠٠ × ٣ مراكز = ١٨ يتجاوز حدَّ اليوم ١٥، فيُرفض الإعدادُ عند البناء.
    assert lim.allocated_margin_per_position == D("150")


def test_a_ninety_one_thousand_balance_does_not_widen_the_position():
    """
    **الفحص الذي يعضّ.** الرصيد التجريبي ٩١ ألفاً، والوقف ست نقاط — وهو
    ما يجعل السلّم يطلب كمياتٍ كبيرة لبلوغ الهدف (٥٫٠٠ بعد الرفع).
    """
    decision = decide(stop_pips="6", broker_cash="91000")
    if decision.approved:
        # لو مرّت، فالهامش لا يتجاوز المخصَّص ÷ المراكز.
        margin = decision.notional * (D("3.333333") / D("100"))
        # يُقرأ من الحدود لا يُكتب رقماً: المخصَّص ÷ المراكز، أيّاً كانا.
        ceiling = limits().allocated_margin_per_position
        assert margin <= ceiling, (
            f"هامش {margin} يتجاوز سقف المخصَّص {ceiling} — الرصيد الكبير وسّع التخصيص."
        )
        assert decision.notional <= ceiling / (D("3.333333") / D("100"))
    else:
        assert decision.reason_code == MARGIN_EXCEEDS_AVAILABLE, decision.reason_ar


def test_three_positions_together_stay_inside_the_allocation():
    """
    مجموع الهوامش الممكنة لا يتجاوز المخصَّص — وهو معنى «مخصَّص».
    """
    lim = limits()
    assert lim.allocated_margin_per_position * lim.max_open_positions <= lim.baseline_equity


def test_a_thin_broker_balance_is_still_the_binding_constraint():
    """والسقف الأصغر يحكم: رصيدٌ ضئيل يبقى قيداً وإن كان المخصَّص أكبر."""
    decision = decide(stop_pips="20", broker_cash="0.50")
    assert decision.decision is Decision.NO_TRADE
    assert decision.reason_code == MARGIN_EXCEEDS_AVAILABLE, decision.reason_ar
    assert "رصيد الحساب عند الوسيط" in decision.reason_ar


def test_the_rejection_names_which_constraint_bound():
    """«الهامش لا يكفي» وحدها ترسل المالكة تبحث في المكان الخطأ."""
    thin = decide(stop_pips="20", broker_cash="0.50")
    assert "المخصَّص" in thin.reason_ar and "المتاح عند الوسيط" in thin.reason_ar


def test_a_normal_daily_stop_is_untouched_by_the_ceiling():
    """
    ولا يضيق القيد على الحالة العادية: وقفٌ بمئة نقطة عند الكمية الدنيا
    هامشُه نحو ٣٫٨٧ دولار — بعيدٌ جداً عن السقف.
    """
    decision = decide(stop_pips="100", broker_cash="91000")
    assert decision.approved, decision.reason_ar
    margin_text = " ".join(m for _, _, m in decision.checks if "الهامش" in m)
    assert "ضمن سقف" in margin_text
