"""
الاقتران عبر عمليتين — الأداة تكتب، والخدمة تقرأ.

## لماذا هذا الملف

توليد رمز الاقتران عمليةٌ **منفصلة** عن الخدمة عمداً: إنشاء التحدّي يحتاج
صدفةً على الخادم، وذلك هو العامل الثاني. ولو كان مساراً في الواجهة لصار
كل من يصل الشبكة الخاصة قادراً على تسجيل جهاز.

وثمن ذلك أن عمليتين تكتبان ملفاً واحداً. والخدمة تحمل حالتها في الذاكرة
وتكتب الملف كاملاً — فتحدٍّ كتبته الأداة بعد إقلاع الخدمة كان يُمحى عند
أوّل حفظ. وتدوير رمزٍ كل ربع ساعة يجعل ذلك واقعاً لا نظرياً: تولّد المالكة
رمزاً، ويُحفظ رمز وصول بعده بثوانٍ، فيختفي التحدّي — فتقرأ «تحدٍّ منتهٍ أو
مُستهلَك» عن رمزٍ وُلد للتوّ.

وهذه الاختبارات تحرس الاتجاهين: التحدّي يعيش عبر الحفظ، و**لا يُبعَث بعد
استهلاكه**.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.mobile.security import MobileSecurityService
from app.mobile.store import MobileStateStore

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def state_path(tmp_path):
    return tmp_path / "mobile-state.json"


def service(state_path) -> MobileSecurityService:
    """خدمةٌ جديدة — كأنها أُقلعت للتوّ فقرأت الملف."""
    return MobileSecurityService(store=MobileStateStore(state_path))


def challenges_on_disk(state_path) -> list[dict]:
    if not state_path.exists():
        return []
    return json.loads(state_path.read_text(encoding="utf-8")).get("challenges", [])


def test_a_challenge_written_by_the_tool_survives_a_save_by_the_service(state_path):
    """**العطل الذي كان يُبطل الرمز قبل مسحه.**"""
    running = service(state_path)          # الخدمة، مُقلعة وحالتها في الذاكرة
    tool = service(state_path)             # أداة الاقتران، عملية أخرى
    challenge = tool.create_enrollment_challenge()

    # الخدمة تحفظ لسببٍ آخر تماماً — تدوير رمز مثلاً.
    running._persist()

    assert any(c["challenge_id"] == challenge.challenge_id for c in challenges_on_disk(state_path))


def test_the_service_can_complete_an_enrolment_it_never_created(state_path):
    """الأداة تولّد، والخدمة تُتمّ. وهذا هو المسار الحقيقي بأكمله."""
    running = service(state_path)
    tool = service(state_path)
    challenge = tool.create_enrollment_challenge()

    device = running.complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="pub-key-1",
        device_name="iPhone",
    )
    assert device is not None


def test_a_consumed_challenge_is_not_resurrected_from_disk(state_path):
    """
    **الحدّ الثاني للحارس، وهو أمانٌ لا راحة.**

    نسخة القرص تحمل `consumed=False` لأنها كُتبت قبل الاستهلاك. فلو ضمّها
    الحفظُ فوق ما في الذاكرة لعاد التحدّي صالحاً — وانكسر شرط «لمرة واحدة»
    الذي هو الفرق بين رمزٍ قصير العمر ورمزٍ لا يُعاد.
    """
    running = service(state_path)
    tool = service(state_path)
    challenge = tool.create_enrollment_challenge()

    first = running.complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="pub-key-1",
        device_name="iPhone",
    )
    assert first is not None

    second = running.complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="pub-key-2",
        device_name="جهاز ثانٍ",
    )
    assert second is None, "تحدٍّ مُستهلَك عاد صالحاً — شرط «لمرة واحدة» مكسور"


def test_a_fresh_service_also_refuses_a_consumed_challenge(state_path):
    """وحتى بعد إعادة تشغيل الخدمة: الاستهلاك مكتوبٌ في الملف لا في الذاكرة."""
    tool = service(state_path)
    challenge = tool.create_enrollment_challenge()
    assert service(state_path).complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="pub-key-1",
        device_name="iPhone",
    ) is not None

    restarted = service(state_path)
    assert restarted.complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="pub-key-2",
        device_name="جهاز ثانٍ",
    ) is None


def test_an_expired_challenge_is_still_refused(state_path):
    """الضمّ لا يمدّ عمراً: المنتهي يبقى منتهياً."""
    tool = service(state_path)
    challenge = tool.create_enrollment_challenge()

    late = service(state_path)
    late.clock = lambda: challenge.expires_utc + timedelta(seconds=1)  # type: ignore[assignment]

    assert late.complete_enrollment(
        challenge_id=challenge.challenge_id,
        public_identity="pub-key-1",
        device_name="iPhone",
    ) is None


def test_devices_and_tokens_are_not_disturbed_by_the_absorption(state_path):
    """الضمّ للتحدّيات وحدها — لا يمسّ جهازاً مسجَّلاً ولا رمزاً."""
    running = service(state_path)
    tool = service(state_path)
    device = running.complete_enrollment(
        challenge_id=tool.create_enrollment_challenge().challenge_id,
        public_identity="pub-key-1",
        device_name="iPhone",
    )
    assert device is not None

    service(state_path).create_enrollment_challenge()   # أداة أخرى تكتب
    running._persist()

    reloaded = service(state_path)
    assert device.device_id in reloaded._devices


# ---------------------------------------------------------------------------
# الحمولة نصّاً — للمحاكي، لا كاميرا فيه
# ---------------------------------------------------------------------------

def test_raw_prints_the_payload_alone_and_nothing_else(state_path, capsys):
    """
    `--raw` مخرَجٌ للحافظة لا للشاشة: الحمولة سطراً واحداً بلا رمزٍ ولا شرح،
    كي تُوجَّه إلى `pbcopy` فلا تمرّ بسجلٍّ ولا تُلتقط في صورة.
    """
    from app.mobile.pairing import main

    code = main([
        "--backend", "https://example.invalid",
        "--state", str(state_path),
        "--raw",
    ])
    assert code == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)                     # سطرٌ واحد، JSON صالح
    assert "\n" not in out
    assert "\x1b" not in out                      # لا مسحُ شاشة ولا ألوان

    # التحدّي نفسه على القرص — لا مسارٌ موازٍ ولا مخزنٌ آخر.
    ids = {c["challenge_id"] for c in challenges_on_disk(state_path)}
    assert payload["c"] in ids or payload.get("challenge_id") in ids


def test_raw_still_refuses_a_loopback_backend(state_path, capsys):
    """السهولة لا تُسقط الحارس: `127.0.0.1` تعني الجوالَ نفسه هنا أيضاً."""
    from app.mobile.pairing import main

    assert main(["--backend", "http://127.0.0.1:8000", "--state", str(state_path), "--raw"]) == 2
    assert capsys.readouterr().out.strip() == ""
    assert challenges_on_disk(state_path) == []


# ---------------------------------------------------------------------------
# المالك — العطل الذي أعاد خمسمئة وقرأه التطبيق «رمزٌ مُستهلَك»
# ---------------------------------------------------------------------------

def test_a_file_owned_by_another_user_is_refused_before_it_is_written(state_path, monkeypatch):
    """
    الأداة منفصلة عن الخدمة عمداً. فإن شُغّلت بمستخدمٍ آخر، نقلت الكتابةُ
    الذرّيّة ملكيةَ الملف إليه، فتُرفَض الخدمةُ عند القراءة بـ`PermissionError`
    وتعيد ٥٠٠ — والتطبيق يقرأها «رمزٌ منتهٍ أو مُستهلَك» فتُولَّد رموزٌ بلا
    نهاية. حدث ذلك فعلاً على الخادم.

    فيُفحَص المالك **قبل** الكتابة، وتُقال العلّة بعلاجها.
    """
    import os

    from app.mobile.store import MobileStateStore, MobileStoreError

    store = MobileStateStore(state_path)
    store.save(devices=[], tokens=[], challenges=[])

    # كأنّ العملية تعمل بمستخدمٍ غير مالك الملف.
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(state_path).st_uid + 1)

    with pytest.raises(MobileStoreError) as exc:
        store.load()
    assert "chown" in str(exc.value)


def test_the_owner_check_passes_for_the_owning_process(state_path):
    from app.mobile.store import MobileStateStore

    store = MobileStateStore(state_path)
    store.save(devices=[], tokens=[], challenges=[])
    assert store.load()["devices"] == []
