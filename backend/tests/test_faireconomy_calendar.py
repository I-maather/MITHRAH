"""
اختبارات تقويم FairEconomy — **بلا شبكة**. الناقل مُقلَّد بالكامل.

القاعدة الحاكمة لهذا المزوّد: **يفشل مغلقاً**. تغذيةٌ غائبة أو مبتورة أو
بايتة تجعله غير مُعدّ، فتسقط أهلية التداول ويمتنع النظام. وهذه الاختبارات
تحرس ذلك قبل أن تحرس أي شيء آخر — لأن الخطأ في الاتجاه الآخر يعني نظاماً
يدخل السوق ظانّاً أن التقويم نظيف وهو لم يقرأه.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.intelligence.snapshot import EventCategory, ImpactLevel
from app.providers.faireconomy_calendar import (
    MAX_FEED_AGE,
    MIN_PLAUSIBLE_EVENTS,
    MIN_REFRESH_INTERVAL,
    THIS_WEEK_URL,
    FairEconomyCalendarProvider,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


class Response:
    def __init__(self, status: int, body) -> None:
        self.status = status
        self.body = body
        self.headers: dict = {}


class FakeTransport:
    """يعيد ما حُقن فيه. لا شبكة، ولا مفاجأة."""

    def __init__(self, response=None, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[str] = []
        self.headers: list[dict] = []

    def get(self, url, *, headers=None, secrets=()):
        self.calls.append(url)
        self.headers.append(dict(headers or {}))
        if self._raises is not None:
            raise self._raises
        return self._response


def rows(count: int, *, impact: str = "High", currency: str = "USD",
         at: datetime = NOW, title: str = "Some Event") -> list[dict]:
    return [
        {
            "title": f"{title} {i}",
            "country": currency,
            "date": (at + timedelta(minutes=i)).isoformat(),
            "impact": impact,
            "forecast": "0.2%",
            "previous": "0.1%",
        }
        for i in range(count)
    ]


def provider(response=None, raises=None) -> FairEconomyCalendarProvider:
    return FairEconomyCalendarProvider(transport=FakeTransport(response, raises))


# ---------------------------------------------------------------------------
# يفشل مغلقاً
# ---------------------------------------------------------------------------
def test_starts_unconfigured_before_any_fetch():
    """لا يدّعي جاهزيةً لم تُثبَت."""
    assert provider().configured is False


def test_asking_whether_configured_does_not_fetch():
    """
    سؤالٌ عن الحال لا يُغيّر ما يسأل عنه. ولو جلب هنا لصار عرضُ شاشةٍ في
    التطبيق طلباً شبكياً في كل مرة.
    """
    p = provider(Response(200, rows(20)))
    assert p.configured is False
    assert p.transport.calls == []


def test_network_failure_leaves_it_unconfigured():
    p = provider(raises=ConnectionError("no route"))
    p.refresh()
    assert p.configured is False
    assert "تعذّر" in p.note_ar


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_a_non_200_leaves_it_unconfigured(status):
    p = provider(Response(status, []))
    p.refresh()
    assert p.configured is False
    assert str(status) in p.note_ar


def test_malformed_body_leaves_it_unconfigured():
    p = provider(Response(200, "not json at all"))
    p.refresh()
    assert p.configured is False


def test_a_json_object_instead_of_a_list_is_refused():
    p = provider(Response(200, {"error": "nope"}))
    p.refresh()
    assert p.configured is False


def test_an_empty_feed_is_treated_as_broken_not_as_a_quiet_week():
    """
    **هذا هو درس FMP.** أعادت صفر أحداث بلا خطأ، فبدت «مُعدّة» أسابيع.
    أسبوعُ عملٍ بلا حدثٍ واحد لا يقع؛ فالصفر عطلٌ لا هدوء.
    """
    p = provider(Response(200, []))
    p.refresh()
    assert p.configured is False
    assert "أقلّ من المعقول" in p.note_ar


def test_a_truncated_feed_is_refused():
    p = provider(Response(200, rows(MIN_PLAUSIBLE_EVENTS - 1)))
    p.refresh()
    assert p.configured is False


def test_a_stale_feed_stops_being_configured():
    """
    تغذيةٌ بايتة أخطر من غيابها: الغياب يمنع، والبيات يُطمئن كذباً.
    """
    p = provider(Response(200, rows(20)))
    p.refresh()
    assert p.configured is True
    p._fetched_at = p._fetched_at - MAX_FEED_AGE - timedelta(minutes=1)
    assert p.configured is False


def test_a_failed_refresh_does_not_erase_good_events():
    """إمّا مجموعةٌ صالحة كاملة أو يبقى القديم. لا حالة نصفية."""
    p = provider(Response(200, rows(20)))
    p.refresh()
    before = len(p._events)
    p.transport._raises = ConnectionError("dropped")
    p.refresh()
    assert len(p._events) == before


# ---------------------------------------------------------------------------
# التحليل
# ---------------------------------------------------------------------------
def test_parses_body_delivered_as_a_json_string():
    p = provider(Response(200, json.dumps(rows(20))))
    p.refresh()
    assert p.configured is True


def test_times_are_converted_to_utc_not_assumed():
    """التغذية تعطي إزاحة زمنية؛ تُحترم ولا تُهمَل."""
    row = {
        "title": "FOMC Statement", "country": "USD",
        "date": "2026-08-31T14:00:00-04:00", "impact": "High",
    }
    p = provider(Response(200, [row] + rows(20)))
    p.refresh()
    match = [e for e in p._events if e.name == "FOMC Statement"][0]
    assert match.scheduled_utc == datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def test_a_naive_timestamp_is_dropped_not_guessed():
    """وقتٌ بلا منطقة لا يُفترض له منطقة — الافتراض هنا يزيح الحدث ساعات."""
    naive = {"title": "Naive", "country": "USD",
             "date": "2026-08-31T14:00:00", "impact": "High"}
    p = provider(Response(200, [naive] + rows(20)))
    p.refresh()
    assert all(e.name != "Naive" for e in p._events)


@pytest.mark.parametrize("raw,expected", [
    ("High", ImpactLevel.HIGH),
    ("Medium", ImpactLevel.MEDIUM),
    ("Low", ImpactLevel.LOW),
    ("Holiday", ImpactLevel.LOW),
    ("", ImpactLevel.UNKNOWN),
    ("Bizarre", ImpactLevel.UNKNOWN),
])
def test_impact_mapping(raw, expected):
    """قيمةٌ غير معروفة تصير UNKNOWN — لا LOW. الجهل ليس طمأنينة."""
    row = {"title": "X", "country": "USD",
           "date": NOW.isoformat(), "impact": raw}
    p = provider(Response(200, [row] + rows(20)))
    p.refresh()
    assert [e for e in p._events if e.name == "X"][0].impact is expected


@pytest.mark.parametrize("title,category", [
    ("Non-Farm Employment Change", EventCategory.NFP),
    ("Federal Funds Rate Decision", EventCategory.CENTRAL_BANK_RATE),
    ("Fed Chair Powell Speaks", EventCategory.CENTRAL_BANK_SPEECH),
    ("CPI m/m", EventCategory.INFLATION),
    ("Unemployment Claims", EventCategory.EMPLOYMENT),
    ("Flash Manufacturing PMI", EventCategory.PMI),
    ("Retail Sales m/m", EventCategory.RETAIL_SALES),
    ("Something Unclassifiable", EventCategory.OTHER),
])
def test_category_from_title(title, category):
    row = {"title": title, "country": "USD",
           "date": NOW.isoformat(), "impact": "High"}
    p = provider(Response(200, [row] + rows(20)))
    p.refresh()
    assert [e for e in p._events if e.name == title][0].category is category


def test_event_id_is_stable_across_refreshes():
    """
    التغذية لا تعطي معرّفاً. لو اشتُقّ من الترتيب لصار الحدث الواحد حدثين
    بعد كل تحديث، ولتكرّر الحجب أو سقط.
    """
    p = provider(Response(200, rows(20)))
    p.refresh()
    first = [e.event_id for e in p._events]
    p.refresh()
    assert [e.event_id for e in p._events] == first


# ---------------------------------------------------------------------------
# الاستعلام
# ---------------------------------------------------------------------------
def test_events_are_filtered_by_window():
    p = provider(Response(200, rows(30)))
    p.refresh()
    got = p.events(
        currencies=["USD"],
        window_start_utc=NOW + timedelta(minutes=5),
        window_end_utc=NOW + timedelta(minutes=10),
    )
    assert got and all(
        NOW + timedelta(minutes=5) <= e.scheduled_utc <= NOW + timedelta(minutes=10)
        for e in got
    )


def test_events_are_filtered_by_currency():
    body = rows(15, currency="USD") + rows(15, currency="JPY", title="JP Event")
    p = provider(Response(200, body))
    p.refresh()
    got = p.events(
        currencies=["USD"],
        window_start_utc=NOW - timedelta(days=1),
        window_end_utc=NOW + timedelta(days=1),
    )
    assert got
    assert all("JP Event" not in e.name for e in got)


def test_events_without_a_currency_are_always_returned():
    """اجتماعٌ كـG20 أثره لا يقتصر على عملة، فلا يُحجب بمرشّح العملة."""
    g20 = {"title": "G20 Meetings", "country": "All",
           "date": NOW.isoformat(), "impact": "Low"}
    p = provider(Response(200, [g20] + rows(20)))
    p.refresh()
    got = p.events(
        currencies=["EUR"],
        window_start_utc=NOW - timedelta(hours=1),
        window_end_utc=NOW + timedelta(hours=1),
    )
    assert any(e.name == "G20 Meetings" for e in got)


def test_querying_an_unconfigured_provider_returns_nothing_and_does_not_raise():
    """
    الاستعلام لا يرفع استثناءً: خطّ القرار يجب أن يقرأ «لا أحداث معروفة»
    فيمتنع، لا أن ينهار داخل معالج خطأ.
    """
    p = provider(raises=ConnectionError("down"))
    got = p.events(
        currencies=["USD"],
        window_start_utc=NOW,
        window_end_utc=NOW + timedelta(hours=2),
    )
    assert got == ()
    assert p.configured is False


def test_querying_fetches_once_when_not_yet_loaded():
    p = provider(Response(200, rows(20)))
    assert p.transport.calls == []
    p.events(currencies=["USD"], window_start_utc=NOW,
             window_end_utc=NOW + timedelta(hours=2))
    assert len(p.transport.calls) == 1


def test_the_request_identifies_itself():
    """
    **العطل الذي كلّف يوماً.** التغذية خلف شبكة توصيل ترفض العملاء بلا
    هويّة: الخادم أعاد 404 بينما العنوان نفسه يعطي ١٢٧ حدثاً من شبكة أخرى.
    و404 هناك ليست «غير موجود» بل «لن أخدمك».

    ولو حُذفت الترويسة في إعادة صياغة لاحقة، لعاد الحارس ميّتاً بصمت —
    فتُثبَّت هنا.
    """
    p = provider(Response(200, rows(20)))
    p.refresh()
    assert p.transport.headers[0].get("User-Agent")


def test_the_identity_does_not_impersonate_a_named_browser():
    """
    الهويّة تُعلن أن العميل برنامج وتسمّيه. وانتحال متصفّح بعينه كذبٌ على
    المضيف، وغير لازم لتجاوز فحصٍ يسأل عن الهويّة لا عن نوعها.
    """
    from app.providers.faireconomy_calendar import REQUEST_HEADERS

    agent = REQUEST_HEADERS["User-Agent"]
    assert "mathrah" in agent.lower()
    for browser in ("chrome", "safari", "firefox", "edge"):
        assert browser not in agent.lower()


def test_a_non_200_reports_what_the_body_said():
    """
    «404» وحدها أرسلتنا نبحث في الكود عن خطأ في العنوان بينما الرفض كان من
    شبكة التوصيل. الرمز وحده لا يشخّص.
    """
    p = provider(Response(404, "Sorry, you have been blocked"))
    p.refresh()
    assert "404" in p.note_ar
    assert "blocked" in p.note_ar


# ---------------------------------------------------------------------------
# عنوانٌ واحد، وبلا إلحاح
# ---------------------------------------------------------------------------
def test_only_one_url_is_requested():
    """
    **العطل الذي منع التقويم من العمل يوماً كاملاً.**

    كان يُجلب عنوانان: الأسبوع الجاري ثم الأسبوع القادم. والثاني **غير
    موجود** — 404 دائماً. فينجح الأول ثم يسقط الثاني، فتُلغى الجلبة
    الناجحة كلها بحكم الذرّية. تقويمٌ لا يمكن أن يُعدّ أبداً، وسببٌ معروض
    يشير إلى المكان الخطأ: «التقويم أعاد 404» بينما التقويم أعطى ١٢٧ حدثاً.
    """
    p = provider(Response(200, rows(20)))
    p.refresh()
    assert p.transport.calls == [THIS_WEEK_URL]


def test_a_recent_successful_fetch_is_not_repeated():
    """
    المضيف يردّ 429 على من يُلحّ — رأيناه: ستة طلبات في نداءين متتاليين
    كفت لتحويل 200 إلى 429. والتغذية أسبوعية، فالإلحاح بلا مقابل.
    """
    p = provider(Response(200, rows(20)))
    p.refresh()
    p.refresh()
    assert len(p.transport.calls) == 1


def test_the_interval_is_bypassed_only_when_asked():
    """`force` للمسبار حين يكون الغرض قياس المضيف لا استعمال البيانات."""
    p = provider(Response(200, rows(20)))
    p.refresh()
    p.refresh(force=True)
    assert len(p.transport.calls) == 2


def test_a_failed_fetch_may_be_retried_immediately():
    """
    القيد على النجاح لا على الإخفاق. لو قيّد الإخفاق أيضاً لبقي التقويم
    معطّلاً عشرين دقيقة بعد انقطاعٍ دام ثانية.
    """
    p = provider(raises=ConnectionError("down"))
    p.refresh()
    p.refresh()
    assert len(p.transport.calls) == 2


def test_too_many_requests_is_reported_as_such():
    p = provider(Response(429, "<html><body>Rate Limited</body></html>"))
    p.refresh()
    assert p.configured is False
    assert "429" in p.note_ar
    assert "Rate Limited" in p.note_ar
    assert "<" not in p.note_ar          # الوسوم تُنزع قبل العرض


def test_the_stale_interval_is_far_longer_than_the_refresh_interval():
    """
    لو تقارب القيدان لتعذّر التحديث قبل البيات، فسقطت الأهلية دورياً بلا
    سبب مفهوم.
    """
    assert MIN_REFRESH_INTERVAL * 4 < MAX_FEED_AGE
