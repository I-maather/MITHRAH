"""
حدّ التعادل في مسح التاريخ يُقرأ من **مستويات الصفقات**، لا من إعدادٍ.

## العطل الذي فرض هذا الملف

كان الحدّ يُحسَب مرّة واحدة من `BacktestConfig` (وقف 30 · هدف 60). وكان
صحيحاً يوم كان المحرّك ينفّذ بذلك الوقف؛ ثم غُيّر المحرّك ليحترم وقف
الإشارة وهدفها، فصار الحكم يقارن معدّل فوز إعدادٍ نُفِّذ بحدّ تعادل إعدادٍ
لم يُنفَّذ منه شيء.

ولا اختبار كان يربط الطرفين، فمرّ التغيير كاملاً وأنتج تقريراً بحكمين
«فوق التعادل» لا يُوثَق بهما. وهذا الملف هو الرباط الغائب.
"""
from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.contracts import StopKind
from app.risk.capital_costs import PROVISIONAL_EURUSD, CapitalComCostModel

REPO = Path(__file__).resolve().parents[2]


def _sweep_module():
    path = REPO / "scripts" / "run_history_sweep.py"
    spec = importlib.util.spec_from_file_location("run_history_sweep", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_history_sweep"] = module
    spec.loader.exec_module(module)
    return module


sweep = _sweep_module()
COSTS = CapitalComCostModel(PROVISIONAL_EURUSD)


#: حجمٌ **مشروع**. `min_deal_size` لهذه الأداة 100 وحدة، وأصغرُ منها ليس
#: صفقةً يقبلها الوسيط أصلاً. وأوّل كتابةٍ لهذا الملف استعملت `size=1`،
#: فرجعت كل التكاليف والخسائر مقرَّبةً إلى 0.01 (حبيبة المال) وصار كل
#: إعدادٍ يعطي نفس الرقم — فأسقط الاختبارُ دالّةً سليمة. **ثغرة مسجَّلة:**
#: نموذج التكلفة لا يرفض حجماً دون الحدّ الأدنى، بل يُخرج رقماً بلا معنى.
SIZE = "100"


def _trade(entry: str, stop: str, target: str, size: str = SIZE):
    return SimpleNamespace(
        entry_price=D(entry),
        stop_price=D(stop),
        take_profit_price=D(target),
        size=D(size),
        nights_held=0,
    )


def _result(trades):
    return SimpleNamespace(trades=list(trades), trade_count=len(trades))


def test_breakeven_reads_the_levels_that_were_actually_traded():
    """
    عائدٌ إلى مخاطرة 1:1 يعطي حدّاً فوق النصف، و2:1 يعطي حدّاً دونه بكثير.

    ولو كانت الدالّة تقرأ إعداداً ثابتاً لأعطت الرقم نفسه في الحالتين —
    وهو بالضبط العطل الذي وقع.
    """
    one_to_one = sweep.breakeven_from_trades(
        _result([_trade("1.10000", "1.09000", "1.11000")]), COSTS, StopKind.NORMAL
    )
    two_to_one = sweep.breakeven_from_trades(
        _result([_trade("1.10000", "1.09000", "1.12000")]), COSTS, StopKind.NORMAL
    )
    assert one_to_one is not None and two_to_one is not None
    assert one_to_one > 0.5, "1:1 بعد التكلفة يحتاج أكثر من نصف الصفقات رابحة"
    assert two_to_one < 0.4
    assert one_to_one - two_to_one > 0.1, "الحدّان لا يكادان يختلفان — الدالّة لا تقرأ المستويات"


def test_the_two_strategies_of_the_sweep_do_not_share_a_breakeven():
    """
    **هذا هو الفرق الذي أخفاه الحدّ الثابت.**

    `TREND_PULLBACK_V2` وقفها 1.5×ATR وهدفها 3.0×ATR من الدخول ⇒ عائد إلى
    مخاطرة 2.0 بالضبط. و`BREAKOUT_RETEST` وقفها 1.2×ATR **من المستوى** لا
    من الدخول، وهدفها 2.4×ATR من الدخول ⇒ مسافة الوقف أوسع بفارق (الدخول −
    المستوى)، فالعائد إلى المخاطرة **أقلّ من 2** ويتغيّر مع كل صفقة.

    فحدٌّ واحد لهما معاً يُجمّل إحداهما ويظلم الأخرى. والفرق ليس تفصيلاً:
    عند 1:1 يصير الحدّ 50٪ بدل 34٪.
    """
    two_r = sweep.breakeven_from_trades(
        _result([_trade("1.10000", "1.09400", "1.11200")]), COSTS, StopKind.NORMAL
    )
    wider_stop = sweep.breakeven_from_trades(   # نفس الهدف، ووقفٌ أبعد كما في الاختراق
        _result([_trade("1.10000", "1.09100", "1.11200")]), COSTS, StopKind.NORMAL
    )
    assert two_r is not None and wider_stop is not None
    assert wider_stop > two_r + 0.05


def test_wider_stops_lower_the_bar_because_cost_is_a_smaller_share():
    """
    الوقف الأوسع يجعل السبريد كسراً أصغر من المخاطرة، فينخفض الحدّ قليلاً
    عند نفس العائد إلى المخاطرة. واتجاه الأثر هذا هو سبب استحالة تخمين
    الحدّ من إعدادٍ آخر: ينقلب مع الوقف كما ينقلب مع العائد.
    """
    narrow = sweep.breakeven_from_trades(
        _result([_trade("1.10000", "1.09700", "1.10600")]), COSTS, StopKind.NORMAL
    )
    wide = sweep.breakeven_from_trades(
        _result([_trade("1.10000", "1.08000", "1.14000")]), COSTS, StopKind.NORMAL
    )
    assert narrow is not None and wide is not None
    assert wide < narrow


def test_no_trades_gives_no_breakeven_not_a_number():
    # صفرُ صفقة لا يعطي حدّاً؛ وإعطاؤه رقماً يجعل الحكم يُبنى على لا شيء.
    assert sweep.breakeven_from_trades(_result([]), COSTS, StopKind.NORMAL) is None


def test_verdict_refuses_to_judge_without_a_breakeven():
    result = SimpleNamespace(trade_count=50, wins=30, win_rate=D("0.6"), net_pnl=D("5"))
    code, _ = sweep.verdict(result, 30, None)
    assert code == "INCONCLUSIVE"


def test_many_configurations_raise_the_bar():
    """
    اثنا عشر إعداداً عند 95٪ لكلٍّ على حدة تُنتج 0.6 نتيجة «فوق التعادل»
    من الصدفة وحدها. فالعتبة ترتفع، ولا تبقى عتبة الاختبار الواحد.
    """
    assert sweep.corrected_z(1) == pytest.approx(sweep.MIN_Z_FOR_EDGE, abs=0.01)
    twelve = sweep.corrected_z(12)
    assert twelve > 2.6
    assert twelve > sweep.MIN_Z_FOR_EDGE


def test_the_two_results_of_2026_09_02_do_not_survive_the_correction():
    """
    الحكمان اللذان طُبعا «✅» في تشغيل 2026-09-02: z=2.02 وz=2.41 على اثني
    عشر إعداداً. وكلاهما دون العتبة المصحَّحة — تُسجَّل الحقيقة في اختبار
    كي لا تُقرأ النتيجة يوماً على أنها اعتماد.
    """
    bar = sweep.corrected_z(12)
    assert 2.02 < bar
    assert 2.41 < bar
