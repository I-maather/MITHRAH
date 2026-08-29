"""
اختبارات طبقة المزوّدات.

**لا شبكة · لا Keychain · لا مفتاح حقيقي.** الناقل مُقلَّد في كل اختبار،
وكل مفتاح هنا نص وهمي مكتوب صراحةً ولا معنى له خارج هذا الملف.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.money import D
from app.providers import PROVIDER_CREDENTIALS
from app.providers.cache import ProviderCache, cache_key, deduplicate
from app.providers.classification import (
    CLASSIFICATION_POLICY_VERSION,
    classify_event,
    parse_provider_impact,
)
from app.providers.composite import (
    CompositeMacroDataProvider,
    CompositeVerifiedNewsProvider,
    OfficialRelease,
    OfficialSourceProvider,
)
from app.providers.ecb_macro import (
    ECB_REGISTRY,
    LEGACY_HOST,
    SERIES_BY_KEY as ECB_SERIES,
    EcbMacroDataProvider,
    parse_sdmx_json,
)
from app.providers.finnhub_news import (
    FORBIDDEN_FIELDS,
    PERMITTED_FIELDS,
    FinnhubForexNewsProvider,
)
from app.providers.fmp_calendar import (
    CONTRACT_VERIFIED,
    MAX_WINDOW_DAYS,
    FmpEconomicCalendarProvider,
)
from app.providers.fred_macro import (
    FRED_REGISTRY,
    SERIES_BY_ID,
    FredMacroDataProvider,
    MacroCategory,
)
from app.providers.health import ProviderHealthRegistry
from app.providers.http import (
    HttpResponse,
    ProviderHttpError,
    ProviderTransport,
    RateLimiter,
    backoff_delay,
    redact_text,
    redact_url,
)
from app.providers.probe import PROBE_ENDPOINT_AVAILABLE, probe_fmp_calendar
from app.providers.provenance import (
    Freshness,
    LicenseClass,
    build_provenance,
    raw_checksum,
    source_domain,
    to_utc,
)
from app.providers.results import (
    FAILURE_STATES,
    ProviderResult,
    ProviderResultState,
    merge_states,
)
from app.providers.verification import (
    MAY_CREATE_A_TRADE,
    DomainPolicy,
    NewsCandidate,
    VerificationLevel,
    classify_news,
)
from tests.test_private_store import make_repo

UTC = timezone.utc
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

FAKE_KEY = "fake-provider-key-000000000000"


def transport_returning(*responses: HttpResponse) -> ProviderTransport:
    """ناقل مُقلَّد يعيد استجابات مُعدّة سلفاً. **لا شبكة.**"""
    box = list(responses)

    def sender(url, headers, timeout):
        return box.pop(0) if len(box) > 1 else box[0]

    return ProviderTransport(sender=sender)


def no_wait_limiter(name: str = "test") -> RateLimiter:
    return RateLimiter(name=name, max_calls=1000, per_seconds=1.0)


# ===========================================================================
# 1. حالات النتيجة
# ===========================================================================

def test_all_nine_states_exist():
    assert {s.value for s in ProviderResultState} == {
        "FRESH", "STALE", "PARTIAL", "UNAVAILABLE", "UNAVAILABLE_PLAN",
        "AUTH_FAILED", "RATE_LIMITED", "MALFORMED", "UNKNOWN",
    }


def test_empty_records_do_not_mean_no_data_unless_fresh():
    """
    القاعدة المركزية: القائمة الفارغة **لا تعني «لا أحداث»** إلا مع `FRESH`.
    """
    for state in ProviderResultState:
        result = ProviderResult(provider="x", state=state, records=())
        assert result.means_no_data_exists is (state is ProviderResultState.FRESH)


def test_only_fresh_is_usable_for_a_decision():
    for state in ProviderResultState:
        usable = ProviderResult(provider="x", state=state).usable_for_decision
        assert usable is (state is ProviderResultState.FRESH)


def test_stale_is_not_usable_for_a_decision():
    assert not ProviderResult(
        provider="x", state=ProviderResultState.STALE, records=(1,)
    ).usable_for_decision


@pytest.mark.parametrize(
    "states, expected",
    [
        ([ProviderResultState.FRESH, ProviderResultState.FRESH], ProviderResultState.FRESH),
        ([ProviderResultState.FRESH, ProviderResultState.UNAVAILABLE], ProviderResultState.PARTIAL),
        ([ProviderResultState.FRESH, ProviderResultState.STALE], ProviderResultState.STALE),
        ([ProviderResultState.AUTH_FAILED, ProviderResultState.UNAVAILABLE],
         ProviderResultState.AUTH_FAILED),
        ([], ProviderResultState.UNAVAILABLE),
    ],
)
def test_merge_takes_the_worst(states, expected):
    """الدمج **بالأسوأ يفوز** — التفاؤل هنا يُنتج «لا أخبار» من مزوّد ساقط."""
    assert merge_states(states) is expected


# ===========================================================================
# 2. تنقية الأسرار
# ===========================================================================

def test_query_string_secrets_are_redacted():
    url = f"https://api.stlouisfed.org/fred/series?series_id=UNRATE&api_key={FAKE_KEY}"
    cleaned = redact_url(url)
    assert FAKE_KEY not in cleaned
    assert "***REDACTED***" in cleaned
    assert "series_id=UNRATE" in cleaned      # البنية تبقى للتشخيص


@pytest.mark.parametrize("param", ["api_key", "apikey", "token", "key", "secret", "password"])
def test_every_secret_parameter_name_is_redacted(param):
    assert FAKE_KEY not in redact_url(f"https://x.test/a?{param}={FAKE_KEY}")


def test_transport_records_only_redacted_urls():
    transport = transport_returning(HttpResponse(200, []))
    transport.get(f"https://x.test/a?apikey={FAKE_KEY}")
    assert all(FAKE_KEY not in u for u in transport.sent)


def test_transport_exception_does_not_leak_the_key():
    """
    استثناء `httpx` الخام يحمل العنوان كاملاً بمفتاحه. يُلتقط ويُعاد منقّى.
    """
    def exploding(url, headers, timeout):
        raise RuntimeError(f"connection failed for {url}")

    transport = ProviderTransport(sender=exploding)
    with pytest.raises(ProviderHttpError) as caught:
        transport.get(f"https://x.test/a?api_key={FAKE_KEY}", secrets=(FAKE_KEY,))
    assert FAKE_KEY not in str(caught.value)


def test_redact_text_leaves_short_tokens_alone():
    assert redact_text("ab error", ("ab",)) == "ab error"


def test_provenance_domain_drops_the_query_string():
    """النطاق وحده — سلسلة الاستعلام قد تحمل مفتاحاً."""
    assert source_domain(f"https://www.example.com/a?api_key={FAKE_KEY}") == "example.com"


# ===========================================================================
# 3. حدود المعدل والتراجع
# ===========================================================================

def test_rate_limiter_blocks_past_its_window():
    clock = {"t": 0.0}
    limiter = RateLimiter("x", max_calls=2, per_seconds=60.0, clock=lambda: clock["t"])
    assert limiter.try_acquire() and limiter.try_acquire()
    assert limiter.try_acquire() is False
    clock["t"] = 61.0
    assert limiter.try_acquire() is True


def test_backoff_grows_and_is_capped():
    delays = [backoff_delay(i, jitter=lambda: 1.0) for i in range(1, 8)]
    assert delays == sorted(delays)
    assert max(delays) <= 8.0


def test_auth_failure_is_not_retried():
    """المفتاح المرفوض لا يتغيّر بالإلحاح، والإلحاح يستهلك الحد."""
    from app.providers.http import get_with_retry

    transport = transport_returning(HttpResponse(401, {}))
    with pytest.raises(ProviderHttpError) as caught:
        get_with_retry(transport, "https://x.test/a", sleeper=lambda _s: None)
    assert caught.value.state is ProviderResultState.AUTH_FAILED
    assert len(transport.sent) == 1


def test_plan_error_402_is_not_retried():
    from app.providers.http import get_with_retry

    transport = transport_returning(HttpResponse(402, {}))
    with pytest.raises(ProviderHttpError) as caught:
        get_with_retry(transport, "https://x.test/a", sleeper=lambda _s: None)
    assert caught.value.state is ProviderResultState.UNAVAILABLE_PLAN
    assert len(transport.sent) == 1


def test_rate_limited_is_retried_then_surfaced():
    from app.providers.http import get_with_retry

    transport = transport_returning(HttpResponse(429, {}))
    with pytest.raises(ProviderHttpError) as caught:
        get_with_retry(transport, "https://x.test/a", sleeper=lambda _s: None)
    assert caught.value.state is ProviderResultState.RATE_LIMITED
    assert len(transport.sent) == 3


# ===========================================================================
# 4. سجل المصدر
# ===========================================================================

def test_provenance_carries_all_sixteen_fields():
    p = build_provenance(
        provider="P", raw={"a": 1}, source_id="s1", retrieved_at_utc=NOW,
        event_timestamp_utc=NOW, original_source="Reuters",
        original_url="https://reuters.com/x", currency="USD",
        category="INFLATION", impact="HIGH",
        license_class=LicenseClass.METADATA_ONLY, retention_days=30,
        freshness_window_seconds=600,
    )
    data = p.as_dict()
    for field in (
        "provider", "original_source", "original_url", "domain",
        "event_timestamp_utc", "retrieved_at_utc", "timezone", "currency",
        "category", "impact", "freshness", "source_id", "raw_checksum",
        "normalized_version", "license_class", "retention_days",
    ):
        assert field in data, field
    assert data["domain"] == "reuters.com"
    assert data["freshness"] == Freshness.FRESH.value


def test_checksum_is_stable_across_key_order():
    assert raw_checksum({"a": 1, "b": 2}) == raw_checksum({"b": 2, "a": 1})


def test_checksum_changes_with_the_value():
    assert raw_checksum({"a": 1}) != raw_checksum({"a": 2})


def test_naive_datetime_is_rejected_not_assumed_utc():
    """افتراض UTC خطأً يزيح خبراً ساعات فيُفتح مركز في لحظة القرار."""
    with pytest.raises(ValueError):
        to_utc(datetime(2026, 8, 28, 12, 0))


def test_only_official_licence_permits_full_text():
    for cls, allowed in (
        (LicenseClass.PUBLIC_OFFICIAL, True),
        (LicenseClass.METADATA_ONLY, False),
        (LicenseClass.DISPLAY_ONLY, False),
        (LicenseClass.UNKNOWN, False),
    ):
        p = build_provenance(
            provider="P", raw={}, source_id="s", retrieved_at_utc=NOW, license_class=cls
        )
        assert p.may_store_full_text is allowed


# ===========================================================================
# 5. تقويم FMP
# ===========================================================================

def calendar_body():
    return [
        {"date": "2026-09-01 12:30:00", "country": "US", "event": "Core CPI (YoY)",
         "currency": "USD", "previous": "3.1", "estimate": "3.0", "actual": None,
         "impact": "High"},
        {"date": "2026-09-02 11:45:00", "country": "EA", "event": "ECB Rate Decision",
         "currency": "EUR", "previous": "3.75", "estimate": "3.50", "actual": None,
         "impact": "High"},
    ]


def fmp_provider(*responses):
    return FmpEconomicCalendarProvider(
        api_key=FAKE_KEY, transport=transport_returning(*responses),
        limiter=no_wait_limiter("fmp"),
    )


def test_fmp_normalises_events():
    provider = fmp_provider(HttpResponse(200, calendar_body()))
    result = provider.fetch(
        currencies=("USD", "EUR"), window_start_utc=NOW,
        window_end_utc=NOW + timedelta(days=7), now_utc=NOW,
    )
    assert result.state is ProviderResultState.FRESH
    assert len(result.records) == 2
    names = {e.name for e in result.records}
    assert "Core CPI (YoY)" in names


def test_fmp_plan_error_in_a_200_body_is_caught():
    """
    الخطر الحقيقي: خطأ خطة يصل بحالة **200** فيبدو نجاحاً.
    """
    provider = fmp_provider(HttpResponse(200, {
        "Error Message": "Exclusive Endpoint: This endpoint is not available under your "
                         "current subscription plan.",
    }))
    result = provider.fetch(
        currencies=("USD",), window_start_utc=NOW,
        window_end_utc=NOW + timedelta(days=7), now_utc=NOW,
    )
    assert result.state is ProviderResultState.UNAVAILABLE_PLAN
    assert result.records == ()
    assert "لا يُشترى اشتراك" in result.detail_ar


def test_fmp_402_is_unavailable_plan():
    provider = fmp_provider(HttpResponse(402, {}))
    result = provider.fetch(
        currencies=("USD",), window_start_utc=NOW,
        window_end_utc=NOW + timedelta(days=1), now_utc=NOW,
    )
    assert result.state is ProviderResultState.UNAVAILABLE_PLAN


def test_fmp_unexpected_shape_is_malformed_not_empty():
    provider = fmp_provider(HttpResponse(200, {"unexpected": True}))
    result = provider.fetch(
        currencies=("USD",), window_start_utc=NOW,
        window_end_utc=NOW + timedelta(days=1), now_utc=NOW,
    )
    assert result.state is ProviderResultState.MALFORMED
    assert result.means_no_data_exists is False


def test_fmp_missing_mandatory_field_drops_the_record():
    provider = fmp_provider(HttpResponse(200, [{"country": "US"}]))
    result = provider.fetch(
        currencies=("USD",), window_start_utc=NOW,
        window_end_utc=NOW + timedelta(days=1), now_utc=NOW,
    )
    assert result.state is ProviderResultState.PARTIAL
    assert result.records == ()


def test_fmp_unconfigured_is_unavailable_not_empty():
    provider = FmpEconomicCalendarProvider(api_key=None)
    result = provider.fetch(
        currencies=("USD",), window_start_utc=NOW,
        window_end_utc=NOW + timedelta(days=1), now_utc=NOW,
    )
    assert result.state is ProviderResultState.UNAVAILABLE
    assert result.error_code == "NOT_CONFIGURED"


def test_fmp_contract_is_declared_unverified():
    """الصدق في الواجهة: العقد لم يُقرأ من توثيق رسمي، فيُعلَن ذلك."""
    assert CONTRACT_VERIFIED is False


def test_fmp_rejects_a_window_wider_than_the_documented_maximum():
    provider = fmp_provider(HttpResponse(200, []))
    result = provider.fetch(
        currencies=("USD",), window_start_utc=NOW,
        window_end_utc=NOW + timedelta(days=MAX_WINDOW_DAYS + 1), now_utc=NOW,
    )
    assert result.error_code == "WINDOW_TOO_WIDE"


def test_probe_distinguishes_five_outcomes():
    cases = [
        (HttpResponse(200, calendar_body()), PROBE_ENDPOINT_AVAILABLE),
        (HttpResponse(401, {}), "AUTH_FAILED"),
        (HttpResponse(402, {}), "UNAVAILABLE_PLAN"),
        (HttpResponse(200, {"unexpected": 1}), "MALFORMED"),
    ]
    for response, expected in cases:
        outcome = probe_fmp_calendar(fmp_provider(response), now_utc=NOW)
        assert outcome.verdict == expected, response


# ===========================================================================
# 6. سياسة التصنيف
# ===========================================================================

@pytest.mark.parametrize("name", [
    "Core CPI (YoY)", "Non-Farm Payrolls", "FOMC Rate Decision",
    "ECB Press Conference", "Unemployment Rate", "GDP Growth Rate",
    "Retail Sales", "Core PCE Price Index", "Services PMI",
])
def test_high_impact_names_are_classified_high(name):
    assert classify_event(name).impact.value == "HIGH"


def test_stricter_of_provider_and_policy_wins():
    """المزوّد يقول HIGH لحدث لا تعرفه سياستنا ⇒ **HIGH**."""
    c = classify_event("Some Obscure Index", provider_impact="High")
    assert c.impact.value == "HIGH"
    assert c.policy_impact.value == "LOW"


def test_provider_cannot_weaken_the_policy():
    """المزوّد يقول Low لقرار الفائدة ⇒ يبقى **HIGH**."""
    c = classify_event("FOMC Rate Decision", provider_impact="Low")
    assert c.impact.value == "HIGH"


def test_unknown_provider_impact_is_unknown_not_low():
    assert parse_provider_impact("???").value == "UNKNOWN"
    assert parse_provider_impact(None).value == "UNKNOWN"


def test_classification_carries_its_policy_version():
    assert classify_event("CPI").policy_version == CLASSIFICATION_POLICY_VERSION


# ===========================================================================
# 7. أخبار Finnhub
# ===========================================================================

def news_body():
    return [
        {"category": "forex", "datetime": int(NOW.timestamp()), "headline":
         "ECB raises rates by 25bp", "id": 101, "image": "https://x/y.png",
         "related": "EUR,USD", "source": "Reuters", "summary": "…",
         "url": "https://reuters.com/a"},
    ]


def finnhub_provider(*responses):
    return FinnhubForexNewsProvider(
        api_key=FAKE_KEY, transport=transport_returning(*responses),
        limiter=no_wait_limiter("finnhub"),
    )


def test_finnhub_normalises_and_marks_unverified():
    result = finnhub_provider(HttpResponse(200, news_body())).fetch(now_utc=NOW)
    assert result.state is ProviderResultState.FRESH
    item = result.records[0]
    assert item.verification.value == "UNVERIFIED"
    assert "EUR" in item.currencies and "USD" in item.currencies


def test_finnhub_never_stores_article_body():
    """
    حقول المحتوى الكامل **لا تُقرأ أصلاً** — لا تُقرأ ثم تُحذف.
    """
    body = news_body()
    body[0]["content"] = "FULL ARTICLE TEXT THAT MUST NOT BE STORED"
    result = finnhub_provider(HttpResponse(200, body)).fetch(now_utc=NOW)
    blob = json.dumps(result.records[0].as_dict(), ensure_ascii=False, default=str)
    assert "FULL ARTICLE TEXT" not in blob
    for field in FORBIDDEN_FIELDS:
        assert field not in PERMITTED_FIELDS


def test_finnhub_module_never_calls_the_premium_calendar():
    source = Path("app/providers/finnhub_news.py").read_text(encoding="utf-8")
    code_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith("#") and "calendar/economic" not in line
        or "**لا يُستعمل**" in line
    ]
    assert "/calendar/economic" not in "\n".join(
        line for line in source.splitlines() if "GET" in line or "url" in line.lower()
    )


def test_finnhub_bad_shape_is_malformed():
    result = finnhub_provider(HttpResponse(200, {"nope": 1})).fetch(now_utc=NOW)
    assert result.state is ProviderResultState.MALFORMED


# ===========================================================================
# 8. التحقق من الأخبار
# ===========================================================================

def candidate(headline, domain, *, minutes=0, source=None, raw=None):
    return NewsCandidate(
        headline=headline,
        provenance=build_provenance(
            provider="P", raw=raw if raw is not None else headline,
            source_id=f"{domain}:{headline}", retrieved_at_utc=NOW,
            event_timestamp_utc=NOW + timedelta(minutes=minutes),
            original_source=source, original_url=f"https://{domain}/a",
        ),
    )


def test_no_verification_level_can_create_a_trade():
    """الثابت فارغ **بالتصميم** — ويُختبَر أنه فارغ."""
    assert MAY_CREATE_A_TRADE == frozenset()
    for level in VerificationLevel:
        outcome = classify_news(candidate("x", "unknown.test"), [])
        assert outcome.may_create_trade is False


def test_official_domain_is_official_primary():
    outcome = classify_news(
        candidate("Fed raises rates", "federalreserve.gov"), []
    )
    assert outcome.level is VerificationLevel.OFFICIAL_PRIMARY


def test_aggregator_alone_is_aggregated_unverified():
    outcome = classify_news(candidate("ECB raises rates", "finnhub.io"), [])
    assert outcome.level is VerificationLevel.AGGREGATED_UNVERIFIED
    assert outcome.may_lift_block is False


def test_two_independent_domains_give_multi_source_verified():
    a = candidate("ECB raises rates by 25bp", "reuters.test", minutes=0)
    b = candidate("ECB raises rates by 25 basis points", "bloomberg.test", minutes=5)
    outcome = classify_news(a, [a, b])
    assert outcome.level is VerificationLevel.MULTI_SOURCE_VERIFIED
    assert "bloomberg.test" in outcome.corroborating_domains


def test_contradiction_is_detected_and_beats_everything():
    a = candidate("ECB raises rates", "reuters.test")
    b = candidate("ECB cuts rates", "bloomberg.test", minutes=3)
    outcome = classify_news(a, [a, b])
    assert outcome.level is VerificationLevel.CONTRADICTED
    assert outcome.may_lift_block is False


def test_syndication_is_not_independent_corroboration():
    """
    البصمة الخام نفسها ⇒ نسخة لا تأكيد. رفعُها إلى «مؤكَّد بمصدرين» هو
    بالضبط ما يجعل خبراً واحداً يبدو خبرين.
    """
    shared = {"payload": "identical"}
    a = candidate("ECB raises rates", "siteA.test", raw=shared)
    b = candidate("ECB raises rates", "siteB.test", minutes=0, raw=shared)
    outcome = classify_news(a, [a, b])
    assert outcome.suspected_syndication is True
    assert outcome.level is not VerificationLevel.MULTI_SOURCE_VERIFIED


def test_timestamps_too_far_apart_do_not_corroborate():
    a = candidate("ECB raises rates by 25bp", "reuters.test", minutes=0)
    b = candidate("ECB raises rates by 25bp", "bloomberg.test", minutes=600)
    outcome = classify_news(a, [a, b])
    assert outcome.level is not VerificationLevel.MULTI_SOURCE_VERIFIED


def test_trusted_domains_are_configurable_not_hardcoded():
    policy = DomainPolicy(trusted_domains=frozenset({"mytrusted.test"}))
    outcome = classify_news(
        candidate("x", "mytrusted.test"), [], policy=policy
    )
    assert outcome.level is VerificationLevel.TRUSTED_SINGLE_SOURCE
    # وبلا إضافة صريحة يبقى غير موثوق.
    assert classify_news(
        candidate("x", "mytrusted.test"), [], policy=DomainPolicy()
    ).level is VerificationLevel.UNVERIFIED


def test_composite_news_marks_everything_as_non_trade_creating():
    finnhub = finnhub_provider(HttpResponse(200, news_body()))
    composite = CompositeVerifiedNewsProvider(sources=(finnhub,))
    result = composite.fetch(now_utc=NOW)
    assert result.records
    for record in result.records:
        assert record.may_create_trade is False


def test_composite_with_a_failing_source_is_not_fresh():
    """مصدر ساقط ⇒ **ليس** «لا أخبار»."""
    class Broken:
        name = "Broken"
        configured = True

        def candidates(self, **_):
            raise RuntimeError("down")

    composite = CompositeVerifiedNewsProvider(
        sources=(finnhub_provider(HttpResponse(200, news_body())), Broken())
    )
    result = composite.fetch(now_utc=NOW)
    assert result.state is not ProviderResultState.FRESH
    assert "Broken" in result.missing


def test_official_provider_rejects_a_non_official_domain():
    provider = OfficialSourceProvider(releases=(
        OfficialRelease("x", "randomblog.test", "https://randomblog.test/a", NOW),
    ))
    assert provider.candidates(now_utc=NOW) == ()


# ===========================================================================
# 9. FRED
# ===========================================================================

def fred_provider(*responses):
    return FredMacroDataProvider(
        api_key=FAKE_KEY, transport=transport_returning(*responses),
        limiter=no_wait_limiter("fred"),
    )


def test_fred_registry_covers_the_required_categories():
    assert set(FRED_REGISTRY) == set(MacroCategory)
    for spec in FRED_REGISTRY.values():
        assert spec.official_title and spec.frequency and spec.units
        assert spec.release_source and spec.transformation
        assert spec.validated is False        # لا شيء «مُتحقَّق» قبل الفحص الحيّ


def test_fred_unknown_series_is_refused_not_guessed():
    result = fred_provider(HttpResponse(200, {})).validate_series("MADE_UP", now_utc=NOW)
    assert result.error_code == "UNKNOWN_SERIES"


def test_fred_validation_matches_official_metadata():
    spec = SERIES_BY_ID["UNRATE"]
    provider = fred_provider(HttpResponse(200, {"seriess": [{
        "id": "UNRATE", "title": spec.official_title, "frequency": spec.frequency,
        "units": spec.units, "seasonal_adjustment": spec.seasonal_adjustment,
    }]}))
    result = provider.validate_series("UNRATE", now_utc=NOW)
    assert result.state is ProviderResultState.FRESH
    assert provider.is_validated("UNRATE")


def test_fred_metadata_mismatch_is_not_silently_accepted():
    """سلسلة غيّرت وحدتها قد تكون سلسلة أخرى — لا تُقبل صامتة."""
    provider = fred_provider(HttpResponse(200, {"seriess": [{
        "id": "UNRATE", "title": "Something Else", "frequency": "Daily",
        "units": "Index", "seasonal_adjustment": "Not Seasonally Adjusted",
    }]}))
    result = provider.validate_series("UNRATE", now_utc=NOW)
    assert result.state is ProviderResultState.MALFORMED
    assert result.error_code == "METADATA_MISMATCH"
    assert not provider.is_validated("UNRATE")


def test_fred_observations_refused_before_validation():
    provider = fred_provider(HttpResponse(200, {"observations": []}))
    result = provider.observations("UNRATE", now_utc=NOW)
    assert result.error_code == "SERIES_NOT_VALIDATED"


def test_fred_documented_error_shape_is_recognised():
    provider = fred_provider(HttpResponse(200, {
        "error_code": 400, "error_message": "Bad Request. The series does not exist.",
    }))
    result = provider.validate_series("UNRATE", now_utc=NOW)
    assert result.state is ProviderResultState.MALFORMED


def test_fred_missing_value_dot_is_skipped_not_read_as_zero():
    """FRED يكتب «.» للقيمة الغائبة. قراءتها صفراً تُفسد كل حساب."""
    spec = SERIES_BY_ID["UNRATE"]
    provider = fred_provider(
        HttpResponse(200, {"seriess": [{
            "id": "UNRATE", "title": spec.official_title, "frequency": spec.frequency,
            "units": spec.units, "seasonal_adjustment": spec.seasonal_adjustment,
        }]}),
        HttpResponse(200, {"observations": [
            {"date": "2026-08-01", "value": "."},
            {"date": "2026-07-01", "value": "4.1"},
        ]}),
    )
    provider.validate_series("UNRATE", now_utc=NOW)
    result = provider.observations("UNRATE", now_utc=NOW)
    values = [r["value"] for r in result.records]
    assert values == ["4.1"]


# ===========================================================================
# 10. ECB
# ===========================================================================

def sdmx_body():
    return {
        "header": {"id": "x"},
        "dataSets": [{"series": {"0:0:0": {"observations": {"0": [3.75], "1": [4.0]}}}}],
        "structure": {"dimensions": {"observation": [
            {"id": "TIME_PERIOD", "values": [{"id": "2026-07"}, {"id": "2026-08"}]}
        ]}},
    }


def ecb_provider(*responses):
    return EcbMacroDataProvider(
        transport=transport_returning(*responses), limiter=no_wait_limiter("ecb")
    )


def test_ecb_requires_no_api_key():
    from app.providers.ecb_macro import CREDENTIAL_NAME

    assert CREDENTIAL_NAME is None
    assert EcbMacroDataProvider().configured is True


def test_ecb_uses_the_current_host_not_the_legacy_one():
    from app.providers.ecb_macro import BASE_URL

    assert BASE_URL == "https://data-api.ecb.europa.eu"
    assert LEGACY_HOST not in BASE_URL


def test_ecb_unknown_key_fails_closed():
    result = ecb_provider(HttpResponse(200, sdmx_body())).observations(
        "ICP.M.U2.N.INVENTED.9.XX", now_utc=NOW
    )
    assert result.error_code == "UNKNOWN_SERIES_KEY"
    assert "لا تُخمَّن" in result.detail_ar


def test_ecb_sdmx_parsing_maps_periods_by_position():
    parsed = parse_sdmx_json(sdmx_body())
    assert parsed == [("2026-07", D("3.75")), ("2026-08", D("4.0"))]


def test_ecb_malformed_sdmx_returns_none():
    for bad in ({}, {"dataSets": []}, {"dataSets": [{}], "structure": {}}, "text"):
        assert parse_sdmx_json(bad) is None


def test_ecb_validation_then_observations():
    provider = ecb_provider(HttpResponse(200, sdmx_body()))
    key = "ICP.M.U2.N.000000.4.ANR"
    assert provider.validate_series(key, now_utc=NOW).state is ProviderResultState.FRESH
    result = provider.observations(key, now_utc=NOW)
    assert result.state is ProviderResultState.FRESH
    assert result.records[0]["period"] == "2026-08"     # الأحدث أولاً


def test_ecb_registry_has_all_required_categories():
    from app.providers.ecb_macro import EcbCategory

    assert set(ECB_REGISTRY) == set(EcbCategory)
    for spec in ECB_REGISTRY.values():
        assert spec.dataflow and spec.key and spec.official_title
        assert spec.validated is False


# ===========================================================================
# 11. الدمج الكلي
# ===========================================================================

def test_composite_macro_never_authorises_a_trade():
    composite = CompositeMacroDataProvider()
    _result, assessment = composite.assess(now_utc=NOW)
    assert assessment.authorises_trade is False
    assert assessment.as_dict()["authorises_trade"] is False


def test_composite_macro_does_not_invent_a_bias_from_missing_data():
    composite = CompositeMacroDataProvider()
    _result, assessment = composite.assess(now_utc=NOW)
    assert assessment.usd_bias.value == "UNKNOWN"
    assert assessment.completeness == D("0")
    assert assessment.unknown_fields


# ===========================================================================
# 12. الذاكرة المؤقتة
# ===========================================================================

def test_cache_round_trip(tmp_path):
    repo = make_repo(tmp_path)
    cache = ProviderCache(repo, clock=lambda: NOW)
    key = cache_key("fred", "UNRATE")
    cache.store(key, {"v": 1}, ttl_seconds=600)
    assert cache.for_decision(key) == {"v": 1}


def test_stale_cache_is_display_only(tmp_path):
    repo = make_repo(tmp_path)
    times = {"now": NOW}
    cache = ProviderCache(repo, clock=lambda: times["now"])
    key = cache_key("x")
    cache.store(key, {"v": 1}, ttl_seconds=60)
    times["now"] = NOW + timedelta(hours=2)
    assert cache.for_decision(key) is None          # لا قرار على بائت
    payload, fresh = cache.for_display(key)
    assert payload == {"v": 1} and fresh is False   # عرض موسوم فقط


def test_cache_ignores_a_different_schema_version(tmp_path):
    repo = make_repo(tmp_path)
    ProviderCache(repo, schema_version="1.0.0", clock=lambda: NOW).store(
        cache_key("x"), {"v": 1}, ttl_seconds=600
    )
    other = ProviderCache(repo, schema_version="2.0.0", clock=lambda: NOW)
    assert other.for_decision(cache_key("x")) is None


def test_cache_lives_inside_the_private_tree(tmp_path):
    from app.providers.cache import cache_directory

    repo = make_repo(tmp_path)
    assert cache_directory(repo).relative_to(repo).parts[:2] == ("data", "private")


def test_deduplicate_keeps_first_occurrence_order():
    records = [{"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "c"}]
    out = deduplicate(records, key=lambda r: r["id"])
    assert [r["id"] for r in out] == ["a", "b", "c"]


# ===========================================================================
# 13. لوحة الصحة
# ===========================================================================

def test_health_marks_a_provider_down_after_consecutive_failures():
    registry = ProviderHealthRegistry(clock=lambda: NOW)
    for _ in range(3):
        registry.record(
            ProviderResult(provider="P", state=ProviderResultState.UNAVAILABLE),
            operation="events",
        )
    assert registry.health("P").is_down
    assert "P" in registry.dashboard()["down"]


def test_health_recovers_after_a_success():
    registry = ProviderHealthRegistry(clock=lambda: NOW)
    for _ in range(3):
        registry.record(
            ProviderResult(provider="P", state=ProviderResultState.UNAVAILABLE),
            operation="e",
        )
    registry.record(
        ProviderResult(provider="P", state=ProviderResultState.FRESH), operation="e"
    )
    assert registry.health("P").is_down is False


# ===========================================================================
# 14. العزل — لا مزوّد ينفّذ
# ===========================================================================

PROVIDER_MODULES = sorted(Path("app/providers").glob("*.py"))
BANNED_IMPORT_TOKENS = (
    "execution", "order", "killswitch", "commissioning", "scheduler",
    "brokers.capital.adapter", "pipeline.runner",
)


@pytest.mark.parametrize("module_path", PROVIDER_MODULES, ids=lambda p: p.name)
def test_no_provider_module_imports_execution(module_path):
    """
    فحص AST لا بحث نصّي: ذكر «order» في تعليق شرحي لا يُسقط الاختبار،
    واستيرادٌ فعلي يُسقطه.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    for name in imported:
        low = name.lower()
        for banned in BANNED_IMPORT_TOKENS:
            assert banned not in low, f"{module_path.name} يستورد {name}"


@pytest.mark.parametrize("module_path", PROVIDER_MODULES, ids=lambda p: p.name)
def test_no_provider_defines_an_execution_function(module_path):
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    banned = {
        "place_order", "close_position", "update_position", "submit_order",
        "create_order", "set_leverage", "update_preferences", "top_up",
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in banned, f"{module_path.name}: {node.name}"


def test_provider_credentials_are_named_not_valued():
    assert PROVIDER_CREDENTIALS == ("FMP_API_KEY", "FINNHUB_API_KEY", "FRED_API_KEY")


def test_no_provider_module_contains_a_capital_host():
    for path in PROVIDER_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "api-capital" not in text
        assert "demo-api-capital" not in text
