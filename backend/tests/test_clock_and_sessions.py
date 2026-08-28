from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.clock import (
    format_riyadh,
    to_riyadh,
    trading_day_bounds_utc,
    trading_week_bounds_utc,
    us_market_status,
)

UTC = timezone.utc


def test_riyadh_is_utc_plus_3_all_year():
    """السعودية لا تطبق التوقيت الصيفي — الفارق ثابت +3."""
    for month in (1, 4, 7, 10):
        dt = datetime(2026, month, 15, 12, 0, tzinfo=UTC)
        assert to_riyadh(dt).utcoffset().total_seconds() == 3 * 3600


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        to_riyadh(datetime(2026, 8, 28, 12, 0))


def test_arabic_12_hour_format_pm():
    assert format_riyadh(datetime(2026, 8, 28, 13, 35, tzinfo=UTC)) == "2026-08-28 04:35 م"


def test_arabic_12_hour_format_am():
    assert format_riyadh(datetime(2026, 8, 28, 4, 5, tzinfo=UTC)) == "2026-08-28 07:05 ص"


def test_midnight_renders_as_12_am():
    assert "12:" in format_riyadh(datetime(2026, 8, 28, 21, 0, tzinfo=UTC))  # 00:00 الرياض


# --- US session, DST-aware --------------------------------------------------

def test_session_open_during_us_daylight_time():
    """في التوقيت الصيفي الأمريكي، 9:30 نيويورك = 13:30 UTC."""
    assert us_market_status(datetime(2026, 9, 15, 13, 30, tzinfo=UTC)).is_open
    assert not us_market_status(datetime(2026, 9, 15, 13, 29, tzinfo=UTC)).is_open


def test_session_open_during_us_standard_time():
    """في التوقيت الشتوي، 9:30 نيويورك = 14:30 UTC — الفارق يتغير."""
    assert us_market_status(datetime(2026, 12, 15, 14, 30, tzinfo=UTC)).is_open
    assert not us_market_status(datetime(2026, 12, 15, 13, 30, tzinfo=UTC)).is_open


def test_session_closes_at_1600_new_york():
    assert not us_market_status(datetime(2026, 9, 15, 20, 0, tzinfo=UTC)).is_open
    assert us_market_status(datetime(2026, 9, 15, 19, 59, tzinfo=UTC)).is_open


def test_weekend_is_closed():
    s = us_market_status(datetime(2026, 9, 19, 15, 0, tzinfo=UTC))  # السبت
    assert not s.is_open and s.is_weekend


def test_holiday_is_closed():
    s = us_market_status(datetime(2026, 12, 25, 15, 0, tzinfo=UTC))
    assert not s.is_open and s.is_holiday
    assert s.reason_ar == "عطلة رسمية"


def test_thanksgiving_is_a_holiday():
    assert us_market_status(datetime(2026, 11, 26, 15, 0, tzinfo=UTC)).is_holiday


def test_minutes_since_open_and_to_close():
    s = us_market_status(datetime(2026, 9, 15, 15, 0, tzinfo=UTC))
    assert s.minutes_since_open == 90
    assert s.minutes_to_close == 300


def test_trading_day_bounds_follow_new_york_not_riyadh():
    start, end = trading_day_bounds_utc(datetime(2026, 9, 15, 2, 0, tzinfo=UTC))
    # 02:00 UTC يوم 15 = 22:00 نيويورك يوم 14 => اليوم التداولي هو 14
    assert start.astimezone(UTC).date() == date(2026, 9, 14)
    assert (end - start).total_seconds() == 86400


def test_trading_week_starts_monday():
    start, end = trading_week_bounds_utc(datetime(2026, 9, 17, 15, 0, tzinfo=UTC))  # خميس
    assert (end - start).days == 7
