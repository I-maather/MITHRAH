"""
إطارٌ يُعلَن ولا يُقرأ — فتُقاس فرضيةٌ غير التي كُتبت.

## ما وقع

كل استراتيجيات المشروع تُعلن `timeframe = "1D"`، والحلقة تُشغَّل على
`HOUR_4`. وكان الخط يكتب `TIMEFRAME_MISMATCH` في السجلّ **ثم يشغّلها على
أي حال**: ٧١٥٤ حدثاً في يومٍ واحد، كلّها مكتوبة ولا يمنع منها شيء.

ونتيجةُ استراتيجيةٍ تُعلن اليوم وتُقاس على أربع ساعات ليست نتيجة فرضيتها؛
هي فرضيةٌ أخرى تحمل اسمها. فكل ما يُبنى عليها — اعتمادٌ أو رفضٌ أو حكمٌ
على «الحافّة» — مبنيٌّ على قياسٍ لغير المقصود.

وهو العيب الحاكم في المشروع: قيمةٌ تُعلَن ولا تُقرأ في موضع تنفيذها.

## القاعدة

* الإطار **بوابة**: استراتيجيةٌ خارج أطرها المعتمدة لا تُقيَّم أصلاً.
* الاعتماد يحتاج **دليلاً مُسمّى** (`timeframe_evidence_ar`)، لا رأياً.
* وإذا سقطت كل الاستراتيجيات على هذه البوابة، يُقال ذلك بسببٍ يخصّ
  **الإعداد** لا السوق — لا «لا فرصة مطابقة».
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.contracts import StrategyState
from app.strategies.base import StrategyMetadata


def meta(**over) -> StrategyMetadata:
    base = dict(
        name="X", version="1.0.0", hypothesis_ar="—", markets=("EURUSD",),
        timeframe="1D", entry_conditions_ar=(), exit_conditions_ar=(),
        invalidations_ar=(), min_bars_required=1, assumed_costs_ar="—",
        no_trade_conditions_ar=(), state=StrategyState.RESEARCH, changelog_ar=(),
        backtest_evidence_ar="—", walkforward_evidence_ar="—",
    )
    base.update(over)
    return StrategyMetadata(**base)


def test_by_default_only_the_declared_timeframe_is_allowed():
    m = meta()
    assert m.allowed_timeframes == ("1D",)
    assert m.runs_on("1D")
    assert not m.runs_on("4H")
    assert not m.runs_on("15M")


def test_an_approved_list_replaces_the_declared_one():
    m = meta(approved_timeframes=("1D", "4H"), timeframe_evidence_ar="run_id=abc123")
    assert m.runs_on("1D") and m.runs_on("4H")
    assert not m.runs_on("1H")


def test_an_unknown_running_timeframe_does_not_block():
    """
    غيابُ المعلومة ليس تعارضاً. إعدادٌ لم يصرّح بإطارٍ يجب ألّا يوقف نظاماً
    سليماً — والتعارضُ وحده يمنع.
    """
    assert meta().runs_on(None)
    assert meta().runs_on("")


def test_approving_a_timeframe_without_evidence_is_visible():
    """
    لا يمنعه النوع — يمنعه أن يُقرأ. فحقلُ الدليل جزءٌ من الاعتماد، وخلوّه
    مع قائمةٍ موسَّعة حالةٌ تُرى في المراجعة.
    """
    m = meta(approved_timeframes=("1D", "4H"))
    assert m.timeframe_evidence_ar == ""


# ---------------------------------------------------------------------------
# البوابة داخل الخط
# ---------------------------------------------------------------------------

def test_the_pipeline_helpers_read_the_metadata():
    from app.pipeline.runner import _allowed_timeframes, _runs_on

    m = meta(approved_timeframes=("4H",))
    assert _allowed_timeframes(m) == ("4H",)
    assert _runs_on(m, "4H") and not _runs_on(m, "1D")


def test_the_helpers_tolerate_old_metadata_without_the_field():
    """بياناتٌ قديمة بلا الحقل تُقرأ بإطارها المُعلَن، ولا تنفجر."""
    from types import SimpleNamespace

    from app.pipeline.runner import _allowed_timeframes, _runs_on

    old = SimpleNamespace(timeframe="1D", name="OLD", version="0.1.0")
    assert _allowed_timeframes(old) == ("1D",)
    assert _runs_on(old, "1D") and not _runs_on(old, "4H")


def test_the_reason_code_exists_and_is_distinct():
    from app.pipeline.runner import NO_STRATEGY_FOR_TIMEFRAME, TIMEFRAME_MISMATCH

    assert TIMEFRAME_MISMATCH == "TIMEFRAME_MISMATCH"
    assert NO_STRATEGY_FOR_TIMEFRAME == "NO_STRATEGY_APPROVED_FOR_TIMEFRAME"
    assert NO_STRATEGY_FOR_TIMEFRAME != TIMEFRAME_MISMATCH


def test_every_registered_strategy_declares_a_timeframe():
    """لا استراتيجيةٌ بلا إطار — الإطار جزءٌ من الفرضية لا زينة."""
    from app.strategies.breakout_retest import BreakoutRetest
    from app.strategies.range_mean_reversion import RangeMeanReversion
    from app.strategies.trend_pullback_v1 import TrendPullbackV1
    from app.strategies.trend_pullback_v2 import TrendPullbackV2

    for cls in (TrendPullbackV1, TrendPullbackV2, RangeMeanReversion, BreakoutRetest):
        m = cls.metadata
        assert m.allowed_timeframes, m.name
        assert all(tf for tf in m.allowed_timeframes), m.name
        if len(m.allowed_timeframes) > 1:
            assert m.timeframe_evidence_ar, (
                f"{m.name} تعتمد أكثر من إطار بلا دليل مُسمّى."
            )


def test_the_two_vocabularies_are_reconciled_in_one_place():
    """
    الوسيط يسمّي الدقّة `HOUR_4` والاستراتيجيات تُعلن `4H`. ومقارنةُ
    الاسمين نصّاً تُسقط تطابقاً حقيقياً — طرفان لمعنىً واحد، كلٌّ بلغته.
    """
    from app.pipeline.runner import _canonical_timeframe, _runs_on

    assert _canonical_timeframe("HOUR_4") == "4H"
    assert _canonical_timeframe("4H") == "4H"
    assert _canonical_timeframe("DAY") == "1D"
    assert _canonical_timeframe("day") == "1D"
    assert _canonical_timeframe(None) == ""

    m = meta(timeframe="1D")
    assert _runs_on(m, "DAY")
    assert _runs_on(m, "1D")
    assert not _runs_on(m, "HOUR_4")

    m2 = meta(timeframe="DAY")     # بيانات كُتبت بلغة الوسيط
    assert _runs_on(m2, "1D")


# ---------------------------------------------------------------------------
# الاستثناء المُسمّى على التجريبي
# ---------------------------------------------------------------------------

def test_the_exception_code_is_distinct_from_the_mismatch():
    """
    «تعارضٌ يمنع» و«تعارضٌ مأذونٌ فيه ومَوسوم» حالتان مختلفتان. وخلطهما
    في رمزٍ واحد يجعل قارئ التقرير لا يعرف أيّ نتيجةٍ يُعتدّ بها.
    """
    from app.pipeline.runner import TIMEFRAME_EXCEPTION, TIMEFRAME_MISMATCH

    assert TIMEFRAME_EXCEPTION == "TIMEFRAME_EXCEPTION_DEMO_TRIAL"
    assert TIMEFRAME_EXCEPTION != TIMEFRAME_MISMATCH


def test_the_exception_requires_a_reference_and_a_demo_broker():
    """
    حارسٌ ساكن على شرطَي الاستثناء: مرجعُ موافقةٍ **و** وسيطٌ غير حقيقي.
    وغيابُ أيٍّ منهما يعيد البوابة إلى المنع.
    """
    from pathlib import Path

    from app.pipeline import runner as runner_module

    text = Path(runner_module.__file__).read_text(encoding="utf-8")
    assert "if exception_ref and not self.broker.is_live:" in text, (
        "شرط الاستثناء تغيّر — يُراجَع: استثناءٌ بلا مرجعٍ أو على وسيطٍ حقيقي."
    )
