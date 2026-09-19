"""التقويم لا يجوز أن يصنعَ حجبَه ثمّ يُطيله.

## العطل الذي وُلد هذا الملف منه

١٩ سبتمبر ٢٠٢٦، ١١:٣٤ UTC: أُعيد تشغيل الخدمة، فجُلب التقويم لحظةَ
الإقلاع فأعاد المضيف `429` — ومعناها «سألتَ أكثر مما ينبغي»، لا «مُنعت».
فبقيت بوابةُ الأخبار تقول «غير مؤكد» في كل دورةِ قرارٍ لكل أداة، لأنّ
المحاولةَ التالية كانت مجدولةً بعد **ساعة**.

وأسوأُ منه: `MIN_REFRESH_INTERVAL` يحرسُ النجاحَ وحده، و`events()` تنادي
`refresh()` عند كل استعلامٍ ما لم يكن التقويمُ مُعدّاً. فكلُّ نداءٍ كان
نداءً شبكياً جديداً على مضيفٍ يعاقبُ الإلحاح: النظامُ يصنعُ الحجبَ الذي
يُعطّله، ثمّ يُبقيه.

والسوقُ كان مغلقاً ذلك اليوم (سبت) فلم تُكلّفنا العلّةُ صفقة. ولو وقعت
عند فتحة الأحد ٢١:٠٠ UTC لأخذت الساعةَ الأولى من الأسبوع.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import app.providers.faireconomy_calendar as cal
from app.runtime.heartbeat import CALENDAR_REFRESH_SECONDS

AT_THE_INCIDENT = datetime(2026, 9, 19, 11, 34, tzinfo=timezone.utc)


class _Response:
    """أقلُّ ما يقرأه المزوّد من استجابة النقل: الرمزُ والجسد."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body


class _CountingTransport:
    """نقلٌ يعدُّ النداءات الشبكية — وهي بالضبط ما يقيسه هذا الملف."""

    def __init__(self, *responses: _Response) -> None:
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, headers=None):  # noqa: ANN001, ARG002
        self.calls += 1
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw) -> None:
        self.at += timedelta(**kw)


def _plausible_feed(count: int = 12) -> str:
    """تغذيةٌ فوق `MIN_PLAUSIBLE_EVENTS` كي تُقبل."""
    base = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    return json.dumps([
        {
            "title": f"Scheduled Release {i}",
            "country": "USD",
            "date": (base + timedelta(hours=i)).isoformat(),
            "impact": "High",
        }
        for i in range(count)
    ])


def _provider(monkeypatch, transport):
    clock = _Clock(AT_THE_INCIDENT)
    monkeypatch.setattr(cal, "now_utc", clock)
    return cal.FairEconomyCalendarProvider(transport=transport), clock


# ── ١ · الإلحاح بعد الرفض ────────────────────────────────────────────

def test_a_refused_fetch_is_not_retried_within_five_minutes(monkeypatch):
    transport = _CountingTransport(_Response(429, "Too Many Requests"))
    provider, clock = _provider(monkeypatch, transport)

    provider.refresh()
    assert transport.calls == 1
    assert not provider.configured

    clock.advance(minutes=4)
    provider.refresh()
    assert transport.calls == 1, "الإلحاحُ على مضيفٍ ردَّ 429 هو ما صنع الحجب"


def test_events_does_not_hammer_the_host_while_unconfigured(monkeypatch):
    """المسارُ الذي صنع العطل فعلاً: استعلامٌ يجلب عند كل نداء."""
    transport = _CountingTransport(_Response(429, ""))
    provider, _ = _provider(monkeypatch, transport)

    window_start = AT_THE_INCIDENT - timedelta(hours=12)
    window_end = AT_THE_INCIDENT + timedelta(hours=36)
    for _ in range(6):
        assert provider.events(
            currencies=("USD",),
            window_start_utc=window_start,
            window_end_utc=window_end,
        ) == ()
    assert transport.calls == 1


# ── ٢ · التعافي في خمس دقائق لا ستّين ────────────────────────────────

def test_the_gate_recovers_five_minutes_later_not_an_hour(monkeypatch):
    transport = _CountingTransport(
        _Response(429, ""), _Response(200, _plausible_feed())
    )
    provider, clock = _provider(monkeypatch, transport)

    provider.refresh()
    assert not provider.configured

    clock.advance(minutes=6)
    provider.refresh()
    assert transport.calls == 2
    assert provider.configured, "بعد انقضاء الإمهال يجب أن يتعافى وحده"


def test_the_job_ticks_often_enough_to_use_that_window():
    """الثابتان مربوطان: مجدولٌ أبطأُ من الإمهال يُهدر التعافي."""
    assert CALENDAR_REFRESH_SECONDS <= cal.MIN_RETRY_AFTER_FAILURE.total_seconds()


# ── ٣ · ما لم يتغيّر ─────────────────────────────────────────────────

def test_a_successful_feed_is_still_not_refetched_within_twenty_minutes(monkeypatch):
    transport = _CountingTransport(_Response(200, _plausible_feed()))
    provider, clock = _provider(monkeypatch, transport)

    provider.refresh()
    assert provider.configured
    assert transport.calls == 1

    # بعد الإمهال وقبل فاصل النجاح — لا يجوز نداءٌ جديد.
    clock.advance(minutes=6)
    provider.refresh()
    assert transport.calls == 1


def test_force_is_for_the_probe_and_ignores_both_waits(monkeypatch):
    transport = _CountingTransport(_Response(429, ""))
    provider, _ = _provider(monkeypatch, transport)

    provider.refresh()
    provider.refresh(force=True)
    assert transport.calls == 2
