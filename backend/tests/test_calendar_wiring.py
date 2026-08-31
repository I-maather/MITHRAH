"""
حارس وصل التقويم في السجلّ.

## القاعدة التي يحرسها

التقويم هو ما يمنع الدخول قبل خبرٍ عالي الأثر — اللحظة التي يقفز فيها
السعر عشرات النقاط ووقفُنا خمسٌ وعشرون. فالخطأ فيه ليس نقصَ ميزة، بل
حارسٌ يقول «نظيف» وهو لم يقرأ.

ولذلك ثلاثة أشياء ممنوعة هنا بالاسم:

* **ألّا يُستبدَل التقويم بـFMP.** ثبت بالمسبار أن تقويم FMP خارج الخطة
  المجانية: يعيد صفر أحداث **بلا خطأ**. وبديلٌ يعيد صفراً بلا شكوى ليس
  بديلاً بل تمويه — وهو ما جعلنا نظنّ التقويم عاملاً أسابيع.
* **ألّا يُجلَب عند بناء النظام.** إقلاعٌ معلّق بشبكةٍ خارجية، وانقطاعٌ
  عابر يُعطّل الحارس لعمر العملية.
* **ألّا يبدأ مُعدّاً.** قبل أوّل جلبٍ ناجح لا يعرف النظام شيئاً عن
  الأحداث، فيجب أن يقول ذلك — لا أن يسكت.
"""
from __future__ import annotations

from app.api.state import build_provider_registry
from app.intelligence.providers import ProviderKind
from app.providers.faireconomy_calendar import FairEconomyCalendarProvider
from app.secretstore.provider import InMemorySecretProvider


class BrokerWithoutSession:
    pass


def registry(**kv):
    return build_provider_registry(
        InMemorySecretProvider(dict(kv)), broker=BrokerWithoutSession()
    )


def test_the_calendar_is_the_free_feed():
    assert isinstance(registry().calendar, FairEconomyCalendarProvider)


def test_an_fmp_key_does_not_bring_fmp_back():
    """
    **درس FMP.** وجود المفتاح لا يعني أن الخطة تشمل التقويم. ولو عاد يوماً
    مزوّداً معتمَداً فليَعُد بقرارٍ مكتوب بعد مسبارٍ يثبت أنه يعطي — لا
    لأن مفتاحه صادف وجوده في الأسرار.
    """
    calendar = registry(FMP_API_KEY="a" * 32).calendar
    assert isinstance(calendar, FairEconomyCalendarProvider)
    assert "fmp" not in calendar.name.lower()


def test_building_the_registry_does_not_touch_the_network():
    """
    لو جلب البناء لكان الإقلاع معلّقاً بتغذيةٍ خارجية — وهذا الاختبار نفسه
    كان سيضرب الشبكة في كل تشغيل للمجموعة.
    """
    calendar = registry().calendar
    assert calendar._fetched_at is None


def test_the_calendar_starts_unconfigured_so_trading_is_blocked_until_it_loads():
    """قبل أوّل جلب: «لا أعرف» — لا «لا أحداث»."""
    assert ProviderKind.ECONOMIC_CALENDAR in registry().missing()


def test_the_calendar_needs_no_key():
    """
    لا يسقط لغياب سرّ. هذا هو سبب اختياره: حارسٌ لا يتعطّل عند انتهاء اشتراك.
    """
    assert registry().calendar is not None
