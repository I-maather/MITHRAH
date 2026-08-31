"""
DATA PROVIDER ARCHITECTURE — واجهات المزوّدين، محايدة تجاه الوسيط.

Capital.com يبقى **المرجع الوحيد** لِـ:
  السعر القابل للتنفيذ (bid/ask) · السبريد · حالة التداول · قواعد الأداة ·
  ساعات السوق · مراكز الوسيط · أوامر الوسيط · تأكيدات الوسيط.

كل ما عداه يأتي عبر واجهات مجرّدة:
  EconomicCalendarProvider · MacroDataProvider · VerifiedNewsProvider ·
  MarketDataProvider · FundamentalContextProvider

قاعدتان صارمتان:

1. **لا كشط صفحات ويب عشوائية** كمصدر حقيقة في الإنتاج.
2. **لا اختراع مفتاح API ولا مزوّد.** المزوّد غير المُعدّ يبقى غير مُعدّ،
   ويظهر باسمه الدقيق في التقرير.

عند غياب مزوّد:
  · التحليل المعتمد عليه يُوسَم `UNKNOWN`
  · الأهلية للتداول الحقيقي تسقط إن كان الحقل إلزامياً
  · يُعرض اسم المزوّد الناقص بالضبط
  · يُسمح بالاستمرار في وضع البحث فقط، وحيث يكون ذلك آمناً
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Sequence

from .snapshot import (
    UNKNOWN,
    Candle,
    EconomicEvent,
    NewsItem,
    Sourced,
    SourceReliability,
    Timeframe,
    TimeframeSeries,
)


class ProviderKind(str, Enum):
    ECONOMIC_CALENDAR = "EconomicCalendarProvider"
    MACRO_DATA = "MacroDataProvider"
    VERIFIED_NEWS = "VerifiedNewsProvider"
    MARKET_DATA = "MarketDataProvider"
    FUNDAMENTAL_CONTEXT = "FundamentalContextProvider"


#: المزوّدون الإلزاميون لأهلية التداول الحقيقي.
#: غياب أي منهم ⇒ لا أهلية، مهما كان باقي التحليل ممتازاً.
MANDATORY_FOR_LIVE: frozenset[ProviderKind] = frozenset({
    ProviderKind.ECONOMIC_CALENDAR,
    ProviderKind.VERIFIED_NEWS,
    ProviderKind.MARKET_DATA,
    ProviderKind.MACRO_DATA,
})


class ProviderNotConfigured(RuntimeError):
    """
    يُرفع فقط عند محاولة **إجبار** مزوّد غير مُعدّ على إعطاء قيمة.
    المسار الطبيعي لا يرفع: يعيد `UNKNOWN` ويُسجِّل النقص.
    """

    def __init__(self, kind: ProviderKind) -> None:
        super().__init__(
            f"المزوّد {kind.value} غير مُعدّ. لا يُخترع مزوّد ولا مفتاح — "
            "يُسجَّل النقص وتسقط الأهلية للتداول الحقيقي."
        )
        self.kind = kind


@dataclass(frozen=True)
class ProviderStatus:
    kind: ProviderKind
    configured: bool
    name: str
    note_ar: str

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "configured": self.configured,
            "name": self.name,
            "note_ar": self.note_ar,
        }


class DataProvider(ABC):
    """أب مشترك: كل مزوّد يعلن نوعه وهل هو مُعدّ فعلاً."""

    kind: ProviderKind

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            kind=self.kind,
            configured=self.configured,
            name=self.name,
            note_ar=("مُعدّ." if self.configured else "غير مُعدّ — التحليل المرتبط به UNKNOWN."),
        )


# ---------------------------------------------------------------------------
# الواجهات
# ---------------------------------------------------------------------------

class EconomicCalendarProvider(DataProvider):
    kind = ProviderKind.ECONOMIC_CALENDAR

    @abstractmethod
    def events(
        self, *, currencies: Sequence[str], window_start_utc: datetime, window_end_utc: datetime
    ) -> tuple[EconomicEvent, ...]:
        """الأحداث المجدولة والصادرة ضمن النافذة. لا تُبرمَج نتائج في الكود."""


class MacroDataProvider(DataProvider):
    kind = ProviderKind.MACRO_DATA

    @abstractmethod
    def series(self, *, keys: Sequence[str], as_of_utc: datetime) -> dict[str, Sourced[Any]]:
        """سلاسل كلية (تضخم، بطالة، عوائد سندات...). المفقود يعود `UNKNOWN`."""

    @property
    def known_series_keys(self) -> tuple[str, ...]:
        """
        المفاتيح التي يعرفها هذا المزوّد بأسمائها عنده.

        وُجدت لأن المسبار الحيّ كان يسأل عن مفاتيح **مخترعة**
        (`EUR_POLICY_RATE`) فيعيد المزوّد `UNKNOWN` بحقّ، ويقرأها المسبار
        «صفر من سلسلتين» — أي عطلٌ مُعلَن عن مزوّد سليم. والمفاتيح هنا
        أصلية عند مصدرها (`DGS10` لدى FRED، ومفتاح SDMX كامل لدى ECB) ولا
        تُترجَم إلى أسماء عامة: الترجمة طبقةٌ أخرى، واختراعها هنا يعيد
        العطل نفسه بثوبٍ ألطف.
        """
        return ()


class VerifiedNewsProvider(DataProvider):
    kind = ProviderKind.VERIFIED_NEWS

    @abstractmethod
    def news(
        self, *, currencies: Sequence[str], since_utc: datetime, now_utc: datetime
    ) -> tuple[NewsItem, ...]:
        """أخبار مع حالة تحقق صريحة. غير المُتحقَّق منه لا يُنشئ صفقة أبداً."""


class MarketDataProvider(DataProvider):
    kind = ProviderKind.MARKET_DATA

    @abstractmethod
    def candles(
        self, *, instrument: str, timeframe: Timeframe, count: int, as_of_utc: datetime
    ) -> TimeframeSeries:
        """شموع مكتملة ومرتبة تصاعدياً بلا فجوات."""


class FundamentalContextProvider(DataProvider):
    kind = ProviderKind.FUNDAMENTAL_CONTEXT

    @abstractmethod
    def context(self, *, base: str, quote: str, as_of_utc: datetime) -> dict[str, Sourced[Any]]:
        """موقف السياسة النقدية، فرق الفائدة، اتجاه التضخم، risk-on/off..."""


# ---------------------------------------------------------------------------
# مزوّدون «غير مُعدّين» — السلوك الافتراضي الآمن
# ---------------------------------------------------------------------------

class _Unconfigured(DataProvider):
    """
    السلوك الافتراضي حين لا يوجد مزوّد: **لا شيء**، بصراحة ووضوح.
    لا قيمة مخمَّنة، لا قيمة افتراضية، لا كشط ويب.
    """

    def __init__(self, kind: ProviderKind) -> None:
        self.kind = kind

    @property
    def name(self) -> str:
        return f"<{self.kind.value} غير مُعدّ>"

    @property
    def configured(self) -> bool:
        return False


class UnconfiguredCalendarProvider(_Unconfigured, EconomicCalendarProvider):
    def __init__(self) -> None:
        _Unconfigured.__init__(self, ProviderKind.ECONOMIC_CALENDAR)

    def events(self, **_: Any) -> tuple[EconomicEvent, ...]:
        # ⚠️ قائمة فارغة هنا **لا تعني** «لا توجد أحداث» — تعني «لا نعرف».
        # هذا الفرق يُفرَض في `CalendarGate`: مزوّد غير مُعدّ ⇒ لا أهلية حقيقية.
        return ()


class UnconfiguredMacroProvider(_Unconfigured, MacroDataProvider):
    def __init__(self) -> None:
        _Unconfigured.__init__(self, ProviderKind.MACRO_DATA)

    def series(self, *, keys: Sequence[str], as_of_utc: datetime) -> dict[str, Sourced[Any]]:
        return {k: Sourced.unknown(self.name, "مزوّد الاقتصاد الكلي غير مُعدّ.") for k in keys}


class UnconfiguredNewsProvider(_Unconfigured, VerifiedNewsProvider):
    def __init__(self) -> None:
        _Unconfigured.__init__(self, ProviderKind.VERIFIED_NEWS)

    def news(self, **_: Any) -> tuple[NewsItem, ...]:
        return ()


class UnconfiguredMarketDataProvider(_Unconfigured, MarketDataProvider):
    def __init__(self) -> None:
        _Unconfigured.__init__(self, ProviderKind.MARKET_DATA)

    def candles(
        self, *, instrument: str, timeframe: Timeframe, count: int, as_of_utc: datetime
    ) -> TimeframeSeries:
        return TimeframeSeries(
            timeframe=timeframe,
            candles=(),
            source=self.name,
            retrieved_at_utc=as_of_utc,
            complete=False,
            note_ar="مزوّد بيانات السوق غير مُعدّ — لا شموع.",
        )


class UnconfiguredFundamentalProvider(_Unconfigured, FundamentalContextProvider):
    def __init__(self) -> None:
        _Unconfigured.__init__(self, ProviderKind.FUNDAMENTAL_CONTEXT)

    def context(self, **_: Any) -> dict[str, Sourced[Any]]:
        return {}


# ---------------------------------------------------------------------------
# السجل
# ---------------------------------------------------------------------------

@dataclass
class ProviderRegistry:
    """
    كل المزوّدين في مكان واحد. الافتراضي هو **غير مُعدّ** لكل واحد،
    فلا يمكن أن يبدأ النظام وهو يظن أن لديه بيانات ليست عنده.
    """

    calendar: EconomicCalendarProvider = None
    macro: MacroDataProvider = None
    news: VerifiedNewsProvider = None
    market_data: MarketDataProvider = None
    fundamentals: FundamentalContextProvider = None

    def __post_init__(self) -> None:
        self.calendar = self.calendar or UnconfiguredCalendarProvider()
        self.macro = self.macro or UnconfiguredMacroProvider()
        self.news = self.news or UnconfiguredNewsProvider()
        self.market_data = self.market_data or UnconfiguredMarketDataProvider()
        self.fundamentals = self.fundamentals or UnconfiguredFundamentalProvider()

    def all(self) -> tuple[DataProvider, ...]:
        return (self.calendar, self.macro, self.news, self.market_data, self.fundamentals)

    def statuses(self) -> tuple[ProviderStatus, ...]:
        return tuple(p.status() for p in self.all())

    def missing(self) -> tuple[ProviderKind, ...]:
        return tuple(p.kind for p in self.all() if not p.configured)

    def missing_names(self) -> tuple[str, ...]:
        """الأسماء الدقيقة للمزوّدين الناقصين — تُعرض للمالكة كما هي."""
        return tuple(k.value for k in self.missing())

    def missing_mandatory(self) -> tuple[ProviderKind, ...]:
        return tuple(k for k in self.missing() if k in MANDATORY_FOR_LIVE)

    def live_eligible(self) -> bool:
        """أهلية التداول الحقيقي من ناحية اكتمال المزوّدين وحدها."""
        return not self.missing_mandatory()

    def as_display_dict(self) -> dict:
        return {
            "providers": [s.as_dict() for s in self.statuses()],
            "missing": list(self.missing_names()),
            "missing_mandatory": [k.value for k in self.missing_mandatory()],
            "live_eligible_by_providers": self.live_eligible(),
        }


# ---------------------------------------------------------------------------
# مزوّدون للاختبار — بيانات تُحقَن صراحةً، بلا شبكة
# ---------------------------------------------------------------------------

class StaticCalendarProvider(EconomicCalendarProvider):
    """مزوّد اختباري: يعيد ما حُقن فيه بالضبط. لا شبكة، لا كشط."""

    def __init__(self, events: Sequence[EconomicEvent], name: str = "static-calendar") -> None:
        self._events = tuple(events)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def configured(self) -> bool:
        return True

    def events(
        self, *, currencies: Sequence[str], window_start_utc: datetime, window_end_utc: datetime
    ) -> tuple[EconomicEvent, ...]:
        cur = tuple(currencies)
        return tuple(
            e
            for e in self._events
            if e.affects(cur) and window_start_utc <= e.scheduled_utc <= window_end_utc
        )


class StaticNewsProvider(VerifiedNewsProvider):
    def __init__(self, items: Sequence[NewsItem], name: str = "static-news") -> None:
        self._items = tuple(items)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def configured(self) -> bool:
        return True

    def news(
        self, *, currencies: Sequence[str], since_utc: datetime, now_utc: datetime
    ) -> tuple[NewsItem, ...]:
        cur = set(currencies)
        return tuple(
            n
            for n in self._items
            if (set(n.currencies) & cur) and since_utc <= n.provider_timestamp_utc <= now_utc
        )


class StaticMarketDataProvider(MarketDataProvider):
    def __init__(
        self, series: dict[Timeframe, Sequence[Candle]], name: str = "static-market-data"
    ) -> None:
        self._series = {tf: tuple(c) for tf, c in series.items()}
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def configured(self) -> bool:
        return True

    def candles(
        self, *, instrument: str, timeframe: Timeframe, count: int, as_of_utc: datetime
    ) -> TimeframeSeries:
        got = self._series.get(timeframe, ())
        return TimeframeSeries(
            timeframe=timeframe,
            candles=got[-count:] if count else got,
            source=self._name,
            retrieved_at_utc=as_of_utc,
            complete=len(got) >= count,
            note_ar="" if len(got) >= count else f"عدد الشموع {len(got)} أقل من المطلوب {count}.",
        )


class StaticMacroProvider(MacroDataProvider):
    def __init__(self, values: dict[str, Sourced[Any]], name: str = "static-macro") -> None:
        self._values = dict(values)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def configured(self) -> bool:
        return True

    def series(self, *, keys: Sequence[str], as_of_utc: datetime) -> dict[str, Sourced[Any]]:
        return {
            k: self._values.get(k, Sourced.unknown(self._name, "غير متوفر لدى المزوّد."))
            for k in keys
        }


class StaticFundamentalProvider(FundamentalContextProvider):
    def __init__(self, values: dict[str, Sourced[Any]], name: str = "static-fundamentals") -> None:
        self._values = dict(values)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def configured(self) -> bool:
        return True

    def context(self, *, base: str, quote: str, as_of_utc: datetime) -> dict[str, Sourced[Any]]:
        return dict(self._values)


def sourced_now(
    value: Any,
    source: str,
    *,
    source_time: datetime,
    retrieved: datetime,
    reliability: SourceReliability = SourceReliability.OFFICIAL_PROVIDER,
    note_ar: str = "",
) -> Sourced[Any]:
    """مختصر لبناء قيمة منسوبة كاملة النسب."""
    return Sourced(
        value=value,
        source=source,
        source_timestamp_utc=source_time,
        retrieved_at_utc=retrieved,
        reliability=reliability,
        note_ar=note_ar,
    )


__all__ = [
    "ProviderKind",
    "ProviderStatus",
    "ProviderNotConfigured",
    "MANDATORY_FOR_LIVE",
    "DataProvider",
    "EconomicCalendarProvider",
    "MacroDataProvider",
    "VerifiedNewsProvider",
    "MarketDataProvider",
    "FundamentalContextProvider",
    "ProviderRegistry",
    "UnconfiguredCalendarProvider",
    "UnconfiguredMacroProvider",
    "UnconfiguredNewsProvider",
    "UnconfiguredMarketDataProvider",
    "UnconfiguredFundamentalProvider",
    "StaticCalendarProvider",
    "StaticNewsProvider",
    "StaticMarketDataProvider",
    "StaticMacroProvider",
    "StaticFundamentalProvider",
    "sourced_now",
]
