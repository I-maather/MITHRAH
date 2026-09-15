"""
حارسان يمنعان ما لا يمنعه عدُّ المراكز.

## لماذا هذان الاثنان بالذات

خسائرُ ٤ سبتمبر لم تكن قراراتٍ مستقلّة: ثلاثةُ مراكز GBPUSD بيع خلال
ساعتَين ونصف. وحدُّ العدد رآها ثلاثاً مستقلّة وسمح بها.

⇒ **حدُّ العدد يعدّ ولا يقيس.** وهذان الحارسان يقيسان ما يعدّه:

1. **دلوُ التعرّض** — أدواتٌ تتحرّك بالسبب نفسه ليست فرصاً مستقلّة.
2. **حرارةُ المحفظة** — ثلاثةُ مراكزَ كلٌّ منها عند السقف الصلب تخسر
   مجتمعةً ٤٫٥٠؛ وحدُّ العدد لا يقول ذلك.

## وما تثبته هذه الاختبارات

أن الحارس **يضيّق السقف** لا أنه **يرفض**. الرفضُ يقع فقط حين يثبت سلّمُ
الأحجام أنّ أصغرَ حجمٍ ممكنٍ ما زال فوق السقف الضيّق — وهذا نصُّ فلسفة
المشاركة في دستور المشروع: الحارسُ يضيّق المساحة ولا يغلق الباب.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.contracts import Broker
from app.money import D
from app.risk.constitution import (
    IncoherentRiskLimits,
    RiskLimits,
    RiskMode,
    exposure_bucket,
)
from app.risk.engine import RiskEngine
from tests.conftest import make_state

VALIDATION_300 = RiskLimits.for_mode(RiskMode.VALIDATION, D("300.00"), Broker.CAPITAL_COM)


# ── ١ · الدلو المشترك ────────────────────────────────────────────────

def test_the_euro_and_the_pound_are_one_bet_not_two() -> None:
    assert exposure_bucket("EURUSD") == exposure_bucket("GBPUSD")


def test_the_yen_and_the_gold_keep_their_own_buckets() -> None:
    """الدمجُ على المنطقة الاقتصادية لا على «كلُّها مقابل الدولار»."""
    buckets = {exposure_bucket(s) for s in ("EURUSD", "USDJPY", "GOLD")}
    assert len(buckets) == 3


def test_an_unknown_symbol_gets_its_own_bucket() -> None:
    """المجهولُ يُفترَض **مستقلاً** لا **مثلَ غيره**."""
    assert exposure_bucket("XYZABC") == "XYZABC"


# ── ٢ · قيمةُ السقف ──────────────────────────────────────────────────

def test_the_validation_cap_is_one_trade_per_allowed_position() -> None:
    """السقفُ = عددُ المراكز المسموح × المخاطرة المستهدفة — لا رقمٌ مستقلّ."""
    assert VALIDATION_300.max_portfolio_risk == D("20.00")
    assert (
        VALIDATION_300.max_portfolio_risk
        == VALIDATION_300.target_risk_per_trade * VALIDATION_300.max_open_positions
    )


def test_the_cap_scales_with_the_reference_capital() -> None:
    """نسبةٌ لا رقمٌ مثبَّت: مرجعٌ آخر ⇒ سقفٌ آخر بالنسبة نفسها."""
    half = RiskLimits.for_mode(RiskMode.VALIDATION, D("150.00"), Broker.CAPITAL_COM)
    assert half.max_portfolio_risk == VALIDATION_300.max_portfolio_risk / 2


# ── ٣ · أثرُ الحرارة على السقف ───────────────────────────────────────

def test_an_empty_book_leaves_the_ceiling_to_the_per_trade_limit() -> None:
    engine = RiskEngine(VALIDATION_300)
    state = make_state(baseline_equity=D("300.00"), current_equity=D("300.00"))
    assert engine.remaining_portfolio_heat(state) == D("20.00")
    assert engine.hard_risk_ceiling(state) == VALIDATION_300.effective_max_risk(D("300.00"))


def test_open_heat_narrows_the_ceiling_instead_of_rejecting() -> None:
    """
    **هذا هو جوهرُ الحارس.**

    حرارةٌ مفتوحة 9.50 تترك 0.50 — فيصير السقفُ 0.50 لا 6.00. والإشارةُ
    لا تُرفَض هنا: تُمرَّر إلى سلّم الأحجام بسقفٍ أضيق.
    """
    engine = RiskEngine(VALIDATION_300)
    state = make_state(
        baseline_equity=D("300.00"), current_equity=D("300.00"),
        open_positions=1, open_symbols=("EURUSD",),
        open_risk_at_stop=D("19.50"),
    )
    assert engine.remaining_portfolio_heat(state) == D("0.50")
    assert engine.hard_risk_ceiling(state) == D("0.50")


def test_a_full_book_leaves_no_room_and_says_so_as_zero() -> None:
    engine = RiskEngine(VALIDATION_300)
    state = make_state(
        baseline_equity=D("300.00"), current_equity=D("300.00"),
        open_positions=2, open_risk_at_stop=D("20.00"),
    )
    assert engine.remaining_portfolio_heat(state) == D("0")
    assert engine.hard_risk_ceiling(state) == D("0")


def test_heat_above_the_cap_never_goes_negative() -> None:
    """سقفٌ سالبٌ يعني «استدن مخاطرة» — يُقصّ عند الصفر."""
    engine = RiskEngine(VALIDATION_300)
    state = make_state(
        baseline_equity=D("300.00"), current_equity=D("300.00"),
        open_positions=2, open_risk_at_stop=D("99.99"),
    )
    assert engine.remaining_portfolio_heat(state) == D("0")


# ── ٤ · الجهلُ ليس صفراً ─────────────────────────────────────────────

def test_one_position_without_a_known_stop_closes_the_door() -> None:
    """
    مركزٌ بلا وقفٍ معروف ⇒ الحرارةُ غيرُ قابلةٍ للحساب.

    ومجموعٌ فيه مجهولٌ ليس مجموعاً. فلا يُحسب صفراً ولا يُقدَّر: يُغلَق
    البابُ حتى يُعرَف — وهو نفسُ الفرق الذي أُخذ على `why_no_trade.sh`
    حين عرض «لم أقرأ» على أنه «لا شيء».
    """
    engine = RiskEngine(VALIDATION_300)
    state = make_state(
        baseline_equity=D("300.00"), current_equity=D("300.00"),
        open_positions=1, open_risk_at_stop=D("0.00"), open_risk_unknown=1,
    )
    assert engine.remaining_portfolio_heat(state) == D("0")
    assert engine.hard_risk_ceiling(state) == D("0")


def test_the_unknown_wins_even_when_measured_heat_is_tiny() -> None:
    engine = RiskEngine(VALIDATION_300)
    state = make_state(
        baseline_equity=D("300.00"), current_equity=D("300.00"),
        open_positions=2, open_risk_at_stop=D("0.50"), open_risk_unknown=1,
    )
    assert engine.remaining_portfolio_heat(state) == D("0")


# ── ٥ · وضعٌ بلا سقف ─────────────────────────────────────────────────

def test_a_mode_without_a_cap_is_not_narrowed() -> None:
    """الأوضاعُ التي تسمح بمركزٍ واحد لا تحتاج سقفَ حرارة — ولا يُخترَع لها."""
    single = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING, D("300.00"), Broker.CAPITAL_COM)
    assert single.max_portfolio_risk is None
    engine = RiskEngine(single)
    state = make_state(baseline_equity=D("300.00"), current_equity=D("300.00"))
    assert engine.remaining_portfolio_heat(state) == Decimal("Infinity")
    assert engine.hard_risk_ceiling(state) == single.effective_max_risk(D("300.00"))


# ── ٦ · إعدادٌ يناقض نفسه يُرفَض عند البناء ─────────────────────────

def test_a_cap_below_the_target_is_refused_at_build_not_at_first_signal() -> None:
    """
    سقفٌ أصغرُ من المخاطرة المستهدفة يمنع **أوّلَ** صفقةٍ ولا يحمي شيئاً.

    ويُرفَض عند البناء لا عند أوّل إشارةٍ تُردّ بلا سببٍ مفهوم — وهو نفسُ
    منطق الفحص القائم على الحدّ اليومي.
    """
    fields = {
        f: getattr(VALIDATION_300, f)
        for f in VALIDATION_300.__dataclass_fields__
    }
    fields["max_portfolio_risk"] = VALIDATION_300.target_risk_per_trade - D("0.01")
    with pytest.raises(IncoherentRiskLimits):
        RiskLimits(**fields)


def test_the_shipped_validation_limits_are_coherent() -> None:
    """البناءُ نفسُه هو الاختبار: فحصُ الاتّساق يعمل عند الإنشاء."""
    assert RiskLimits.for_mode(RiskMode.VALIDATION, D("300.00"), Broker.CAPITAL_COM)


# ── ٧ · أرقامُ الرفع، مقروءةً من الدستور لا مكتوبةً هنا مرّتين ────────

def test_the_raised_risk_is_what_the_owner_approved() -> None:
    """
    **قرارُ المالكة ١١ سبتمبر، في التجريبي وحده.**

    اختبارٌ يثبّت القيم المعتمدة كي لا تنزلق بصمت. وهو تشديدٌ لا تخفيف:
    تغييرُ أيٍّ منها يجب أن يكسر هذا الاختبار فيُرى، لا أن يمرّ في مراجعة.
    """
    assert VALIDATION_300.target_risk_per_trade == D("10.00")
    assert VALIDATION_300.max_risk_per_trade == D("12.00")
    assert VALIDATION_300.daily_loss == D("24.00")
    assert VALIDATION_300.weekly_loss == D("48.00")
    assert VALIDATION_300.hard_total_loss == D("72.00")
    assert VALIDATION_300.max_open_positions == 2
    assert VALIDATION_300.max_portfolio_risk == D("20.00")


def test_the_daily_cap_still_absorbs_every_stop_at_once() -> None:
    """
    الثابتُ الذي فرض «مركزان لا ثلاثة»: 12.00 × 2 = 24.00 ≤ 24.00 — بالحدّ تماماً.

    ولو صارت ثلاثة لبلغت 18.00 وتجاوزت حدَّ اليوم ⇒ حدٌّ يُخترَق قبل أن
    يعمل، ويرفضه البناءُ نفسه.
    """
    worst = VALIDATION_300.max_risk_per_trade * VALIDATION_300.max_open_positions
    assert worst <= VALIDATION_300.daily_loss


def test_three_positions_at_this_risk_would_be_refused_at_build() -> None:
    fields = {f: getattr(VALIDATION_300, f) for f in VALIDATION_300.__dataclass_fields__}
    fields["max_open_positions"] = 3
    with pytest.raises(IncoherentRiskLimits):
        RiskLimits(**fields)


def test_the_real_modes_were_not_touched() -> None:
    """الرفعُ في التجريبي وحده — والأوضاعُ التي تلمس مالاً حقيقياً كما كانت."""
    live = RiskLimits.for_mode(RiskMode.LIVE_COMMISSIONING, D("300.00"), Broker.CAPITAL_COM)
    assert live.max_open_positions == 1
    assert live.max_entry_orders_per_day == 1
    assert live.max_risk_per_trade == D("1.50")
