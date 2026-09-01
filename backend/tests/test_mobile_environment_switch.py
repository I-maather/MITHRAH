"""
التبديل بين الحساب التجريبي والحقيقي من الجوال.

## لماذا هذا مقبولٌ من هاتفٍ قد يُسرق

**لأنه ليس مفتاح التداول.** يغيّر الحساب الذي **يُقرأ منه ويُتصل به**، ولا
يفتح الإرسال. وثلاثة أقفال مستقلّة تبقى خارج متناوله:

    LIVE_TRADING           في بيئة الخادم، بيد المالكة وحدها
    ExecutionLock          يرفض كل فعلٍ مُعدِّل قبل مغادرة الطلب
    رفض `is_live`          داخل `place_order` نفسه

⇒ جهازٌ مسروق يبدّل إلى الحساب الحقيقي، **ولا يرسل أمراً واحداً**. أقصى ما
يفعله أن يرى رصيداً.

## وبصمة الوجه ليست الحارس الكافي

هي تحمي من **شخصٍ آخر** يمسك الهاتف — لا من ضغطةٍ خاطئة واليد يد المالكة
والهاتف مفتوح. فالعبارة تحرس ما لا تحرسه البصمة.

## والاتجاه المعاكس لا يطلب عبارة

العودة إلى التجريبي **تقلّل المخاطرة**. وحارسٌ يعرقل التراجع عن الخطر ليس
حارساً — هو عقبةٌ في أسوأ لحظة.
"""
from __future__ import annotations

import pytest

from app.mobile.api import (
    LIVE_ENVIRONMENT_PHRASE,
    RISK_INCREASING_ROUTES,
    RISK_REDUCING_ROUTES,
    MobileActions,
    MobileApi,
    MobileApiError,
)
from tests.test_mobile_backend import enrolled, service

ROUTE = "broker/environment"


class Switcher:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, target: str) -> dict:
        if self.fail is not None:
            raise self.fail
        self.calls.append(target)
        return {
            "environment": target,
            "is_demo": target == "DEMO",
            "broker_name": f"CAPITAL_COM_{target}",
        }


def paired(actions=None):
    svc = service()
    device = enrolled(svc)
    access, _ = svc.issue_tokens(device.device_id)
    return MobileApi(security=svc, actions=actions or MobileActions()), access.token


def api_with_switch(fail=None):
    switcher = Switcher(fail=fail)
    api, token = paired(MobileActions(switch_environment=switcher))
    return api, token, switcher


def switch(api, token, target, **extra):
    payload = {"target": target}
    payload.update(extra)
    return api.handle("POST", ROUTE, token=token, payload=payload)


# ---------------------------------------------------------------------------
# العقد
# ---------------------------------------------------------------------------

def test_the_route_is_declared_as_risk_increasing_not_risk_reducing():
    assert ROUTE in RISK_INCREASING_ROUTES
    assert ROUTE not in RISK_REDUCING_ROUTES


def test_the_route_name_carries_no_forbidden_token():
    """`order` و`position/close` وأمثالهما ممنوعة في أي مسار من هذا المجال."""
    from app.mobile.api import FORBIDDEN_ROUTE_TOKENS

    for token in FORBIDDEN_ROUTE_TOKENS:
        assert token not in ROUTE


# ---------------------------------------------------------------------------
# الاتجاه الآمن: العودة إلى التجريبي
# ---------------------------------------------------------------------------

def test_going_back_to_demo_needs_no_phrase():
    """حارسٌ يعرقل التراجع عن الخطر ليس حارساً."""
    api, token, switcher = api_with_switch()
    body = switch(api, token, "DEMO").body
    assert body["accepted"] is True and body["is_demo"] is True
    assert switcher.calls == ["DEMO"]


# ---------------------------------------------------------------------------
# الاتجاه الخطر: الانتقال إلى الحقيقي
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("confirm", ["", "نعم", "أنتقل", "انتقل إلى الحساب الحقيقي"])
def test_going_live_without_the_exact_phrase_changes_nothing(confirm):
    api, token, switcher = api_with_switch()
    with pytest.raises(MobileApiError) as exc:
        switch(api, token, "LIVE", confirm=confirm)
    assert exc.value.status == 400
    assert switcher.calls == [], "بُدِّلت البيئة رغم رفض العبارة"


def test_the_exact_phrase_switches_to_live():
    api, token, switcher = api_with_switch()
    body = switch(api, token, "LIVE", confirm=LIVE_ENVIRONMENT_PHRASE).body
    assert body["environment"] == "LIVE" and body["is_demo"] is False
    assert switcher.calls == ["LIVE"]


def test_the_reply_says_plainly_that_no_trading_opened():
    """
    شاشةٌ تقول «انتقلتِ إلى الحقيقي» بلا أكثر تُقرأ «صار يتداول بمالي».
    والحقيقة أنه يقرأ فقط — وقولها في نصّ الردّ لا في وثيقةٍ جانبية.
    """
    api, token, _ = api_with_switch()
    note = switch(api, token, "LIVE", confirm=LIVE_ENVIRONMENT_PHRASE).body["note_ar"]
    assert "لم يُفتح تداول" in note
    assert "قفل التنفيذ" in note


# ---------------------------------------------------------------------------
# الرفض والفشل المغلق
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", ["", "PAPER", "live "])
def test_an_unknown_destination_is_refused(target):
    api, token, switcher = api_with_switch()
    with pytest.raises(MobileApiError) as exc:
        switch(api, token, target)
    assert exc.value.status == 400
    assert switcher.calls == []


def test_an_unwired_switch_fails_closed():
    api, token = paired(MobileActions())
    with pytest.raises(MobileApiError) as exc:
        switch(api, token, "DEMO")
    assert exc.value.status == 503, "قيل «تمّ» ولا شيء موصول"


def test_a_broker_that_will_not_connect_leaves_the_environment_alone():
    """
    **يفشل مغلقاً.** الوسيط الجديد يُوصَل قبل أن يحلّ محلّ القديم؛ فإن أخفق
    بقيت البيئة كما هي — بدل نظامٍ بلا وسيطٍ أصلاً، وهو أسوأ من نظامٍ على
    الحساب السابق.
    """
    blocked = MobileApiError("تعذّر الوصل بحساب LIVE — لم تتغيّر البيئة.", status=502)
    api, token, _ = api_with_switch(fail=blocked)
    with pytest.raises(MobileApiError) as exc:
        switch(api, token, "LIVE", confirm=LIVE_ENVIRONMENT_PHRASE)
    assert exc.value.status == 502 and "لم تتغيّر البيئة" in str(exc.value)


def test_every_outcome_is_audited_with_its_truth():
    """رفضٌ يُدوَّن إخفاقاً، ونجاحٌ يُدوَّن نجاحاً. وسجلٌّ يقول غير ما وقع أسوأ من لا سجلّ."""
    api, token, _ = api_with_switch()
    with pytest.raises(MobileApiError):
        switch(api, token, "LIVE", confirm="لا")
    switch(api, token, "DEMO")

    entries = [e.as_dict() for e in api.security.audit()]
    assert any(
        e["action"] == "MOBILE_ENVIRONMENT_REFUSED" and e["success"] is False
        for e in entries
    )
    assert any(
        e["action"] == "MOBILE_ENVIRONMENT_SWITCHED" and e["success"] is True
        for e in entries
    )


# ---------------------------------------------------------------------------
# الأقفال الثلاثة لا تُمسّ
# ---------------------------------------------------------------------------

def test_the_switch_touches_no_lock():
    """
    فحصٌ ساكن على المُنفِّذ نفسه: لا يكتب `live_trading`، ولا يفتح قفل
    تنفيذ، ولا يقلب ثابت أمان. تبديلُ حسابٍ يمسّ قفلاً لم يعد تبديل حساب.
    """
    import inspect

    from app.main import _mobile_switch_environment

    source = inspect.getsource(_mobile_switch_environment)
    for forbidden in ("live_trading", "authorise", "LIVE_API_ENABLED", "STOP_DISTANCE"):
        assert forbidden not in source, f"المُنفِّذ يمسّ {forbidden}"
    assert "execution_lock" not in source, "يمرّر قفل تنفيذ — والافتراضي مغلق"


# ---------------------------------------------------------------------------
# المُنفِّذ نفسه — لا المُقلَّد
#
# ⚠️ **درسٌ من طفرةٍ لم تعضّ.** كانت الفحوص أعلاه تحقن `switch_environment`
# مُقلَّداً، فلم يكن أيٌّ منها يمرّ بالدالة الحقيقية. وإسقاط `candidate.connect()`
# منها لم يُسقط اختباراً واحداً — أي أن «يفشل مغلقاً» كان **ادّعاءً بلا حارس**.
# ---------------------------------------------------------------------------

class FakeAdapter:
    def __init__(self, *, live: bool, connects: bool = True) -> None:
        self.is_live = live
        self.name = "CAPITAL_COM_LIVE" if live else "CAPITAL_COM_DEMO"
        self.connects = connects
        self.connected = False

    def connect(self) -> None:
        if not self.connects:
            raise ConnectionError("الوسيط لا يستجيب")
        self.connected = True


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[str] = []

    def record(self, **kw) -> None:
        self.records.append(kw.get("decision", ""))


class FakeSystem:
    def __init__(self) -> None:
        self.broker = FakeAdapter(live=False)
        self.broker_note_ar = "ملاحظة قديمة"
        self.audit = FakeAudit()
        self.settings = type("S", (), {"secrets_file": "/dev/null"})()


def install(monkeypatch, *, candidate: FakeAdapter) -> FakeSystem:
    import app.main as main

    fake = FakeSystem()
    monkeypatch.setattr(main, "system", lambda: fake)
    monkeypatch.setattr(
        "app.secretstore.provider.build_secret_provider", lambda **kw: object()
    )
    # **تُلتقط البيئة المطلوبة**، لا يُكتفى بما يعيده المحوّل المُقلَّد:
    # مُقلَّدٌ يعيد ما نريد يمرّ حتى لو طُلبت البيئة الخطأ تماماً.
    asked: list = []

    def capture(environment, **kwargs):
        asked.append(environment)
        return candidate

    monkeypatch.setattr("app.brokers.factory.build_capital_adapter", capture)
    fake.asked = asked          # type: ignore[attr-defined]
    return fake


def test_a_broker_that_cannot_connect_never_replaces_the_working_one(monkeypatch):
    """
    **العطل الذي تمنعه:** استبدالُ الوسيط قبل التحقّق من وصله يترك النظام
    بلا وسيطٍ أصلاً — وهو أسوأ من نظامٍ على الحساب السابق.
    """
    import app.main as main

    broken = FakeAdapter(live=True, connects=False)
    fake = install(monkeypatch, candidate=broken)
    before = fake.broker

    with pytest.raises(MobileApiError) as exc:
        main._mobile_switch_environment("LIVE")

    assert exc.value.status == 502
    assert "لم تتغيّر البيئة" in str(exc.value)
    assert fake.broker is before, "استُبدل الوسيط رغم إخفاق الوصل"
    assert fake.audit.records == [], "سُجِّل تبديلٌ لم يقع"


def test_a_successful_switch_replaces_the_broker_and_clears_the_stale_note(monkeypatch):
    import app.main as main

    good = FakeAdapter(live=True)
    fake = install(monkeypatch, candidate=good)

    described = main._mobile_switch_environment("LIVE")

    assert fake.broker is good and good.connected is True
    assert described == {
        "environment": "LIVE", "is_demo": False, "broker_name": "CAPITAL_COM_LIVE",
    }
    # ملاحظةٌ عن وسيطٍ سابق تبقى معلّقة على وسيطٍ جديد فتصف حالاً لم يعد قائماً.
    assert fake.broker_note_ar == ""
    assert fake.audit.records == ["BROKER_ENVIRONMENT_LIVE"]


@pytest.mark.parametrize("target,expected", [
    ("LIVE", "LIVE"),
    ("DEMO", "DEMO"),
    # أيّ مدخلٍ غير `LIVE` يعني التجريبي: الافتراض الآمن أن المجهول **ليس**
    # الحساب الحقيقي — لا العكس.
    ("", "DEMO"),
    ("something-else", "DEMO"),
])
def test_the_environment_actually_requested_matches_the_destination(
    monkeypatch, target, expected
):
    """
    **البيئة المطلوبة تُفحَص عند البناء لا عند الردّ.** محوّلٌ يعيد ما نريد
    يمرّ حتى لو طُلبت البيئة الخطأ — وذلك أخطر خطأ ممكن هنا: نظنّه على
    التجريبي وهو على الحقيقي.
    """
    from app.brokers.capital.endpoints import CapitalEnvironment
    import app.main as main

    fake = install(monkeypatch, candidate=FakeAdapter(live=(expected == "LIVE")))
    main._mobile_switch_environment(target)
    assert fake.asked == [getattr(CapitalEnvironment, expected)]
