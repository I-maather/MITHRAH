"""
Time. داخلياً UTC دائماً، وللعرض فقط Asia/Riyadh بنظام 12 ساعة.

الأخطاء الزمنية في أنظمة التداول تكلف مالاً حقيقياً، لذلك:
  * لا يوجد datetime بلا tzinfo في أي مكان في النظام.
  * التحويل للعرض يحدث في طبقة واحدة فقط (هذه).
  * جلسة السوق تُحسب بتوقيت America/New_York (يتعامل مع DST تلقائياً).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
RIYADH = ZoneInfo("Asia/Riyadh")
NEW_YORK = ZoneInfo("America/New_York")

REGULAR_SESSION_OPEN = time(9, 30)
REGULAR_SESSION_CLOSE = time(16, 0)

ARABIC_AM = "ص"
ARABIC_PM = "م"

# عطلات NYSE/NASDAQ المعروفة. تُراجَع سنوياً — انظر docs/OPERATIONS_RUNBOOK.md.
US_MARKET_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime rejected — كل الأوقات يجب أن تحمل tzinfo")
    return dt.astimezone(UTC)


def to_riyadh(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(RIYADH)


def format_riyadh(dt: datetime) -> str:
    """'2026-08-28 04:35 م' — نظام 12 ساعة بالعربية."""
    local = to_riyadh(dt)
    hour12 = local.hour % 12 or 12
    marker = ARABIC_AM if local.hour < 12 else ARABIC_PM
    return f"{local:%Y-%m-%d} {hour12:02d}:{local:%M} {marker}"


@dataclass(frozen=True)
class MarketStatus:
    is_open: bool
    is_holiday: bool
    is_weekend: bool
    session_open_utc: datetime | None
    session_close_utc: datetime | None
    minutes_since_open: int | None
    minutes_to_close: int | None
    reason_ar: str


def _session_bounds_utc(ny_date: date) -> tuple[datetime, datetime]:
    open_ny = datetime.combine(ny_date, REGULAR_SESSION_OPEN, tzinfo=NEW_YORK)
    close_ny = datetime.combine(ny_date, REGULAR_SESSION_CLOSE, tzinfo=NEW_YORK)
    return open_ny.astimezone(UTC), close_ny.astimezone(UTC)


def us_market_status(at: datetime | None = None, holidays: set[date] | None = None) -> MarketStatus:
    at = ensure_utc(at or now_utc())
    holidays = US_MARKET_HOLIDAYS_2026 if holidays is None else holidays
    ny = at.astimezone(NEW_YORK)
    d = ny.date()

    is_weekend = d.weekday() >= 5
    is_holiday = d in holidays
    if is_weekend or is_holiday:
        return MarketStatus(
            is_open=False,
            is_holiday=is_holiday,
            is_weekend=is_weekend,
            session_open_utc=None,
            session_close_utc=None,
            minutes_since_open=None,
            minutes_to_close=None,
            reason_ar="عطلة رسمية" if is_holiday else "نهاية الأسبوع",
        )

    open_utc, close_utc = _session_bounds_utc(d)
    is_open = open_utc <= at < close_utc
    since = int((at - open_utc).total_seconds() // 60)
    to_close = int((close_utc - at).total_seconds() // 60)
    return MarketStatus(
        is_open=is_open,
        is_holiday=False,
        is_weekend=False,
        session_open_utc=open_utc,
        session_close_utc=close_utc,
        minutes_since_open=since,
        minutes_to_close=to_close,
        reason_ar="الجلسة الأساسية مفتوحة" if is_open else "خارج الجلسة الأساسية",
    )


def trading_day_bounds_utc(at: datetime | None = None) -> tuple[datetime, datetime]:
    """حدود اليوم التداولي بتوقيت نيويورك، معبَّراً عنها بـUTC."""
    at = ensure_utc(at or now_utc())
    ny = at.astimezone(NEW_YORK)
    start = datetime.combine(ny.date(), time(0, 0), tzinfo=NEW_YORK)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def trading_week_bounds_utc(at: datetime | None = None) -> tuple[datetime, datetime]:
    at = ensure_utc(at or now_utc())
    ny = at.astimezone(NEW_YORK)
    monday = ny.date() - timedelta(days=ny.weekday())
    start = datetime.combine(monday, time(0, 0), tzinfo=NEW_YORK)
    return start.astimezone(UTC), (start + timedelta(days=7)).astimezone(UTC)
