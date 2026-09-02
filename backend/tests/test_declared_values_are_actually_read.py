"""
**قيمٌ تُعلَن ولا تُقرأ — أربعُ حالاتٍ من العائلة الحاكمة.**

المشروع يُعلن قيماً في مواضعها الصحيحة ثم لا يقرؤها في مواضع استعمالها:
سبريدٌ موروثٌ يمرّ كأنه مقيس، وإطارٌ زمنيٌّ تُعلنه كل استراتيجيةٍ ولا
يقارنه شيء، وحالةُ سوقٍ تُقرأ لأداةٍ وتُعرض عن أربع، وسعرٌ يُسجَّل بمنزلتين
مهما كانت دقّة الأداة.

وكلُّها كانت صحيحةً يوم كان النظام يتداول أداةً واحدة على إطارٍ واحد.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.money import D
from app.risk.capital_costs import ValueProvenance
from app.risk.instrument_registry import InstrumentRegistry


def row(**over) -> dict:
    base = {
        "epic": "GOLD", "pip_size": "0.01", "lot_size": "1",
        "min_deal_size": "0.01", "size_increment": "0.01",
        "margin_factor": "5", "margin_factor_unit": "PERCENTAGE",
        "min_stop_distance": "0.001", "spread_price": "0.50",
        "quote_currency": "USD", "provenance": "BROKER_DISCOVERY",
        "spread_samples": 5, "measured_at_utc": "2026-09-02T00:00:00+00:00",
    }
    base.update(over)
    return {"instruments": {base["epic"]: base}}


class TestTheSpreadMustBeMeasuredNotInherited:
    def test_a_row_without_a_measured_spread_is_not_executable(self):
        """
        **الفحص الذي يعضّ.** صفٌّ برصداتٍ بلا `spread_price` كان ينجح في
        `executable` ويرث `CfdCostAssumptions.default()` — و`0.00006`
        سبريدُ **اليورو** (0.6 نقطة).

        على الذهب سبريدُه المقيس 0.50 دولار: الفارق نحو ثمانية آلاف ضعف،
        ويدخل حساب التعادل ونسبة التكلفة بلا أن يُقال إنه موروث.
        """
        registry = InstrumentRegistry.from_dict(row(spread_price=None))
        assert "GOLD" not in registry.executable_epics()
        assert "موروث" in registry.why_not("GOLD")

    def test_a_measured_spread_is_executable(self):
        registry = InstrumentRegistry.from_dict(row())
        assert "GOLD" in registry.executable_epics()
        measured = registry.get("GOLD")
        assert measured.assumptions.spread_price == D("0.50")
        assert (
            measured.assumptions.spread_provenance
            is ValueProvenance.BROKER_DISCOVERY
        )

    def test_the_other_two_conditions_still_bind(self):
        """ولم يُخفَّف شيء: الشرطان القديمان كما هما."""
        assert "GOLD" not in InstrumentRegistry.from_dict(
            row(min_stop_distance=None)
        ).executable_epics()
        assert "GOLD" not in InstrumentRegistry.from_dict(
            row(spread_samples=0)
        ).executable_epics()


class TestThePriceKeepsItsPrecision:
    @pytest.mark.parametrize(
        "raw, shown",
        [
            ("1.14523", "1.14523"),   # اليورو — كان يُسجَّل «1.15»
            ("1.10000", "1.10000"),   # ولا تُقصّ الأصفار
            ("4389.12", "4389.12"),   # الذهب
            ("146.825", "146.825"),   # الين
        ],
    )
    def test_a_stop_is_recorded_at_its_own_precision(self, raw, shown):
        """
        `f"{price:.2f}"` صحيحٌ للذهب ويهدم اليورو: وقفٌ عند 1.14523 يُسجَّل
        «1.15» — بعيدٌ 47.7 نقطة، نحو نصف أدنى مسافةٍ يقبلها الوسيط.

        وهذا النصّ يُكتب في **خط التدقيق**: السجلّ البشري لما أُمر به من
        حماية. فرقمٌ مقرَّبٌ فيه ليس تجميلاً.
        """
        from app.execution.orders import _price

        assert _price(D(raw)) == shown


class TestTheTimeframeIsCompared:
    def test_the_map_covers_every_resolution_the_trial_accepts(self):
        """
        حارسٌ ضدّ الشيخوخة: إطارٌ تقبله التجربة ولا اسم له في الجدول يجعل
        المقارنة تصمت عنه — وهو الصمت نفسه الذي جاء هذا الفحص ليمنعه.
        """
        from app.pipeline.runner import TIMEFRAME_NAMES
        from app.runtime.demo_trial import ALLOWED_RESOLUTIONS

        missing = [r for r in ALLOWED_RESOLUTIONS if r not in TIMEFRAME_NAMES]
        assert not missing, f"أطرٌ بلا اسمٍ معلَن: {missing}"

    def test_every_strategy_declares_a_timeframe_the_map_can_match(self):
        """
        وإعلانٌ لا يطابق أي اسمٍ في الجدول يعني مقارنةً تُنبّه أبداً — وهو
        ضجيجٌ يُعلَّم أن يُتجاهَل.
        """
        from app.api.state import build_system
        from app.pipeline.runner import TIMEFRAME_NAMES

        declared = {
            s.metadata.timeframe for s in build_system().pipeline.strategies
        }
        unknown = declared - set(TIMEFRAME_NAMES.values())
        assert not unknown, f"أطرٌ مُعلَنة لا يعرفها الجدول: {unknown}"


class TestTheScreenSaysWhoseHoursTheseAre:
    @pytest.fixture(scope="class")
    def status(self):
        from app.api.state import build_system
        from app.mobile.state import build_mobile_state

        return build_mobile_state(build_system())["status"]

    def test_the_forex_hours_are_labelled_as_forex_hours(self, status):
        """
        كانت اللوحة تقول «سوق الفوركس مفتوح» عن أداةٍ يقول الوسيط إنها
        مقفلة — وقع ذلك في 21:21 UTC أربعاء، والذهب في استراحته اليومية.
        """
        assert "scope_ar" in status["market"]
        assert "ساعات الفوركس" in status["market"]["scope_ar"]

    def test_each_instrument_carries_the_brokers_own_word(self, status):
        """
        **وقائمةٌ فارغة ليست نجاحاً.** أوّل كتابةٍ لهذا الفحص مرّت على
        `for entry in rows` وحدها، فقُلبت طفرةٌ تجعلها `[]` — ومرّ الفحص.
        حلقةٌ على فراغٍ تصدق أبداً؛ وهو فخُّ «المقارنة الفارغة» نفسه الذي
        أفرغ برهان IBKR قبل ساعات.

        فيُشترَط أن تغطّي القائمة **كل أداةٍ يمسحها المحرّك**.
        """
        from app.api.state import build_system

        expected = set(build_system().limits.allowed_instruments)
        rows = status["market"]["per_instrument"]
        assert isinstance(rows, list) and rows, "قائمةٌ فارغة — الفحص بلا معنى."
        assert {r["symbol"] for r in rows} == expected, (
            "الشاشة لا تغطّي كل أداةٍ يمسحها المحرّك."
        )
        for entry in rows:
            assert {"symbol", "status", "tradable", "reason_ar"} <= set(entry)
            # وما لم يُعلنه الوسيط يُقال «غير معلومة» ولا يُملأ بحالة الفوركس.
            if entry["status"] is None:
                assert entry["tradable"] is None
                assert "لم يُعلن" in entry["reason_ar"]


class TestTheDrawdownCapFollowsTheConstitution:
    def test_it_scales_with_the_baseline_instead_of_being_copied(self):
        """
        كان `MAX_DRAWDOWN_USD = D("6.50")` وتعليقُه «الحد التشغيلي نفسه».
        وليس نفسه: الدستور يقيسه بـ`_scaled(base, 6.50)` فيتبع المرجع.
        عند 150 يتفقان، وعند 300 يصير الدستوري 13.00 والبوّابة ما زالت
        تقيس بـ6.50 — نسخةٌ تشيخ عند أوّل تغييرٍ في المرجع.
        """
        from app.contracts import Broker
        from app.risk.constitution import RiskLimits, RiskMode
        from app.strategies.gates import max_drawdown_usd

        at_150 = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("150"), Broker.CAPITAL_COM)
        at_300 = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("300"), Broker.CAPITAL_COM)
        assert max_drawdown_usd(at_300) == max_drawdown_usd(at_150) * 2, (
            "الحدّ لا يتبع المرجع — فهو نسخةٌ لا اشتقاق."
        )

    def test_the_gate_reports_the_cap_it_actually_used(self):
        """ورقمُ الحدّ في نصّ البوّابة هو الذي قُورن به، لا ثابتٌ آخر."""
        from app.contracts import Broker
        from app.risk.constitution import RiskLimits, RiskMode
        from app.strategies.gates import evaluate_admission, max_drawdown_usd

        limits = RiskLimits.for_mode(RiskMode.CONSERVATIVE_LIVE, D("300"), Broker.CAPITAL_COM)
        report = evaluate_admission(strategy_label="X", limits=limits)
        cap = max_drawdown_usd(limits)
        drawdown_gates = [g for g in report.gates if g.name == "MAX_DRAWDOWN"]
        for gate in drawdown_gates:
            assert f"{cap:.2f}" in gate.detail_ar


class TestTheStartupNoteSaysWhatTheCodeDoes:
    def test_it_does_not_promise_execution_on_assumptions(self):
        """
        كانت الملاحظة تقول «التنفيذ يجري على اقتصادياتٍ مفترضة» عند غياب
        القياس — وهو **عكس** ما يجري: `cfd_review` ترفض كل أداة CFD بلا
        قياس. فتُرسَل المالكة تبحث عن صفقاتٍ على تخمين، ولا صفقة أصلاً.
        """
        import inspect

        from app.api import state as state_module

        source = inspect.getsource(state_module.build_system)
        assert "لا تُنفَّذ أي صفقة CFD" in source
        assert "التنفيذ يجري على اقتصادياتٍ **مفترضة**" not in source


class TestTheQuoteCurrencyIsNotInvented:
    def test_a_row_without_a_currency_keeps_none(self):
        """
        `or "USD"` كان يمنح صفّاً بلا عملةٍ عملةَ الحساب **بمصدر
        `BROKER_DISCOVERY`** — أي يؤكّد ما لم يقرأه. وطبقةُ الأهلية هي
        التي تقول صراحةً إنها مفترضة من قائمتنا.
        """
        registry = InstrumentRegistry.from_dict(row(quote_currency=None))
        assert registry.get("GOLD").economics.quote_currency is None

    def test_a_declared_currency_is_kept(self):
        registry = InstrumentRegistry.from_dict(row(quote_currency="JPY", epic="USDJPY"))
        assert registry.get("USDJPY").economics.quote_currency == "JPY"
