"""
LIVE MARKET DATA PROVIDER — أسعار حقيقية، للقراءة والبحث فقط.

يُغذّي `MarketDataProvider` من بيانات Capital.com الحقيقية لأجل:
  * الاكتشاف قراءةً فقط
  * جلب بيانات Backtest حيث يكون ذلك مناسباً
  * Shadow Mode مستقبلاً على بيانات حقيقية **بلا إرسال أي أمر**

**لا يُوصَل بأي خدمة تنفيذ.** هذا الملف لا يستورد تنفيذاً ولا موجّه أوامر،
ويستقبل جلسة قراءة فقط يفرض ناقلُها القائمة البيضاء على مستوى HTTP.
Shadow Mode يبقى عاجزاً بنيوياً عن استيراد أو استدعاء كود التنفيذ.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Sequence

from ..intelligence.providers import MarketDataProvider
from ..intelligence.snapshot import Candle, Timeframe, TimeframeSeries
from ..money import D
from .session import LiveSession

#: تحويل أطر النظام إلى دقّات Capital.com الرسمية.
RESOLUTION_BY_TIMEFRAME: dict[Timeframe, str] = {
    Timeframe.W1: "WEEK",
    Timeframe.D1: "DAY",
    Timeframe.H4: "HOUR_4",
    Timeframe.H1: "HOUR",
    Timeframe.M15: "MINUTE_15",
    Timeframe.M5: "MINUTE_5",
}


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _mid(block: Any) -> Optional[Decimal]:
    """
    شمعة Capital.com تحمل جانبَي العرض والطلب. النقطة الوسطى هي التمثيل
    المستعمل للتحليل — والسبريد يُحتسب **منفصلاً** في نموذج التكلفة،
    فلا يُحتسب مرتين.
    """
    if not isinstance(block, dict):
        return None
    bid = _dec(block.get("bid"))
    ask = _dec(block.get("ask"))
    if bid is None or ask is None:
        return bid if ask is None else ask
    return (bid + ask) / D("2")


class LiveReadOnlyMarketDataProvider(MarketDataProvider):
    """
    مزوّد بيانات سوق من الحساب الحقيقي — **قراءة فقط**.

    لا يملك ميثوداً واحداً يرسل أمراً، ولا يستورد ما يستطيع ذلك.
    """

    def __init__(self, session: LiveSession, *, name: str = "capital.com-live-readonly") -> None:
        self._session = session
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def configured(self) -> bool:
        return self._session.authenticated

    def candles(
        self, *, instrument: str, timeframe: Timeframe, count: int, as_of_utc: datetime
    ) -> TimeframeSeries:
        resolution = RESOLUTION_BY_TIMEFRAME.get(timeframe)
        if resolution is None:
            return TimeframeSeries(
                timeframe=timeframe, candles=(), source=self._name,
                retrieved_at_utc=as_of_utc, complete=False,
                note_ar=f"إطار غير مدعوم لدى الوسيط: {timeframe.value}",
            )

        try:
            response = self._session.get(
                f"/api/v1/prices/{instrument}",
                params={"resolution": resolution, "max": max(1, int(count))},
            )
        except Exception as exc:  # noqa: BLE001
            return TimeframeSeries(
                timeframe=timeframe, candles=(), source=self._name,
                retrieved_at_utc=as_of_utc, complete=False,
                note_ar=f"تعذّرت القراءة ({type(exc).__name__}).",
            )

        if not response.ok or not isinstance(response.body, dict):
            return TimeframeSeries(
                timeframe=timeframe, candles=(), source=self._name,
                retrieved_at_utc=as_of_utc, complete=False,
                note_ar=f"استجابة غير صالحة (HTTP {response.status}).",
            )

        raw = response.body.get("prices")
        candles = tuple(self._to_candles(raw if isinstance(raw, list) else []))
        return TimeframeSeries(
            timeframe=timeframe,
            candles=candles,
            source=self._name,
            retrieved_at_utc=as_of_utc,
            complete=len(candles) >= count,
            note_ar=(
                "" if len(candles) >= count
                else f"عدد الشموع {len(candles)} أقل من المطلوب {count}."
            ),
        )

    @staticmethod
    def _to_candles(rows: Sequence[Any]) -> list[Candle]:
        out: list[Candle] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            stamp = row.get("snapshotTimeUTC") or row.get("snapshotTime")
            if not isinstance(stamp, str):
                continue
            try:
                start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)

            o = _mid(row.get("openPrice"))
            h = _mid(row.get("highPrice"))
            l = _mid(row.get("lowPrice"))
            c = _mid(row.get("closePrice"))
            if None in (o, h, l, c):
                continue

            candle = Candle(
                start_utc=start, open=o, high=h, low=l, close=c,
                volume=_dec(row.get("lastTradedVolume")) or D("0"),
            )
            # الشمعة المستحيلة تُسقَط ولا تُصحَّح — التصحيح يخفي عطلاً.
            if candle.is_structurally_valid:
                out.append(candle)

        out.sort(key=lambda x: x.start_utc)
        return out


__all__ = ["LiveReadOnlyMarketDataProvider", "RESOLUTION_BY_TIMEFRAME"]
