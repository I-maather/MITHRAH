"""
SPREAD SAMPLER — قياس سبريد EUR/USD عبر الزمن، قراءةً فقط.

## لماذا يوجد هذا الملف

أظهر الاكتشاف الأول سبريداً قدره **3 نقاط** على EUR/USD. وهو رقم واسع لزوجٍ
هو الأكثر سيولة في العالم، وأثره غير خطي: عند وقف 25 نقطة يلتهم السبريد
والانزلاق **13.8%** من الخسارة الكلية، وهو الفارق بين اجتياز الملف المتحفّظ
وسقوطه.

لكن **لقطة واحدة ليست السبريد المعتاد**. قد تكون ساعةً ميتة بعد إغلاق نيويورك،
أو تجديداً ليلياً، أو دقيقةً قبل إغلاق الجمعة. الاستنتاج من قياس واحد هو نفس
نوع الخطأ الذي أنتج «150 هي الحد الأدنى» و«تكلفة تبييت مئة ضعف».

    هذا الأمر **لا يصنّف أي عيّنة منفردة سبريداً معتاداً** — ولا حتى الوسيط.
    يجمع توزيعاً، ويعرض مئينات، ويَسِم ما يقع قرب الإغلاق، ويرفض البائت.

## حدود صارمة

  * المضيف الحقيقي، **قراءة فقط**، بالقائمة البيضاء نفسها على مستوى HTTP
  * **جلسة مصادقة واحدة** لكل تشغيل — يُفرض بعدّاد ويُختبَر
  * **EUR/USD وحده**
  * `GET /api/v1/markets/EURUSD` **فقط** بعد المصادقة
  * **لا `/accounts`** ولا `/accounts/preferences` ولا مراكز ولا أوامر —
    القياس لا يحتاج رصيداً، فلا يُطلب رصيد
  * المخرَج **غير حسّاس**: أسعار وشروط أداة، بلا أي قيمة حساب
  * **لا ادعاء ربحية** بحال
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Callable, Optional, Sequence

from ..money import D
from .discovery import LiveInstrumentInfo, _extract_instrument
from .session import LiveSession

#: الأداة الوحيدة التي يقيسها هذا الأمر.
SPREAD_SAMPLE_EPIC = "EURUSD"

#: أقصى عمر مقبول للقطة السعر. أقدم من ذلك = بائتة، تُرفض ولا تدخل الإحصاء.
MAX_ACCEPTABLE_DATA_AGE_SECONDS = 120.0

#: حالة السوق الوحيدة التي تُقبل عيّناتها.
TRADEABLE_STATUS = "TRADEABLE"

#: إغلاق الأسبوع في سوق الفوركس ≈ 21:00 UTC يوم الجمعة.
WEEKLY_CLOSE_WEEKDAY = 4          # الاثنين = 0
WEEKLY_CLOSE_UTC = time(21, 0)
#: نافذة «قرب الإغلاق» قبله — السبريد يتّسع فيها بانتظام.
NEAR_CLOSE_MINUTES = 120

#: التجديد اليومي (swap) ≈ 21:00 UTC — نافذة اتساع معروفة أخرى.
DAILY_ROLLOVER_UTC = time(21, 0)
NEAR_ROLLOVER_MINUTES = 30

#: أسباب الرفض.
REJECT_STALE = "STALE_SNAPSHOT"
REJECT_NOT_TRADEABLE = "MARKET_NOT_TRADEABLE"
REJECT_NO_PRICES = "PRICES_MISSING"
REJECT_BAD_SPREAD = "SPREAD_NOT_POSITIVE"

#: وسوم السياق.
FLAG_NEAR_WEEKLY_CLOSE = "NEAR_WEEKLY_CLOSE"
FLAG_NEAR_DAILY_ROLLOVER = "NEAR_DAILY_ROLLOVER"


class SpreadSamplerError(RuntimeError):
    """خطأ في إعداد أو تشغيل أخذ العيّنات."""


# ---------------------------------------------------------------------------
# العيّنة
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpreadSample:
    """عيّنة واحدة — **لا تُقدَّم وحدها كسبريد معتاد** بأي حال."""

    taken_at_utc: datetime
    snapshot_time: Optional[str]
    market_status: Optional[str]
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    spread_price: Optional[Decimal]
    spread_pips: Optional[Decimal]
    data_age_seconds: Optional[float]
    accepted: bool
    reject_reason: Optional[str]
    flags: tuple[str, ...]

    def as_dict(self) -> dict:
        def s(v: Optional[Decimal]) -> Optional[str]:
            return str(v) if v is not None else None

        return {
            "taken_at_utc": self.taken_at_utc.isoformat(),
            "snapshot_time": self.snapshot_time,
            "market_status": self.market_status,
            "bid": s(self.bid),
            "ask": s(self.ask),
            "spread_price": s(self.spread_price),
            "spread_pips": s(self.spread_pips),
            "data_age_seconds": self.data_age_seconds,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason,
            "flags": list(self.flags),
        }


def pip_size_for(epic: str) -> Decimal:
    return D("0.01") if epic.upper().endswith("JPY") else D("0.0001")


def close_flags(moment: datetime) -> tuple[str, ...]:
    """
    يَسِم اللحظات التي يتّسع فيها السبريد **بنيوياً** لا عشوائياً.

    عيّنة عند 20:30 الجمعة ليست خاطئة — لكنها لا تمثّل ساعة التداول العادية،
    ودمجها بلا وسم في المتوسط يُنتج رقماً لا يصف أي ساعة فعلية.
    """
    moment = moment.astimezone(timezone.utc)
    flags: list[str] = []

    close_at = datetime.combine(moment.date(), WEEKLY_CLOSE_UTC, tzinfo=timezone.utc)
    if moment.weekday() == WEEKLY_CLOSE_WEEKDAY:
        delta = (close_at - moment).total_seconds() / 60
        if -NEAR_CLOSE_MINUTES <= delta <= NEAR_CLOSE_MINUTES:
            flags.append(FLAG_NEAR_WEEKLY_CLOSE)

    rollover_at = datetime.combine(
        moment.date(), DAILY_ROLLOVER_UTC, tzinfo=timezone.utc
    )
    minutes_to_rollover = abs((rollover_at - moment).total_seconds()) / 60
    if minutes_to_rollover <= NEAR_ROLLOVER_MINUTES:
        flags.append(FLAG_NEAR_DAILY_ROLLOVER)

    return tuple(flags)


def build_sample(
    instrument: LiveInstrumentInfo, *, taken_at_utc: datetime, epic: str = SPREAD_SAMPLE_EPIC
) -> SpreadSample:
    """
    يبني عيّنة ويقرّر قبولها. **الرفض صريح ومُعلَّل** — لا عيّنة تُسقط بصمت.
    """
    flags = close_flags(taken_at_utc)
    spread = instrument.spread
    pips = (spread / pip_size_for(epic)) if spread is not None else None

    def reject(reason: str) -> SpreadSample:
        return SpreadSample(
            taken_at_utc=taken_at_utc,
            snapshot_time=instrument.snapshot_time,
            market_status=instrument.market_status,
            bid=instrument.bid, ask=instrument.ask,
            spread_price=spread, spread_pips=pips,
            data_age_seconds=instrument.data_age_seconds,
            accepted=False, reject_reason=reason, flags=flags,
        )

    if not instrument.found or instrument.bid is None or instrument.ask is None:
        return reject(REJECT_NO_PRICES)
    if (instrument.market_status or "").upper() != TRADEABLE_STATUS:
        return reject(REJECT_NOT_TRADEABLE)
    age = instrument.data_age_seconds
    if age is None or age > MAX_ACCEPTABLE_DATA_AGE_SECONDS or age < 0:
        return reject(REJECT_STALE)
    if spread is None or spread <= 0:
        return reject(REJECT_BAD_SPREAD)

    return SpreadSample(
        taken_at_utc=taken_at_utc,
        snapshot_time=instrument.snapshot_time,
        market_status=instrument.market_status,
        bid=instrument.bid, ask=instrument.ask,
        spread_price=spread, spread_pips=pips,
        data_age_seconds=age,
        accepted=True, reject_reason=None, flags=flags,
    )


# ---------------------------------------------------------------------------
# الإحصاء
# ---------------------------------------------------------------------------

def percentile(values: Sequence[Decimal], fraction: Decimal) -> Optional[Decimal]:
    """
    مئين بترتيب أقرب رتبة (nearest-rank) — حتمي وقابل للتفسير.

    الاستيفاء الخطي يُنتج قيمة **لم تُرصَد قط**، وهو غير مرغوب حين نتحدث عن
    سبريد فعلي: p95 يجب أن تكون عيّنة حقيقية شوهدت، لا متوسطاً بين عيّنتين.
    """
    if not values:
        return None
    if not (0 < fraction <= 1):
        raise ValueError("الكسر يجب أن يقع في (0، 1].")
    ordered = sorted(values)
    rank = int(-(-(fraction * len(ordered)) // 1))     # سقف القسمة
    return ordered[max(0, min(rank - 1, len(ordered) - 1))]


def median(values: Sequence[Decimal]) -> Optional[Decimal]:
    """
    الوسيط. عند عدد زوجي يُعاد **متوسط الوسطيين** بحساب `Decimal` — وهو
    التعريف القياسي للوسيط ويختلف عمداً عن قاعدة أقرب رتبة أعلاه.
    """
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / D("2")


@dataclass(frozen=True)
class SpreadStatistics:
    count_accepted: int
    count_rejected: int
    minimum: Optional[Decimal]
    median: Optional[Decimal]
    p75: Optional[Decimal]
    p95: Optional[Decimal]
    maximum: Optional[Decimal]

    def as_dict(self) -> dict:
        def s(v: Optional[Decimal]) -> Optional[str]:
            return f"{v:.2f}" if v is not None else None

        return {
            "count_accepted": self.count_accepted,
            "count_rejected": self.count_rejected,
            "min_pips": s(self.minimum),
            "median_pips": s(self.median),
            "p75_pips": s(self.p75),
            "p95_pips": s(self.p95),
            "max_pips": s(self.maximum),
        }


def summarise(samples: Sequence[SpreadSample]) -> SpreadStatistics:
    pips = [s.spread_pips for s in samples if s.accepted and s.spread_pips is not None]
    rejected = sum(1 for s in samples if not s.accepted)
    return SpreadStatistics(
        count_accepted=len(pips),
        count_rejected=rejected,
        minimum=min(pips) if pips else None,
        median=median(pips),
        p75=percentile(pips, D("0.75")),
        p95=percentile(pips, D("0.95")),
        maximum=max(pips) if pips else None,
    )


# ---------------------------------------------------------------------------
# التشغيل
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpreadSampleRun:
    epic: str
    started_at_utc: datetime
    finished_at_utc: datetime
    duration_minutes: int
    interval_seconds: int
    samples: tuple[SpreadSample, ...]
    statistics: SpreadStatistics
    operations_sent: tuple[tuple[str, str], ...]
    errors: tuple[str, ...]

    @property
    def flagged_samples(self) -> tuple[SpreadSample, ...]:
        return tuple(s for s in self.samples if s.flags)

    def as_dict(self) -> dict:
        return {
            "epic": self.epic,
            "started_at_utc": self.started_at_utc.isoformat(),
            "finished_at_utc": self.finished_at_utc.isoformat(),
            "duration_minutes": self.duration_minutes,
            "interval_seconds": self.interval_seconds,
            "samples": [s.as_dict() for s in self.samples],
            "statistics": self.statistics.as_dict(),
            "operations_sent": [list(op) for op in self.operations_sent],
            "errors": list(self.errors),
            "authorises_execution": False,
            "single_snapshot_is_not_the_normal_spread": True,
            "profitability_claim": None,
        }


def run_spread_sampling(
    session: LiveSession,
    *,
    duration_minutes: int,
    interval_seconds: int,
    epic: str = SPREAD_SAMPLE_EPIC,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleeper: Callable[[float], None] = None,
) -> SpreadSampleRun:
    """
    يأخذ عيّنات على فترات، بجلسة مصادقة **واحدة** أُنشئت خارج هذه الدالة.

    الدالة **لا تُصادق ولا تُعيد المصادقة** — تستقبل جلسة مُصادَقاً عليها.
    وهذا ليس تفصيلاً: إعادة المصادقة داخل حلقة هي أسرع طريق إلى قفل الحساب.
    """
    if epic != SPREAD_SAMPLE_EPIC:
        raise SpreadSamplerError(
            f"هذا الأمر مقصور على {SPREAD_SAMPLE_EPIC} — لا يقبل {epic}."
        )
    if duration_minutes <= 0:
        raise SpreadSamplerError("المدة يجب أن تكون موجبة.")
    if interval_seconds < 5:
        raise SpreadSamplerError("الفاصل الأدنى 5 ثوانٍ — احتراماً لحدود الوسيط.")
    if not session.authenticated:
        raise SpreadSamplerError("الجلسة غير مُصادَق عليها، ولا تُصادِق هذه الدالة.")

    import time as _time
    sleep = sleeper if sleeper is not None else _time.sleep

    started = clock()
    deadline = started + timedelta(minutes=duration_minutes)
    samples: list[SpreadSample] = []
    errors: list[str] = []

    # سقف صلب لعدد اللقطات، مستقلٌّ عن الساعة.
    # ساعةٌ لا تتقدّم — تراجُع NTP، أو ساعة معطوبة — تُحوّل «حتى الموعد» إلى
    # حلقة أبدية تقصف الوسيط بالطلبات حتى يقفل الحساب. الحد الزمني وحده لا
    # يكفي حارساً حين يكون الزمن نفسه هو المتغيّر المشكوك فيه.
    max_samples = int(duration_minutes * 60 // interval_seconds) + 2

    while len(samples) < max_samples:
        now = clock()
        if now > deadline:
            break
        try:
            response = session.get(f"/api/v1/markets/{epic}")
            instrument = _extract_instrument(epic, response.body, now)
            samples.append(build_sample(instrument, taken_at_utc=now, epic=epic))
        except Exception as exc:                     # noqa: BLE001 — يُسجَّل ويُكمل
            errors.append(f"{type(exc).__name__}: {exc}")
        if clock() + timedelta(seconds=interval_seconds) > deadline:
            break
        sleep(float(interval_seconds))

    return SpreadSampleRun(
        epic=epic,
        started_at_utc=started,
        finished_at_utc=clock(),
        duration_minutes=duration_minutes,
        interval_seconds=interval_seconds,
        samples=tuple(samples),
        statistics=summarise(samples),
        operations_sent=tuple(getattr(session.transport, "sent", ()) or ()),
        errors=tuple(errors),
    )


def render_spread_report(run: SpreadSampleRun) -> str:
    """تقرير **غير حسّاس**: أسعار وسبريد فقط. لا قيمة حساب ولا ادعاء ربح."""
    stats = run.statistics
    lines = [
        f"# توزيع سبريد {run.epic}",
        "",
        "> **تقرير عام.** لا رصيد ولا أموال متاحة ولا ربح/خسارة ولا معرّف حساب.",
        "> لم يُطلب من الوسيط أي بيانات حساب أصلاً — القياس لا يحتاجها.",
        "",
        "> **لا لقطة واحدة تساوي «السبريد المعتاد»** — ولا حتى الوسيط.",
        "> ما يلي توزيعٌ لفترة محدودة، لا خاصيةٌ ثابتة للأداة.",
        "",
        "| البند | القيمة |",
        "|---|---|",
        f"| البداية (UTC) | {run.started_at_utc.isoformat()} |",
        f"| النهاية (UTC) | {run.finished_at_utc.isoformat()} |",
        f"| المدة المطلوبة | {run.duration_minutes} دقيقة |",
        f"| الفاصل | {run.interval_seconds} ثانية |",
        f"| عيّنات مقبولة | {stats.count_accepted} |",
        f"| عيّنات مرفوضة | {stats.count_rejected} |",
        "",
    ]

    if stats.count_accepted == 0:
        lines += [
            "> ⛔ **لا عيّنة مقبولة واحدة.** لا يُستخرج توزيع من لا شيء،",
            "> ولن يُقدَّم رقم بديل.",
            "",
        ]
    else:
        def p(v):
            return f"{v:.2f}" if v is not None else "—"
        lines += [
            "## التوزيع (بالنقاط)",
            "",
            "| الإحصاء | النقاط |",
            "|---|---|",
            f"| الأدنى | {p(stats.minimum)} |",
            f"| الوسيط | {p(stats.median)} |",
            f"| p75 | {p(stats.p75)} |",
            f"| **p95** | **{p(stats.p95)}** |",
            f"| الأقصى | {p(stats.maximum)} |",
            "",
            "> **p95 هو الرقم الذي يُخطَّط عليه**، لا الوسيط: التكلفة التي تؤذي",
            "> هي التي تصادفك في أسوأ الأوقات لا في أوسطها.",
            "",
        ]

    flagged = run.flagged_samples
    lines += ["## عيّنات قرب الإغلاق أو التجديد", ""]
    if not flagged:
        lines += ["لا عيّنة وقعت في نافذة إغلاق أو تجديد.", ""]
    else:
        lines += [
            "> السبريد يتّسع بنيوياً في هذه النوافذ. إدراجها في المتوسط بلا وسم",
            "> يُنتج رقماً لا يصف أي ساعة تداول فعلية.",
            "",
            "| اللحظة (UTC) | النقاط | الوسم | مقبولة؟ |",
            "|---|---|---|---|",
        ]
        for s in flagged:
            pips = f"{s.spread_pips:.2f}" if s.spread_pips is not None else "—"
            lines.append(
                f"| {s.taken_at_utc.isoformat()} | {pips} | "
                f"{'، '.join(s.flags)} | {'نعم' if s.accepted else 'لا'} |"
            )
        lines.append("")

    rejected = [s for s in run.samples if not s.accepted]
    if rejected:
        lines += ["## عيّنات مرفوضة", "", "| اللحظة (UTC) | السبب |", "|---|---|"]
        for s in rejected:
            lines.append(f"| {s.taken_at_utc.isoformat()} | `{s.reject_reason}` |")
        lines.append("")

    lines += [
        "## ما لا يعنيه هذا التقرير",
        "",
        "- **لا يدّعي ربحية**، ولا يقترب من ادعائها.",
        "- **لا يأذن بالتنفيذ.** لا استراتيجية معتمدة، وقفل Live مغلق.",
        "- فترة قياس واحدة ليست كل الظروف: الأخبار وأوقات الجلسات وأيام العطل",
        "  تُغيّر التوزيع. تكرار القياس في أوقات مختلفة هو ما يبني صورة.",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "SPREAD_SAMPLE_EPIC",
    "MAX_ACCEPTABLE_DATA_AGE_SECONDS",
    "REJECT_STALE",
    "REJECT_NOT_TRADEABLE",
    "REJECT_NO_PRICES",
    "REJECT_BAD_SPREAD",
    "FLAG_NEAR_WEEKLY_CLOSE",
    "FLAG_NEAR_DAILY_ROLLOVER",
    "SpreadSample",
    "SpreadStatistics",
    "SpreadSampleRun",
    "SpreadSamplerError",
    "close_flags",
    "build_sample",
    "percentile",
    "median",
    "summarise",
    "run_spread_sampling",
    "render_spread_report",
]
