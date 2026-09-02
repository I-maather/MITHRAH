"""
**الخط كان يقرّر بعمولات IBKR على صفقات كابيتال.**

## العطل

`runner.py` كان يستدعي `risk.evaluate` دائماً — مسار **أسهم IBKR**: جدول
`IBKR_PRO_TIERED_US_STOCK`، وكميةٌ تُحلّ عكسياً بالسهم الواحد، وشرطُ أن
تقع القيمة الاسمية داخل النقد المسوّى. وكل ذلك يخصّ سهماً يُشترى نقداً، لا
عقد فروقاتٍ يُفتَح بهامش.

وفي المقابل: `evaluate_cfd` و`CapitalComCostModel` و`InstrumentRegistry`
مكتوبةٌ ومُختبَرة، والاقتصاديات **تُقاس من الوسيط فعلاً** وتُحمَّل في
`build_system` وتُعرض في الشاشة — ثم لا تدخل القرار. كانت تُستدعى في
الظلّ وحده (`shadow.py`).

⇒ النظام يقيس اقتصاديات كابيتال، ويعرضها، **ويقرّر بغيرها**. وهو الشكل
الحادي عشر من العيب الحاكم في هذا المشروع: قيمةٌ تُعرَض أو تُقاس ولا
تُقرأ من موضع استعمالها.

## ولماذا لم يسقط فحصٌ واحد

لأن ألفاً وستّمئة فحصٍ تمرّ سواءٌ سعّر الخط بكابيتال أو بـIBKR: لم يكن
هناك فحصٌ يسأل **أيّ نموذجٍ قرّر**. فهذه الفحوص تسأله.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.audit.log import AuditLog, InMemoryAuditStore
from app.brokers.mock import MockBehaviour, MockBrokerAdapter, make_quote
from app.contracts import (
    AccountKind, AssetClass, Broker, ClientClassification, DataSource, Decision,
    InstrumentDetails, Side, Signal, StrategyState, TradingPermissions,
)
from app.execution.orders import ExecutionService, IdempotencyGuard
from app.killswitch.engine import KillSwitch
from app.money import D
from app.pipeline.runner import (
    INSTRUMENT_ECONOMICS_UNMEASURED,
    STOP_BELOW_BROKER_MINIMUM,
    BlackoutCalendar,
    MacroAssessment,
    Pipeline,
    is_cfd,
)
from app.risk.capital_costs import ValueProvenance
from app.risk.constitution import RiskLimits, RiskMode
from app.risk.engine import ACCOUNT_SIZE_INSUFFICIENT_FOR_BROKER_MINIMUM
from app.risk.costs import IBKR_PRO_TIERED_US_STOCK, CostAssumptions
from app.risk.engine import RiskEngine, SessionRiskState
from app.risk.instrument_registry import InstrumentRegistry
from app.strategies.base import Strategy, StrategyMetadata
from tests.conftest import MID_SESSION, make_balances, make_permissions, uptrend_bars


def capital_permissions(at):
    """صلاحيات حساب كابيتال: هامشٌ وفوركسٌ وبيعٌ على المكشوف — وهي **متوقّعة**
    هنا لا مخالفة، بخلاف سياسة الأسهم النقدية."""
    return TradingPermissions(
        account_id="****1234", account_kind=AccountKind.MARGIN,
        classification=ClientClassification.RETAIL, us_stocks=False,
        fractional_enabled=False, options=False, futures=False, forex=True,
        crypto=False, short_selling=True, margin_enabled=True, as_of_utc=at,
    )

UTC = timezone.utc
NO_MACRO = MacroAssessment(blocks_trading=False, reason_ar="لا مانع كلي.")

#: القياس كما خرج من حساب Demo (2026-09-01). لا رقم هنا مخترع.
MEASURED = {
    "instruments": {
        "EURUSD": {
            "epic": "EURUSD", "pip_size": "0.0001", "lot_size": "1",
            "min_deal_size": "100", "size_increment": "1",
            "margin_factor": "3.33", "margin_factor_unit": "PERCENTAGE",
            "min_stop_distance": "0.0100", "spread_price": "0.00007",
            "quote_currency": "USD", "provenance": "BROKER_DISCOVERY",
            "spread_samples": 5, "measured_at_utc": "2026-09-01T00:00:00+00:00",
        },
        "GOLD": {
            "epic": "GOLD", "pip_size": "0.1", "lot_size": "1",
            "min_deal_size": "0.01", "size_increment": "0.01",
            "margin_factor": "5", "margin_factor_unit": "PERCENTAGE",
            "min_stop_distance": "0.01", "spread_price": "5",
            "quote_currency": "USD", "provenance": "BROKER_DISCOVERY",
            "spread_samples": 5, "measured_at_utc": "2026-09-01T00:00:00+00:00",
        },
    }
}


class CapitalLikeBroker(MockBrokerAdapter):
    """وسيطٌ يعلن أدواته عقودَ فروقات — كما يفعل كابيتال."""

    CLASSES = {
        "EURUSD": (AssetClass.CFD_CURRENCY, D("100"), D("0.0100")),
        "GOLD": (AssetClass.CFD_COMMODITY, D("0.01"), D("0.01")),
    }

    def get_instrument_details(self, symbol: str) -> InstrumentDetails:
        base = super().get_instrument_details(symbol)
        row = self.CLASSES.get(symbol)
        if row is None:
            return base
        asset_class, min_quantity, min_stop = row
        return base.model_copy(update={
            "asset_class": asset_class, "exchange": "CAPITAL_COM", "currency": "USD",
            "broker": Broker.CAPITAL_COM, "epic": symbol,
            "min_quantity": min_quantity, "min_stop_distance": min_stop,
            "quote_currency": "USD", "supports_fractional": True,
        })


class FixedSignal(Strategy):
    """استراتيجيةٌ تُعيد إشارةً معلومة — الفحص على التسعير لا على الإشارة."""

    metadata = StrategyMetadata(
        name="FIXED", version="1.0.0", hypothesis_ar="ثابتة للاختبار",
        markets=("EURUSD", "GOLD"), timeframe="DAY",
        entry_conditions_ar=(), exit_conditions_ar=(), invalidations_ar=(),
        min_bars_required=1, assumed_costs_ar="—", no_trade_conditions_ar=(),
        state=StrategyState.APPROVED, changelog_ar=(),
        backtest_evidence_ar="—", walkforward_evidence_ar="—",
    )

    def __init__(self, *, entry: str, stop: str, target: str) -> None:
        self.entry, self.stop, self.target = D(entry), D(stop), D(target)

    def evaluate(self, *, symbol, bars, quote, now):
        return Signal(
            strategy_name="FIXED", strategy_version="1.0.0", symbol=symbol,
            side=Side.BUY, entry_price=self.entry, stop_price=self.stop,
            take_profit_price=self.target, generated_at_utc=now,
            rationale_ar="إشارة ثابتة للاختبار.", invalidation_ar="—",
            inputs_digest="test",
        )


def build(*, symbol, entry, stop, target, baseline, bid, ask, registry=None,
          mode=RiskMode.VALIDATION, broker_kind=None, now=MID_SESSION):
    broker = CapitalLikeBroker(behaviour=MockBehaviour(stop_on_fractional_supported=True))
    broker.connect()
    broker.balances = make_balances(baseline, at=now)
    broker.permissions = (
        capital_permissions(now) if symbol in CapitalLikeBroker.CLASSES
        else make_permissions(at=now)
    )
    broker.set_quote(make_quote(symbol, bid, ask, at=now, source=DataSource.REALTIME))
    audit = AuditLog(InMemoryAuditStore())
    pipeline = Pipeline(
        broker=broker,
        risk_engine=RiskEngine(RiskLimits.for_mode(
            mode, D(baseline),
            broker_kind or (
                Broker.CAPITAL_COM if symbol in CapitalLikeBroker.CLASSES else Broker.IBKR
            ),
        )),
        kill_switch=KillSwitch(), audit=audit,
        execution=ExecutionService(broker=broker, audit=audit, guard=IdempotencyGuard()),
        strategies=[FixedSignal(entry=entry, stop=stop, target=target)],
        schedule=IBKR_PRO_TIERED_US_STOCK,
        assumptions=CostAssumptions(D("0.01"), D("0.0005"), D("0")),
        blackouts=BlackoutCalendar(entries=[], confirmed_for={now.date()}),
        instruments=(
            InstrumentRegistry.from_dict(MEASURED) if registry is None else registry
        ),
    )
    state = SessionRiskState(
        baseline_equity=D(baseline), current_equity=D(baseline),
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )
    return pipeline, state, broker


def run(pipeline, state, symbol, now=MID_SESSION):
    return pipeline.run(symbol=symbol, bars=uptrend_bars(), state=state,
                        macro=NO_MACRO, now=now)


# ---------------------------------------------------------------------------
# ١ · التوجيه: مَن يسعّر؟
# ---------------------------------------------------------------------------

def test_the_cfd_predicate_is_the_one_eligibility_uses():
    """
    مُسنَدٌ واحد لا نسختان: أداةٌ تُفحَص أهليتها كـCFD ثم تُسعَّر كسهم هي
    بالضبط العطل الذي وقع.
    """
    from app.eligibility.allowlist import CFD_ASSET_CLASSES
    for asset_class in CFD_ASSET_CLASSES:
        assert is_cfd(type("D", (), {"asset_class": asset_class})())
    assert not is_cfd(type("D", (), {"asset_class": AssetClass.ETF})())
    assert not is_cfd(None)


def test_a_cfd_is_sized_at_the_broker_minimum_not_solved_backwards():
    """
    **الفحص الذي يعضّ.** مسار الأسهم يحلّ الكمية عكسياً من الميزانية،
    فيُخرج كسراً من سهم. ومسار CFD لا يحلّ شيئاً: الوسيط يفرض 0.01 أونصة،
    والسؤال هل تقع خسارتها في الميزانية.
    """
    pipeline, state, _ = build(
        symbol="GOLD", entry="3300.0", stop="3280.0", target="3340.0",
        baseline="300", bid="3299.5", ask="3300.0",
    )
    result = run(pipeline, state, "GOLD")
    assert result.risk_decision is not None, result.reason_ar
    assert result.risk_decision.quantity == D("0.01"), (
        "الكمية ليست الكمية الدنيا للوسيط — أي أن مسار الأسهم هو الذي سعّر."
    )


def test_the_risk_shown_is_the_capital_model_not_the_ibkr_schedule():
    """
    الخسارة المتوقعة يجب أن تطابق `CapitalComCostModel` حرفاً — لا جدول
    عمولات أسهم أمريكية.
    """
    pipeline, state, _ = build(
        symbol="GOLD", entry="3300.0", stop="3280.0", target="3340.0",
        baseline="300", bid="3299.5", ask="3300.0",
    )
    result = run(pipeline, state, "GOLD")
    model = InstrumentRegistry.from_dict(MEASURED).cost_model_for("GOLD")
    expected = model.estimate(
        size=D("0.01"), entry_price=D("3300.0"),
        stop_distance_pips=D("20.0") / D("0.1"),
        take_profit_distance_pips=D("40.0") / D("0.1"),
    )
    assert result.risk_decision.expected_risk_usd == expected.all_in_risk
    assert result.risk_decision.expected_costs_usd == expected.total_costs


def test_a_stock_still_takes_the_stock_path():
    """التشديد على CFD لا يمسّ مسار الأسهم: `SPY` تبقى كما كانت."""
    pipeline, state, _ = build(
        symbol="SPY", entry="640.00", stop="630.00", target="660.00",
        baseline="5000", bid="639.99", ask="640.00",
        mode=RiskMode.CONSERVATIVE_LIVE, broker_kind=Broker.IBKR,
    )
    result = run(pipeline, state, "SPY")
    assert result.risk_decision is not None
    # مسار الأسهم يحلّ الكمية، فتكون أكبر من الواحد ولا تساوي كمية وسيطٍ دنيا.
    assert result.risk_decision.quantity > 0
    assert result.reason_code != INSTRUMENT_ECONOMICS_UNMEASURED


# ---------------------------------------------------------------------------
# ٢ · الاكتشاف الذي غيّر الخطّة: 300 دولار لا تكفي EUR/USD
# ---------------------------------------------------------------------------

def test_three_hundred_dollars_can_never_open_eurusd():
    """
    **الرقم الذي غيّر قرار المالكة.** أرخص صفقة يقبلها كابيتال على
    EUR/USD (100 وحدة × 100 نقطة) تكلّف 1.02 دولار، وميزانية الصفقة عند
    مرجع 300 في وضع التحقّق 0.75 دولار. فالرفض دائم — لا يزول بانتظار
    فرصةٍ أفضل.
    """
    pipeline, state, _ = build(
        symbol="EURUSD", entry="1.16000", stop="1.15000", target="1.18000",
        baseline="300", bid="1.15993", ask="1.16000",
    )
    result = run(pipeline, state, "EURUSD")
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == ACCOUNT_SIZE_INSUFFICIENT_FOR_BROKER_MINIMUM, result.reason_ar


def test_gold_fits_the_same_three_hundred_dollars():
    """
    **الخطة (ب).** الكمية الدنيا للذهب 0.01 أونصة لا 100 وحدة، فتنزل
    المخاطرة معها. وهذا هو ما يجعل النظام يعمل على 300 دولار **بلا تخفيف
    حدٍّ واحد** — وهو الفرق بين حلٍّ وتنازل.
    """
    pipeline, state, _ = build(
        symbol="GOLD", entry="3300.0", stop="3280.0", target="3360.0",
        baseline="300", bid="3299.5", ask="3300.0",
    )
    result = run(pipeline, state, "GOLD")
    assert result.risk_decision is not None and result.risk_decision.approved, (
        result.reason_ar
    )
    assert result.risk_decision.expected_risk_usd <= D("1.50")


def test_a_two_to_one_target_is_not_two_to_one_after_the_gold_spread():
    """
    **ما يجب أن تعرفه المالكة قبل أن تعتمد على الذهب.**

    سبريد الذهب المقيس يبتلع جزءاً من العائد، فهدفٌ عند ضِعف الوقف يصير
    نسبته الصافية 1.35 — تحت حدّ الدستور 1.5 — فيُرفض. أي أن الذهب يحتاج
    هدفاً عند **2.5 ضعف الوقف على الأقل**، لا ضِعفين.

    وهذا رفضٌ صحيح لا عطل: العائد يُقاس بعد التكاليف أو لا يُقاس.
    """
    pipeline, state, _ = build(
        symbol="GOLD", entry="3300.0", stop="3280.0", target="3340.0",
        baseline="300", bid="3299.5", ask="3300.0",
    )
    result = run(pipeline, state, "GOLD")
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == "NET_REWARD_RISK_TOO_LOW", result.reason_ar


# ---------------------------------------------------------------------------
# ٣ · ما لا يُقاس لا يُسعَّر
# ---------------------------------------------------------------------------

def test_an_unmeasured_cfd_is_refused_not_priced_as_a_stock():
    """
    القاعدة «المقيس وحده يُنفَّذ عليه» لم تكن مطبَّقة في القرار: أداةٌ بلا
    قياس كانت تُسعَّر بجدول أسهم وتُنفَّذ. والصواب رفضٌ **بسببٍ يُقرأ**.
    """
    pipeline, state, _ = build(
        symbol="GOLD", entry="3300.0", stop="3280.0", target="3340.0",
        baseline="300", bid="3299.5", ask="3300.0",
        registry=InstrumentRegistry.empty(),
    )
    result = run(pipeline, state, "GOLD")
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == INSTRUMENT_ECONOMICS_UNMEASURED
    assert "discover_instrument_economics" in result.reason_ar


def test_a_stop_tighter_than_the_broker_allows_is_refused_here_not_there():
    """
    رفضُ الوسيط أغلى من رفضنا: يقع بعد أن صار للأمر أثر. ولا يُوسَّع الوقف
    تلقائياً — التوسيع يغيّر المخاطرة التي وافقت عليها المالكة.
    """
    pipeline, state, _ = build(
        symbol="EURUSD", entry="1.16000", stop="1.15900", target="1.16300",
        baseline="10000", bid="1.15993", ask="1.16000",
    )
    result = run(pipeline, state, "EURUSD")
    assert result.decision is Decision.NO_TRADE
    assert result.reason_code == STOP_BELOW_BROKER_MINIMUM, result.reason_ar
    assert "0.0100" in result.reason_ar or "0.01" in result.reason_ar


# ---------------------------------------------------------------------------
# ٤ · الرقم الذي تقرأه المالكة
# ---------------------------------------------------------------------------

def test_a_rejected_stop_is_readable_not_twenty_eight_decimals():
    """
    **ظهر على شاشتها بالحرف:**

        مسافة الوقف 0.0023321165761706818242605020 أضيق من أدنى ما يقبله
        الوسيط (0.01) على EURUSD

    ثمانٍ وعشرون منزلة — دقّةُ `Decimal` بعد قسمة، لا دقّةُ سعرٍ عند وسيط.
    ورقمٌ بهذا الطول لا يُقرأ، فيُقرأ أنه عطب: تنظر المالكة إلى رفضٍ صحيح
    فتظنّ النظام مكسوراً.

    وهو العيب الحاكم في وجهه الآخر: قيمةٌ تُعرَض **بغير الدقّة التي تعنيها**.
    """
    pipeline, state, _ = build(
        # **وقفٌ بذيلٍ طويل كالذي أنتجته `1.5×ATR` فعلاً.**
        #
        # أوّل كتابةٍ لهذا الفحص استعملت وقفاً عند 1.15900 — فرقُه 0.001،
        # رقمٌ نظيف بلا قسمة. فمرّ الفحص تحت الطفرة: لا ذيل ليُقصّ.
        # واختبارٌ لا يُعيد إنتاج الشرط لا يفحصه — وهو فخّ «المقارنة
        # الفارغة» نفسه للمرّة الثالثة اليوم.
        symbol="EURUSD", entry="1.16000",
        stop="1.157667883423829318175739498", target="1.16300",
        baseline="10000", bid="1.15993", ask="1.16000",
    )
    result = run(pipeline, state, "EURUSD")
    assert result.reason_code == STOP_BELOW_BROKER_MINIMUM, result.reason_ar
    longest = max(
        (len(part.split(".")[1]) for part in result.reason_ar.replace("(", " ").split()
         if "." in part and part.replace(".", "").replace(",", "").isdigit()),
        default=0,
    )
    assert longest <= 8, f"رقمٌ بـ{longest} منزلة في نصٍّ تقرأه المالكة."


def test_the_rejection_also_speaks_in_pips():
    """
    و«0.00233 مقابل 0.01» صحيحٌ ولا يُقرأ. والمتداولة تفكّر بالنقاط:
    **23.32 نقطة مقابل 100** — وهي الجملة التي تُفهَم بلا حساب.
    """
    pipeline, state, _ = build(
        symbol="EURUSD", entry="1.16000",
        stop="1.157667883423829318175739498", target="1.16300",
        baseline="10000", bid="1.15993", ask="1.16000",
    )
    result = run(pipeline, state, "EURUSD")
    assert "نقطة" in result.reason_ar
    assert "100" in result.reason_ar


def test_a_value_smaller_than_a_pip_is_still_shown():
    """
    وأدنى وقفٍ على الذهب `0.001` وحجم نقطته `0.01`: القصُّ على منازل النقطة
    وحدها يطبعه «0.000» — أي يمحو الرقم الذي جاء السطر ليقوله.
    """
    from app.pipeline.runner import _at_pip

    assert _at_pip(D("0.001"), D("0.01")) == "0.00100"
    assert _at_pip(D("0.0005"), D("0.01")) == "0.000500"
    assert D(_at_pip(D("0.0005"), D("0.01"))) > 0
