"""
تقويم اقتصادي مجاني — تغذية FairEconomy الأسبوعية.

## لماذا هذا المزوّد

مسبار FMP أثبت أن التقويم **خارج الخطة المجانية**: أعاد صفر أحداث، لا
لعطلٍ بل لأن الطبقة لا تشمله. والتقويم ليس زينة — هو الحارس الذي يمنع
الدخول قبل خبرٍ عالي الأثر، وهي اللحظة التي يقفز فيها السعر عشرات النقاط
في ثانية بينما وقفُنا خمسٌ وعشرون.

وبدائل مجانية كثيرة تعطي **تاريخاً بلا وقت** — ومنها FRED. وتاريخٌ بلا
وقت يعني حجب اليوم كلّه، وهو حارسٌ يمنع أكثر مما يحمي.

وهذه التغذية تعطي الوقت الدقيق بمنطقته الزمنية، والعملة، ومستوى الأثر:

    {"title":"Prelim Industrial Production m/m","country":"JPY",
     "date":"2026-08-30T19:50:00-04:00","impact":"Low",
     "forecast":"-0.7%","previous":"1.3%"}

## ما يجب أن تعرفه المالكة عن هذا الاختيار

**هذه تغذية عامة، لا واجهة تعاقدية.** لا اتفاق خدمة، ولا ضمان استمرار،
وقد يتغيّر شكلها أو تُغلق بلا إشعار. مقابل ذلك: بلا مفتاح، وبلا اشتراك،
وبوقتٍ دقيق.

ولذلك بُني **فاشلاً مغلقاً**: أي إخفاق في الجلب أو الشكل أو الطزاجة يجعل
المزوّد `configured=False`، فتسقط أهلية التداول ويمتنع النظام. لا يُخمَّن
حدث، ولا تُفترض سلامة السوق من صمت التغذية.

وحين تقررين الاشتراك في مزوّد تعاقدي، يُستبدل هذا الملف وحده.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Optional, Sequence

from ..clock import now_utc
from ..intelligence.providers import EconomicCalendarProvider
from ..intelligence.snapshot import UNKNOWN, EconomicEvent, EventCategory, ImpactLevel
from .http import ProviderTransport

PROVIDER_NAME = "faireconomy-calendar"

#: التغذية الأسبوعية. الأسبوع الجاري يكفي لحارسٍ مداه ساعات.
THIS_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEXT_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

#: أقصى عمر مقبول للتغذية. أقدم من ذلك ⇒ لا يُعتمد عليها.
#: تغذيةٌ بايتة أخطر من غيابها: الغياب يمنع، والبيات يُطمئن كذباً.
MAX_FEED_AGE = timedelta(hours=12)

#: أقلّ عدد أحداث يُتوقَّع في أسبوع عمل. أقلّ منه ⇒ التغذية مبتورة.
#: صفرُ أحداث هو بالضبط ما أعادته FMP حين مُنعت — ولم نعرف إلا بالمسبار.
MIN_PLAUSIBLE_EVENTS = 10

_IMPACT = {
    "high": ImpactLevel.HIGH,
    "medium": ImpactLevel.MEDIUM,
    "low": ImpactLevel.LOW,
    "holiday": ImpactLevel.LOW,
}

#: تصنيف الحدث من عنوانه. الترتيب مقصود: الأخصّ قبل الأعمّ.
_CATEGORY_HINTS: tuple[tuple[tuple[str, ...], EventCategory], ...] = (
    (("non-farm", "nonfarm", "non farm"), EventCategory.NFP),
    (("rate decision", "rate statement", "interest rate", "fomc statement",
      "cash rate", "official bank rate"), EventCategory.CENTRAL_BANK_RATE),
    (("speaks", "speech", "testimony", "press conference", "minutes"),
     EventCategory.CENTRAL_BANK_SPEECH),
    (("cpi", "ppi", "inflation", "price index"), EventCategory.INFLATION),
    (("employment", "unemployment", "jobless", "payrolls", "claims"),
     EventCategory.EMPLOYMENT),
    (("gdp",), EventCategory.GDP),
    (("pmi",), EventCategory.PMI),
    (("retail sales",), EventCategory.RETAIL_SALES),
)


def _category_of(title: str) -> EventCategory:
    lowered = title.lower()
    for needles, category in _CATEGORY_HINTS:
        if any(needle in lowered for needle in needles):
            return category
    return EventCategory.OTHER


class CalendarFeedError(RuntimeError):
    """التغذية غير صالحة. لا تُبتلع — المزوّد يصير غير مُعدّ."""


@dataclass
class FairEconomyCalendarProvider(EconomicCalendarProvider):
    """
    تقويم اقتصادي بلا مفتاح.

    `configured` يعني **«جُلبت تغذية صالحة وطازجة»**، لا «العنوان مكتوب في
    الكود». وهذا الفرق هو ما ضاع علينا مع FMP: كانت «مُعدّة» وتعيد صفراً.
    """

    transport: ProviderTransport = None  # type: ignore[assignment]
    include_next_week: bool = True

    _events: tuple[EconomicEvent, ...] = field(default_factory=tuple, init=False)
    _fetched_at: Optional[datetime] = field(default=None, init=False)
    _failure_ar: str = field(default="", init=False)

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = ProviderTransport()

    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def configured(self) -> bool:
        """
        لا يُجلب هنا. سؤالٌ عن الحال لا يُغيّر ما يسأل عنه، وإلا صار عرضُ
        شاشةٍ في التطبيق جلباً شبكياً.
        """
        if self._fetched_at is None:
            return False
        return (now_utc() - self._fetched_at) <= MAX_FEED_AGE

    @property
    def note_ar(self) -> str:
        if self._failure_ar:
            return self._failure_ar
        if self._fetched_at is None:
            return "لم تُجلب التغذية بعد."
        return f"{len(self._events)} حدثاً · جُلبت {self._fetched_at:%H:%M} UTC"

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """
        يجلب التغذية ويستبدل المحفوظ **ذرّياً**: إمّا مجموعةٌ صالحة كاملة،
        أو يبقى القديم وتُسجَّل العلّة. لا حالة نصفية.
        """
        urls = [THIS_WEEK_URL] + ([NEXT_WEEK_URL] if self.include_next_week else [])
        collected: list[EconomicEvent] = []
        retrieved = now_utc()

        for url in urls:
            try:
                response = self.transport.get(url)
            except Exception as exc:  # noqa: BLE001
                self._failure_ar = f"تعذّر جلب التقويم ({type(exc).__name__})."
                return
            if getattr(response, "status", 0) != 200:
                self._failure_ar = f"التقويم أعاد رمز {getattr(response, 'status', '?')}."
                return
            try:
                raw = response.body
                rows = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                if not isinstance(rows, list):
                    raise CalendarFeedError("الجذر ليس قائمة")
            except Exception as exc:  # noqa: BLE001
                self._failure_ar = f"شكل التقويم غير متوقَّع ({type(exc).__name__})."
                return
            collected.extend(self._parse(rows, retrieved))

        if len(collected) < MIN_PLAUSIBLE_EVENTS:
            # صفرٌ أو قلّةٌ شاذّة تعني تغذيةً مبتورة، لا أسبوعاً هادئاً.
            self._failure_ar = (
                f"التقويم أعاد {len(collected)} حدثاً فقط — أقلّ من المعقول. "
                "يُعامَل كغير مُعدّ."
            )
            return

        self._events = tuple(sorted(collected, key=lambda e: e.scheduled_utc))
        self._fetched_at = retrieved
        self._failure_ar = ""

    def _parse(self, rows: Sequence[dict], retrieved: datetime) -> list[EconomicEvent]:
        out: list[EconomicEvent] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            currency = str(row.get("country") or "").strip().upper()
            raw_date = str(row.get("date") or "").strip()
            if not title or not raw_date:
                continue
            try:
                scheduled = datetime.fromisoformat(raw_date)
            except ValueError:
                continue
            if scheduled.tzinfo is None:
                # وقتٌ بلا منطقة لا يُفترض له منطقة — يُسقَط.
                continue
            scheduled = scheduled.astimezone(timezone.utc)

            impact = _IMPACT.get(str(row.get("impact") or "").strip().lower(),
                                 ImpactLevel.UNKNOWN)
            #: مُعرّف ثابت مشتقّ من محتوى الحدث — التغذية لا تعطي معرّفاً،
            #: والاعتماد على الترتيب يجعل نفس الحدث حدثين بعد كل تحديث.
            event_id = sha256(
                f"{title}|{currency}|{scheduled.isoformat()}".encode("utf-8")
            ).hexdigest()[:16]

            out.append(EconomicEvent(
                event_id=event_id,
                name=title,
                category=_category_of(title),
                currencies=(currency,) if currency and currency != "ALL" else (),
                impact=impact,
                scheduled_utc=scheduled,
                provider=PROVIDER_NAME,
                provider_timestamp_utc=retrieved,
                retrieved_at_utc=retrieved,
                expected_value=row.get("forecast") or UNKNOWN,
                previous_value=row.get("previous") or UNKNOWN,
                source_reference=THIS_WEEK_URL,
            ))
        return out

    # ------------------------------------------------------------------
    def events(
        self,
        *,
        currencies: Sequence[str],
        window_start_utc: datetime,
        window_end_utc: datetime,
    ) -> tuple[EconomicEvent, ...]:
        """
        أحداث النافذة للعملات المطلوبة.

        يُجلب عند الحاجة فقط: أوّل نداء، أو حين تبيت المحفوظة. والأحداث
        التي لا عملة لها (اجتماعات عامة كـG20) تُعاد دائماً — أثرها لا
        يقتصر على عملة.
        """
        if not self.configured:
            self.refresh()
        if not self.configured:
            return ()

        wanted = {c.strip().upper() for c in currencies if c}
        return tuple(
            e for e in self._events
            if window_start_utc <= e.scheduled_utc <= window_end_utc
            and (not e.currencies or not wanted or bool(set(e.currencies) & wanted))
        )
