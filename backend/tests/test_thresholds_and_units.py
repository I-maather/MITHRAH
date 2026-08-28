"""
اختبارات تصحيحات التدقيق: العتبات · سلسلة الخسائر · وحدة التبييت ·
شروط الأداة العامة.

**لا شبكة · لا Keychain · لا اعتماد حقيقي.**
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.live_readonly.overnight import (
    DECLARED_CAPITAL_OVERNIGHT_UNIT,
    OVERNIGHT_RATE_UNIT_UNKNOWN,
    OvernightRate,
    OvernightRateUnit,
    OvernightRateUnitUnknown,
    compute_overnight,
    implied_annual_percent,
    normalize_rate,
    parse_unit,
    resolve_unit,
)
from app.live_readonly.report import (
    FORBIDDEN_PUBLIC_KEYS,
    PLANNED_CAPITAL_USD,
    PUBLIC_INSTRUMENT_FIELDS,
    compute_feasibility,
    render_instrument_conditions_markdown,
    render_public_feasibility_markdown,
)
from app.money import D
from app.profiles import (
    GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD,
    PROFILE_SPECS,
    ProfileLimits,
    TradingProfile,
)
from app.profiles.thresholds import (
    TRADING_DAYS_PER_WEEK,
    loss_sequence_limits,
    minimum_equity_for,
    scenario_fits_at_equity,
)

BAL = TradingProfile.BALANCED
CP = TradingProfile.CAPITAL_PRESERVATION
AC = TradingProfile.ACTIVE_CONTROLLED


# ===========================================================================
# 1. الحد الأدنى لحقوق الملكية — الخطأ الأول في التدقيق
# ===========================================================================

def test_balanced_054_needs_108_not_150():
    """
    الادعاء المصحَّح حرفياً: خسارة 0.54 في المتوازن تحتاج **108 دولاراً**،
    لا 150. الرقم 150 كان نقطة انقلاب السقف، وهو مفهوم آخر تماماً.
    """
    t = minimum_equity_for(BAL, D("0.54"))
    assert t.minimum_equity_from_percentage == D("108")
    assert t.percentage == D("0.0050")
    assert t.fixed_cap == D("0.75")
    assert t.exceeds_fixed_cap is False
    # ونقطة انقلاب السقف رقم **مختلف** يقع صدفةً عند 150.
    assert t.cap_binding_equity == D("150")
    assert t.minimum_equity_from_percentage != t.cap_binding_equity


def test_balanced_054_passes_at_120_where_effective_cap_is_060():
    """عند 120 دولاراً يصبح الحد الفعّال 0.60 — و0.54 **تمرّ**."""
    limits = ProfileLimits.for_profile(BAL, D("120"))
    assert limits.max_risk_per_trade == D("0.60")
    assert scenario_fits_at_equity(BAL, D("0.54"), D("120")) is True


def test_the_minimum_is_exact_not_approximate():
    """108 هو الحد بالضبط: يمرّ عنده، ويسقط تحته بسنت واحد."""
    assert scenario_fits_at_equity(BAL, D("0.54"), D("108")) is True
    assert scenario_fits_at_equity(BAL, D("0.54"), D("107.99")) is False


@pytest.mark.parametrize(
    "equity, expected",
    [
        (D("108"), True), (D("110"), True), (D("120"), True),
        (D("150"), True), (D("500"), True),
        (D("107.99"), False), (D("100"), False), (D("50"), False),
    ],
)
def test_balanced_054_across_equities(equity, expected):
    assert scenario_fits_at_equity(BAL, D("0.54"), equity) is expected


def test_cap_crossover_is_not_the_minimum_for_any_profile():
    """
    الخلط بين المفهومين هو الخطأ نفسه. هنا يُثبَت أنهما يختلفان في كل ملف
    ولكل سيناريو — إلا حين تساوي الخسارةُ السقفَ بالضبط.
    """
    for profile in TradingProfile:
        for risk in (D("0.29"), D("0.54"), D("0.79")):
            t = minimum_equity_for(profile, risk)
            if t.exceeds_fixed_cap:
                assert t.minimum_equity_from_percentage is None
                continue
            if risk == t.fixed_cap:
                assert t.minimum_equity_from_percentage == t.cap_binding_equity
            else:
                assert t.minimum_equity_from_percentage < t.cap_binding_equity


def test_risk_above_the_fixed_cap_is_impossible_at_any_equity():
    """
    السقف الدولاري لا يرتفع بزيادة رأس المال. خسارة 0.54 في **المتحفّظ**
    (سقفه 0.50) مستحيلة عند مليون دولار كما هي عند مئة.
    """
    t = minimum_equity_for(CP, D("0.54"))
    assert t.exceeds_fixed_cap is True
    assert t.minimum_equity_from_percentage is None
    for equity in (D("150"), D("1000"), D("1000000")):
        assert scenario_fits_at_equity(CP, D("0.54"), equity) is False


def test_capital_preservation_cap_binds_from_14286():
    """0.50 ÷ 0.35% = 142.86 — وفوقها لا ترتفع الحدود مهما زاد المال."""
    t = minimum_equity_for(CP, D("0.29"))
    assert t.cap_binding_equity.quantize(D("0.01")) == D("142.86")
    assert ProfileLimits.for_profile(CP, D("142.86")).max_risk_per_trade == D("0.50")
    assert ProfileLimits.for_profile(CP, D("100000")).max_risk_per_trade == D("0.50")


def test_minimum_equity_rejects_non_positive_risk():
    for bad in (D("0"), D("-1")):
        with pytest.raises(ValueError):
            minimum_equity_for(BAL, bad)


# ===========================================================================
# 2. سلسلة الخسائر — الخطأ الثاني في التدقيق
# ===========================================================================

def test_twelve_losses_of_054_do_not_exceed_the_operational_stop():
    """
    12 × 0.54 = **6.48**، وهو **لا يتجاوز** 6.50. الثالثة عشرة (7.02) هي
    التي تتجاوزه. الصياغة السابقة «12 خسارة حتى الحد» كانت مضلِّلة.
    """
    seq = loss_sequence_limits(BAL, D("0.54"), equity=D("150"))
    assert seq.losses_until_operational_stop == 12
    assert seq.cumulative_at_operational_limit == D("6.48")
    assert seq.cumulative_at_operational_limit <= GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD
    assert D("13") * D("0.54") > GLOBAL_OPERATIONAL_DRAWDOWN_STOP_USD


def test_daily_weekly_and_total_limits_interact():
    """
    الحدود لا تُجمع — الأشد يفوز. وفي المتوازن عند 0.54 يكون القيد اليومي
    الفعلي هو **عدد أوامر الدخول (1)** لا حدّ الخسارة اليومي (1.50) الذي
    يتّسع نظرياً لخسارتين.
    """
    seq = loss_sequence_limits(BAL, D("0.54"), equity=D("150"))
    assert seq.daily_limit == D("1.50")
    assert seq.losses_per_day_by_limit == 2          # الحد يتّسع لاثنتين
    assert seq.max_entry_orders_per_day == 1
    assert seq.losses_per_day_effective == 1         # لكن التواتر يسمح بواحدة
    assert seq.binding_constraint == "MAX_ENTRY_ORDERS_PER_DAY"

    assert seq.weekly_limit == D("3.00")
    assert seq.losses_per_week_by_limit == 5
    assert seq.losses_per_week_effective == 5
    assert seq.trading_days_to_operational_stop == 12


def test_weekly_limit_binds_before_the_week_ends_for_a_larger_loss():
    """عند 0.79 يسمح الأسبوعي 3.00 بثلاث خسائر فقط — قبل استيفاء الأيام الخمسة."""
    seq = loss_sequence_limits(AC, D("0.79"), equity=D("150"))
    assert seq.losses_per_week_by_limit == 3
    assert seq.losses_per_week_effective == 3
    assert seq.losses_per_week_effective < seq.losses_per_day_effective * TRADING_DAYS_PER_WEEK
    assert seq.binding_constraint == "WEEKLY_LOSS_LIMIT"


def test_a_loss_larger_than_the_daily_limit_permits_no_trading_day():
    """خسارة تتجاوز الحد اليومي وحده ⇒ صفر خسائر في اليوم، ولا أيام."""
    seq = loss_sequence_limits(CP, D("0.79"), equity=D("150"))
    assert seq.daily_limit == D("0.75")
    assert seq.losses_per_day_by_limit == 0
    assert seq.losses_per_day_effective == 0
    assert seq.trading_days_to_operational_stop is None
    assert seq.binding_constraint == "DAILY_LOSS_LIMIT"
    assert seq.scenario_permitted is False           # يتجاوز حدّ الصفقة أصلاً


def test_absolute_boundary_allows_more_than_the_operational_stop():
    """الحد المطلق 7.50 أوسع من التشغيلي 6.50 — واحتياطي الفجوة هو الفرق."""
    seq = loss_sequence_limits(BAL, D("0.54"), equity=D("150"))
    assert seq.operational_stop == D("6.50")
    assert seq.absolute_boundary == D("7.50")
    assert seq.losses_until_absolute_boundary > seq.losses_until_operational_stop


def test_scenario_permitted_flag_tracks_the_per_trade_cap():
    permitted = loss_sequence_limits(BAL, D("0.54"), equity=D("150"))
    refused = loss_sequence_limits(CP, D("0.54"), equity=D("150"))
    assert permitted.scenario_permitted is True
    assert refused.scenario_permitted is False


# ===========================================================================
# 3. وحدة التبييت — لا استنتاج صامت
# ===========================================================================

def test_declared_unit_is_unknown_until_a_human_establishes_it():
    """
    الافتراضي **UNKNOWN** عمداً. جعله PERCENT لأن الرقم «يبدو كبيراً» هو
    تخمين في الاتجاه المعاكس، وهو ما يمنعه هذا الاختبار.
    """
    assert DECLARED_CAPITAL_OVERNIGHT_UNIT is OvernightRateUnit.UNKNOWN


def test_percentage_normalisation_divides_by_one_hundred():
    """0.0086% ⇒ 0.000086 — وهو جوهر تصحيح خطأ المئة ضعف."""
    assert normalize_rate(D("0.0086"), OvernightRateUnit.PERCENT) == D("0.000086")
    assert normalize_rate(D("0.0086"), OvernightRateUnit.FRACTION) == D("0.0086")


def test_percentage_cash_fee_matches_the_required_formula():
    """cash = notional × |raw| ÷ 100 — بالحرف."""
    rate = compute_overnight(
        D("0.0086"), notional=D("115.837"), unit=OvernightRateUnit.PERCENT
    )
    assert rate.cash_fee == D("115.837") * D("0.0086") / D("100")
    assert rate.normalized_rate == D("0.000086")
    assert rate.failure_code is None


def test_a_hundredfold_error_is_impossible_when_the_unit_is_percent():
    """
    الحارس الأهم: الفرق بين التفسيرين **مئة بالضبط**. لو عاد تفسير الكسر
    مكان النسبة لظهر هنا فوراً.
    """
    notional = D("115.837")
    as_percent = compute_overnight(
        D("0.0086"), notional=notional, unit=OvernightRateUnit.PERCENT
    )
    as_fraction = compute_overnight(
        D("0.0086"), notional=notional, unit=OvernightRateUnit.FRACTION
    )
    assert as_fraction.cash_fee == as_percent.cash_fee * 100
    # والرقم الذي أنتجه الخطأ الأصلي:
    assert as_fraction.cash_fee.quantize(D("0.000001")) == D("0.996198")
    assert as_percent.cash_fee.quantize(D("0.000001")) == D("0.009962")


def test_implied_annual_percent_exposes_the_unit_error():
    """314% سنوياً يكشف الخطأ فوراً؛ 3.14% معقول."""
    wrong = implied_annual_percent(D("0.0086"))
    right = implied_annual_percent(D("0.000086"))
    assert wrong.quantize(D("0.01")) == D("313.90")
    assert right.quantize(D("0.01")) == D("3.14")


def test_unknown_unit_fails_closed_without_computing_anything():
    rate = compute_overnight(
        D("0.0086"), notional=D("115.837"), unit=OvernightRateUnit.UNKNOWN
    )
    assert rate.failure_code == OVERNIGHT_RATE_UNIT_UNKNOWN
    assert rate.normalized_rate is None
    assert rate.cash_fee is None
    assert rate.raw_value == D("0.0086")     # الخام محفوظ رغم الفشل
    assert rate.resolved is False


def test_normalize_raises_on_unknown_unit():
    with pytest.raises(OvernightRateUnitUnknown):
        normalize_rate(D("0.0086"), OvernightRateUnit.UNKNOWN)


def test_missing_rate_is_distinct_from_unknown_unit():
    """الغياب والوحدة المجهولة **حالتان مختلفتان** برمزين مختلفين."""
    rate = compute_overnight(None, notional=D("100"), unit=OvernightRateUnit.PERCENT)
    assert rate.failure_code == "OVERNIGHT_RATE_MISSING"
    assert rate.failure_code != OVERNIGHT_RATE_UNIT_UNKNOWN


@pytest.mark.parametrize(
    "token, expected",
    [
        ("PERCENT", OvernightRateUnit.PERCENT),
        ("percentage", OvernightRateUnit.PERCENT),
        ("%", OvernightRateUnit.PERCENT),
        ("FRACTION", OvernightRateUnit.FRACTION),
        ("decimal", OvernightRateUnit.FRACTION),
        ("bananas", OvernightRateUnit.UNKNOWN),
        (None, OvernightRateUnit.UNKNOWN),
        (0.0086, OvernightRateUnit.UNKNOWN),
    ],
)
def test_parse_unit(token, expected):
    assert parse_unit(token) is expected


def test_resolve_unit_prefers_an_explicit_broker_field():
    unit, source = resolve_unit({"longRate": 0.0086, "unit": "PERCENT"})
    assert unit is OvernightRateUnit.PERCENT
    assert "حقل صريح" in source


def test_resolve_unit_returns_unknown_without_evidence():
    unit, source = resolve_unit({"longRate": 0.0086})
    assert unit is OvernightRateUnit.UNKNOWN
    assert "لم يُعلن" in source


def test_resolve_unit_never_infers_from_magnitude():
    """
    قيمة كبيرة وقيمة صغيرة تعطيان النتيجة نفسها: `UNKNOWN`. حجم الرقم
    **ليس دليلاً** على وحدته.
    """
    big, _ = resolve_unit({"longRate": 8.6})
    small, _ = resolve_unit({"longRate": 0.000000086})
    assert big is small is OvernightRateUnit.UNKNOWN


def test_feasibility_keeps_the_four_overnight_values_separate():
    from tests.test_live_readonly import authenticated_session, run_live_discovery

    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    planned = compute_feasibility(
        report.instrument("EURUSD"), equity=PLANNED_CAPITAL_USD
    )
    block = planned["overnight"]
    assert set(block) >= {
        "raw_value", "unit", "normalized_rate_per_night",
        "cash_fee_one_night", "failure_code",
    }
    # التجهيزة لا تُعلن وحدة ⇒ فشل مغلق، بلا تكلفة مخترَعة.
    assert block["unit"] == "UNKNOWN"
    assert block["failure_code"] == OVERNIGHT_RATE_UNIT_UNKNOWN
    assert block["cash_fee_one_night"] is None
    assert block["raw_value"] is not None


def test_feasibility_computes_the_fee_when_the_unit_is_declared():
    from tests.test_live_readonly import (
        LiveResponse, MockLiveTransport, market_body, rsa_key_b64, full_routes, secrets,
    )
    from app.live_readonly.discovery import run_live_discovery as run_disc
    from app.live_readonly.session import LiveSession

    body = market_body("EURUSD")
    body["instrument"]["overnightFee"]["unit"] = "PERCENT"

    routes = full_routes(rsa_key_b64())
    routes[("GET", "/api/v1/markets/EURUSD")] = LiveResponse(200, {}, body)
    transport = MockLiveTransport(routes)
    session = LiveSession(transport=transport, secrets=secrets())
    session.authenticate()
    report = run_disc(session)
    session.discard()

    instrument = report.instrument("EURUSD")
    assert instrument.overnight_rate_unit == "PERCENT"
    planned = compute_feasibility(instrument, equity=PLANNED_CAPITAL_USD)
    block = planned["overnight"]
    assert block["failure_code"] is None
    assert block["cash_fee_one_night"] is not None
    assert D(block["normalized_rate_per_night"]) == D("-0.0000411") / D("100")


# ===========================================================================
# 4. شروط الأداة العامة
# ===========================================================================

REQUIRED_PUBLIC_FIELDS = (
    "min_deal_size", "min_deal_size_unit",
    "size_increment", "size_increment_unit",
    "margin_factor", "margin_factor_unit",
    "min_step_distance", "min_step_distance_unit",
    "min_stop_distance", "min_stop_distance_unit",
    "min_guaranteed_stop_distance", "min_guaranteed_stop_distance_unit",
    "guaranteed_stop_available", "guaranteed_stop_premium",
    "lot_size", "pip_position", "tick_size",
    "decimal_places_factor", "scaling_factor",
    "overnight_fee_long", "overnight_fee_short", "overnight_rate_unit",
    "trading_hours", "snapshot_time", "market_status",
)


def test_every_requested_dealing_rule_field_exists_on_the_instrument():
    from app.live_readonly.discovery import LiveInstrumentInfo

    data = LiveInstrumentInfo(epic="EURUSD", found=True).as_dict()
    for field in REQUIRED_PUBLIC_FIELDS:
        assert field in data, f"حقل مفقود من الأداة: {field}"


def test_every_requested_field_is_rendered_in_the_public_table():
    rendered = {key for key, _label, _unit in PUBLIC_INSTRUMENT_FIELDS}
    unit_keys = {u for _k, _l, u in PUBLIC_INSTRUMENT_FIELDS if u}
    covered = rendered | unit_keys
    for field in REQUIRED_PUBLIC_FIELDS:
        assert field in covered, f"حقل لا يظهر في التقرير العام: {field}"


def test_public_instrument_table_shows_values_and_units():
    from tests.test_live_readonly import authenticated_session, run_live_discovery

    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()

    lines = render_instrument_conditions_markdown(report.instrument("EURUSD"))
    text = "\n".join(lines)
    assert "أدنى حجم صفقة" in text and "AMOUNT" in text
    assert "معامل الهامش" in text and "PERCENTAGE" in text
    assert "أدنى مسافة وقف/هدف" in text and "POINTS" in text
    assert "أدنى مسافة وقف مضمون" in text
    assert "الوقف المضمون متاح؟" in text
    assert "وحدة معدّل التبييت" in text


def test_missing_broker_field_shows_a_dash_not_a_zero():
    """
    «—» تعني «لم يُعِدها الوسيط». عرضها صفراً كان سيبدو قيمة حقيقية،
    وهو بالضبط الفرق بين معرفة الشرط وتجاهله.
    """
    from app.live_readonly.discovery import LiveInstrumentInfo

    lines = render_instrument_conditions_markdown(
        LiveInstrumentInfo(epic="EURUSD", found=True)
    )
    text = "\n".join(lines)
    assert "| حجم اللوت | — | — |" in text
    assert "| حجم التِّك | — | — |" in text


def test_public_report_contains_no_account_data():
    from tests.test_live_readonly import authenticated_session, run_live_discovery

    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()
    instrument = report.instrument("EURUSD")

    text = render_public_feasibility_markdown(
        planned=compute_feasibility(instrument, equity=PLANNED_CAPITAL_USD),
        instrument=instrument,
    )
    for key in FORBIDDEN_PUBLIC_KEYS:
        assert key not in text, f"مفتاح حساب في التقرير العام: {key}"
    for value in ("212.34", "210.00", "-2.34", "****6655", "9988776655"):
        assert value not in text, f"قيمة حساب في التقرير العام: {value}"


def test_public_report_carries_the_three_corrected_sections():
    from tests.test_live_readonly import authenticated_session, run_live_discovery

    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()
    instrument = report.instrument("EURUSD")

    text = render_public_feasibility_markdown(
        planned=compute_feasibility(instrument, equity=PLANNED_CAPITAL_USD),
        instrument=instrument,
    )
    assert "ثلاثة أرقام لا رقم واحد" in text
    assert "نقطة انقلاب السقف" in text
    assert "سلسلة الخسائر المأذون بها" in text
    assert "الوحدة تُثبَت ولا تُخمَّن" in text
    assert "شروط الأداة لدى الوسيط" in text
    assert "لا يعني أن التداول مربح" in text


def test_cli_public_report_includes_the_instrument_conditions_table(
    monkeypatch, tmp_path
):
    """
    الجدول لا ينفع في الكود وحده — لا بد أن يصل إلى الملف الذي تقرأينه.
    غيابه عن `docs/` هو ما عطّل التدقيق أصلاً.
    """
    import app.cli as cli
    from tests.test_private_store import make_repo
    from tests.test_live_readonly import MockLiveTransport, full_routes, rsa_key_b64, secrets
    from app.live_readonly.session import LiveSession

    repo = make_repo(tmp_path)
    (repo / "docs").mkdir()
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    monkeypatch.setattr(cli, "build_secret_provider", lambda **_: secrets())

    transport = MockLiveTransport(full_routes(rsa_key_b64()))
    monkeypatch.setattr(cli, "LiveReadOnlyTransport", lambda *a, **k: transport)
    monkeypatch.setattr(
        cli, "LiveSession",
        lambda **kw: LiveSession(transport=transport, secrets=kw["secrets"]),
    )

    args = cli.build_parser().parse_args(
        ["capital-live-discover", "--acknowledge-live-read-only"]
    )
    assert cli.cmd_capital_live_discover(args) == 0

    text = (repo / "docs" / "CAPITAL_COM_150_USD_FEASIBILITY.md").read_text(
        encoding="utf-8"
    )
    assert "شروط الأداة لدى الوسيط" in text
    assert "أدنى مسافة وقف/هدف" in text
    assert "أدنى مسافة وقف مضمون" in text
    assert "أصغر زيادة حجم" in text
    assert "ثلاثة أرقام لا رقم واحد" in text
    assert "سلسلة الخسائر المأذون بها" in text
    # ولا قيمة حساب فيه رغم أن الاكتشاف قرأ رصيداً.
    for value in ("212.34", "210.00", "-2.34", "****6655"):
        assert value not in text
