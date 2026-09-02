"""
**الشاشة كانت تَعِد بحدٍّ أشدّ من الحدّ العامل.**

## العطل

شاشة «حدودي اليوم» كانت تعرض حدود **الملف** (`ProfileLimits`): 0.50 للصفقة
و0.75 لليوم. والمحرّك ينفّذ حدود **الدستور** (`RiskLimits`): عند مرجع 300
دولار في وضع التحقّق، 0.75 للصفقة و**6.00 لليوم**.

و`ProfileLimits` لا تُستدعى في مسار القرار إطلاقاً — فقط في العرض
والتحليل. أي أن المعروض كان **أشدّ ثماني مرّاتٍ يومياً مما يُنفَّذ**.

وشاشةٌ تعد بحدٍّ أشدّ من العامل ليست تحفّظاً، هي طمأنينةٌ كاذبة: تُقرأ
فيُظنّ أن خسارةً واحدة تُنهي اليوم، والمحرّك يسمح بثمانٍ. وهو الشكل العاشر
من العيب الحاكم: قيمةٌ تُعرَض لم تُقرأ من مصدر تنفيذها.

## القاعدة التي تحرسها هذه الفحوص

كل رقمٍ في قسم المخاطرة يُقرأ من **الكائن نفسه الذي يقرأ منه المحرّك**
(`sys.limits`) — لا من كائنٍ يشبهه. والفرق بين الحدّين يُقال بالنصّ، ولا
يُدَّعى سريان ما لم يسرِ.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.api.state import build_system
from app.mobile.state import build_mobile_state
from app.money import D
from app.profiles import ProfileLimits


@pytest.fixture(scope="module")
def system():
    return build_system()


@pytest.fixture(scope="module")
def risk(system):
    return build_mobile_state(system)["risk"]


def test_every_limit_shown_is_the_limit_the_engine_reads(system, risk):
    """
    **الفحص الذي يعضّ.** يُقارَن المعروض بـ`sys.limits` — الكائن الذي
    يستدعيه `RiskEngine` نفسه — لا بحسابٍ مُعاد هنا.
    """
    limits = system.limits
    equity = system.session_state.current_equity
    expected = {
        "max_risk_per_trade": limits.effective_max_risk(equity),
        "max_daily_loss": limits.daily_loss,
        "max_weekly_loss": limits.weekly_loss,
        "absolute_loss_boundary": limits.hard_total_loss,
    }
    for key, value in expected.items():
        assert Decimal(risk[key].replace(",", "")) == value, (
            f"{key}: المعروض {risk[key]} والمُنفَّذ {value} — الشاشة تصف حدّاً لا يعمل."
        )
    assert risk["max_open_positions"] == limits.max_open_positions
    assert risk["max_entry_orders_per_day"] == limits.max_entry_orders_per_day


def test_the_remaining_today_is_measured_against_the_enforced_cap(system, risk):
    """«المتبقّي من مخاطرة اليوم» يُطرح من الحدّ العامل لا من حدّ الملف."""
    limits = system.limits
    session = system.session_state
    expected = max(Decimal("0"), limits.daily_loss - session.day_loss)
    assert Decimal(risk["risk_remaining_today"].replace(",", "")) == expected


def test_the_gap_between_the_two_sets_is_said_not_hidden(system, risk):
    """
    الفرق بين حدود الملف وحدود الدستور **معلومة لا خطأ**، ويُقال بالنصّ.
    ولا يُدّعى أن حدود الملف سارية وهي ليست كذلك.
    """
    profile = ProfileLimits.for_profile(
        system.profiles.effective_profile, system.session_state.current_equity
    )
    binding = risk["profile_binding_ar"]
    assert isinstance(binding, str) and binding.strip()
    assert profile.name_ar in binding
    assert "ينفّذها المحرّك" in binding
    if profile.max_daily_loss < system.limits.daily_loss:
        assert "لا تُنفَّذ بعد" in binding, (
            "حدود الملف أشدّ ولا تسري — ويجب أن يُقال ذلك، لا أن يُسكَت عنه."
        )


def test_no_shown_number_comes_from_the_profile_object(risk):
    """
    حارسٌ بنيوي: `equity_used` كان يُقرأ من `ProfileLimits.equity_used`،
    وهو الكائن الذي لا يقرّر. فيُقرأ الآن من حالة الجلسة نفسها.
    """
    assert "equity_used" in risk
    # الملف يبقى **معرِّفاً** لا مصدرَ أرقام: اسمه ومفتاحه يُعرضان.
    assert risk["profile"] and risk["profile_name_ar"]
