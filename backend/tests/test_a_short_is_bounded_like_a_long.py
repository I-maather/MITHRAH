"""
هل خسارةُ البيع مقيّدةٌ كخسارة الشراء؟ — يُقاس، لا يُستفتى فيه.

## السؤال ولماذا لا يُحال إلى المالكة

قالت: «الهدف أن النظام هو يقرّر، لا أنا». والذهب اليوم في هبوطٍ مؤكَّد
(ADX14 = 49.4، متوسط 10 تحت متوسط 30) — فالإشارة التي ينتظرها النظام
**بيعٌ**، و`CFD_ALLOW_SHORT = False` سترفضها. أي أن النظام يرصد الاتجاه
الوحيد المتاح ثم يمنع نفسه من التصرّف فيه.

وسؤال «هل نسمح بالبيع؟» ليس رأياً يُطلب منها؛ هو سؤالٌ **قابل للقياس**:
هل خسارة البيع في هذا النظام مقيّدةٌ بالقيد نفسه الذي يقيّد الشراء؟

## من أين جاءت الرايةُ أصلاً

هي مكتوبةٌ تحت كتلة سياسة أسهم IBKR مباشرة:

    ALLOW_MARGIN = False          # لأسهم IBKR
    ALLOW_SHORT = False
    ...
    CFD_ALLOW_SHORT = False

وفي بيع الأسهم النقدي ثلاثةُ مخاطر حقيقية: أجرةُ اقتراض السهم، واستدعاءُ
المُقرِض (buy-in)، وخسارةٌ غير محدودة إن لم يُنفَّذ الوقف. **ولا واحدٌ
منها قائم هنا**: عقد الفروقات لا يُقترَض فيه شيء، والوقف عند الوسيط
إلزامي (`CFD_REQUIRE_BROKER_STOP = True`)، والمبيت ممنوع
(`allow_overnight = False`) فلا فائدةَ تبييتٍ تختلف بين الجهتين.

⇒ الرايةُ لم تكن قراراً في سياقها؛ كانت **منقولةً من سياقٍ آخر**. وهذا
هو الصنف الحاكم في هذا المشروع بعينه: قيمةٌ تُطبَّق حيث لم تُقَس.

## وما وجدَه هذا الملف حين قِيسَ بدل أن يُفترَض

الطفرة الأولى (رفع الراية وتشغيل بيعٍ حقيقي عبر خط الأنابيب كاملاً)
انتهت بـ:

    RECONCILIATION_MISMATCH: لدينا 0.01 ولدى الوسيط -0.01

أمرُ بيعٍ **نُفِّذ في السوق**، ومركزٌ مفتوح، ثم نظامٌ يوقف نفسه لأننا
كتبنا الكمية بلا جهتها بينما يُبلّغها الوسيط سالبة. فلو فُتحت الراية
وحدها لكانت أوّل صفقة بيعٍ تُملأ ثم تُجمّد الآلة وهي في السوق.

⇒ فتحُ البيع ليس تغيير راية. هذا الملف يُثبت **التماثل**، ويحرس الموضع
الذي لولاه لصار التماثل نظرياً وحده.

## ما يبقى غير متماثل — ويُقال ولا يُخفى

سعرُ الأداة ينزل إلى الصفر وحسب، ويصعد بلا سقفٍ نظري. فالذيل غير
المحدود يخصّ البيع وحده — **إن اختُرِق الوقف**. وهذا الاختراق ممكنٌ في
الجهتين (فجوةُ سعر)، ويقيّده هنا شيئان: الوقف عند الوسيط لا عندنا، وأن
المركز لا يبيت ولا يعبر عطلة. ويبقى فرقاً حقيقياً في الذيل، لا يُلغى
بحجّة، ويُقاس على الذهب في `scripts/prove_short_symmetry.py`.
"""
from __future__ import annotations

import inspect
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.contracts import Decision, Side
from app.money import D
from app.risk.capital_costs import CapitalComCostModel
from app.risk.constitution import (
    CFD_ALLOW_HEDGING,
    CFD_REQUIRE_BROKER_STOP,
    Broker,
    RiskLimits,
    RiskMode,
)
from tests.test_the_pipeline_prices_with_the_right_broker import build, run

#: زوجٌ متناظر على الذهب: المسافة نفسها في الجهتين، والهدف 6R كي **يُقبَل**
#: الطرفان. ولو قُبل أحدهما ورُفض الآخر لصار الفحص مقارنةَ فشلٍ بفشل.
ENTRY = "3300.0"
BUY_LEG = dict(side=Side.BUY, stop="3280.0", target="3420.0")
SELL_LEG = dict(side=Side.SELL, stop="3320.0", target="3180.0")


def leg(**kw):
    """يشغّل ساقاً واحدة عبر خط الأنابيب الحقيقي بالراية مرفوعة."""
    side, stop, target = kw["side"], kw["stop"], kw["target"]
    with patch("app.risk.engine.CFD_ALLOW_SHORT", True):
        pipeline, state, broker = build(
            symbol="GOLD", entry=ENTRY, stop=stop, target=target,
            baseline="300", bid="3299.5", ask="3300.0", side=side,
        )
        return run(pipeline, state, "GOLD")


@pytest.fixture(scope="module")
def pair():
    return leg(**BUY_LEG), leg(**SELL_LEG)


# ---------------------------------------------------------------------------
# ١ · حارسُ الحارس: هل بلغ الطرفان التنفيذ أصلاً؟
# ---------------------------------------------------------------------------
def test_both_legs_actually_reached_a_decision_to_trade(pair):
    """
    **بلا هذا الفحص، ما بعده بلا معنى.** رفضان متطابقان يبدوان تماثلاً
    تاماً — وهو الفخّ الذي وقعتُ فيه ثلاث مرات في هذه الجلسة وحدها.
    """
    buy, sell = pair
    assert buy.decision is Decision.TRADE, buy.reason_ar
    assert sell.decision is Decision.TRADE, sell.reason_ar
    assert buy.risk_decision.quantity > 0 and sell.risk_decision.quantity > 0


# ---------------------------------------------------------------------------
# ٢ · التماثل العددي عبر النظام كاملاً
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field",
    ["quantity", "notional", "expected_risk_usd", "expected_costs_usd", "risk_budget_usd"],
)
def test_the_two_legs_carry_the_same_money(pair, field):
    """الرقم الذي يهمّ: كم دولاراً تخسر إن ضُرب الوقف — ومعه الهامش والتكلفة."""
    buy, sell = pair
    assert getattr(buy.risk_decision, field) == getattr(sell.risk_decision, field), (
        f"{field} اختلف بين الجهتين — التماثل ادّعاء لا قياس"
    )


def test_the_cost_model_never_sees_the_side(pair):
    """
    التماثل ليس صدفةً عددية: `estimate` **لا تستقبل الجهة إطلاقاً**،
    فلا موضع فيها يفرّق بين شراءٍ وبيع.
    """
    params = inspect.signature(CapitalComCostModel.estimate).parameters
    assert "side" not in params, (
        "صارت الجهة تدخل نموذج التكلفة — فالتماثل لم يعد بنيوياً ويحتاج قياساً جديداً"
    )


# ---------------------------------------------------------------------------
# ٣ · العطل الذي كشفه القياس: كميةٌ بلا جهة
# ---------------------------------------------------------------------------
def test_a_filled_short_is_recorded_with_its_sign(pair):
    """
    **العطل بعينه.** الوسيط يُبلّغ المركز القصير سالباً؛ كنّا نكتبه موجباً،
    فتنهار المطابقة على أوّل بيعٍ يُملأ — بعد أن يكون الأمر قد نُفِّذ.
    """
    _, sell = pair
    assert sell.reconciliation_ok, f"المطابقة سقطت: {sell.reason_ar}"
    assert sell.reason_code != "RECONCILIATION_MISMATCH"


def test_a_filled_long_is_still_recorded_positive(pair):
    """ولا يُصلَح البيع على حساب الشراء."""
    buy, _ = pair
    assert buy.reconciliation_ok, f"المطابقة سقطت: {buy.reason_ar}"


def test_the_sign_comes_from_the_executed_order_not_the_signal():
    """
    المطابقة تسأل عمّا في السوق. فالجهة تُقرأ من الأمر المُنفَّذ
    (`submission.order.side`) لا من الإشارة — ولو تباعدا لكانت الإشارة
    هي الرواية الخاطئة.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "pipeline" / "runner.py").read_text(
        encoding="utf-8"
    )
    assert "submission.order.side is _Side.SELL" in source
    assert "signal.side is _Side.SELL" not in source


# ---------------------------------------------------------------------------
# ٤ · ما الذي يقيّد الخسارة فعلاً — وهو مشتركٌ بين الجهتين
# ---------------------------------------------------------------------------
def test_the_stop_lives_at_the_broker_not_in_our_process():
    """قيدُ الخسارة لا يعتمد على بقاء برنامجنا حيّاً — وهذا هو أساس التماثل."""
    assert CFD_REQUIRE_BROKER_STOP is True


@pytest.mark.parametrize("mode", [RiskMode.VALIDATION, RiskMode.CONSERVATIVE_LIVE])
def test_no_position_survives_the_night_or_the_weekend(mode):
    """
    فائدةُ التبييت هي الموضع الوحيد الذي يفرّق فيه الوسيط بين الجهتين
    عدديّاً. والمبيت ممنوع — فالفرق لا ينشأ.
    """
    limits = RiskLimits.for_mode(mode, D("300"), Broker.CAPITAL_COM)
    assert limits.allow_overnight is False
    assert limits.allow_weekend_hold is False


def test_hedging_stays_closed_so_a_short_cannot_mask_a_long():
    """التماثل يفترض مركزاً واحداً في الاتجاه المقاس، لا مركزين متعاكسين."""
    assert CFD_ALLOW_HEDGING is False


def test_no_borrow_cost_exists_in_the_cfd_model():
    """
    المخاطر الثلاثة التي كُتبت `ALLOW_SHORT = False` لأجلها — أجرة
    الاقتراض والاستدعاء والخسارة غير المحدودة — أوّلُها غير موجودٍ أصلاً
    في نموذج تكلفة عقود الفروقات.
    """
    from app.risk.capital_costs import CfdTradeEconomics

    fields = set(CfdTradeEconomics.__dataclass_fields__)
    assert not {f for f in fields if "borrow" in f or "اقتراض" in f}
    assert "overnight_cost" in fields  # الوحيد ذو الصلة — وهو صفرٌ بلا مبيت


# ---------------------------------------------------------------------------
# ٥ · وما زال البيع ممنوعاً حتى تُغيَّر الراية صراحةً
# ---------------------------------------------------------------------------
def test_the_flag_was_opened_deliberately_and_the_version_says_so():
    """
    **فُتح البيع في الدستور 0.3.0 بتفويض المالكة الصريح، بعد هذا القياس.**

    والمحروس هنا أن الفتح **معلَن**: راية مرفوعة وإصدارٌ مرفوع معها. لأن
    تغيير سياسةٍ تحت رقم الإصدار نفسه هو انحرافٌ صامت — والبصمة المسجَّلة
    مع كل قرار تصير كاذبةً عن دستورها.
    """
    from app.risk.constitution import CFD_ALLOW_SHORT, CONSTITUTION_VERSION

    assert CFD_ALLOW_SHORT is True
    assert CONSTITUTION_VERSION == "0.3.0", (
        "الراية تغيّرت والإصدار لم يتغيّر — سياسةٌ تنزلق بلا سجل"
    )


def test_the_fingerprint_moves_when_the_policy_moves():
    """
    البصمة تُسجَّل مع كل قرار مخاطرة. فإن لم تتحرّك بتحرّك الراية، صار
    السجل يشهد لدستورٍ غير الذي حكم — وهو أسوأ من غياب السجل.
    """
    from unittest.mock import patch as _patch

    from app.risk import constitution as C

    before = C.constitution_fingerprint(RiskMode.VALIDATION, Broker.CAPITAL_COM)
    with _patch.object(C, "CFD_ALLOW_SHORT", False):
        after = C.constitution_fingerprint(RiskMode.VALIDATION, Broker.CAPITAL_COM)
    assert before != after, "بصمةٌ لا تتأثّر بالراية — فالسجل لا يميّز الدستورين"
