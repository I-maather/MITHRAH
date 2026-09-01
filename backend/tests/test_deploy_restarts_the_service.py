"""
النشرة تُعيد تشغيل الخدمة، وتُثبت أن الكود الجديد هو العامل.

## العطل الذي كلّف ليلةً كاملة

كانت الخطوة السادسة في `server_bootstrap.sh` تنادي:

    systemctl enable --now mathrah

و`--now` **يشغّل الخدمة إن لم تكن تعمل، ولا يعيد تشغيلها إن كانت تعمل**.
فكل نشرة بعد أوّل إقلاع كانت تنقل الكود الجديد إلى القرص وتترك العملية
القديمة تخدم بالكود القديم. وسجل الخدمة أثبته: عمليةٌ واحدة (`uvicorn[35389]`)
تخدم من 21:52 مساءً حتى 06:03 صباحاً عبر خمس نشرات.

**وأخفاه فحصُ الجاهزية تحته مباشرةً:** يسأل «هل يردّ أحدٌ على 8000؟» —
والعملية القديمة تردّ. فيُطبع «✅ الخدمة تعمل وتستجيب» عن خدمةٍ تعمل بكودٍ
عمره ساعات. **فحصُ حياة، لا فحصُ إصدار.**

## ولماذا بدا النظام يناقض نفسه

المسابر (`provider_smoke`، `run_history_sweep`، `capital-auth-probe`) عمليات
**منفصلة** تُشغَّل بأمر وتقرأ الكود من القرص — فكانت تعمل بالجديد وتُظهر كل
إصلاح. والخدمة تعمل بالقديم. فقال المسبار «التقويم يعطي ٢٨ حدثاً» وقالت
الخدمة «الوسيط غير متصل» — وكلاهما صادق، وكلٌّ يتكلّم عن كودٍ آخر.

وهذا أخبث أشكال صنف اليوم: ليس حقلاً يكذب، بل **نسختان من النظام تعملان
معاً**، والتقارير تخلط بينهما.

## ما يحرسه هذا الملف

فحصٌ ساكن على سكربت النشر — لأن الانحدار هنا لا يظهر في أي اختبار وحدة،
ولا في أي نداء واجهة، ولا في السجل. يظهر فقط بأن **لا شيء يتغيّر** بعد
النشر، وهو أصعب أثرٍ يُلاحَظ.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[2] / "deploy" / "server_bootstrap.sh"
SOURCE = BOOTSTRAP.read_text(encoding="utf-8")

#: الأوامر وحدها بلا تعليقات.
#:
#: العطل يُشرَح في تعليقٍ داخل السكربت نفسه — وهو الموضع الصحيح للشرح.
#: ولو فُحص النصّ كلّه لاصطدم الحارس بشرحِ العطل وحسبه العطل. فحصُ سلوكٍ
#: يخلط الشرح بالفعل يمنع توثيق ما أُصلح، وذلك ثمنٌ لا يُدفَع.
COMMANDS = "\n".join(
    line for line in SOURCE.splitlines() if not line.lstrip().startswith("#")
)


def test_the_bootstrap_script_exists():
    assert BOOTSTRAP.is_file(), "سكربت التهيئة مفقود — لا نشرة بلا سكربت"


def test_the_service_is_restarted_not_merely_enabled():
    """**العطل بعينه.** `--now` لا يعيد تشغيل خدمةً تعمل."""
    assert "systemctl restart mathrah" in COMMANDS, (
        "لا إعادة تشغيل صريحة — الكود الجديد لن يُقرأ ما دامت العملية القديمة حيّة."
    )
    assert "enable --now mathrah" not in COMMANDS, (
        "`enable --now` يشغّل ولا يعيد التشغيل. هو سبب أن خمس نشرات لم تُغيّر شيئاً."
    )


def test_the_process_identifier_is_compared_before_and_after():
    """
    الاستجابة ليست دليلاً: عمليةٌ قديمة تستجيب بالقدر نفسه. الدليل الوحيد
    أن **المعرّف الرقمي تغيّر**.
    """
    assert "pid_before" in COMMANDS and "pid_after" in COMMANDS, (
        "لا مقارنة للمعرّف الرقمي قبلَ وبعد"
    )
    comparison = re.search(r'if \[ "\$pid_after" = "\$pid_before" \]', COMMANDS)
    assert comparison, "المعرّفان يُقرآن ولا يُقارَنان — قراءةٌ بلا حكم"


def test_an_unchanged_process_fails_the_deploy():
    """
    وأن يكون الحكم **إخفاقاً** لا تحذيراً: نشرةٌ لم تُغيّر شيئاً ويُقال عنها
    «تمّت» هي بالضبط ما وقع خمس مرّات الليلة.
    """
    block = COMMANDS[COMMANDS.index("pid_after="):]
    head = block[: block.index("green")] if "green" in block else block
    assert "exit 1" in head, "العملية لم تتغيّر ومع ذلك تمضي النشرة"


def test_the_running_commit_is_read_from_the_service_itself():
    """
    الكوميت يُقرأ من **الخدمة**، لا من القرص: القرص قد يحمل شيئاً والذاكرة
    غيره — وذلك هو العطل نفسه.
    """
    assert "/api/version" in COMMANDS, "لا يُسأل الخادم عن الكوميت الذي يعمل به"
    assert "running_sha" in COMMANDS and "EXPECTED_SHA" in COMMANDS, (
        "الكوميت العامل لا يُقارَن بالمنشور"
    )


def test_the_version_endpoint_reports_the_boot_commit_not_the_disk():
    """
    ولو قُرئ الكوميت عند كل طلب لتَبع القرص لا الذاكرة — فأعاد الخداع نفسه
    بثوبٍ جديد: خدمةٌ قديمة تُبلّغ عن كوميتٍ جديد.
    """
    import app.main as main

    assert hasattr(main, "_BOOT_COMMIT"), "لا ثابت يحمل كوميت الإقلاع"
    first = main._BOOT_COMMIT
    assert isinstance(first, str) and first, "كوميت الإقلاع فارغ"
    assert main.version()["commit"] == first

    source = Path(main.__file__).read_text(encoding="utf-8")
    body = source[source.index("def version()"): source.index("@app.get(\"/api/health\")")]
    assert "_read_boot_commit()" not in body, (
        "المسار يقرأ القرص عند كل طلب — فيتبع القرص لا العملية"
    )


@pytest.mark.parametrize("promise", [
    "أُعيد تشغيل الخدمة",
    "الخدمة تعمل بالكوميت المنشور",
])
def test_the_script_only_claims_what_it_proved(promise):
    """
    كل جملة نجاح تُطبع بعد الدليل الذي يسندها، لا قبله. و«تعمل وتستجيب»
    حُذفت لأنها كانت تُقال عن عمليةٍ قديمة.
    """
    assert promise in COMMANDS
    assert "الخدمة تعمل وتستجيب على" not in COMMANDS, (
        "الجملة القديمة باقية — وهي التي طمأنتنا خمس مرّات بلا حق"
    )
