"""يقيسُ ما تُنفّذه الخدمةُ فعلاً، لا ما اختبرناه تأدّباً.

كانت السويةُ خضراءَ وهي تقيسُ المرجعَ ‎١٥٠، والخدمةُ تعملُ على ‎٣٠٠.
فكلُّ رقمٍ يُخاطر بالمال كان بلا حارس: يُضاعَف عند البناء ولا يَفحصُه
اختبار. هذا هو الحارس الغائب — أيُّ تغييرٍ يمسُّ الأرقامَ النافذة
يجب أن يُسقِطَ هذا الملفَ أوّلاً.
"""

from __future__ import annotations

from app.contracts import Broker
from app.money import D
from app.risk.constitution import (
    CONSTITUTION_VERSION,
    PauseScope,
    RiskLimits,
    RiskMode,
)

#: المرجعُ المنشور — ‎٣٠٠ دولاراً، وهو قرارُ المالكة الثابت.
DEPLOYED = RiskLimits.for_mode(RiskMode.VALIDATION, D("300.00"), Broker.CAPITAL_COM)


def test_the_constitution_in_force_is_0_7_0():
    assert CONSTITUTION_VERSION == "0.7.0"


def test_the_target_is_five_dollars_at_the_deployed_reference():
    assert DEPLOYED.target_risk_per_trade == D("5.00")


def test_the_hard_ceiling_is_ten_dollars_by_owner_decision():
    """قرارُ المالكة ‎١٩ سبتمبر ‎٢٠٢٦: عشرةُ دولاراتٍ سقفاً صلباً للصفقة."""
    assert DEPLOYED.max_risk_per_trade == D("10.00")


def test_the_budgets_are_measured_not_described():
    assert DEPLOYED.daily_loss == D("30.00")
    assert DEPLOYED.weekly_loss == D("60.00")
    assert DEPLOYED.hard_total_loss == D("72.00")
    assert DEPLOYED.max_portfolio_risk == D("20.00")


def test_two_losses_cool_down_they_do_not_lock():
    """الرسالةُ يجب أن تَعِدَ بما ينفّذه كود: تهدئةٌ تنتهي بنفسها."""
    assert DEPLOYED.consecutive_losses_pause == 2
    assert DEPLOYED.consecutive_losses_kill == 3
    assert DEPLOYED.pause_scope is PauseScope.COOLDOWN_WINDOW


def test_the_daily_budget_can_absorb_every_open_stop_at_once():
    """الثابتُ الرابط الذي يمنع الخدمةَ من الإقلاع إن كُسِر."""
    assert DEPLOYED.daily_loss >= (
        DEPLOYED.max_risk_per_trade * DEPLOYED.max_open_positions
    )


def test_the_day_stops_where_the_kill_switch_stops():
    """**الاشتقاقُ نفسُه كحارس.**

    قرارُ المالكة: عشرةٌ للصفقة، وثلاثون لليوم. وثلاثون ليست رقماً
    مستقلّاً بل ثلاثُ خسائرَ كاملة — وهي نقطةُ قاطع الطوارئ عينها. فلو
    تحرّك أحدُ الرقمَين دون الآخر عاد الحارسان يقولان رقمَين مختلفَين،
    وهذا ما كان قبل 0.7.0 (24.00 = خسارتان وأربعةُ أعشار).

    والأسبوعيُّ ضِعفُ اليومي: أسبوعيٌّ أقلُّ من ذلك يجعلُ يوماً سيّئاً
    واحداً يُقفل الأسبوعَ كلَّه.
    """
    assert DEPLOYED.daily_loss == (
        DEPLOYED.max_risk_per_trade * DEPLOYED.consecutive_losses_kill
    )
    assert DEPLOYED.weekly_loss == DEPLOYED.daily_loss * 2
    assert DEPLOYED.hard_total_loss >= DEPLOYED.weekly_loss
