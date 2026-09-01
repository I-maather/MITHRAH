"""
زرّ الاستئناف — أوّل مسارٍ في مجال الجوال **يزيد** المخاطرة.

## لماذا كان غائباً، ولماذا عاد

كان العقد صريحاً: قراءة + ثلاثة مسارات كلّها تقلّل المخاطرة. فصار في يد
المالكة أن توقف النظام من جوالها ولا تستطيع تشغيله — وهو نقصٌ حقيقي.

والإضافة **لا تُلغي العقد بل توسّعه بفئةٍ مسمّاة**: `RISK_INCREASING_ROUTES`.
ولو أُضيف الاستئناف إلى `RISK_REDUCING_ROUTES` لبقي الاسم وصار كاذباً — وهو
أخطر من مسارٍ مفتوح، لأن القارئ يثق بالاسم.

## ولماذا هو مقبول أصلاً من جهازٍ قد يُسرق

لأنه **ليس مفتاح التداول**. يرفع `locally_paused` وحده ولا يمسّ الأقفال
الأربعة الباقية. فأسوأ ما يفعله جهازٌ مسروق أن يعيد النظام من «موقوف» إلى
«يقيّم» — ولا يستطيع بعدها إرسال أمرٍ واحد.

## الأسوار الثلاثة

  ١  عبارة تأكيد كاملة حرفاً بحرف — زرٌّ يُضغط بالخطأ في الجيب لا يكتب جملة.
  ٢  مرفوض ما دام قاطع الطوارئ مفعّلاً — والرفض من عند المصدر لا الواجهة.
  ٣  يفشل مغلقاً إن لم يكن موصولاً، ولا يقول «تمّ».
"""
from __future__ import annotations

import pytest

from tests.test_mobile_backend import enrolled, service
from app.mobile.api import (
    READ_ROUTES,
    RESUME_PHRASE,
    RISK_INCREASING_ROUTES,
    RISK_REDUCING_ROUTES,
    MobileActions,
    MobileApi,
    MobileApiError,
    describe_api,
)


class Recorder:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, reason_ar: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.calls.append(reason_ar)


def paired(actions=None):
    """مجالٌ حقيقي بجهازٍ مقترن — الأفعال تُحقن لتُقاس."""
    svc = service()
    device = enrolled(svc)
    access, _ = svc.issue_tokens(device.device_id)
    return MobileApi(security=svc, actions=actions or MobileActions()), access.token


@pytest.fixture()
def api_and_token():
    recorder = Recorder()
    api, token = paired(MobileActions(resume=recorder))
    api._resume_recorder = recorder          # type: ignore[attr-defined]
    return api, token


def resume(api, token, **payload):
    body = {"confirm": RESUME_PHRASE}
    body.update(payload)
    return api.handle("POST", "pause/resume", token=token, payload=body)


# ---------------------------------------------------------------------------
# العقد
# ---------------------------------------------------------------------------

def test_the_resume_route_is_declared_in_its_own_named_category():
    """**لا توسيع صامت.** الاسم `RISK_REDUCING` يجب أن يبقى صادقاً."""
    assert "pause/resume" in RISK_INCREASING_ROUTES
    assert "pause/resume" not in RISK_REDUCING_ROUTES
    assert "pause/resume" not in READ_ROUTES


def test_the_published_description_admits_the_new_category():
    described = describe_api()
    assert "pause/resume" in described["risk_increasing_routes"]
    assert described["trading_routes"] == [], "ظهر مسار تداول في مجال الجوال"
    assert "قاطع الطوارئ" in described["note_ar"]


def test_no_other_post_route_slipped_in():
    api, paired_token = paired()
    for route in ("killswitch/deactivate", "profile/select", "order/submit", "trade"):
        with pytest.raises(MobileApiError) as exc:
            api.handle("POST", route, token=paired_token, payload={})
        assert exc.value.status in (403, 404)


# ---------------------------------------------------------------------------
# السور الأول — العبارة
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("confirm", ["", "استأنف", "أستأنف", "نعم", "أستأنف التداول الآن"])
def test_nothing_resumes_without_the_exact_phrase(api_and_token, confirm):
    api, paired_token = api_and_token
    with pytest.raises(MobileApiError) as exc:
        api.handle("POST", "pause/resume", token=paired_token, payload={"confirm": confirm})
    assert exc.value.status == 400
    assert api._resume_recorder.calls == [], "استُؤنف رغم رفض العبارة"


def test_the_exact_phrase_resumes(api_and_token):
    api, paired_token = api_and_token
    body = resume(api, paired_token).body
    assert body["data"]["action"] == "RESUMED" and body["data"]["accepted"] is True
    assert api._resume_recorder.calls, "قيل «تمّ» ولم يُنفَّذ شيء"


def test_the_refusal_is_audited_as_a_failure(api_and_token):
    api, paired_token = api_and_token
    with pytest.raises(MobileApiError):
        api.handle("POST", "pause/resume", token=paired_token, payload={"confirm": "لا"})
    entries = [e.as_dict() for e in api.security.audit()]
    assert any(
        e["action"] == "MOBILE_RESUME_REFUSED" and e["success"] is False for e in entries
    )


# ---------------------------------------------------------------------------
# السور الثاني — لا يُقال «تمّ» عن شيء لم يقع
# ---------------------------------------------------------------------------

def test_an_unwired_resume_fails_closed():
    """
    **العطل الذي وقع فعلاً في زرّي الإيقاف والقاطع:** يعيدان `accepted: true`
    ولا يفعلان شيئاً. فشلٌ ظاهرٌ خيرٌ من نجاحٍ كاذب.
    """
    api, paired_token = paired(MobileActions())
    with pytest.raises(MobileApiError) as exc:
        resume(api, paired_token)
    assert exc.value.status == 503


def test_a_refusal_from_the_system_is_surfaced_not_swallowed():
    """رفضُ الخادم (قاطع مفعّل مثلاً) يصل المالكة بنصّه لا يُبتلع."""
    blocked = MobileApiError("قاطع الطوارئ مفعّل — الاستئناف لا يرفعه.", status=409)
    api, paired_token = paired(MobileActions(resume=Recorder(fail=blocked)))
    with pytest.raises(MobileApiError) as exc:
        resume(api, paired_token)
    assert exc.value.status == 409 and "قاطع الطوارئ" in str(exc.value)
    entries = [e.as_dict() for e in api.security.audit()]
    assert any(e["action"] == "MOBILE_RESUME_FAILED" for e in entries)


# ---------------------------------------------------------------------------
# السور الثالث — لا يفتح شيئاً آخر
# ---------------------------------------------------------------------------

def test_the_reply_says_plainly_that_no_other_lock_opened(api_and_token):
    api, paired_token = api_and_token
    note = resume(api, paired_token).body["data"]["note_ar"]
    assert "لم يُفتح أي قفل آخر" in note
    assert "لا يستطيع إرسال أمر" in note


class FakeKill:
    def __init__(self, active: bool) -> None:
        self.is_active = active

    class _State:
        current_event = None

    state = _State()


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[str] = []

    def record(self, **kw) -> None:
        self.records.append(kw.get("decision", ""))


class FakeSystem:
    def __init__(self, *, kill_active: bool) -> None:
        self.kill_switch = FakeKill(kill_active)
        self.locally_paused = True
        self.audit = FakeAudit()


def test_resuming_is_refused_while_the_kill_switch_is_active(monkeypatch):
    """
    **الفحص على المصدر لا على الواجهة.** الإيقاف المحلي قرار، والقاطع حكم.
    ورفعُ الأوّل بينما الثاني مفعّل يجعل الشاشة تقول «يعمل» عن نظامٍ ممنوع.
    """
    import app.main as main

    fake = FakeSystem(kill_active=True)
    monkeypatch.setattr(main, "system", lambda: fake)
    with pytest.raises(MobileApiError) as exc:
        main._mobile_resume("محاولة استئناف")
    assert exc.value.status == 409
    assert "قاطع الطوارئ" in str(exc.value)
    assert fake.locally_paused is True, "رُفع الإيقاف رغم الرفض"
    assert fake.audit.records == [], "سُجّل استئنافٌ لم يقع"


def test_a_clean_resume_actually_clears_the_local_pause(monkeypatch):
    """والزرّ يفعل، لا يسجّل فقط — وهو العطل الذي أصاب أخويه من قبل."""
    import app.main as main

    fake = FakeSystem(kill_active=False)
    monkeypatch.setattr(main, "system", lambda: fake)
    main._mobile_resume("استئناف من الجوال")
    assert fake.locally_paused is False
    assert fake.audit.records == ["LOCAL_RESUME"], "لم يُسجَّل الاستئناف"
