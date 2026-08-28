"""
GATES — بوابات المنع الإلزامية.

    1. Data Health Gate
    2. Market Status Gate
    3. Economic Calendar Gate
    5. Verified News Assessment

**لا مرحلة لاحقة تستطيع نقض رفض من بوابة إلزامية سابقة.**
درجة جودة 100/100 لا تلغي رفض بوابة. هذا مفروض في `pipeline.py` بالبنية:
البوابات تعيد قراراً نهائياً، ولا يستقبل المصنِّف مسار تجاوز.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from ..money import D
from .providers import ProviderKind, ProviderRegistry
from .snapshot import (
    EconomicEvent,
    EventCategory,
    ImpactLevel,
    MarketSnapshot,
    MarketStatus,
    NewsItem,
    NewsVerification,
    Timeframe,
    TIMEFRAME_ORDER,
    _Unknown,
    is_unknown,
)


class HealthVerdict(str, Enum):
    PASS = "PASS"
    DEGRADED_RESEARCH_ONLY = "DEGRADED_RESEARCH_ONLY"
    FAIL_NO_TRADE = "FAIL_NO_TRADE"


@dataclass(frozen=True)
class GateCheck:
    key: str
    passed: bool
    detail_ar: str
    blocking: bool = True

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "passed": self.passed,
            "detail_ar": self.detail_ar,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class DataHealthResult:
    verdict: HealthVerdict
    checks: tuple[GateCheck, ...]
    missing_providers: tuple[str, ...]
    unknown_fields: tuple[str, ...]

    @property
    def live_eligible(self) -> bool:
        """الأهلية للتداول الحقيقي تتطلب PASS — لا شيء أقل."""
        return self.verdict is HealthVerdict.PASS

    @property
    def allows_research(self) -> bool:
        return self.verdict is not HealthVerdict.FAIL_NO_TRADE

    def failed(self) -> tuple[GateCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "live_eligible": self.live_eligible,
            "allows_research": self.allows_research,
            "checks": [c.as_dict() for c in self.checks],
            "missing_providers": list(self.missing_providers),
            "unknown_fields": list(self.unknown_fields),
        }


# ---------------------------------------------------------------------------
# 1. Data Health Gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionHealth:
    """حالة التنفيذ والحساب كما تراها وحدات أخرى — تُقرأ ولا تُعدَّل هنا."""

    account_reconciled: bool = True
    unknown_executions: int = 0
    risk_lock_active: bool = False
    kill_switch_active: bool = False


def run_data_health_gate(
    snapshot: MarketSnapshot,
    registry: ProviderRegistry,
    execution: ExecutionHealth,
    *,
    now: datetime,
    max_quote_age_seconds: int = 60,
    required_bars: int = 60,
) -> DataHealthResult:
    checks: list[GateCheck] = []

    def check(key: str, ok: bool, ok_msg: str, bad_msg: str, blocking: bool = True) -> None:
        checks.append(GateCheck(key, ok, ok_msg if ok else bad_msg, blocking))

    # -- مزوّدون --------------------------------------------------------
    missing = registry.missing_names()
    missing_mandatory = registry.missing_mandatory()
    check(
        "PROVIDERS_CONFIGURED",
        not missing_mandatory,
        "كل المزوّدين الإلزاميين مُعدّون.",
        "مزوّدون إلزاميون ناقصون: " + "، ".join(k.value for k in missing_mandatory),
    )

    # -- السعر ----------------------------------------------------------
    bid_known = snapshot.bid.known
    ask_known = snapshot.ask.known
    check(
        "QUOTE_PRESENT",
        bid_known and ask_known,
        "سعر العرض والطلب متوفران.",
        "سعر العرض أو الطلب غير متوفر — UNKNOWN، ولا يُستبدل بتقدير.",
    )

    if bid_known and ask_known:
        check(
            "BID_BELOW_ASK",
            snapshot.bid.value < snapshot.ask.value,
            "العرض أقل من الطلب.",
            f"عرض {snapshot.bid.value} ليس أقل من طلب {snapshot.ask.value} — بيانات مستحيلة.",
        )
        spread_val = (
            snapshot.spread.value if snapshot.spread.known
            else snapshot.ask.value - snapshot.bid.value
        )
        check(
            "SPREAD_NON_NEGATIVE",
            spread_val >= 0,
            f"السبريد {spread_val} غير سالب.",
            f"سبريد سالب {spread_val} — بيانات مستحيلة.",
        )

    age = snapshot.bid.age_seconds(now)
    check(
        "QUOTE_FRESH",
        age is not None and age <= max_quote_age_seconds,
        f"عمر السعر {age:.0f} ثانية ضمن الحد {max_quote_age_seconds}." if age is not None else "",
        (
            "طابع زمني للسعر غير موجود."
            if age is None
            else f"عمر السعر {age:.0f} ثانية يتجاوز الحد {max_quote_age_seconds}."
        ),
    )

    # -- الشموع ---------------------------------------------------------
    for tf in TIMEFRAME_ORDER:
        series = snapshot.series.get(tf)
        if series is None:
            check(f"SERIES_{tf.value}", False, "", f"شموع {tf.value} غير متوفرة.")
            continue
        candles = series.candles
        ok_count = len(candles) >= required_bars and series.complete
        check(
            f"SERIES_{tf.value}_COUNT",
            ok_count,
            f"{tf.value}: {len(candles)} شمعة مكتملة.",
            f"{tf.value}: {len(candles)} شمعة والمطلوب {required_bars} مكتملة.",
        )
        if not candles:
            continue
        bad_ohlc = [c for c in candles if not c.is_structurally_valid]
        check(
            f"SERIES_{tf.value}_OHLC",
            not bad_ohlc,
            f"{tf.value}: كل قيم OHLC منطقية.",
            f"{tf.value}: {len(bad_ohlc)} شمعة بقيم OHLC مستحيلة.",
        )
        starts = [c.start_utc for c in candles]
        check(
            f"SERIES_{tf.value}_NO_DUPLICATES",
            len(set(starts)) == len(starts),
            f"{tf.value}: لا شموع مكررة.",
            f"{tf.value}: توجد شموع مكررة.",
        )
        check(
            f"SERIES_{tf.value}_SORTED",
            starts == sorted(starts),
            f"{tf.value}: الشموع مرتبة زمنياً.",
            f"{tf.value}: الشموع غير مرتبة زمنياً.",
        )
        tz_ok = all(c.start_utc.tzinfo is not None for c in candles)
        check(
            f"SERIES_{tf.value}_TZ",
            tz_ok,
            f"{tf.value}: كل الطوابع الزمنية بمنطقة زمنية صريحة.",
            f"{tf.value}: طوابع زمنية بلا منطقة زمنية — التطبيع مفقود.",
        )

    # -- السوق والحساب --------------------------------------------------
    status_known = snapshot.market_status.known
    check(
        "MARKET_STATUS_KNOWN",
        status_known,
        f"حالة السوق: {snapshot.market_status.value}.",
        "حالة السوق غير معلومة.",
    )
    check(
        "ACCOUNT_RECONCILED",
        execution.account_reconciled,
        "حالة الحساب مطابَقة.",
        "حالة الحساب غير مطابَقة.",
    )
    check(
        "NO_UNKNOWN_EXECUTION",
        execution.unknown_executions == 0,
        "لا توجد حالة تنفيذ غير معلومة.",
        f"{execution.unknown_executions} حالة تنفيذ UNKNOWN — تُحلّ قبل أي تحليل.",
    )
    check(
        "NO_RISK_LOCK",
        not execution.risk_lock_active,
        "لا قفل مخاطرة نشط.",
        "قفل مخاطرة نشط.",
    )
    check(
        "NO_KILL_SWITCH",
        not execution.kill_switch_active,
        "Kill Switch غير مفعّل.",
        "Kill Switch مفعّل — لا تحليل ولا دخول.",
    )

    failed_blocking = [c for c in checks if not c.passed and c.blocking]
    if not failed_blocking:
        verdict = HealthVerdict.PASS
    else:
        # فشل يمنع أي عمل إطلاقاً مقابل فشل يسمح بالبحث فقط.
        hard_keys = {
            "NO_KILL_SWITCH",
            "NO_UNKNOWN_EXECUTION",
            "NO_RISK_LOCK",
            "ACCOUNT_RECONCILED",
            "BID_BELOW_ASK",
            "SPREAD_NON_NEGATIVE",
        }
        hard = any(c.key in hard_keys for c in failed_blocking) or any(
            c.key.endswith("_OHLC") or c.key.endswith("_NO_DUPLICATES")
            for c in failed_blocking
        )
        verdict = (
            HealthVerdict.FAIL_NO_TRADE if hard else HealthVerdict.DEGRADED_RESEARCH_ONLY
        )

    return DataHealthResult(
        verdict=verdict,
        checks=tuple(checks),
        missing_providers=missing,
        unknown_fields=snapshot.unknown_critical_fields(),
    )


# ---------------------------------------------------------------------------
# 2. Market Status Gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketStatusResult:
    passed: bool
    status: MarketStatus | _Unknown
    reason_ar: str

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "status": str(self.status.value if isinstance(self.status, MarketStatus) else self.status),
            "reason_ar": self.reason_ar,
        }


def run_market_status_gate(snapshot: MarketSnapshot) -> MarketStatusResult:
    if not snapshot.market_status.known:
        return MarketStatusResult(False, snapshot.market_status.value, "حالة السوق غير معلومة.")
    status = snapshot.market_status.value
    if status is MarketStatus.OPEN:
        return MarketStatusResult(True, status, "السوق مفتوح.")
    reasons = {
        MarketStatus.CLOSED: "السوق مغلق.",
        MarketStatus.WEEKEND: "عطلة نهاية الأسبوع — الاحتفاظ ممنوع في كل الملفات.",
        MarketStatus.PRE_OPEN: "ما قبل الافتتاح — السيولة غير ممثِّلة.",
        MarketStatus.HALTED: "تداول موقوف.",
        MarketStatus.UNKNOWN: "حالة السوق غير معلومة.",
    }
    return MarketStatusResult(False, status, reasons.get(status, "حالة غير صالحة للتداول."))


# ---------------------------------------------------------------------------
# 3. Economic Calendar Gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlackoutWindow:
    """نافذة حجب لفئة حدث. **قابلة للضبط، وغير قابلة للتجاوز من أي ملف تداول.**"""

    category: EventCategory
    minutes_before: int
    minutes_after: int
    note_ar: str = ""


#: افتراضات أولية آمنة. قرارات الفائدة والمؤتمرات الصحفية تحتاج نافذة أطول.
DEFAULT_BLACKOUTS: dict[EventCategory, BlackoutWindow] = {
    EventCategory.CENTRAL_BANK_RATE: BlackoutWindow(
        EventCategory.CENTRAL_BANK_RATE, 120, 90,
        "قرار فائدة ومؤتمر صحفي — التقلب يمتد بعد الإعلان.",
    ),
    EventCategory.CENTRAL_BANK_SPEECH: BlackoutWindow(
        EventCategory.CENTRAL_BANK_SPEECH, 60, 45
    ),
    EventCategory.NFP: BlackoutWindow(EventCategory.NFP, 60, 45),
    EventCategory.INFLATION: BlackoutWindow(EventCategory.INFLATION, 60, 30),
    EventCategory.EMPLOYMENT: BlackoutWindow(EventCategory.EMPLOYMENT, 60, 30),
    EventCategory.GDP: BlackoutWindow(EventCategory.GDP, 60, 30),
    EventCategory.PMI: BlackoutWindow(EventCategory.PMI, 60, 30),
    EventCategory.RETAIL_SALES: BlackoutWindow(EventCategory.RETAIL_SALES, 60, 30),
    EventCategory.GEOPOLITICAL: BlackoutWindow(EventCategory.GEOPOLITICAL, 60, 30),
    EventCategory.SYSTEMIC_RISK: BlackoutWindow(EventCategory.SYSTEMIC_RISK, 60, 60),
    EventCategory.OTHER: BlackoutWindow(EventCategory.OTHER, 60, 30),
}

#: تمديد الحجب حين يبقى السبريد أو التقلب شاذاً بعد انتهاء النافذة.
ABNORMAL_EXTENSION_MINUTES = 30


@dataclass(frozen=True)
class CalendarResult:
    passed: bool
    in_blackout: bool
    reason_ar: str
    blocking_events: tuple[EconomicEvent, ...]
    upcoming: tuple[EconomicEvent, ...]
    provider_configured: bool
    extended_for_abnormal: bool = False

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "in_blackout": self.in_blackout,
            "reason_ar": self.reason_ar,
            "blocking_events": [e.as_dict() for e in self.blocking_events],
            "upcoming": [e.as_dict() for e in self.upcoming],
            "provider_configured": self.provider_configured,
            "extended_for_abnormal": self.extended_for_abnormal,
        }


def run_calendar_gate(
    snapshot: MarketSnapshot,
    registry: ProviderRegistry,
    *,
    now: datetime,
    currencies: tuple[str, ...] = ("EUR", "USD"),
    blackouts: Optional[dict[EventCategory, BlackoutWindow]] = None,
    conditions_abnormal: bool = False,
) -> CalendarResult:
    """
    نافذة الحجب لا يستطيع أي ملف تداول تجاوزها — الدالة لا تستقبل الملف أصلاً.
    """
    windows = blackouts or DEFAULT_BLACKOUTS
    configured = registry.calendar.configured

    if not configured:
        # مزوّد غير مُعدّ لا يعني «لا أحداث» — يعني «لا نعرف»، والقرار NO_TRADE.
        return CalendarResult(
            passed=False,
            in_blackout=False,
            reason_ar=(
                "مزوّد التقويم الاقتصادي غير مُعدّ. قائمة الأحداث الفارغة لا تعني "
                "خلوّ اليوم من الأحداث — تعني أننا لا نعرف. القرار NO_TRADE."
            ),
            blocking_events=(),
            upcoming=(),
            provider_configured=False,
        )

    blocking: list[EconomicEvent] = []
    upcoming: list[EconomicEvent] = []
    extended = False

    for event in snapshot.scheduled_events:
        if not event.affects(currencies):
            continue
        if event.impact is not ImpactLevel.HIGH:
            if event.scheduled_utc >= now:
                upcoming.append(event)
            continue

        w = windows.get(event.category, windows[EventCategory.OTHER])
        after_minutes = w.minutes_after
        if conditions_abnormal:
            after_minutes += ABNORMAL_EXTENSION_MINUTES
        start = event.scheduled_utc - timedelta(minutes=w.minutes_before)
        end = event.scheduled_utc + timedelta(minutes=after_minutes)
        if start <= now <= end:
            blocking.append(event)
            if conditions_abnormal:
                extended = True
        elif event.scheduled_utc >= now:
            upcoming.append(event)

    if blocking:
        names = "، ".join(e.name for e in blocking)
        return CalendarResult(
            passed=False,
            in_blackout=True,
            reason_ar=(
                f"نافذة حجب حدث عالي الأثر: {names}."
                + (" مُمدَّدة لبقاء الظروف شاذة." if extended else "")
            ),
            blocking_events=tuple(blocking),
            upcoming=tuple(upcoming),
            provider_configured=True,
            extended_for_abnormal=extended,
        )

    return CalendarResult(
        passed=True,
        in_blackout=False,
        reason_ar="لا نافذة حجب حدث عالي الأثر سارية الآن.",
        blocking_events=(),
        upcoming=tuple(sorted(upcoming, key=lambda e: e.scheduled_utc)),
        provider_configured=True,
    )


# ---------------------------------------------------------------------------
# 5. Verified News Assessment
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NewsResult:
    passed: bool
    reason_ar: str
    blocking_items: tuple[NewsItem, ...]
    verified_items: tuple[NewsItem, ...]
    unverified_items: tuple[NewsItem, ...]
    provider_configured: bool

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason_ar": self.reason_ar,
            "blocking_items": [n.as_dict() for n in self.blocking_items],
            "verified": [n.as_dict() for n in self.verified_items],
            "unverified": [n.as_dict() for n in self.unverified_items],
            "provider_configured": self.provider_configured,
        }


#: مدة اعتبار الخبر العاجل غير المُتحقَّق منه حاجباً قبل أن تنتهي صلاحيته.
UNVERIFIED_NEWS_BLOCK_SECONDS = 3600


def run_news_gate(
    snapshot: MarketSnapshot,
    registry: ProviderRegistry,
    *,
    now: datetime,
    currencies: tuple[str, ...] = ("EUR", "USD"),
) -> NewsResult:
    """
    الخبر غير المُتحقَّق منه **لا يُنشئ صفقة أبداً**.
    كل ما يستطيعه: منع التداول حتى يُتحقَّق منه أو تنتهي صلاحيته.
    """
    if not registry.news.configured:
        return NewsResult(
            passed=False,
            reason_ar="مزوّد الأخبار المُتحقَّق منها غير مُعدّ — لا يمكن تأكيد خلوّ السوق من حدث.",
            blocking_items=(),
            verified_items=(),
            unverified_items=(),
            provider_configured=False,
        )

    relevant = [n for n in snapshot.news if set(n.currencies) & set(currencies)]
    verified = tuple(n for n in relevant if n.verification is NewsVerification.VERIFIED)
    unverified = tuple(n for n in relevant if n.verification is NewsVerification.UNVERIFIED)

    blocking: list[NewsItem] = []
    for n in relevant:
        if n.impact is not ImpactLevel.HIGH:
            continue
        if n.verification is NewsVerification.EXPIRED:
            continue
        if n.verification is NewsVerification.UNVERIFIED:
            if n.freshness_seconds(now) <= UNVERIFIED_NEWS_BLOCK_SECONDS:
                blocking.append(n)
            continue
        # مُتحقَّق منه وعالي الأثر وحديث ⇒ حاجب أيضاً.
        if n.freshness_seconds(now) <= UNVERIFIED_NEWS_BLOCK_SECONDS:
            blocking.append(n)

    if blocking:
        return NewsResult(
            passed=False,
            reason_ar=(
                "أخبار عالية الأثر حديثة تمنع التداول: "
                + "، ".join(n.headline for n in blocking)
                + ". الخبر غير المُتحقَّق منه يمنع فقط ولا يُنشئ صفقة."
            ),
            blocking_items=tuple(blocking),
            verified_items=verified,
            unverified_items=unverified,
            provider_configured=True,
        )

    return NewsResult(
        passed=True,
        reason_ar="لا أخبار عالية الأثر حديثة تمنع التداول.",
        blocking_items=(),
        verified_items=verified,
        unverified_items=unverified,
        provider_configured=True,
    )


__all__ = [
    "HealthVerdict",
    "GateCheck",
    "DataHealthResult",
    "ExecutionHealth",
    "run_data_health_gate",
    "MarketStatusResult",
    "run_market_status_gate",
    "BlackoutWindow",
    "DEFAULT_BLACKOUTS",
    "ABNORMAL_EXTENSION_MINUTES",
    "CalendarResult",
    "run_calendar_gate",
    "NewsResult",
    "UNVERIFIED_NEWS_BLOCK_SECONDS",
    "run_news_gate",
]
