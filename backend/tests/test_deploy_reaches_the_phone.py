"""
النشر يُصلح الشبكة بنفسه، ولا يحيل المالكة إلى أمرٍ يعرفه.

## العطل

بعد نشرة `a44b889` طبع الخادم:

    BOOTSTRAP_NETWORK=SERVE_MISSING
    tailscale serve --bg 8000

أي: اكتشف السكربت — وهو **على الخادم، بصلاحية الجذر، في تلك اللحظة** — أن
المنفذ ٨٠٠٠ غير منشور على الشبكة الخاصة، فطبع الأمر لتنفّذه هي بيدها. وهي
في تلك الدقيقة كانت تبني التطبيق في Xcode، فبُني تطبيقٌ لا يجد خادمه.

ثم ختم `deploy_to_server.sh` بسطرٍ أسوأ:

    «حالة الشبكة الخاصة مذكورة في آخر مخرَج الخادم أعلاه.»

فحوّل إليها قراءةً يقدر عليها هو، وأعلن «تمّ» ورمزُ خروجه صفر — عن نشرةٍ
لا يصلها الجوال.

## الصنف

هذا هو صنف اليوم في ثوبه التشغيلي: **قيمةٌ يعرفها السكربت ولا يتصرّف بها**.
وقاعدة المالكة صريحة: «الهدف أن النظام هو يقرّر، لا أنا». وقرارُ نشرِ منفذٍ
على شبكةٍ خاصة ليس قراراً تجارياً ولا يحتاج رأياً — هو خطوةٌ ميكانيكية
معروفة الأمر ومعروفة النتيجة.

## ما يحرسه هذا الملف

فحصٌ ساكن، لأن الانحدار هنا لا يظهر إلا حين لا يفتح التطبيق — بعد النشر
بساعات، وفي يد المالكة لا في يد الاختبار.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "deploy" / "server_bootstrap.sh"
DEPLOY = ROOT / "scripts" / "deploy_to_server.sh"

BOOTSTRAP_SOURCE = BOOTSTRAP.read_text(encoding="utf-8")
DEPLOY_SOURCE = DEPLOY.read_text(encoding="utf-8")


def _commands(source: str) -> str:
    """الأوامر وحدها — الشرح في التعليقات لا يُحسَب فعلاً."""
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


BOOTSTRAP_COMMANDS = _commands(BOOTSTRAP_SOURCE)
DEPLOY_COMMANDS = _commands(DEPLOY_SOURCE)


# ---------------------------------------------------------------------------
# ١ · الخادم يُصلح نفسه
# ---------------------------------------------------------------------------
def test_the_bootstrap_actually_publishes_the_port():
    """**العطل بعينه.** كان يطبع الأمر؛ الآن ينفّذه."""
    assert "tailscale serve --bg 8000" in BOOTSTRAP_COMMANDS, (
        "التهيئة لا تنادي نشر المنفذ إطلاقاً"
    )
    assert 'TS_SERVE_ERR="$(tailscale serve --bg 8000 2>&1)"' in BOOTSTRAP_COMMANDS, (
        "نداء النشر يجب أن يُنفَّذ ويُلتقط خطؤه، لا أن يُطبع نصّاً"
    )


def test_the_bootstrap_rereads_the_state_after_trying():
    """نجاحُ الأمر ليس دليلاً. الحالة تُقرأ بعده."""
    body = BOOTSTRAP_COMMANDS
    attempt = body.index('TS_SERVE_ERR="$(tailscale serve --bg 8000 2>&1)"')
    after = body[attempt:]
    assert "serve_is_up" in after, (
        "لا تُقرأ الحالة بعد محاولة النشر — وهذا تصديقُ نيّةِ الأمر لا أثره"
    )
    assert "TS_SERVED=1" in after, "لا تُرفَع الراية إلا بعد قراءةٍ تُثبتها"


def test_the_bootstrap_no_longer_hands_the_owner_a_command_it_can_run():
    assert "SERVE_MISSING" not in BOOTSTRAP_SOURCE, (
        "الحالة القديمة ما زالت موجودة — وهي التي تُحيل المالكة إلى الطرفية"
    )
    assert "BOOTSTRAP_NETWORK=SERVE_FAILED" in BOOTSTRAP_COMMANDS, (
        "لا بدّ من حالةٍ صريحة تقول: حاولتُ ولم أنجح"
    )


def test_a_failed_publish_is_reported_with_the_broker_of_truth_verbatim():
    """حين يفشل النشر، يُنقل نصّ `tailscale` لا تفسيري له."""
    assert 'printf \'%s\\n\' "$TS_SERVE_ERR"' in BOOTSTRAP_COMMANDS, (
        "سبب الفشل يُطبع حرفياً — التفسير المخترَع هو أصل هذا الصنف"
    )


def test_publishing_is_only_attempted_when_the_server_joined_the_network():
    """لا يُنادى النشر على خادمٍ غير منضمّ — الفشل حينها مضلِّل."""
    assert 'if [ "$TS_UP" -eq 1 ]; then' in BOOTSTRAP_COMMANDS


# ---------------------------------------------------------------------------
# ٢ · النشر يتحقّق بنفسه ولا يحيل القراءة
# ---------------------------------------------------------------------------
def test_the_deploy_script_reads_the_network_state_itself():
    assert "tailscale serve status" in DEPLOY_COMMANDS, (
        "سكربت النشر لا يقرأ حالة الشبكة — يصدّق مخرَج التهيئة"
    )
    assert "SERVED" in DEPLOY_COMMANDS and "MISSING" in DEPLOY_COMMANDS


def test_the_deploy_script_fails_when_the_phone_cannot_reach_the_server():
    """**أخطر ما في العطل:** نشرةٌ لا يصلها الجوال كانت تنتهي بالرمز صفر."""
    body = DEPLOY_COMMANDS
    assert "MISSING)" in body, "لا فرع صريح لحالة «غير منشورة»"
    branch = body[body.index("MISSING)") : body.index("esac")]
    assert "exit 1" in branch, (
        "النشر يعلن النجاح والتطبيق لا يصل — وهذا أسوأ من الفشل الصريح"
    )


def test_an_unreadable_state_is_not_read_as_success():
    """الغياب لا يُقرأ نجاحاً ولا فشلاً — يُقرأ «لم أقرأ»."""
    assert "UNREACHABLE" in DEPLOY_COMMANDS
    body = DEPLOY_COMMANDS
    default = body[body.index("  *)") : body.index("esac")]
    assert "exit 1" in default, "حالةٌ لم تُقرأ لا يجوز أن تمرّ صامتة"


def test_the_deploy_script_no_longer_defers_the_reading_to_the_owner():
    assert "مذكورة في آخر مخرَج الخادم" not in DEPLOY_SOURCE, (
        "ما زال السكربت يطلب منها أن تقرأ ما يقدر هو على قراءته"
    )


def test_the_success_line_names_the_address_the_app_will_use():
    assert "https://${HOSTNAME_TS}" in DEPLOY_COMMANDS
