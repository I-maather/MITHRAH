"""
IMMUTABLE MARKET SNAPSHOT — لقطة السوق غير القابلة للتعديل.

كل دورة تحليل تُنشئ لقطة واحدة، ثم **كل** المحلّلين في تلك الدورة يقرأون
منها هي وحدها. لا يجوز لمحلّل أن يحدّث حقلاً واحداً بصمت ويدمجه مع حقول أقدم.

ثلاث قواعد لا تُخرَق:

1. اللقطة مجمّدة (`frozen=True`) وتحمل بصمة SHA-256 لمحتواها.
2. كل حقل يحمل **مصدره ووقت مصدره ووقت جلبه وعمره**.
3. القيمة الحرجة غير المتوفرة تُسجَّل `UNKNOWN` — **لا تُستبدل ولا تُقدَّر
   ولا تُختلق أبداً**.

`UNKNOWN` قيمة صالحة في كل مكان في هذا النظام. غيابها هو الخطر.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Mapping, Optional, TypeVar

from ..clock import to_riyadh

T = TypeVar("T")


# ---------------------------------------------------------------------------
# UNKNOWN
# ---------------------------------------------------------------------------

class _Unknown:
    """قيمة «غير معلوم» الوحيدة. `bool(UNKNOWN)` هو False عمداً."""

    _instance: Optional["_Unknown"] = None

    def __new__(cls) -> "_Unknown":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __str__(self) -> str:
        return "UNKNOWN"

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Unknown)

    def __hash__(self) -> int:
        return hash("__UNKNOWN__")


UNKNOWN = _Unknown()


def is_unknown(value: Any) -> bool:
    return isinstance(value, _Unknown)


# ---------------------------------------------------------------------------
# مصادر البيانات ومستويات الثقة
# ---------------------------------------------------------------------------

class SourceReliability(str, Enum):
    """
    مستوى الثقة بالمصدر. يُستعمل في التصنيف والتناقضات، ولا يُستعمل أبداً
    لترقية قيمة `UNKNOWN` إلى قيمة معلومة.
    """

    BROKER_AUTHORITATIVE = "BROKER_AUTHORITATIVE"   # Capital.com للسعر والحالة
    OFFICIAL_PROVIDER = "OFFICIAL_PROVIDER"         # مزوّد رسمي مُعرَّف
    DERIVED_LOCAL = "DERIVED_LOCAL"                 # محسوب محلياً من بيانات موثّقة
    CONFIGURED_ASSUMPTION = "CONFIGURED_ASSUMPTION" # افتراض متحفظ مُعلن
    UNVERIFIED = "UNVERIFIED"                       # لا يُبنى عليه قرار
    NONE = "NONE"


@dataclass(frozen=True)
class Sourced(Generic[T]):
    """
    قيمة مع نسبها الكامل. لا توجد قيمة في اللقطة بلا نسب.
    """

    value: T | _Unknown
    source: str
    source_timestamp_utc: Optional[datetime]
    retrieved_at_utc: Optional[datetime]
    reliability: SourceReliability = SourceReliability.NONE
    note_ar: str = ""

    @staticmethod
    def unknown(source: str = "—", note_ar: str = "غير متوفر") -> "Sourced[Any]":
        return Sourced(
            value=UNKNOWN,
            source=source,
            source_timestamp_utc=None,
            retrieved_at_utc=None,
            reliability=SourceReliability.NONE,
            note_ar=note_ar,
        )

    @property
    def known(self) -> bool:
        return not is_unknown(self.value)

    def age_seconds(self, now: datetime) -> Optional[float]:
        if self.source_timestamp_utc is None:
            return None
        return (now - self.source_timestamp_utc).total_seconds()

    def as_dict(self) -> dict:
        return {
            "value": _jsonable(self.value),
            "source": self.source,
            "source_timestamp_utc": (
                self.source_timestamp_utc.isoformat() if self.source_timestamp_utc else None
            ),
            "retrieved_at_utc": (
                self.retrieved_at_utc.isoformat() if self.retrieved_at_utc else None
            ),
            "reliability": self.reliability.value,
            "known": self.known,
            "note_ar": self.note_ar,
        }


def _jsonable(value: Any) -> Any:
    if is_unknown(value):
        return "UNKNOWN"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return value


# ---------------------------------------------------------------------------
# عناصر التقويم والأخبار
# ---------------------------------------------------------------------------

class ImpactLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class EventCategory(str, Enum):
    CENTRAL_BANK_RATE = "CENTRAL_BANK_RATE"
    CENTRAL_BANK_SPEECH = "CENTRAL_BANK_SPEECH"
    INFLATION = "INFLATION"
    EMPLOYMENT = "EMPLOYMENT"
    NFP = "NFP"
    GDP = "GDP"
    PMI = "PMI"
    RETAIL_SALES = "RETAIL_SALES"
    GEOPOLITICAL = "GEOPOLITICAL"
    SYSTEMIC_RISK = "SYSTEMIC_RISK"
    OTHER = "OTHER"


class NewsVerification(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class EconomicEvent:
    """
    حدث اقتصادي مجدول أو صادر. **لا تُبرمَج نتائج الأحداث في الكود إطلاقاً** —
    كل القيم تأتي من المزوّد وتُسجَّل كما وردت.
    """

    event_id: str
    name: str
    category: EventCategory
    currencies: tuple[str, ...]
    impact: ImpactLevel
    scheduled_utc: datetime
    provider: str
    provider_timestamp_utc: datetime
    retrieved_at_utc: datetime
    expected_value: Any = UNKNOWN
    previous_value: Any = UNKNOWN
    actual_value: Any = UNKNOWN
    source_reference: str = ""

    @property
    def is_released(self) -> bool:
        return not is_unknown(self.actual_value)

    def affects(self, currencies: tuple[str, ...]) -> bool:
        return any(c in self.currencies for c in currencies)

    def as_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "category": self.category.value,
            "currencies": list(self.currencies),
            "impact": self.impact.value,
            "scheduled_utc": self.scheduled_utc.isoformat(),
            "provider": self.provider,
            "provider_timestamp_utc": self.provider_timestamp_utc.isoformat(),
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "expected_value": _jsonable(self.expected_value),
            "previous_value": _jsonable(self.previous_value),
            "actual_value": _jsonable(self.actual_value),
            "source_reference": self.source_reference,
        }


@dataclass(frozen=True)
class NewsItem:
    """
    خبر. الخبر غير المُتحقَّق منه **لا يُنشئ صفقة أبداً** — يستطيع فقط أن
    يمنع التداول حتى يُتحقَّق منه أو تنتهي صلاحيته.
    """

    news_id: str
    headline: str
    currencies: tuple[str, ...]
    impact: ImpactLevel
    category: EventCategory
    verification: NewsVerification
    provider: str
    provider_timestamp_utc: datetime
    retrieved_at_utc: datetime
    source_reference: str = ""

    def freshness_seconds(self, now: datetime) -> float:
        return (now - self.provider_timestamp_utc).total_seconds()

    def as_dict(self) -> dict:
        return {
            "news_id": self.news_id,
            "headline": self.headline,
            "currencies": list(self.currencies),
            "impact": self.impact.value,
            "category": self.category.value,
            "verification": self.verification.value,
            "provider": self.provider,
            "provider_timestamp_utc": self.provider_timestamp_utc.isoformat(),
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "source_reference": self.source_reference,
        }


# ---------------------------------------------------------------------------
# الأطر الزمنية
# ---------------------------------------------------------------------------

class Timeframe(str, Enum):
    W1 = "W1"
    D1 = "D1"
    H4 = "H4"
    H1 = "H1"
    M15 = "M15"
    M5 = "M5"


#: تسلسل هرمي مقصود، لا تصويت مؤشرات عشوائي.
TIMEFRAME_ROLE_AR: dict[Timeframe, str] = {
    Timeframe.W1: "سياق بعيد المدى فقط",
    Timeframe.D1: "نظام السوق الأساسي",
    Timeframe.H4: "الاتجاه الهيكلي",
    Timeframe.H1: "سياق الإعداد",
    Timeframe.M15: "إعداد الدخول",
    Timeframe.M5: "التوقيت فقط — لا يحدّد الاتجاه أبداً",
}

#: من الأعلى إلى الأدنى.
TIMEFRAME_ORDER: tuple[Timeframe, ...] = (
    Timeframe.W1,
    Timeframe.D1,
    Timeframe.H4,
    Timeframe.H1,
    Timeframe.M15,
    Timeframe.M5,
)

TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.W1: 604800,
    Timeframe.D1: 86400,
    Timeframe.H4: 14400,
    Timeframe.H1: 3600,
    Timeframe.M15: 900,
    Timeframe.M5: 300,
}


@dataclass(frozen=True)
class Candle:
    """شمعة مُتحقَّق منها. الفحوص البنيوية في `intelligence/health.py`."""

    start_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    @property
    def is_structurally_valid(self) -> bool:
        return (
            self.high >= self.low
            and self.high >= self.open
            and self.high >= self.close
            and self.low <= self.open
            and self.low <= self.close
            and self.open > 0
            and self.low > 0
        )

    @property
    def range(self) -> Decimal:
        return self.high - self.low

    def as_dict(self) -> dict:
        return {
            "start_utc": self.start_utc.isoformat(),
            "o": str(self.open),
            "h": str(self.high),
            "l": str(self.low),
            "c": str(self.close),
            "v": str(self.volume),
        }


@dataclass(frozen=True)
class TimeframeSeries:
    timeframe: Timeframe
    candles: tuple[Candle, ...]
    source: str
    retrieved_at_utc: datetime
    complete: bool
    note_ar: str = ""

    @property
    def last_close(self) -> Decimal | _Unknown:
        return self.candles[-1].close if self.candles else UNKNOWN

    def checksum(self) -> str:
        blob = json.dumps(
            [c.as_dict() for c in self.candles], separators=(",", ":"), sort_keys=True
        ).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {
            "timeframe": self.timeframe.value,
            "role_ar": TIMEFRAME_ROLE_AR[self.timeframe],
            "bars": len(self.candles),
            "source": self.source,
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "complete": self.complete,
            "checksum": self.checksum(),
            "note_ar": self.note_ar,
        }


# ---------------------------------------------------------------------------
# اللقطة
# ---------------------------------------------------------------------------

class MarketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    HALTED = "HALTED"
    WEEKEND = "WEEKEND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BrokerConditions:
    """شروط التداول من الوسيط — Capital.com هو المرجع الوحيد لها."""

    epic: Sourced[str]
    min_quantity: Sourced[Decimal]
    quantity_increment: Sourced[Decimal]
    lot_size: Sourced[Decimal]
    margin_factor: Sourced[Decimal]
    min_stop_distance_pips: Sourced[Decimal]
    guaranteed_stop_available: Sourced[bool]
    overnight_fee_daily: Sourced[Decimal]
    market_status: Sourced[MarketStatus]

    def as_dict(self) -> dict:
        return {k: v.as_dict() for k, v in self.__dict__.items()}

    def unknown_fields(self) -> tuple[str, ...]:
        return tuple(k for k, v in self.__dict__.items() if not v.known)


@dataclass(frozen=True)
class MarketSnapshot:
    """
    لقطة غير قابلة للتعديل. تُبنى مرة واحدة لكل دورة قرار.

    `snapshot_id` بصمة محتواها: لقطتان بمحتوى مختلف لا تحملان المعرّف نفسه أبداً،
    ولذلك يكفي مقارنة المعرّف للتأكد أن كل المحلّلين على البيانات نفسها.
    """

    instrument: str
    captured_at_utc: datetime

    bid: Sourced[Decimal]
    ask: Sourced[Decimal]
    spread: Sourced[Decimal]

    series: Mapping[Timeframe, TimeframeSeries]
    scheduled_events: tuple[EconomicEvent, ...]
    news: tuple[NewsItem, ...]
    fundamentals: Mapping[str, Sourced[Any]]
    technical_inputs: Mapping[str, Sourced[Any]]
    market_status: Sourced[MarketStatus]
    broker_conditions: BrokerConditions

    missing_providers: tuple[str, ...] = ()
    build_notes_ar: tuple[str, ...] = ()
    snapshot_id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            object.__setattr__(self, "snapshot_id", self._compute_id())

    def _compute_id(self) -> str:
        payload = {
            "instrument": self.instrument,
            "captured_at_utc": self.captured_at_utc.isoformat(),
            "bid": self.bid.as_dict(),
            "ask": self.ask.as_dict(),
            "spread": self.spread.as_dict(),
            "series": {
                tf.value: s.checksum() for tf, s in sorted(
                    self.series.items(), key=lambda kv: kv[0].value
                )
            },
            "events": [e.as_dict() for e in self.scheduled_events],
            "news": [n.as_dict() for n in self.news],
            "fundamentals": {k: v.as_dict() for k, v in sorted(self.fundamentals.items())},
            "technical_inputs": {
                k: v.as_dict() for k, v in sorted(self.technical_inputs.items())
            },
            "market_status": self.market_status.as_dict(),
            "broker_conditions": self.broker_conditions.as_dict(),
            "missing_providers": list(self.missing_providers),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(blob).hexdigest()

    # -- قراءة -------------------------------------------------------------

    @property
    def captured_at_riyadh(self) -> datetime:
        return to_riyadh(self.captured_at_utc)

    @property
    def mid(self) -> Decimal | _Unknown:
        if self.bid.known and self.ask.known:
            return (self.bid.value + self.ask.value) / Decimal("2")
        return UNKNOWN

    def quote_age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        return self.bid.age_seconds(now or self.captured_at_utc)

    def unknown_critical_fields(self) -> tuple[str, ...]:
        out: list[str] = []
        for name in ("bid", "ask", "spread", "market_status"):
            if not getattr(self, name).known:
                out.append(name)
        out.extend(f"broker.{f}" for f in self.broker_conditions.unknown_fields())
        for tf in TIMEFRAME_ORDER:
            s = self.series.get(tf)
            if s is None:
                out.append(f"series.{tf.value}")
            elif not s.complete:
                out.append(f"series.{tf.value}.incomplete")
        return tuple(out)

    def events_affecting(
        self, currencies: tuple[str, ...], impact: ImpactLevel = ImpactLevel.HIGH
    ) -> tuple[EconomicEvent, ...]:
        return tuple(
            e for e in self.scheduled_events if e.impact is impact and e.affects(currencies)
        )

    def checksums(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "series": {tf.value: s.checksum() for tf, s in self.series.items()},
        }

    def as_display_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "instrument": self.instrument,
            "captured_at_utc": self.captured_at_utc.isoformat(),
            "captured_at_riyadh": self.captured_at_riyadh.isoformat(),
            "bid": self.bid.as_dict(),
            "ask": self.ask.as_dict(),
            "spread": self.spread.as_dict(),
            "market_status": self.market_status.as_dict(),
            "series": {tf.value: s.as_dict() for tf, s in self.series.items()},
            "scheduled_events": [e.as_dict() for e in self.scheduled_events],
            "news": [n.as_dict() for n in self.news],
            "fundamentals": {k: v.as_dict() for k, v in self.fundamentals.items()},
            "broker_conditions": self.broker_conditions.as_dict(),
            "missing_providers": list(self.missing_providers),
            "unknown_critical_fields": list(self.unknown_critical_fields()),
            "build_notes_ar": list(self.build_notes_ar),
        }


class SnapshotMismatch(RuntimeError):
    """رُفعت لأن مكوّنين في الدورة نفسها يعملان على لقطتين مختلفتين."""


def assert_same_snapshot(*snapshots: MarketSnapshot) -> str:
    """
    يضمن أن كل المحلّلين في الدورة يستعملون اللقطة نفسها حرفياً.
    الخلط بين لقطتين هو بالضبط الخطأ الذي يجعل تحليلاً يبدو متسقاً وهو ليس كذلك.
    """
    ids = {s.snapshot_id for s in snapshots}
    if len(ids) > 1:
        raise SnapshotMismatch(
            "مكوّنات الدورة تعمل على لقطات مختلفة: " + ", ".join(sorted(i[:12] for i in ids))
        )
    return next(iter(ids)) if ids else ""


__all__ = [
    "UNKNOWN",
    "is_unknown",
    "Sourced",
    "SourceReliability",
    "EconomicEvent",
    "NewsItem",
    "ImpactLevel",
    "EventCategory",
    "NewsVerification",
    "Timeframe",
    "TIMEFRAME_ORDER",
    "TIMEFRAME_ROLE_AR",
    "TIMEFRAME_SECONDS",
    "Candle",
    "TimeframeSeries",
    "MarketStatus",
    "BrokerConditions",
    "MarketSnapshot",
    "SnapshotMismatch",
    "assert_same_snapshot",
]
