"""
اختبارات سكربت إعداد الاعتمادات `scripts/configure_capital_credentials.sh`.

**كل القيم هنا وهمية**، وأمر macOS `security` **مُقلَّد** بملف تنفيذي مؤقت.
لا يلمس أي اختبار: Keychain حقيقياً · سجل الصدفة · الحافظة · اعتماداً حقيقياً ·
الشبكة. ولا يُقرأ أي متغيّر بيئة سرّي.

يُشغَّل السكربت على **pty حقيقي** لأن `read -p` لا يطبع سؤاله إلا على طرفية —
والعطل المُبلَّغ عنه كان بالضبط: «لا يظهر أي سؤال».

## العطل الأصلي

    line 30: CAPITAL_API_KEY: unbound variable

السبب: `declare -A` (مصفوفة ترابطية) من bash 4.0، و**macOS يشحن bash 3.2**.
هناك يُفسَّر `[CAPITAL_API_KEY]` رمزاً حسابياً لا مفتاحاً نصياً، فيصبح اسماً
لمتغيّر غير معيَّن، و`set -u` يُسقط السكربت **قبل طباعة أي سؤال**.

بما أن الاختبارات تعمل على bash 5 (حيث `declare -A` صالحة)، فإن الحارس الدائم
ضد عودة العطل هو **الفحوص الثابتة** أدناه، لا التشغيل التفاعلي وحده.
"""
from __future__ import annotations

import os
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "configure_capital_credentials.sh"

pytestmark = pytest.mark.skipif(
    not SCRIPT.exists() or sys.platform.startswith("win"),
    reason="السكربت غير موجود أو النظام لا يدعم pty.",
)

# قيم وهمية بحتة — لا معنى لها خارج هذا الملف.
DUMMY_KEY = "dummy-api-key-0001"
DUMMY_IDENTIFIER = "dummy@example.invalid"
DUMMY_PASSWORD = "dummy-key-password-0001"

DUMMY = {
    "CAPITAL_API_KEY": DUMMY_KEY,
    "CAPITAL_IDENTIFIER": DUMMY_IDENTIFIER,
    "CAPITAL_API_PASSWORD": DUMMY_PASSWORD,
}

ANSI = re.compile(r"\x1b\[[0-9;]*m")

ALL_THREE = [
    ("القيمة:", DUMMY_KEY),
    ("أعيدي الإدخال للتأكيد:", DUMMY_KEY),
    ("القيمة:", DUMMY_IDENTIFIER),
    ("أعيدي الإدخال للتأكيد:", DUMMY_IDENTIFIER),
    ("القيمة:", DUMMY_PASSWORD),
    ("أعيدي الإدخال للتأكيد:", DUMMY_PASSWORD),
]


class Harness:
    """بيئة معزولة تماماً: HOME مؤقت و`security` و`uname` مُقلَّدان."""

    def __init__(self, *, fake_darwin: bool) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="credtest-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.store = self.tmp / "keychain-store"
        self.store.mkdir()
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        target = self.repo / "scripts" / SCRIPT.name
        shutil.copy2(SCRIPT, target)
        target.chmod(0o755)
        self._fake_security()
        if fake_darwin:
            self._fake_uname()

    def _fake_security(self) -> None:
        p = self.bin / "security"
        p.write_text(
            "#!/usr/bin/env bash\nset -u\n"
            f'STORE="{self.store}"\n'
            'cmd="${1:-}"; shift || true\n'
            'svc=""; acct=""; val=""\n'
            'while [[ $# -gt 0 ]]; do\n'
            '  case "$1" in\n'
            '    -s) svc="$2"; shift 2 ;;\n'
            '    -a) acct="$2"; shift 2 ;;\n'
            '    -w) val="$2"; shift 2 ;;\n'
            '    *) shift ;;\n'
            '  esac\n'
            'done\n'
            'f="$STORE/${svc}__${acct}"\n'
            'case "$cmd" in\n'
            '  add-generic-password)    printf "%s" "$val" > "$f"; exit 0 ;;\n'
            '  find-generic-password)   [[ -f "$f" ]] && exit 0 || exit 44 ;;\n'
            '  delete-generic-password) rm -f "$f"; exit 0 ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n'
        )
        p.chmod(0o755)

    def _fake_uname(self) -> None:
        p = self.bin / "uname"
        p.write_text('#!/usr/bin/env bash\necho Darwin\n')
        p.chmod(0o755)

    @property
    def script(self) -> Path:
        return self.repo / "scripts" / SCRIPT.name

    def env(self) -> dict:
        return {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.tmp),
            "TERM": "dumb",
            "LANG": "en_US.UTF-8",
        }

    def stored(self, key: str) -> str | None:
        f = self.store / f"maather-autonomous-trader__{key}"
        return f.read_text() if f.exists() else None

    @property
    def secrets_file(self) -> Path:
        return self.repo / "secrets" / "capital.env"

    def run(self, args=(), answers=(), timeout: float = 20.0) -> tuple[str, int]:
        return _run_pty(self, list(args), list(answers), timeout)

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def _run_pty(h: Harness, args, answers, timeout) -> tuple[str, int]:
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(h.repo)
        os.execve("/bin/bash", ["bash", str(h.script), *args], h.env())
        os._exit(127)

    out = ""
    pending = list(answers)
    deadline = time.time() + timeout
    eof = False

    while time.time() < deadline and not eof:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                eof = True          # EIO عند خروج الابن — ليس خطأً
                break
            if not chunk:
                eof = True
                break
            out += chunk.decode("utf-8", "replace")
        if pending:
            pattern, send = pending[0]
            if pattern in ANSI.sub("", out):
                try:
                    os.write(fd, (send + "\n").encode())
                except OSError:
                    eof = True
                    break
                pending.pop(0)
                time.sleep(0.1)

    try:
        os.close(fd)
    except OSError:
        pass

    if eof:
        _, status = os.waitpid(pid, 0)
        return ANSI.sub("", out), os.waitstatus_to_exitcode(status)

    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except OSError:
        pass
    return ANSI.sub("", out), -1


@pytest.fixture
def mac() -> Harness:
    h = Harness(fake_darwin=True)
    yield h
    h.cleanup()


@pytest.fixture
def linux() -> Harness:
    h = Harness(fake_darwin=False)
    yield h
    h.cleanup()


# ---------------------------------------------------------------------------
# سبب العطل — توثيق قابل للتشغيل
# ---------------------------------------------------------------------------

def test_bash32_associative_array_pattern_is_what_broke_the_script():
    """
    إعادة إنتاج آلية العطل بالضبط: مصفوفة **مفهرسة** بمفتاح نصي تحت `set -u`
    تُنتج «unbound variable» — وهو ما يفعله bash 3.2 بـ`declare -A`.
    """
    result = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; declare -a P=([CAPITAL_API_KEY]="x")'],
        capture_output=True, text=True,
    )
    assert "CAPITAL_API_KEY: unbound variable" in result.stderr


# ---------------------------------------------------------------------------
# فحوص ثابتة — الحارس الدائم ضد عودة العطل
# ---------------------------------------------------------------------------

def _code_lines() -> list[str]:
    return [
        l for l in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not l.lstrip().startswith("#")
    ]


def test_no_associative_arrays_anywhere_in_the_code():
    """`declare -A` من bash 4.0 — وmacOS يشحن bash 3.2."""
    assert not any("declare -A" in l for l in _code_lines())
    assert not any("PROMPTS[" in l for l in _code_lines())


def test_positional_parameter_expansion_is_guarded():
    """في bash < 4.4 يُعتبر "$@" غير مُعرَّف تحت `set -u` بلا وسائط."""
    src = SCRIPT.read_text(encoding="utf-8")
    if 'for arg in "$@"' in src:
        assert "$# -gt 0" in src, "توسعة \"$@\" بلا حارس $# تسقط في bash 3.2"


def test_strict_mode_is_preserved():
    """المطلوب صراحةً: الإبقاء على `set -euo pipefail`."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in src


def test_security_guarantees_are_preserved():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "set +o history" in src
    assert "umask 077" in src
    assert "read -r -s -p" in src          # إخفاء الإدخال
    assert "chmod 600" in src
    assert 'echo "$value"' not in src
    assert "echo $value" not in src


def test_variables_read_later_are_never_unset():
    """`unset` تحت `set -u` يحوّل أي قراءة لاحقة إلى خطأ قاتل."""
    assert "unset value confirm_value" not in SCRIPT.read_text(encoding="utf-8")


def test_keychain_call_is_not_a_bare_and_list():
    """`a && b` كعبارة مستقلة تُسقط السكربت تحت `set -e` على نظام بلا Keychain."""
    assert "  have_keychain && keychain_remove" not in SCRIPT.read_text(encoding="utf-8")


def test_script_parses_under_bash():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 1. الإعداد لأول مرة
# ---------------------------------------------------------------------------

def test_first_time_configuration_prompts_and_stores(mac: Harness):
    out, code = mac.run(answers=ALL_THREE)

    assert "unbound variable" not in out
    assert code == 0, out[-500:]
    # العطل المُبلَّغ عنه كان «لا يظهر أي سؤال» — هذا ما يثبت زواله:
    assert out.count("القيمة:") == 3
    assert "أعيدي الإدخال للتأكيد:" in out
    assert "مفتاح Capital.com API" in out
    assert "معرّف الدخول" in out
    assert "كلمة المرور المخصّصة للمفتاح" in out
    assert "اكتمل الإعداد" in out

    for key, value in DUMMY.items():
        assert mac.stored(key) == value


def test_no_entered_value_is_ever_echoed(mac: Harness):
    out, _ = mac.run(answers=ALL_THREE)
    for value in DUMMY.values():
        assert value not in out


# ---------------------------------------------------------------------------
# 2. عدم تطابق التأكيد
# ---------------------------------------------------------------------------

def test_confirmation_mismatch_reprompts_and_stores_nothing_wrong(mac: Harness):
    out, code = mac.run(answers=[
        ("القيمة:", "dummy-typo-a"),
        ("أعيدي الإدخال للتأكيد:", "dummy-typo-b"),
        ("القيمتان غير متطابقتين", ""),
        *ALL_THREE,
    ])

    assert "القيمتان غير متطابقتين" in out
    assert "unbound variable" not in out
    assert out.count("القيمة:") >= 4          # أُعيد السؤال
    assert code == 0
    assert mac.stored("CAPITAL_API_KEY") == DUMMY_KEY
    assert mac.stored("CAPITAL_API_KEY") != "dummy-typo-a"


# ---------------------------------------------------------------------------
# 3. الإدخال الفارغ
# ---------------------------------------------------------------------------

def test_empty_input_is_rejected_and_reprompted(mac: Harness):
    out, code = mac.run(answers=[
        ("القيمة:", ""),
        ("القيمة فارغة", ""),
        *ALL_THREE,
    ])

    assert "القيمة فارغة" in out
    assert "unbound variable" not in out
    # لا يُطلب تأكيد لقيمة فارغة
    assert out.index("القيمة فارغة") < out.index("أعيدي الإدخال للتأكيد:")
    assert code == 0
    assert mac.stored("CAPITAL_API_KEY") == DUMMY_KEY


# ---------------------------------------------------------------------------
# 4. ‎--check
# ---------------------------------------------------------------------------

def test_check_reports_missing_credentials_without_revealing_anything(mac: Harness):
    out, code = mac.run(args=["--check"])

    assert "unbound variable" not in out
    assert code == 1                       # ناقص ⇒ خروج غير صفري
    assert out.count("❌") == 3
    assert "لن تُعرض أي قيمة" in out
    assert all(v not in out for v in DUMMY.values())


def test_check_after_configuration_succeeds_and_names_the_store(mac: Harness):
    mac.run(answers=ALL_THREE)
    out, code = mac.run(args=["--check"])

    assert code == 0, out
    assert out.count("✅") == 3
    assert "macOS Keychain" in out
    assert all(v not in out for v in DUMMY.values())


# ---------------------------------------------------------------------------
# 5. المسار بلا Keychain
# ---------------------------------------------------------------------------

def test_file_fallback_creates_a_600_file(linux: Harness):
    out, code = linux.run(answers=ALL_THREE)

    assert "unbound variable" not in out
    assert code == 0, out[-400:]
    assert linux.secrets_file.exists()
    assert oct(linux.secrets_file.stat().st_mode)[-3:] == "600"


def test_check_reads_the_file_store_and_reports_the_mode_correctly(linux: Harness):
    """
    `stat -f` يعني «تنسيق» في BSD و«نظام الملفات» في GNU — أي أنه **ينجح**
    على لينكس بمخرَج لا علاقة له بالصلاحيات، فيُنتج تحذيراً كاذباً.
    """
    linux.run(answers=ALL_THREE)
    out, code = linux.run(args=["--check"])

    assert code == 0, out
    assert "ملف محلي" in out
    assert "صلاحيات" not in out            # لا تحذير كاذب


# ---------------------------------------------------------------------------
# 6. رفض تمرير سرّ كوسيط
# ---------------------------------------------------------------------------

def test_a_value_passed_on_the_command_line_is_refused(mac: Harness):
    out, code = mac.run(args=["dummy-value-on-cli"])

    assert code == 2
    assert "لا يقبل قيماً في سطر الأوامر" in out
    assert "unbound variable" not in out


def test_help_and_remove_flags_do_not_crash(mac: Harness):
    out, code = mac.run(args=["--help"])
    assert "unbound variable" not in out
    assert code == 0

    out2, code2 = mac.run(args=["--remove"], answers=[("متأكدة", "no")])
    assert "unbound variable" not in out2
    assert code2 == 0
    assert "أُلغي" in out2
