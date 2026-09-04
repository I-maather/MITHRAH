"""
إدارةُ المركز — القاعدة تُعلَن بدليل، والحارس يمنع ما يزيد الخسارة.

## لماذا هذا الملف

`exit_conditions_ar` نصٌّ عربيّ جميل في كل استراتيجية، وفيه سطرٌ يقول «لا
مبيت: تُغلق قبل نهاية الجلسة» — ولا سطرَ في المشروع يغلق مركزاً قبل نهاية
الجلسة. خروجٌ مُعلَن ولا يُنفَّذ، وهو نفس العيب الذي أكلَ `timeframe`: قيمةٌ
تُعلَن ولا تُقرأ.

والعلاج ليس تحويلَ النصّ إلى قاعدةٍ تُطبَّق على الجميع. القاعدةُ الديناميكية
رهانٌ على تحسين النتيجة، والرهان يحتاج دليلاً. فالافتراض خروجٌ ثابتٌ معتمد،
والقدرةُ الديناميكية لا تُسجَّل بلا اختبارٍ تاريخيّ وخارجَ العيّنة وورقيّ.

وهذه الاختبارات تحرس الحرّاس الثلاثة: لا يُوسَّع وقف، ولا تزيد المخاطرة عمّا
اعتُمد عند الدخول، ولا يُرسَل أمرٌ بلا أثر.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.money import D
from app.positions.engine import (
    ACTION_MOVE_STOP,
    SKIP_FIXED_ONLY,
    SKIP_NOT_RECONCILED,
    SKIP_NO_CHANGE,
    SKIP_UNATTRIBUTED,
    PositionManager,
    risk_at,
    tightens,
)
from app.positions.policy import (
    Capability,
    ManagementPolicy,
    PolicyRegistry,
    PolicyRejected,
    default_policy,
)

NOW = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)

EVIDENCE = dict(
    backtest_evidence_ar="مسح 2020-2026 · معرّف run-441",
    out_of_sample_evidence_ar="2026 خارج العيّنة · run-442",
    paper_evidence_ar="ثلاثون يوماً ورقياً · run-443",
)


def _row(**over):
    base = dict(
        broker_deal_id="d-1", symbol="GBPUSD", quantity=D("-200"),
        entry_price=D("1.35000"), attribution="LINKED",
        strategy_name="SHORT_SYMMETRY", strategy_version="v3",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _live(**over):
    base = dict(
        deal_id="d-1", symbol="GBPUSD", quantity=D("-200"),
        entry_price=D("1.35000"), stop_price=D("1.35400"), market_price=D("1.34600"),
    )
    base.update(over)
    return SimpleNamespace(**base)


def _registry(policy=None) -> PolicyRegistry:
    registry = PolicyRegistry()
    if policy is not None:
        registry.register(policy)
    return registry


def _break_even(**over) -> ManagementPolicy:
    return ManagementPolicy(
        strategy_name="SHORT_SYMMETRY", strategy_version="v3", policy_version="be-1",
        capabilities=frozenset({Capability.FIXED_EXIT, Capability.BREAK_EVEN}),
        break_even_after_r=D("1.0"), **{**EVIDENCE, **over},
    )


# --- ١ · الدليل شرطُ التسجيل --------------------------------------------------


def test_a_dynamic_capability_without_evidence_is_refused():
    with pytest.raises(PolicyRejected) as exc:
        ManagementPolicy(
            strategy_name="X", strategy_version="v1", policy_version="p1",
            capabilities=frozenset({Capability.TRAILING_STOP}),
            trailing_atr_multiple=D("2"),
        )
    assert "دليل" in str(exc.value)


def test_partial_evidence_is_still_no_evidence():
    with pytest.raises(PolicyRejected):
        ManagementPolicy(
            strategy_name="X", strategy_version="v1", policy_version="p1",
            capabilities=frozenset({Capability.BREAK_EVEN}),
            break_even_after_r=D("1"),
            backtest_evidence_ar="run-1",
        )


def test_a_fixed_policy_needs_no_evidence():
    policy = default_policy("X", "v1")
    assert policy.is_fixed_only


def test_an_unknown_strategy_gets_the_fixed_default_not_an_error():
    """الغياب حالةٌ عاديّة معناها «لا إدارة ديناميكية»، لا عطل."""
    policy = PolicyRegistry().for_strategy("مجهولة", "v9")
    assert policy.is_fixed_only and policy.policy_version == "fixed-1"


# --- ٢ · لا فعلَ بلا مطابقة ---------------------------------------------------


def test_a_position_missing_from_the_broker_is_never_modified():
    plan = PositionManager(_registry(_break_even())).plan(
        broker_positions=[], book_rows=[_row()], now=NOW
    )
    assert plan.actions == ()
    assert plan.skipped[0].code == SKIP_NOT_RECONCILED


def test_a_quantity_mismatch_blocks_any_modification():
    """
    تعديلُ مركزٍ بكميةٍ قديمة قد يُوسّع وقفاً على مركزٍ صار أكبر — وهو أسوأ
    من عدم التعديل.
    """
    plan = PositionManager(_registry(_break_even())).plan(
        broker_positions=[_live(quantity=D("-400"))], book_rows=[_row()], now=NOW
    )
    assert plan.actions == ()
    assert plan.skipped[0].code == SKIP_NOT_RECONCILED


# --- ٣ · لا نسبةَ لا سياسة ----------------------------------------------------


def test_an_unattributed_position_is_left_on_its_fixed_exit():
    """
    المراكز الخمسة المفتوحة اليوم كلُّها كذلك: فُتحت وجداولُ الأوامر فارغة،
    فلا يُعرَف أيُّ قرارٍ فتحها. ولا تُطبَّق عليها قواعدُ استراتيجيةٍ لم
    تفتحها — وهو ما قرّرته المالكة نصّاً: **لا أثرَ رجعيّاً**.
    """
    plan = PositionManager(_registry(_break_even())).plan(
        broker_positions=[_live()],
        book_rows=[_row(attribution="UNLINKED", strategy_name="")],
        now=NOW,
    )
    assert plan.actions == ()
    assert plan.skipped[0].code == SKIP_UNATTRIBUTED


def test_a_fixed_only_strategy_produces_no_action():
    plan = PositionManager(PolicyRegistry()).plan(
        broker_positions=[_live()], book_rows=[_row()], now=NOW
    )
    assert plan.actions == ()
    assert plan.skipped[0].code == SKIP_FIXED_ONLY


# --- ٤ · الحارس الأوّل: لا يُوسَّع وقفٌ أبداً ------------------------------------


def test_the_stop_only_ever_moves_closer():
    assert tightens(is_long=True, entry=D("1.0"), old_stop=D("0.9"), new_stop=D("0.95")) is True
    assert tightens(is_long=True, entry=D("1.0"), old_stop=D("0.9"), new_stop=D("0.85")) is False
    assert tightens(is_long=False, entry=D("1.0"), old_stop=D("1.1"), new_stop=D("1.05")) is True
    assert tightens(is_long=False, entry=D("1.0"), old_stop=D("1.1"), new_stop=D("1.15")) is False


def test_a_policy_that_would_widen_the_stop_is_refused_not_applied():
    """
    التعادل على مركزٍ قصيرٍ يعني نقلَ الوقف إلى الدخول. فإن كان الوقف القائم
    **أضيق** من الدخول أصلاً، فالنقل توسيع — ويُرفَض ويُسجَّل.
    """
    plan = PositionManager(_registry(_break_even())).plan(
        broker_positions=[_live(stop_price=D("1.34900"), market_price=D("1.34000"))],
        book_rows=[_row()],
        now=NOW,
    )
    assert plan.actions == ()
    assert plan.skipped[0].code == SKIP_NO_CHANGE
    assert "لا يُوسَّع" in plan.skipped[0].reason_ar


def test_risk_after_management_never_exceeds_the_risk_before():
    before = risk_at(entry=D("1.35"), stop=D("1.354"), quantity=D("-200"))
    after = risk_at(entry=D("1.35"), stop=D("1.352"), quantity=D("-200"))
    assert after < before


# --- ٥ · التماثل --------------------------------------------------------------


def test_the_same_value_is_not_sent_twice():
    """
    إعادةُ إرسال القيمة القائمة أمرٌ بلا أثر — وأثرُه الوحيد ضجيجٌ في السجل،
    وتُعلَّم به إعادةُ تشغيلٍ في منتصف الدورة فتُنتج أمراً ثانياً.

    المطاردة تقترح ‎1.34600 + 1.5×0.00200 = 1.34900‎ — وهو الوقف القائم.
    """
    policy = ManagementPolicy(
        strategy_name="SHORT_SYMMETRY", strategy_version="v3", policy_version="tr-1",
        capabilities=frozenset({Capability.FIXED_EXIT, Capability.TRAILING_STOP}),
        trailing_atr_multiple=D("1.5"), **EVIDENCE,
    )
    plan = PositionManager(_registry(policy)).plan(
        broker_positions=[_live(stop_price=D("1.34900"), market_price=D("1.34600"))],
        book_rows=[_row()],
        now=NOW,
        atr_by_symbol={"GBPUSD": D("0.00200")},
    )
    assert plan.actions == ()
    assert plan.skipped[0].code == SKIP_NO_CHANGE


def test_a_second_identical_cycle_produces_the_same_empty_plan():
    manager = PositionManager(_registry(_break_even()))
    args = dict(broker_positions=[_live()], book_rows=[_row()], now=NOW)
    first = manager.plan(**args)
    second = manager.plan(**args)
    assert [a.as_dict() for a in first.actions] == [a.as_dict() for a in second.actions]


# --- ٦ · الفعل حين يستحقّ -----------------------------------------------------


def test_break_even_moves_the_stop_and_records_both_values():
    """المركز القصير ربح 1R، فينتقل الوقف من 1.35400 إلى الدخول 1.35000."""
    plan = PositionManager(_registry(_break_even())).plan(
        broker_positions=[_live(stop_price=D("1.35400"), market_price=D("1.34600"))],
        book_rows=[_row()],
        now=NOW,
    )
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.kind == ACTION_MOVE_STOP
    assert action.old_value == D("1.35400")
    assert action.new_value == D("1.35000")
    assert action.policy_version == "be-1"
    assert action.strategy_version == "v3"
    assert action.deal_id == "d-1", "الهويّة هويّةُ الوسيط"


def test_break_even_does_not_fire_before_its_trigger():
    plan = PositionManager(_registry(_break_even())).plan(
        broker_positions=[_live(stop_price=D("1.35400"), market_price=D("1.34900"))],
        book_rows=[_row()],
        now=NOW,
    )
    assert plan.actions == ()


def test_a_trailing_stop_tightens_and_is_recorded_with_its_multiple():
    policy = ManagementPolicy(
        strategy_name="SHORT_SYMMETRY", strategy_version="v3", policy_version="tr-1",
        capabilities=frozenset({Capability.FIXED_EXIT, Capability.TRAILING_STOP}),
        trailing_atr_multiple=D("1.5"), **EVIDENCE,
    )
    plan = PositionManager(_registry(policy)).plan(
        broker_positions=[_live(stop_price=D("1.35400"), market_price=D("1.34600"))],
        book_rows=[_row()],
        now=NOW,
        atr_by_symbol={"GBPUSD": D("0.00200")},
    )
    assert len(plan.actions) == 1
    # ‏1.34600 + 1.5×0.00200 = 1.34900 — أضيق من 1.35400 فيُقبل.
    assert plan.actions[0].new_value == Decimal("1.34900")
    assert "1.5" in plan.actions[0].reason_ar


# --- ٧ · لا R بلا وقف ---------------------------------------------------------


def test_a_position_without_a_broker_stop_is_not_managed():
    plan = PositionManager(_registry(_break_even())).plan(
        broker_positions=[_live(stop_price=None)], book_rows=[_row()], now=NOW
    )
    assert plan.actions == ()
    assert plan.skipped[0].code == "NO_STOP"
