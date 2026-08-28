"""
Market data gate — بوابة البيانات.

قاعدة: لا قرار تداول على بيانات لا نعرف عمرها ومصدرها.
البحث في الويب ليس مصدر أسعار تنفيذ ولا يُستدعى من هنا إطلاقاً.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..clock import now_utc
from ..contracts import DataSource, Quote
from ..money import D, safe_div
from ..risk.constitution import MAX_DATA_STALENESS_SECONDS, MAX_SPREAD_PCT_OF_PRICE


class DataVerdict(str, Enum):
    OK = "OK"
    MISSING = "MISSING"
    STALE = "STALE"
    NOT_REALTIME = "NOT_REALTIME"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    CROSSED_MARKET = "CROSSED_MARKET"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"


@dataclass(frozen=True)
class DataQuality:
    verdict: DataVerdict
    reason_ar: str
    age_seconds: Optional[float]
    spread_pct: Optional[Decimal]
    source: Optional[DataSource]
    checked_at_utc: datetime

    @property
    def tradable(self) -> bool:
        return self.verdict is DataVerdict.OK


def assess_quote(
    quote: Optional[Quote],
    *,
    now: datetime | None = None,
    require_realtime: bool = True,
    max_age_seconds: int = MAX_DATA_STALENESS_SECONDS,
    max_spread_pct: Decimal = MAX_SPREAD_PCT_OF_PRICE,
) -> DataQuality:
    now = now or now_utc()

    if quote is None:
        return DataQuality(DataVerdict.MISSING, "لا توجد بيانات سوق للرمز.", None, None, None, now)

    if quote.bid <= 0 or quote.ask <= 0 or quote.last <= 0:
        return DataQuality(
            DataVerdict.NON_POSITIVE_PRICE, "سعر غير صالح (صفر أو سالب).", None, None, quote.source, now
        )

    age = quote.age_seconds(now)
    if age < -5:
        return DataQuality(
            DataVerdict.FUTURE_TIMESTAMP,
            f"طابع زمني في المستقبل بمقدار {abs(age):.0f} ثانية — خلل ساعة.",
            age, None, quote.source, now,
        )

    if require_realtime and quote.source not in (DataSource.REALTIME, DataSource.SNAPSHOT, DataSource.MOCK):
        return DataQuality(
            DataVerdict.NOT_REALTIME,
            f"مصدر البيانات {quote.source.value} وليس فورياً — ممنوع اتخاذ قرار تنفيذ عليه.",
            age, None, quote.source, now,
        )

    if age > max_age_seconds:
        return DataQuality(
            DataVerdict.STALE,
            f"عمر البيانات {age:.0f} ثانية يتجاوز الحد {max_age_seconds} ثانية.",
            age, None, quote.source, now,
        )

    if quote.ask < quote.bid:
        return DataQuality(
            DataVerdict.CROSSED_MARKET, "سوق متقاطع: الطلب أقل من العرض.", age, None, quote.source, now
        )

    spread_pct = safe_div(quote.spread, quote.mid, D("1"))
    if spread_pct > max_spread_pct:
        return DataQuality(
            DataVerdict.SPREAD_TOO_WIDE,
            f"السبريد {spread_pct * 100:.3f}% يتجاوز الحد {max_spread_pct * 100:.3f}%.",
            age, spread_pct, quote.source, now,
        )

    return DataQuality(DataVerdict.OK, "البيانات فورية وحديثة والسبريد ضمن الحد.", age, spread_pct, quote.source, now)
