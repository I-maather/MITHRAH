"""
المسح المتعدد وسقف مصدر التعرّض والثابت الرابط بين الحدود.

## الطلب الذي أنتج هذا الملف

«الهدف من التطبيق أنه يراقب السوق ٢٤/٧ لرصد الفرص والدخول حسب الفرصة… ٢–٣
مراكز مفتوحة في نفس الوقت عشان ما تضيع الفرص» — المالكة، 2026-09-01.

وكانت حلقة القرار تأخذ **أوّل أداة مسموحة وتتجاهل الباقي** (`next(iter(...))`)،
فيبقى «يراقب السوق» جملةً صحيحة عن أداة واحدة وخاطئة عن السوق.

## والثلاثة التي يفرضها هذا الملف

  ١  المسح يمرّ على **كل** أداة، ويتوقّف عند أوّل تنفيذ.
  ٢  مركز واحد لكل **مصدر تعرّض** — وإلا صار ثلاثة مراكز رهاناً واحداً
     بثلاثة أضعاف الحجم، وحدود المخاطرة تحسبه ثلاثة فتكذب ثلاث مرّات.
  ٣  الحدّ اليومي ≥ عدد المراكز × المخاطرة — وإلا فهو حدٌّ **يُخترَق قبل
     أن يعمل**: يُقرأ في التقارير ويطمئن، ولا يمنع شيئاً.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.contracts import Decision
from app.money import D
from app.pipeline.runner import PipelineResult
from app.risk.constitution import (
    MODE_SPECS,
    Broker,
    IncoherentRiskLimits,
    RiskLimits,
    RiskMode,
    exposure_bucket,
)
from app.runtime.heartbeat import _chosen

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def result(decision=Decision.NO_TRADE, code="NO_SIGNAL", stage="strategy") -> PipelineResult:
    return PipelineResult(decision, code, f"سبب {code}", stage, at_utc=NOW)


# ---------------------------------------------------------------------------
# ١ · الثابت الرابط
# ---------------------------------------------------------------------------

def test_the_daily_cap_can_absorb_every_stop_at_once():
    """
    **العطل الذي يمنعه.** ثلاثة مراكز × 0.75 = 2.25 قد تُضرب في اللحظة نفسها،
    وحدٌّ يوميّ عند 1.50 يُتجاوَز قبل أن يتمكّن من التصرّف.
    """
    for mode in RiskMode:
        limits = RiskLimits.for_mode(mode, D("150"), Broker.CAPITAL_COM)
        worst = limits.max_risk_per_trade * limits.max_open_positions
        assert limits.daily_loss >= worst, (
            f"{mode.value}: الحدّ اليومي {limits.daily_loss} < أسوأ خسارة متزامنة {worst}"
        )


def test_an_incoherent_configuration_refuses_to_be_built():
    """يُرفَض **عند البناء** لا عند أوّل خسارة: إعدادٌ متناقض يمنع الإقلاع."""
    with pytest.raises(IncoherentRiskLimits) as exc:
        RiskLimits(
            mode=RiskMode.VALIDATION, broker=Broker.CAPITAL_COM,
            constitution_version="0.2.0", baseline_equity=D("150"),
            hard_total_loss=D("15"), daily_loss=D("1.50"), weekly_loss=D("7.50"),
            target_risk_per_trade=D("0.38"), max_risk_per_trade=D("0.75"),
            max_risk_pct_of_current_equity=None, operational_drawdown_stop=None,
            gap_slippage_reserve=None,
            max_open_positions=3,                     # ← 3 × 0.75 = 2.25 > 1.50
            max_entry_orders_per_day=6,
            consecutive_losses_pause=2, pause_scope=MODE_SPECS[RiskMode.VALIDATION].pause_scope,
            consecutive_losses_kill=3, min_reward_risk_ratio=D("1.5"),
            enforce_economic_viability=True, max_cost_ratio_of_risk=D("0.35"),
            max_breakeven_move_pct=D("0.006"), max_lifetime_entry_orders=None,
            requires_per_order_approval=False, require_take_profit=True,
            prefer_guaranteed_stop=False, allow_overnight=False, allow_weekend_hold=False,
            allows_entries=True, allowed_instruments=frozenset({"EURUSD"}),
            quantity_policy=MODE_SPECS[RiskMode.VALIDATION].quantity_policy_by_broker[
                Broker.CAPITAL_COM
            ],
        )
    assert "يُخترق قبل أن يعمل" in str(exc.value)


# ---------------------------------------------------------------------------
# ٢ · مصدر التعرّض
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol,bucket", [
    ("EURUSD", "EUR"), ("GBPUSD", "GBP"), ("USDJPY", "JPY"), ("GOLD", "XAU"),
    ("eurusd", "EUR"),
])
def test_each_instrument_maps_to_its_non_dollar_leg(symbol, bucket):
    assert exposure_bucket(symbol) == bucket


def test_an_unknown_instrument_gets_its_own_bucket_not_a_shared_one():
    """
    الافتراض الآمن أن المجهول **مستقل** لا أن المجهول **مثل غيره**: خلطه في
    دلوٍ معلوم يمنع فتحه بلا سبب، وإفراده يمنع فقط تكراره هو.
    """
    assert exposure_bucket("SPX") == "SPX"
    assert exposure_bucket("SPX") != exposure_bucket("EURUSD")


def test_the_four_do_not_collapse_into_one_bucket():
    """ولو انهارت في دلو واحد لصار سقف «مركز لكل مصدر» يعني مركزاً واحداً."""
    buckets = {exposure_bucket(s) for s in ("EURUSD", "GBPUSD", "USDJPY", "GOLD")}
    assert len(buckets) == 4


# ---------------------------------------------------------------------------
# ٣ · اختيار ما يُعرَض من المسح
# ---------------------------------------------------------------------------

def test_a_trade_always_wins_the_display():
    scan = [
        ("EURUSD", result(code="NO_SIGNAL")),
        ("GOLD", result(Decision.TRADE, None, "execution")),
    ]
    assert _chosen(scan).decision is Decision.TRADE


def test_a_fault_is_shown_before_a_normal_no_opportunity():
    """
    «لم أرَ السوق» عطلٌ يُصلَح، و«رأيتُه ولم أجد فرصة» عملٌ طبيعي. وعرضُ
    الثاني مكان الأوّل يرسل المالكة إلى المكان الخطأ تماماً.
    """
    scan = [
        ("EURUSD", result(code="NO_SIGNAL")),
        ("GOLD", result(code="INSUFFICIENT_BARS", stage="runtime")),
    ]
    assert _chosen(scan).reason_code == "INSUFFICIENT_BARS"


def test_an_empty_scan_invents_nothing():
    assert _chosen([]) is None


# ---------------------------------------------------------------------------
# ٤ · الحلقة تمسح الأدوات كلّها
# ---------------------------------------------------------------------------

class FakeScheduler:
    def __init__(self) -> None:
        self.jobs = {}

    def register(self, name, *, kind, interval, func):
        self.jobs[name] = func


class FakeBroker:
    def health_check(self) -> bool:
        return True

    def get_candles(self, symbol, resolution="DAY", max_bars=120):
        return []


class FakeKill:
    is_active = False


class FakePipeline:
    def __init__(self, trade_on=None) -> None:
        self.seen: list[str] = []
        self.trade_on = trade_on

    def run(self, *, symbol, bars, state, macro):
        self.seen.append(symbol)
        if symbol == self.trade_on:
            return result(Decision.TRADE, None, "execution")
        return result(code="NO_SIGNAL")


class FakeState:
    def __init__(self, symbols, pipeline) -> None:
        self.locally_paused = False
        self.broker = FakeBroker()
        self.kill_switch = FakeKill()
        self.limits = RiskLimits.for_mode(RiskMode.VALIDATION, D("150"), Broker.CAPITAL_COM)
        object.__setattr__(self.limits, "allowed_instruments", frozenset(symbols))
        self.db_session = object()
        self.pipeline = pipeline
        self.scheduler = FakeScheduler()
        self.last_result = None
        self.last_scan = []
        self.last_bars: dict = {}
        self.session_state = None


def decision_job(state):
    from app.runtime.heartbeat import DECISION_JOB, register_runtime_jobs

    register_runtime_jobs(state)
    return state.scheduler.jobs[DECISION_JOB]


@pytest.fixture()
def no_db(monkeypatch):
    """حالة المخاطرة تُحقن — الغرض فحص المسح لا قاعدة البيانات."""
    from app.risk.engine import SessionRiskState

    monkeypatch.setattr(
        "app.runtime.heartbeat.load_session_state",
        lambda session, *, baseline_equity: SessionRiskState(
            baseline_equity=baseline_equity, current_equity=baseline_equity,
            realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
            open_positions=0, entry_orders_today=0, consecutive_losses=0,
        ),
    )
    # الشموع كافية دائماً: البند المفحوص هنا هو المسح لا جودة البيانات.
    # الدقّة تُمرَّر الآن من الحالة — والبديل يقبلها ويسجّلها كي يُفحَص
    # أنها تصل فعلاً، لا أن تُبتلع في وسيطٍ لا أحد ينظر إليه.
    seen_resolutions: list[str] = []

    def _fake_bars(broker, symbol, resolution="DAY"):
        seen_resolutions.append(resolution)
        return ["bar"] * 120

    monkeypatch.setattr("app.runtime.heartbeat._bars", _fake_bars)


def test_every_allowed_instrument_is_scanned(no_db):
    """**العطل بعينه.** كان يأخذ أوّل أداة ويترك الباقي بلا أن يُقال ذلك."""
    pipeline = FakePipeline()
    state = FakeState(["EURUSD", "GBPUSD", "USDJPY", "GOLD"], pipeline)
    decision_job(state)()
    assert pipeline.seen == ["EURUSD", "GBPUSD", "GOLD", "USDJPY"]
    assert len(state.last_scan) == 4


def test_the_scan_stops_at_the_first_trade(no_db):
    """
    المضيّ بعد التنفيذ يقيّم بقيّة الأدوات على حالة مخاطرة **صارت بائدة في
    السطر السابق** — فيُفتح مركزٌ ثانٍ بميزانيةٍ أُنفقت.
    """
    pipeline = FakePipeline(trade_on="GBPUSD")
    state = FakeState(["EURUSD", "GBPUSD", "USDJPY", "GOLD"], pipeline)
    decision_job(state)()
    assert pipeline.seen == ["EURUSD", "GBPUSD"]
    assert state.last_result.decision is Decision.TRADE


def test_the_risk_state_is_read_once_per_scan_not_once_per_instrument(no_db, monkeypatch):
    """قراءتها بين الأدوات تجعل نتيجة الثانية تعتمد على أثر الأولى في المنتصف."""
    calls = []
    from app.risk.engine import SessionRiskState

    def counted(session, *, baseline_equity):
        calls.append(1)
        return SessionRiskState(
            baseline_equity=baseline_equity, current_equity=baseline_equity,
            realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
            open_positions=0, entry_orders_today=0, consecutive_losses=0,
        )

    monkeypatch.setattr("app.runtime.heartbeat.load_session_state", counted)
    state = FakeState(["EURUSD", "GBPUSD", "GOLD"], FakePipeline())
    decision_job(state)()
    assert len(calls) == 1


def test_no_allowed_instrument_says_so_and_clears_the_scan(no_db):
    state = FakeState([], FakePipeline())
    decision_job(state)()
    assert state.last_result.reason_code == "NO_INSTRUMENT"
    assert state.last_scan == []


# ---------------------------------------------------------------------------
# ٥ · البوابة نفسها داخل المحرّك
# ---------------------------------------------------------------------------

def cfd_engine():
    from app.risk.engine import RiskEngine

    return RiskEngine(RiskLimits.for_mode(RiskMode.VALIDATION, D("150"), Broker.CAPITAL_COM))


def fx_signal(symbol: str):
    from app.contracts import Side, Signal

    return Signal(
        strategy_name="TEST", strategy_version="0.0.0", symbol=symbol, side=Side.BUY,
        entry_price=D("1.16000"), stop_price=D("1.15700"), take_profit_price=D("1.16600"),
        generated_at_utc=NOW, rationale_ar="اختبار", invalidation_ar="اختبار",
        inputs_digest="abc123",
    )


def state_with(open_symbols):
    from app.risk.engine import SessionRiskState

    return SessionRiskState(
        baseline_equity=D("150"), current_equity=D("150"),
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=len(open_symbols), entry_orders_today=0, consecutive_losses=0,
        open_symbols=tuple(open_symbols),
    )


def gate_verdict(symbol: str, open_symbols):
    """يشغّل البوابات وحدها ويعيد رمز الرفض إن وُجد."""
    engine = cfd_engine()
    rejection, _checks, _budget = engine._run_gates(   # noqa: SLF001
        signal=fx_signal(symbol), state=state_with(open_symbols),
        kill_switch_active=False, now=NOW,
    )
    return rejection.reason_code if rejection is not None else None


def test_a_second_position_on_the_same_exposure_is_refused_by_name():
    verdict = gate_verdict("EURUSD", ["EURUSD"])
    assert verdict == "EXPOSURE_BUCKET_ALREADY_OCCUPIED"


def test_a_different_exposure_is_allowed_alongside():
    """السقف يوزّع ولا يمنع: الذهب مع اليورو مسموح، واليورو مع اليورو لا."""
    assert gate_verdict("GOLD", ["EURUSD"]) != "EXPOSURE_BUCKET_ALREADY_OCCUPIED"
    assert gate_verdict("USDJPY", ["EURUSD", "GOLD"]) != "EXPOSURE_BUCKET_ALREADY_OCCUPIED"


def test_the_refusal_names_the_position_that_occupies_the_bucket():
    """رفضٌ لا يقول أيّ مركزٍ يشغل المكان يرسل القارئ يبحث بلا دليل."""
    engine = cfd_engine()
    rejection, _c, _b = engine._run_gates(            # noqa: SLF001
        signal=fx_signal("EURUSD"), state=state_with(["EURUSD"]),
        kill_switch_active=False, now=NOW,
    )
    assert "EUR" in rejection.reason_ar and "EURUSD" in rejection.reason_ar


def test_the_dollar_correlation_is_declared_not_silently_claimed_solved():
    """
    الأربع كلها مقابل الدولار، والفصل هنا على الطرف غير الدولاري **وحده**.
    وهذا نقصٌ يُعلَن في نصّ الفحص الناجح نفسه — لا يُموَّه بمعامل ارتباط مخترع.
    """
    engine = cfd_engine()
    _r, checks, _b = engine._run_gates(               # noqa: SLF001
        signal=fx_signal("GOLD"), state=state_with(["EURUSD"]),
        kill_switch_active=False, now=NOW,
    )
    bucket_check = [c for c in checks if c[0] == "EXPOSURE_BUCKET"]
    assert bucket_check, "لا أثر للفحص في سجلّ القرار"
    assert "الدولار" in bucket_check[0][2]


# ---------------------------------------------------------------------------
# ٦ · المسح يصل إلى صاحبته
#
# ## الفجوة التي يسدّها هذا القسم
#
# بحث المنافسين في هذا المشروع وجد الفراغ الوظيفي بنفسه: **لا شاشة في ٦٩
# لقطة تقول «لماذا لم أتداول»**. ثم بنينا تطبيقاً يقول «لا تداول: رمزٌ ما»
# — وهي حقيقة، وليست جواباً.
#
# والجواب محفوظٌ في `last_scan` منذ صار المسح يمرّ على الأدوات كلّها، ولم
# تكن أي شاشة تعرضه: **أثمن ما في النظام في الذاكرة ولا يصل إلى صاحبته.**
# ---------------------------------------------------------------------------

def test_the_scan_reaches_the_phone_instrument_by_instrument():
    from app.mobile.state import _scan

    class Sys:
        last_scan = [
            ("EURUSD", result(code="NO_APPROVED_STRATEGY")),
            ("GOLD", result(code="INSUFFICIENT_BARS", stage="runtime")),
        ]

    view = _scan(Sys())
    assert view["scanned"] == 2
    assert [i["symbol"] for i in view["instruments"]] == ["EURUSD", "GOLD"]
    assert all(i["reason_ar"] for i in view["instruments"]), "أداةٌ بلا سبب مكتوب"


def test_a_fault_is_marked_apart_from_a_normal_no_opportunity():
    """
    «لم أرَ السوق» عطلٌ يُصلَح، و«رأيتُه ولم أجد فرصة» عملُ النظام الطبيعي.
    وعرضُهما بلونٍ واحد يجعل المالكة إمّا تقلق كل يوم أو تتجاهل اليوم الذي
    يهمّ. والتمييز يُحسب من الرمز لا يُكتب بيد.
    """
    from app.mobile.state import _scan

    class Sys:
        last_scan = [
            ("EURUSD", result(code="NO_SIGNAL")),
            ("GOLD", result(code="INSUFFICIENT_BARS", stage="runtime")),
        ]

    view = _scan(Sys())
    assert view["faults"] == 1
    marked = {i["symbol"]: i["needs_a_hand"] for i in view["instruments"]}
    assert marked == {"EURUSD": False, "GOLD": True}


def test_an_empty_scan_says_so_and_invents_no_summary():
    from app.mobile.state import _scan

    class Sys:
        last_scan: list = []

    view = _scan(Sys())
    assert view["scanned"] == 0 and view["instruments"] == []
    assert "لم تبدأ" in view["summary_ar"]


def test_the_summary_counts_and_does_not_interpret():
    """
    جملةٌ تُقرأ في ثانية — وتُبنى من العدّ لا من التفسير. وتفسيرٌ يُكتب هنا
    («يبدو أن السوق هادئ») ادّعاءٌ لا يسنده المسح.
    """
    from app.mobile.state import _scan

    class Sys:
        last_scan = [(f"SYM{i}", result(code="NO_SIGNAL")) for i in range(4)]

    summary = _scan(Sys())["summary_ar"]
    assert "4" in summary
    assert "لم تكتمل شروط الدخول" in summary


def test_the_scan_route_is_a_read_route_not_a_mutation():
    from app.mobile.api import READ_ROUTES, RISK_INCREASING_ROUTES, RISK_REDUCING_ROUTES

    assert "scan/latest" in READ_ROUTES
    assert "scan/latest" not in RISK_REDUCING_ROUTES + RISK_INCREASING_ROUTES


def test_the_loop_reads_the_resolution_the_owner_configured(monkeypatch, no_db):
    """
    الحلقة كانت تقرأ شموعاً **يومية** مثبَّتة وتكرّر السؤال 1440 مرّة في
    اليوم على نفس الشمعة — فإشارةٌ واحدة كل ثلاثة أسابيع تقريباً.

    والدقّة الآن من الحالة. ولو عادت مثبَّتة لسقط هذا: لا يكفي أن يقبل
    `_bars` وسيطاً، بل أن يصل إليه ما ضُبط.
    """
    seen: list[str] = []

    def _fake_bars(broker, symbol, resolution="DAY"):
        seen.append(resolution)
        return ["bar"] * 120

    monkeypatch.setattr("app.runtime.heartbeat._bars", _fake_bars)

    state = FakeState(["EURUSD", "GBPUSD"], FakePipeline())
    state.candle_resolution = "MINUTE_15"
    decision_job(state)()

    assert seen, "لم تُقرأ شموعٌ إطلاقاً — الفحص بلا معنى"
    assert set(seen) == {"MINUTE_15"}


def test_without_configuration_it_stays_on_daily(monkeypatch, no_db):
    """الافتراض الأسلم: أبطأ إشارةً لا أخطر."""
    seen: list[str] = []
    monkeypatch.setattr(
        "app.runtime.heartbeat._bars",
        lambda broker, symbol, resolution="DAY": (seen.append(resolution), ["bar"] * 120)[1],
    )
    decision_job(FakeState(["EURUSD"], FakePipeline()))()
    assert set(seen) == {"DAY"}
