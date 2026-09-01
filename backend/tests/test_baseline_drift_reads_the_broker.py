"""
فحص انحراف رأس المال يقرأ الوسيط **بميثودٍ موجودة**.

## العطل الذي أنتج هذا الملف

كان `check_baseline_against_broker` ينادي `broker.get_account_snapshot()`
— **وهي غير موجودة على أي وسيط في المشروع**: لا في العقد المجرَّد
`BrokerAdapter`، ولا في محوّل كابيتال، ولا في الوهمي.

فكان النداء يرفع `AttributeError` في كل مرّة، ويُبتلَع في `except`، فيُعاد
«تعذّرت قراءة الرصيد» **دائماً** — ووسيطٌ متصلٌ تماماً لا يُقرأ رصيده أبداً.

ولم يُكشَف لأن الدالة كُتبت ولم تُوصَل بشيء يومين. ثم وُصلت بشاشة المحفظة،
فرأت المالكة الأثر في اللحظة نفسها التي تقول فيها شاشة النظام إن الوسيط
**متصل**: شاشتان تتناقضان.

نفس عائلة `SourceReliability.UNRELIABLE` و`observed_at_utc` و
`app.backtest.runner`: **اسمٌ كُتب من الذاكرة لا من العقد**، في مسارٍ لا
يُنفَّذ فلا ينكشف.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.money import D
from app.risk.session_state import check_baseline_against_broker

BASELINE = D("140.00")


class Balances:
    def __init__(self, net: str | None, total: str | None = None, settled: str | None = None):
        self.net_liquidation = D(net) if net else None
        self.total_cash = D(total) if total else None
        self.settled_cash = D(settled) if settled else None


class Broker:
    """وسيطٌ يملك **ما يملكه العقد المجرَّد** لا أكثر."""

    def __init__(self, balances: Balances, accounts=("acct-1",)) -> None:
        self._balances = balances
        self._accounts = list(accounts)
        self.asked_for = None

    def get_accounts(self):
        return self._accounts

    def get_balances(self, account_id: str):
        self.asked_for = account_id
        return self._balances


def test_the_balance_is_read_through_a_method_the_contract_declares():
    """**العطل بعينه.** الميثود المستعملة يجب أن تكون في العقد المجرَّد."""
    from app.brokers.base import BrokerAdapter

    assert hasattr(BrokerAdapter, "get_balances")
    assert not hasattr(BrokerAdapter, "get_account_snapshot"), (
        "عادت الميثود الوهمية إلى العقد — أو أن الاسم صحيح والفحص بائد"
    )

    broker = Broker(Balances("140.00"))
    drift = check_baseline_against_broker(broker, BASELINE)
    assert drift.broker_equity == D("140.00")
    assert broker.asked_for == "acct-1"


def test_net_liquidation_wins_over_cash():
    """
    حقوق الملكية = الرصيد **زائد ربح المراكز المفتوحة**. والنقد المسوّى
    وحده يُنقص ما هو في السوق، فيبدو الحساب أصغر مما هو — وحدودُ المخاطرة
    تُحسب على الفرق.
    """
    drift = check_baseline_against_broker(
        Broker(Balances("152.30", total="140.00", settled="100.00")), BASELINE
    )
    assert drift.broker_equity == D("152.30")


def test_it_falls_back_when_net_liquidation_is_absent():
    assert check_baseline_against_broker(
        Broker(Balances(None, total="140.00")), BASELINE
    ).broker_equity == D("140.00")


def test_a_broker_without_accounts_is_still_asked():
    """حسابٌ واحد ضمنيّ عند بعض الوسطاء — الغياب ليس منعاً من السؤال."""
    broker = Broker(Balances("140.00"), accounts=())
    assert check_baseline_against_broker(broker, BASELINE).broker_equity == D("140.00")
    assert broker.asked_for == ""


class Unreachable:
    def get_accounts(self):
        raise ConnectionError("down")


class MissingMethod:
    """وسيطٌ ينقصه ما نناديه — وهي الحالة التي وقعت فعلاً."""


@pytest.mark.parametrize("broker,marker", [
    (Unreachable(), "ConnectionError"),
    (MissingMethod(), "AttributeError"),
])
def test_a_failed_read_names_its_cause_and_invents_nothing(broker, marker):
    """
    **لا يُختلق رقم، ولا يُخمَّن سبب.** وسيطٌ لا يُقرأ منه لا يُثبت شيئاً عن
    الرصيد؛ فيُعاد `None` مع نوع العلّة بالاسم — وهو ما تعرضه الشاشة.
    وعرضُ سببٍ مفترض («الوسيط غير متصل») عن علّةٍ أخرى يجعل شاشتين تتناقضان.
    """
    drift = check_baseline_against_broker(broker, BASELINE)
    assert drift.broker_equity is None
    assert drift.diverged is False, "تعذُّر القراءة ليس انحرافاً"
    assert marker in drift.reason_ar


def test_a_real_divergence_is_named_loudly():
    """
    ١٥٠ مرجعاً و١٤٠ في الحساب بقيت صامتة حتى انكشفت بالمصادفة. والانحراف
    يعني أن **كل الحدود تُحسب على رقم غير واقعي**.
    """
    drift = check_baseline_against_broker(Broker(Balances("90.00")), BASELINE)
    assert drift.diverged is True
    assert "90" in drift.reason_ar and "140" in drift.reason_ar


def test_a_non_positive_balance_is_not_a_divergence_verdict():
    """صفرٌ أو سالب من الوسيط عطلُ قراءة لا حكمٌ على المرجع."""
    drift = check_baseline_against_broker(Broker(Balances("0")), BASELINE)
    assert drift.diverged is False


# ---------------------------------------------------------------------------
# رأس المال المحاكى
#
# ## الطلب الذي أنتج هذا القسم (2026-09-01)
#
# رصيد حساب الديمو ٩١٬٠٠٠ دولار، والخطة أن يُقاس النظام كما لو كان ٣٠٠ —
# لأن نظاماً يتداول ٩١ ألفاً **ليس هو** الذي سيتداول ٣٠٠: قيد الكمية الدنيا
# غير ملزم هناك وملزمٌ في كل صفقة هنا، والهامش يقفز من ٠٫٢٪ إلى ٥٨٪.
#
# ## ولماذا لا يُسمّى ذلك انحرافاً
#
# الفارق **تصميمٌ لا خلل**. وإنذارٌ دائم يشتعل بلا سبب يُدرَّب على تجاهله،
# فيصمت في اليوم الذي يهمّ — وهو نفس صنف العطل الذي نطارده: حقلٌ يقول ما لا
# يسنده مصدره.
#
# والسؤال الصحيح يختلف: لا «أيطابق الرصيدُ المرجع؟» بل **«أيكفي؟»**
# ---------------------------------------------------------------------------

def test_a_large_demo_balance_against_a_small_baseline_is_not_a_divergence():
    drift = check_baseline_against_broker(
        Broker(Balances("91000.00")), D("300.00"), simulated_capital=True
    )
    assert drift.diverged is False
    assert "محاكى" in drift.reason_ar
    assert "300" in drift.reason_ar and "91000" in drift.reason_ar


def test_a_balance_below_the_simulated_baseline_is_a_real_divergence():
    """
    **الخطر الحقيقي في الاتجاه الآخر.** رصيدٌ أقلّ من المرجع يعني حدوداً
    محسوبة على مالٍ غير موجود — وهو خطأ في الحالتين، محاكاةً كانت أو لا.
    """
    drift = check_baseline_against_broker(
        Broker(Balances("120.00")), D("300.00"), simulated_capital=True
    )
    assert drift.diverged is True
    assert "غير موجود" in drift.reason_ar


def test_the_live_account_still_demands_a_match():
    """ولا يُستعمل هذا الباب للتساهل على الحساب الحقيقي: ١٥٠ مقابل ١٤٠ بقيت صامتة."""
    drift = check_baseline_against_broker(Broker(Balances("91000.00")), D("300.00"))
    assert drift.diverged is True, "الحساب الحقيقي يقبل انحرافاً هائلاً"
