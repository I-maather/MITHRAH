"""
تجهيزات الاختبار لطبقة الاستخبارات — **بلا أي وصول شبكي**.

كل شمعة وكل حدث وكل خبر يُبنى هنا صراحةً. لا يوجد مزوّد حقيقي، ولا استدعاء
HTTP واحد في أي اختبار في هذا الملف أو ما يستهلكه.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.contracts import Broker
from app.intelligence.gates import ExecutionHealth
from app.intelligence.providers import (
    ProviderRegistry,
    StaticCalendarProvider,
    StaticFundamentalProvider,
    StaticMacroProvider,
    StaticMarketDataProvider,
    StaticNewsProvider,
)
from app.intelligence.snapshot import (
    BrokerConditions,
    Candle,
    EconomicEvent,
    EventCategory,
    ImpactLevel,
    MarketSnapshot,
    MarketStatus,
    NewsItem,
    NewsVerification,
    SourceReliability,
    Sourced,
    Timeframe,
    TIMEFRAME_ORDER,
    TimeframeSeries,
)
from app.money import D
from app.risk.capital_costs import (
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
BASE_PRICE = D("1.08500")


def utc(offset_minutes: int = 0) -> datetime:
    return NOW + timedelta(minutes=offset_minutes)


# ---------------------------------------------------------------------------
# شموع
# ---------------------------------------------------------------------------

def _lcg(seed: int):
    """
    مولّد أرقام خطي بسيط — **حتمي تماماً**: نفس البذرة تعطي نفس الشموع دائماً.
    يُستعمل لصنع تذبذب واقعي، لا لمحاكاة سوق حقيقي ولا لتوليد نتائج.
    """
    state = seed
    while True:
        state = (1103515245 * state + 12345) % (2 ** 31)
        yield state / (2 ** 31)


def uptrend_candles(
    count: int = 140,
    *,
    timeframe: Timeframe = Timeframe.D1,
    start_price: Decimal = BASE_PRICE,
    step: Decimal = D("0.0012"),
    end_utc: datetime = NOW,
    seed: int = 20260828,
) -> list[Candle]:
    """
    اتجاه صاعد بتذبذب واقعي: انحياز صعودي ثابت + ضجيج حتمي + تصحيحات دورية.
    الهدف أن ينتج ADX في نطاق اتجاه حقيقي ومئيناً تقلبياً متوسطاً — لا خطاً مستقيماً
    ينتج ADX = 100 ومئيناً = 100 (وهو ما يصنّفه النظام تقلباً شاذاً بحق).
    """
    from app.intelligence.snapshot import TIMEFRAME_SECONDS

    seconds = TIMEFRAME_SECONDS[timeframe]
    rng = _lcg(seed)
    out: list[Candle] = []
    price = start_price
    peak = max(1, int(count * 0.4))
    for i in range(count):
        # سعة تقلب متغيّرة ببطء تبلغ ذروتها في منتصف السلسلة ثم تهدأ،
        # فيقع التقلب **الحالي** في وسط توزيعه التاريخي بدل قمته.
        ramp = D(i) / D(peak) if i <= peak else D(count - i) / D(max(1, count - peak))
        amp = D("0.45") + D("0.85") * max(D("0"), min(D("1"), ramp))
        noise = D(str(round(next(rng), 6))) - D("0.5")        # −0.5 .. +0.5
        # آخر أربع شموع تصحيح مقصود: هكذا يكون النظام TREND لا BREAKOUT_CONFIRMED،
        # ويكون السعر في ارتداد — وهو بالضبط ما تبحث عنه TREND_PULLBACK.
        in_final_pullback = i >= count - 4
        pullback = in_final_pullback or (i % 7 == 5)
        drift = -step * D("0.6") if pullback else step * D("0.55")
        move = drift + noise * step * D("0.9") * amp
        o = price
        c = price + move
        wick = step * amp * (D("0.2") + D(str(round(next(rng), 6))) * D("0.4"))
        hi = max(o, c) + wick
        lo = min(o, c) - wick
        start = end_utc - timedelta(seconds=seconds * (count - i))
        out.append(Candle(start, o, hi, lo, c, D("1000")))
        price = c
    return out


def range_candles(
    count: int = 140,
    *,
    timeframe: Timeframe = Timeframe.D1,
    centre: Decimal = BASE_PRICE,
    width: Decimal = D("0.0040"),
    end_utc: datetime = NOW,
) -> list[Candle]:
    """نطاق ضيق متكرر — ADX منخفض وبنية نطاقية."""
    from app.intelligence.snapshot import TIMEFRAME_SECONDS

    seconds = TIMEFRAME_SECONDS[timeframe]
    out: list[Candle] = []
    period = 8          # دورة قصيرة: DI⁺ و DI⁻ يتوازنان ⇒ ADX منخفض حقيقي
    half = period // 2
    modulation = 23     # تعديل بطيء للسعة كي لا يكون التقلب الحالي طرفاً في توزيعه
    mod_half = modulation // 2
    for i in range(count):
        mp = i % modulation
        mtri = D(mp) / D(mod_half) if mp <= mod_half else D(modulation - mp) / D(mod_half)
        w = width * (D("0.75") + D("0.5") * mtri)

        phase = i % period
        tri = D(phase) / D(half) if phase <= half else D(period - phase) / D(half)
        offset = w * (tri * D("2") - D("1"))

        o = centre + offset
        c = centre + offset
        wick = w * D("0.10")
        start = end_utc - timedelta(seconds=seconds * (count - i))
        out.append(Candle(start, o, max(o, c) + wick, min(o, c) - wick, c, D("1000")))
    return out


def all_timeframe_series(
    *, trending: bool = True, end_utc: datetime = NOW, count: int = 140
) -> dict[Timeframe, TimeframeSeries]:
    maker = uptrend_candles if trending else range_candles
    out: dict[Timeframe, TimeframeSeries] = {}
    for tf in TIMEFRAME_ORDER:
        out[tf] = TimeframeSeries(
            timeframe=tf,
            candles=tuple(maker(count, timeframe=tf, end_utc=end_utc)),
            source="static-market-data",
            retrieved_at_utc=end_utc,
            complete=True,
        )
    return out


# ---------------------------------------------------------------------------
# أحداث وأخبار
# ---------------------------------------------------------------------------

def high_impact_event(
    *, minutes_from_now: int, category: EventCategory = EventCategory.NFP,
    now: datetime = NOW, name: str = "تقرير الوظائف غير الزراعية",
) -> EconomicEvent:
    return EconomicEvent(
        event_id=f"evt-{category.value}-{minutes_from_now}",
        name=name,
        category=category,
        currencies=("USD",),
        impact=ImpactLevel.HIGH,
        scheduled_utc=now + timedelta(minutes=minutes_from_now),
        provider="static-calendar",
        provider_timestamp_utc=now - timedelta(hours=12),
        retrieved_at_utc=now,
        source_reference="fixture",
    )


def low_impact_event(*, minutes_from_now: int, now: datetime = NOW) -> EconomicEvent:
    return EconomicEvent(
        event_id=f"evt-low-{minutes_from_now}",
        name="مؤشر ثانوي",
        category=EventCategory.OTHER,
        currencies=("EUR",),
        impact=ImpactLevel.LOW,
        scheduled_utc=now + timedelta(minutes=minutes_from_now),
        provider="static-calendar",
        provider_timestamp_utc=now - timedelta(hours=6),
        retrieved_at_utc=now,
    )


def news_item(
    *,
    verification: NewsVerification,
    impact: ImpactLevel = ImpactLevel.HIGH,
    minutes_ago: int = 5,
    now: datetime = NOW,
    headline: str = "خبر عاجل",
) -> NewsItem:
    return NewsItem(
        news_id=f"news-{verification.value}-{minutes_ago}",
        headline=headline,
        currencies=("EUR", "USD"),
        impact=impact,
        category=EventCategory.GEOPOLITICAL,
        verification=verification,
        provider="static-news",
        provider_timestamp_utc=now - timedelta(minutes=minutes_ago),
        retrieved_at_utc=now,
        source_reference="fixture",
    )


# ---------------------------------------------------------------------------
# الأساسيات
# ---------------------------------------------------------------------------

def macro_values(
    *, bullish_eur: bool = True, now: datetime = NOW, complete: bool = True
) -> dict[str, Sourced]:
    from app.intelligence.fundamentals import REQUIRED_MACRO_KEYS

    eur_side = "HAWKISH" if bullish_eur else "DOVISH"
    usd_side = "DOVISH" if bullish_eur else "HAWKISH"
    mapping = {
        "fed_policy_stance": usd_side,
        "ecb_policy_stance": eur_side,
        "rate_differential": "RISING" if bullish_eur else "FALLING",
        "inflation_direction_us": "FALLING" if bullish_eur else "RISING",
        "inflation_direction_ea": "RISING" if bullish_eur else "FALLING",
        "labour_direction_us": "WEAKENING" if bullish_eur else "STRENGTHENING",
        "labour_direction_ea": "STRENGTHENING" if bullish_eur else "WEAKENING",
        "growth_direction_us": "FALLING" if bullish_eur else "RISING",
        "growth_direction_ea": "RISING" if bullish_eur else "FALLING",
        "bond_yield_direction": "STABLE",
        "risk_sentiment": "RISK_ON",
        "usd_strength": "WEAKENING" if bullish_eur else "STRENGTHENING",
        "eur_strength": "STRENGTHENING" if bullish_eur else "WEAKENING",
    }
    keys = REQUIRED_MACRO_KEYS if complete else REQUIRED_MACRO_KEYS[:4]
    return {
        k: Sourced(
            value=mapping[k],
            source="static-macro",
            source_timestamp_utc=now - timedelta(hours=3),
            retrieved_at_utc=now,
            reliability=SourceReliability.OFFICIAL_PROVIDER,
        )
        for k in keys
    }


# ---------------------------------------------------------------------------
# اللقطة
# ---------------------------------------------------------------------------

def broker_conditions(
    *, now: datetime = NOW, market_status: MarketStatus = MarketStatus.OPEN,
    unknown_margin: bool = False,
) -> BrokerConditions:
    def s(value, note: str = "") -> Sourced:
        return Sourced(
            value=value,
            source="capital.com-demo",
            source_timestamp_utc=now,
            retrieved_at_utc=now,
            reliability=SourceReliability.BROKER_AUTHORITATIVE,
            note_ar=note,
        )

    return BrokerConditions(
        epic=s("EURUSD"),
        min_quantity=s(D("100")),
        quantity_increment=s(D("1")),
        lot_size=s(D("1")),
        margin_factor=Sourced.unknown("capital.com-demo") if unknown_margin else s(D("0.01")),
        min_stop_distance_pips=s(D("5")),
        guaranteed_stop_available=s(False),
        overnight_fee_daily=s(D("0.00007")),
        market_status=s(market_status),
    )


def make_snapshot(
    *,
    now: datetime = NOW,
    trending: bool = True,
    bid: Optional[Decimal] = D("1.08540"),
    ask: Optional[Decimal] = D("1.08546"),
    market_status: MarketStatus = MarketStatus.OPEN,
    events: Sequence[EconomicEvent] = (),
    news: Sequence[NewsItem] = (),
    fundamentals: Optional[dict] = None,
    quote_age_seconds: int = 5,
    series: Optional[dict] = None,
    missing_providers: tuple[str, ...] = (),
    incomplete_timeframe: Optional[Timeframe] = None,
    bad_ohlc: bool = False,
    duplicate_bars: bool = False,
) -> MarketSnapshot:
    quote_time = now - timedelta(seconds=quote_age_seconds)

    def s(value) -> Sourced:
        return Sourced(
            value=value,
            source="capital.com-demo",
            source_timestamp_utc=quote_time,
            retrieved_at_utc=now,
            reliability=SourceReliability.BROKER_AUTHORITATIVE,
        )

    ser = dict(series) if series is not None else all_timeframe_series(
        trending=trending, end_utc=now
    )

    if incomplete_timeframe is not None:
        old = ser[incomplete_timeframe]
        ser[incomplete_timeframe] = TimeframeSeries(
            timeframe=incomplete_timeframe,
            candles=old.candles[:10],
            source=old.source,
            retrieved_at_utc=old.retrieved_at_utc,
            complete=False,
            note_ar="ناقص عمداً في التجهيزة.",
        )
    if bad_ohlc:
        old = ser[Timeframe.D1]
        broken = list(old.candles)
        c = broken[-1]
        broken[-1] = Candle(c.start_utc, c.open, c.low, c.high, c.close, c.volume)  # high<low
        ser[Timeframe.D1] = TimeframeSeries(
            Timeframe.D1, tuple(broken), old.source, old.retrieved_at_utc, True
        )
    if duplicate_bars:
        old = ser[Timeframe.D1]
        dup = list(old.candles)
        dup[-1] = dup[-2]
        ser[Timeframe.D1] = TimeframeSeries(
            Timeframe.D1, tuple(dup), old.source, old.retrieved_at_utc, True
        )

    return MarketSnapshot(
        instrument="EURUSD",
        captured_at_utc=now,
        bid=s(bid) if bid is not None else Sourced.unknown("capital.com-demo"),
        ask=s(ask) if ask is not None else Sourced.unknown("capital.com-demo"),
        spread=(
            s(ask - bid) if (bid is not None and ask is not None)
            else Sourced.unknown("capital.com-demo")
        ),
        series=ser,
        scheduled_events=tuple(events),
        news=tuple(news),
        fundamentals=fundamentals if fundamentals is not None else macro_values(now=now),
        technical_inputs={},
        market_status=s(market_status),
        broker_conditions=broker_conditions(now=now, market_status=market_status),
        missing_providers=missing_providers,
    )


# ---------------------------------------------------------------------------
# السجل والمزوّدون
# ---------------------------------------------------------------------------

def full_registry(
    *,
    events: Sequence[EconomicEvent] = (),
    news: Sequence[NewsItem] = (),
    macro: Optional[dict] = None,
    now: datetime = NOW,
) -> ProviderRegistry:
    """سجل كامل بمزوّدين ثابتين — كل شيء مُعدّ، لا شبكة."""
    return ProviderRegistry(
        calendar=StaticCalendarProvider(events),
        news=StaticNewsProvider(news),
        macro=StaticMacroProvider(macro if macro is not None else macro_values(now=now)),
        market_data=StaticMarketDataProvider(
            {tf: s.candles for tf, s in all_timeframe_series(end_utc=now).items()}
        ),
        fundamentals=StaticFundamentalProvider({}),
    )


def healthy_execution() -> ExecutionHealth:
    return ExecutionHealth(
        account_reconciled=True,
        unknown_executions=0,
        risk_lock_active=False,
        kill_switch_active=False,
    )


# ---------------------------------------------------------------------------
# نموذج التكلفة
# ---------------------------------------------------------------------------

DISCOVERED_EURUSD = InstrumentEconomics(
    epic="EURUSD",
    pip_size=D("0.0001"),
    lot_size=D("1"),
    min_deal_size=D("100"),
    size_increment=D("1"),
    margin_factor=D("1"),
    margin_factor_unit="PERCENTAGE",
    min_stop_distance=D("5"),
    min_guaranteed_stop_distance=None,
    guaranteed_stop_available=False,
    quote_currency="USD",
    overnight_fee_rate_daily=D("0.00007"),
    provenance=ValueProvenance.BROKER_DISCOVERY,
)


def cost_model(*, spread_pips: Decimal = D("0.6")) -> CapitalComCostModel:
    return CapitalComCostModel(
        economics=DISCOVERED_EURUSD,
        assumptions=CfdCostAssumptions(
            spread_price=spread_pips * D("0.0001"),
            spread_provenance=ValueProvenance.BROKER_DISCOVERY,
            slippage_reserve_pips=D("1"),
            guaranteed_stop_premium_pips=None,
            currency_conversion_pct=D("0"),
            nights_held=0,
        ),
    )


__all__ = [
    "NOW",
    "BASE_PRICE",
    "utc",
    "uptrend_candles",
    "range_candles",
    "all_timeframe_series",
    "high_impact_event",
    "low_impact_event",
    "news_item",
    "macro_values",
    "broker_conditions",
    "make_snapshot",
    "full_registry",
    "healthy_execution",
    "DISCOVERED_EURUSD",
    "cost_model",
]
