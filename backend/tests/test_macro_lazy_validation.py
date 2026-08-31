"""
حارسٌ على مزوّدي الكلّيات: التحقّق يقع، والزمنان لا يُخلطان.

## العطلان اللذان أنتجا هذا الملف

**الأول — حارسٌ ميّت بلا شكوى.** كلا المزوّدين يشترط `validate_series`
قبل قراءة أي ملاحظة، ولم يكن في النظام كلّه سطرٌ واحد يستدعيه. فكان كل
مفتاح يعود `UNKNOWN` إلى الأبد، والسبب المكتوب «المفتاح لم يُتحقَّق منه» —
جملةٌ صحيحة تصف عطلاً دائماً، ولا أحد يقرأها.

**الثاني — زمنٌ واحد مكان زمنين.** بُنيت `Sourced` بوسيطٍ مخترع
`observed_at_utc` يجمع لحظة الرصد ووقت الجلب. ودمجُهما ليس تبسيطاً بل عطلٌ
في الأمان: `age_seconds` تُحسب من لحظة الرصد، فلو حملت وقت الجلب لقال
النظام إن سعر فائدةٍ نُشر قبل ثلاثة أشهر عمرُه ثوانٍ.

ولا شبكة هنا: الملاحظات والتحقّق مُقلَّدان.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.intelligence.snapshot import SourceReliability
from app.providers.ecb_macro import EcbMacroDataProvider
from app.providers.fred_macro import FredMacroDataProvider
from app.providers.period import period_to_utc
from app.providers.results import ProviderResult, ProviderResultState

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def fresh(records) -> ProviderResult:
    return ProviderResult(
        provider="fake", state=ProviderResultState.FRESH,
        records=tuple(records), retrieved_at_utc=NOW,
    )


def wire(provider, key: str, record: dict):
    """يُقلّد التحقّق والملاحظات، ويعدّ نداءات التحقّق."""
    calls = {"validate": 0}

    def validate_series(series_key, *, now_utc=None):
        calls["validate"] += 1
        provider._validated.add(series_key)
        return fresh([record])

    def observations(series_key, **kwargs):
        if series_key not in provider._validated:
            return ProviderResult(
                provider="fake", state=ProviderResultState.MALFORMED,
                retrieved_at_utc=NOW, error_code="UNVALIDATED",
                detail_ar="المفتاح لم يُتحقَّق منه.",
            )
        return fresh([record])

    provider.validate_series = validate_series  # type: ignore[assignment]
    provider.observations = observations        # type: ignore[assignment]
    return calls


PROVIDERS = [
    pytest.param(
        lambda: EcbMacroDataProvider(),
        "FM.D.U2.EUR.4F.KR.DFR.LEV",
        {"period": "2026-07", "value": "2.15"},
        id="ecb",
    ),
    pytest.param(
        lambda: FredMacroDataProvider(api_key="k" * 32),
        "DGS10",
        {"date": "2026-07-31", "value": "4.28"},
        id="fred",
    ),
]


@pytest.mark.parametrize("build,key,record", PROVIDERS)
def test_series_validates_a_key_it_has_not_validated_yet(build, key, record):
    """**العطل الأول.** بلا هذا النداء يبقى كل مفتاح `UNKNOWN` إلى الأبد."""
    provider = build()
    calls = wire(provider, key, record)

    out = provider.series(keys=[key], as_of_utc=NOW)

    assert calls["validate"] == 1
    assert out[key].known is True


@pytest.mark.parametrize("build,key,record", PROVIDERS)
def test_a_validated_key_is_not_revalidated_on_every_call(build, key, record):
    """
    التحقّق نداءٌ شبكيّ. إعادته في كل دورة تقييم تضاعف الطلبات بلا فائدة
    وتصطدم بحدود المزوّد.
    """
    provider = build()
    calls = wire(provider, key, record)

    provider.series(keys=[key], as_of_utc=NOW)
    provider.series(keys=[key], as_of_utc=NOW)

    assert calls["validate"] == 1


@pytest.mark.parametrize("build,key,record", PROVIDERS)
def test_the_two_timestamps_are_distinct_and_measured(build, key, record):
    """**العطل الثاني.** لحظة الرصد من فترة السلسلة، ووقت الجلب من الساعة."""
    provider = build()
    wire(provider, key, record)

    value = provider.series(keys=[key], as_of_utc=NOW)[key]

    assert value.retrieved_at_utc == NOW
    assert value.source_timestamp_utc == period_to_utc(
        record.get("period") or record.get("date")
    )
    assert value.source_timestamp_utc != NOW
    assert value.reliability is SourceReliability.OFFICIAL_PROVIDER


@pytest.mark.parametrize("build,key,record", PROVIDERS)
def test_an_unusable_result_has_no_observation_time_at_all(build, key, record):
    """
    لا قيمة ⇒ لا لحظة رصد. ووضعُ وقت الجلب هناك يجعل «لا أعرف» تبدو
    ملاحظةً طازجة عمرُها ثوانٍ.
    """
    provider = build()
    wire(provider, key, record)
    provider.observations = lambda series_key, **kw: ProviderResult(  # type: ignore[assignment]
        provider="fake", state=ProviderResultState.MALFORMED,
        retrieved_at_utc=NOW, error_code="NO_OBSERVATIONS", detail_ar="لا ملاحظات.",
    )

    value = provider.series(keys=[key], as_of_utc=NOW)[key]

    assert value.known is False
    assert value.source_timestamp_utc is None
    assert value.retrieved_at_utc == NOW
    assert value.age_seconds(NOW) is None


@pytest.mark.parametrize("build,key,record", PROVIDERS)
def test_every_provider_declares_the_keys_it_knows(build, key, record):
    """
    المسبار الحيّ كان يسأل عن مفاتيح مخترعة (`EUR_POLICY_RATE`) فيقرأ
    الجواب الصحيح `UNKNOWN` عطلاً. فصار يسأل المزوّد عن مفاتيحه.
    """
    provider = build()
    assert key in provider.known_series_keys


# ---------------------------------------------------------------------------
# فترة السلسلة ⇐ لحظة
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("period,expected", [
    ("2026-07-31", datetime(2026, 7, 31, tzinfo=timezone.utc)),
    ("2026-07", datetime(2026, 7, 1, tzinfo=timezone.utc)),
    ("2026-Q3", datetime(2026, 7, 1, tzinfo=timezone.utc)),
    ("2026Q1", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ("2026", datetime(2026, 1, 1, tzinfo=timezone.utc)),
])
def test_period_shapes_that_are_read(period, expected):
    assert period_to_utc(period) == expected


@pytest.mark.parametrize("period", ["", "  ", "julyish", "2026-13", "2026-02-31", None, 7])
def test_a_period_that_is_not_read_is_not_guessed(period):
    """
    `None` تعني «لا أعرف العمر» — وهو الجواب الصحيح. وتخمينُ تاريخٍ هنا
    يُنتج عمراً مُختلَقاً يمرّ على حارس الطزاجة.
    """
    assert period_to_utc(period) is None
