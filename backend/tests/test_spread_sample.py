"""
اختبارات أخذ عيّنات السبريد — قراءة فقط، بلا شبكة ولا Keychain.

الزمن مُحقَّن بالكامل (`clock` و`sleeper`)، فلا اختبار ينتظر ثانية واحدة.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.live_readonly.allowlist import (
    LIVE_BASE_URL,
    UNCONDITIONALLY_BLOCKED_METHODS,
    AllowlistViolation,
    assert_allowed,
)
from app.live_readonly.session import LiveAuthAlreadyAttempted, LiveSession
from app.live_readonly.spread_sample import (
    FLAG_NEAR_DAILY_ROLLOVER,
    FLAG_NEAR_WEEKLY_CLOSE,
    MAX_ACCEPTABLE_DATA_AGE_SECONDS,
    REJECT_BAD_SPREAD,
    REJECT_NOT_TRADEABLE,
    REJECT_NO_PRICES,
    REJECT_STALE,
    SPREAD_SAMPLE_EPIC,
    SpreadSamplerError,
    build_sample,
    close_flags,
    median,
    percentile,
    render_spread_report,
    run_spread_sampling,
    summarise,
)
from app.money import D

from tests.test_live_readonly import (
    FAKE_ACCOUNT_ID,
    LiveResponse,
    MockLiveTransport,
    full_routes,
    market_body,
    rsa_key_b64,
    secrets,
)

UTC = timezone.utc


def instrument_from(body, *, now=None):
    from app.live_readonly.discovery import _extract_instrument

    return _extract_instrument(
        SPREAD_SAMPLE_EPIC, body, now or datetime.now(UTC)
    )


def snapshot_body(*, bid=1.08540, offer=1.08546, status="TRADEABLE", age_seconds=0.0):
    body = market_body(SPREAD_SAMPLE_EPIC, bid=bid, offer=offer)
    body["snapshot"]["marketStatus"] = status
    body["snapshot"]["updateTime"] = (
        datetime.now(UTC) - timedelta(seconds=age_seconds)
    ).isoformat()
    return body


def sampling_session(routes=None):
    transport = MockLiveTransport(routes or full_routes(rsa_key_b64()))
    session = LiveSession(transport=transport, secrets=secrets())
    session.authenticate()
    return session, transport


# ===========================================================================
# 1. المئينات
# ===========================================================================

def test_percentile_uses_nearest_rank_and_returns_an_observed_value():
    """
    p95 يجب أن تكون عيّنة **شوهدت فعلاً**، لا استيفاءً بين عيّنتين. رقمٌ لم
    يُرصَد قط لا يصلح أساساً لتخطيط تكلفة.
    """
    values = [D(str(v)) for v in range(1, 21)]     # 1..20
    assert percentile(values, D("0.95")) == D("19")
    assert percentile(values, D("0.75")) == D("15")
    assert percentile(values, D("1")) == D("20")
    for fraction in (D("0.5"), D("0.75"), D("0.95")):
        assert percentile(values, fraction) in values


def test_percentile_on_a_single_sample():
    assert percentile([D("3.0")], D("0.95")) == D("3.0")


def test_percentile_on_empty_is_none():
    assert percentile([], D("0.95")) is None


def test_percentile_rejects_a_fraction_outside_the_range():
    for bad in (D("0"), D("-0.1"), D("1.5")):
        with pytest.raises(ValueError):
            percentile([D("1")], bad)


def test_median_of_even_count_averages_the_middle_two():
    assert median([D("1"), D("2"), D("3"), D("4")]) == D("2.5")
    assert median([D("1"), D("2"), D("3")]) == D("2")
    assert median([]) is None


def test_median_is_decimal_not_float():
    """حساب `Decimal` خالص — لا يتسرّب `float` إلى رقم يُخطَّط عليه."""
    result = median([D("0.6"), D("0.7")])
    assert isinstance(result, Decimal)
    assert result == D("0.65")


def test_summarise_reports_all_five_statistics():
    samples = [
        build_sample(
            instrument_from(snapshot_body(bid=1.08540, offer=1.08540 + s / 10000)),
            taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC),
        )
        for s in (0.6, 1.0, 1.4, 2.0, 3.0)
    ]
    stats = summarise(samples)
    assert stats.count_accepted == 5
    assert stats.count_rejected == 0
    assert stats.minimum.quantize(D("0.1")) == D("0.6")
    assert stats.maximum.quantize(D("0.1")) == D("3.0")
    assert stats.median.quantize(D("0.1")) == D("1.4")
    payload = stats.as_dict()
    assert set(payload) >= {
        "min_pips", "median_pips", "p75_pips", "p95_pips", "max_pips"
    }


# ===========================================================================
# 2. رفض العيّنات البائتة وغير القابلة للتداول
# ===========================================================================

def test_stale_sample_is_rejected():
    body = snapshot_body(age_seconds=MAX_ACCEPTABLE_DATA_AGE_SECONDS + 30)
    sample = build_sample(
        instrument_from(body), taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC)
    )
    assert sample.accepted is False
    assert sample.reject_reason == REJECT_STALE


def test_non_tradeable_sample_is_rejected():
    for status in ("CLOSED", "EDITS_ONLY", "OFFLINE", "SUSPENDED"):
        sample = build_sample(
            instrument_from(snapshot_body(status=status)),
            taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC),
        )
        assert sample.accepted is False
        assert sample.reject_reason == REJECT_NOT_TRADEABLE


def test_missing_prices_are_rejected():
    body = snapshot_body()
    body["snapshot"]["bid"] = None
    body["snapshot"]["offer"] = None
    sample = build_sample(
        instrument_from(body), taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC)
    )
    assert sample.accepted is False
    assert sample.reject_reason == REJECT_NO_PRICES


def test_non_positive_spread_is_rejected():
    """سبريد صفر أو سالب بيانات معطوبة، لا فرصة."""
    sample = build_sample(
        instrument_from(snapshot_body(bid=1.08546, offer=1.08546)),
        taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC),
    )
    assert sample.accepted is False
    assert sample.reject_reason == REJECT_BAD_SPREAD


def test_rejected_samples_are_excluded_from_the_statistics():
    good = build_sample(
        instrument_from(snapshot_body(offer=1.08546)),
        taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC),
    )
    bad = build_sample(
        instrument_from(snapshot_body(status="CLOSED")),
        taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC),
    )
    stats = summarise([good, bad])
    assert stats.count_accepted == 1
    assert stats.count_rejected == 1


def test_a_rejected_sample_keeps_its_observed_values_for_the_record():
    """الرفض لا يعني الحذف — تبقى القيمة مرئية مع سببها."""
    sample = build_sample(
        instrument_from(snapshot_body(status="CLOSED")),
        taken_at_utc=datetime(2026, 8, 26, 12, tzinfo=UTC),
    )
    assert sample.spread_pips is not None
    assert sample.market_status == "CLOSED"


# ===========================================================================
# 3. وسم الإغلاق
# ===========================================================================

def test_friday_close_samples_are_labelled():
    """2026-08-28 جمعة. الإغلاق ≈ 21:00 UTC."""
    friday_late = datetime(2026, 8, 28, 20, 30, tzinfo=UTC)
    assert FLAG_NEAR_WEEKLY_CLOSE in close_flags(friday_late)

    friday_after = datetime(2026, 8, 28, 21, 30, tzinfo=UTC)
    assert FLAG_NEAR_WEEKLY_CLOSE in close_flags(friday_after)


def test_friday_midday_is_not_labelled_as_near_close():
    friday_noon = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    assert FLAG_NEAR_WEEKLY_CLOSE not in close_flags(friday_noon)


def test_a_wednesday_at_the_same_hour_is_not_a_weekly_close():
    """الوسم يخص **الجمعة** — لا كل يوم في الساعة نفسها."""
    wednesday = datetime(2026, 8, 26, 20, 30, tzinfo=UTC)
    flags = close_flags(wednesday)
    assert FLAG_NEAR_WEEKLY_CLOSE not in flags
    assert FLAG_NEAR_DAILY_ROLLOVER in flags     # لكنه قرب التجديد اليومي


def test_daily_rollover_is_labelled_on_any_weekday():
    assert FLAG_NEAR_DAILY_ROLLOVER in close_flags(
        datetime(2026, 8, 25, 21, 5, tzinfo=UTC)
    )
    assert FLAG_NEAR_DAILY_ROLLOVER not in close_flags(
        datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    )


def test_flagged_sample_appears_in_the_report_with_its_label():
    session, _ = sampling_session()
    run = run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime(2026, 8, 28, 20, 30, tzinfo=UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()
    text = render_spread_report(run)
    assert FLAG_NEAR_WEEKLY_CLOSE in text
    assert "عيّنات قرب الإغلاق أو التجديد" in text


def _advancing_clock(start, step_seconds=30):
    """ساعة محقونة تتقدّم بخطوة ثابتة عند كل قراءة — كالزمن الحقيقي."""
    state = {"now": start}

    def clock():
        current = state["now"]
        state["now"] = current + timedelta(seconds=step_seconds)
        return current

    return clock


def _frozen_clock(moment):
    """
    ساعة **لا تتقدّم أبداً** — لاختبار الحارس الصلب ضد الحلقة الأبدية.
    ساعة معطوبة أو تراجُع NTP يُنتجان هذا السلوك بالضبط.
    """
    return lambda: moment


# ===========================================================================
# 4. حدود الشبكة — قائمة بيضاء، جلسة واحدة، لا تعديل
# ===========================================================================

def test_sampler_sends_only_the_market_snapshot_endpoint():
    session, transport = sampling_session()
    run = run_spread_sampling(
        session, duration_minutes=2, interval_seconds=60,
        clock=_advancing_clock(datetime.now(UTC), 20),
        sleeper=lambda _s: None,
    )
    session.discard()

    after_auth = [op for op in transport.sent if op != ("GET", "/api/v1/session/encryptionKey")
                  and op != ("POST", "/api/v1/session")]
    assert after_auth, "لم تُؤخذ أي عيّنة."
    assert set(after_auth) == {("GET", f"/api/v1/markets/{SPREAD_SAMPLE_EPIC}")}
    assert run.statistics.count_accepted >= 1


def test_sampler_never_requests_account_data():
    """القياس لا يحتاج رصيداً — فلا يُطلب. هذا قيد لا تفصيل."""
    session, transport = sampling_session()
    run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()

    paths = [path for _method, path in transport.sent]
    for forbidden in ("/api/v1/accounts", "/api/v1/accounts/preferences"):
        assert forbidden not in paths


def test_sampler_sends_no_mutating_request():
    session, transport = sampling_session()
    run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()

    methods = {method for method, _ in transport.sent}
    assert methods & UNCONDITIONALLY_BLOCKED_METHODS == set()
    posts = [op for op in transport.sent if op[0] == "POST"]
    assert posts == [("POST", "/api/v1/session")]
    for _method, path in transport.sent:
        low = path.lower()
        for word in ("position", "order", "topup", "deposit", "withdraw", "confirm"):
            assert word not in low


def test_every_sampler_operation_passes_the_allowlist():
    session, transport = sampling_session()
    run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()
    for method, path in transport.sent:
        assert_allowed(method, LIVE_BASE_URL + path)     # يرفع لو مُنع


def test_only_one_authentication_per_run():
    session, transport = sampling_session()
    run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    auth_calls = [op for op in transport.sent if op == ("POST", "/api/v1/session")]
    assert len(auth_calls) == 1

    # ومحاولة ثانية مرفوضة بنيوياً، لا بالانضباط.
    with pytest.raises(LiveAuthAlreadyAttempted):
        session.authenticate()
    session.discard()


def test_sampler_refuses_an_unauthenticated_session():
    """الدالة **لا تُصادق** — إعادة المصادقة داخل حلقة أسرع طريق إلى القفل."""
    transport = MockLiveTransport(full_routes(rsa_key_b64()))
    session = LiveSession(transport=transport, secrets=secrets())
    with pytest.raises(SpreadSamplerError):
        run_spread_sampling(session, duration_minutes=1, interval_seconds=30)
    assert transport.sent == []


def test_sampler_refuses_any_epic_other_than_eurusd():
    session, _ = sampling_session()
    with pytest.raises(SpreadSamplerError):
        run_spread_sampling(
            session, duration_minutes=1, interval_seconds=30, epic="GBPUSD"
        )
    session.discard()


@pytest.mark.parametrize(
    "duration, interval", [(0, 60), (-5, 60), (30, 4), (30, 0), (30, -1)]
)
def test_sampler_rejects_impossible_parameters(duration, interval):
    session, _ = sampling_session()
    with pytest.raises(SpreadSamplerError):
        run_spread_sampling(
            session, duration_minutes=duration, interval_seconds=interval
        )
    session.discard()


# ===========================================================================
# 5. المخرَج
# ===========================================================================

def test_report_never_claims_a_single_snapshot_is_the_normal_spread():
    session, _ = sampling_session()
    run = run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()
    text = render_spread_report(run)
    assert "لا لقطة واحدة تساوي «السبريد المعتاد»" in text
    assert run.as_dict()["single_snapshot_is_not_the_normal_spread"] is True


def test_report_makes_no_profitability_claim():
    session, _ = sampling_session()
    run = run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()
    text = render_spread_report(run)
    assert "لا يدّعي ربحية" in text
    assert "لا يأذن بالتنفيذ" in text
    assert run.as_dict()["authorises_execution"] is False
    assert run.as_dict()["profitability_claim"] is None


def test_report_contains_no_account_value():
    session, _ = sampling_session()
    run = run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()
    text = render_spread_report(run)
    for forbidden in ("212.34", "210.00", "-2.34", FAKE_ACCOUNT_ID, "****6655"):
        assert forbidden not in text


def test_report_states_plainly_when_no_sample_was_accepted():
    routes = full_routes(rsa_key_b64())
    routes[("GET", f"/api/v1/markets/{SPREAD_SAMPLE_EPIC}")] = LiveResponse(
        200, {}, snapshot_body(status="CLOSED")
    )
    session, _ = sampling_session(routes)
    run = run_spread_sampling(
        session, duration_minutes=1, interval_seconds=30,
        clock=_advancing_clock(datetime.now(UTC), 10),
        sleeper=lambda _s: None,
    )
    session.discard()
    text = render_spread_report(run)
    assert run.statistics.count_accepted == 0
    assert "لا عيّنة مقبولة واحدة" in text
    assert "لن يُقدَّم رقم بديل" in text


def test_cli_spread_command_requires_the_acknowledgement(capsys):
    from app.cli import build_parser, cmd_capital_live_spread_sample

    args = build_parser().parse_args(["capital-live-spread-sample"])
    assert args.acknowledge_live_read_only is False
    assert cmd_capital_live_spread_sample(args) == 2
    assert "إقرار صريح" in capsys.readouterr().err


def test_cli_spread_command_defaults_match_the_documented_invocation():
    from app.cli import build_parser

    args = build_parser().parse_args(
        ["capital-live-spread-sample", "--acknowledge-live-read-only"]
    )
    assert args.duration_minutes == 30
    assert args.interval_seconds == 60


def test_a_frozen_clock_cannot_produce_an_endless_request_loop():
    """
    الحارس الصلب: ساعةٌ لا تتقدّم — ساعة معطوبة أو تراجُع NTP — كانت ستُبقي
    الحلقة تقصف الوسيط بلا نهاية حتى يُقفَل الحساب. الحدّ الزمني وحده لا
    يكفي حين يكون **الزمن نفسه** هو المتغيّر المشكوك فيه.
    """
    session, transport = sampling_session()
    run = run_spread_sampling(
        session, duration_minutes=30, interval_seconds=60,
        clock=_frozen_clock(datetime.now(UTC)),
        sleeper=lambda _s: None,
    )
    session.discard()

    expected_cap = int(30 * 60 // 60) + 2
    assert len(run.samples) == expected_cap
    market_calls = [
        op for op in transport.sent
        if op == ("GET", f"/api/v1/markets/{SPREAD_SAMPLE_EPIC}")
    ]
    assert len(market_calls) == expected_cap
