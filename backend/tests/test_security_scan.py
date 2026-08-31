"""
فحوص أمنية على **المستودع كله** — لا على وحدة بعينها.

## لماذا فحوص على الشجرة لا على الكود

الاختبار الوحدوي يثبت أن دالة تتصرّف صحيحاً. لا يثبت أن أحداً لم يلصق مفتاحاً
في ملف إعداد، ولا أن حزمة الجوال لا تحتوي عنوان الوسيط، ولا أن الخادم لا يربط
نفسه بـ`0.0.0.0`. هذه فحوص على **ما هو موجود فعلاً على القرص**.

**لا شبكة · لا Keychain.**
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
MOBILE = REPO_ROOT / "mobile"

#: مجلدات لا تُفحَص: تبعيات ومخرجات بناء، ليست مصدرنا.
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".next",
    ".pytest_cache", ".expo", "dist", "build", "data", "_to_delete",
    # اعتماديات موردة يولّدها CocoaPods. ليست مصدرنا ولا تُودَع (mobile/.gitignore
    # يستبعد ios/ كاملاً)، ومسحُها أنتج إنذاراً كاذباً واحداً بعينه:
    # Pods/boost/.../keyword/private.hpp — ترويسة C++ لا علاقة لها ببياناتنا.
    #
    # والاستثناء **للمورَّد وحده، لا لـios/ كلها**: ملفٌ من بياناتها يُنسخ إلى
    # حزمة التطبيق هو بالضبط ما يحرسه هذا الفحص، فلا يُوسَّع الاستثناء إليه.
    "Pods", "Carthage",
}


def source_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    out: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in suffixes:
            out.append(path)
    return out


MOBILE_SOURCES = source_files(MOBILE, (".ts", ".tsx", ".js", ".jsx", ".json", ".md"))
BACKEND_SOURCES = source_files(BACKEND / "app", (".py",))


# ===========================================================================
# 1. لا مضيف وسيط في مصدر الجوال
# ===========================================================================

#: تُبنى من أجزاء كي لا يحتوي ملف الاختبار نفسه السلسلة المحظورة.
_CAPITAL_HOST_PATTERNS = (
    "capital" + ".com",
    "api-" + "capital",
    "demo-api-" + "capital",
    "backend-" + "capital",
)


@pytest.mark.skipif(not MOBILE.exists(), reason="لا مجلد mobile/ بعد.")
def test_no_capital_host_in_mobile_source():
    """
    الهاتف **لا يتصل بالوسيط إطلاقاً**. وجود العنوان في المصدر يعني أن أحداً
    فكّر في ذلك، وهو أول خطوة نحو تنفيذه.
    """
    offenders: list[str] = []
    for path in MOBILE_SOURCES:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for pattern in _CAPITAL_HOST_PATTERNS:
            if pattern in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {pattern}")
    assert not offenders, offenders


# ===========================================================================
# 2. لا مفاتيح في المستودع ولا في حزمة الجوال
# ===========================================================================

#: أنماط تُشبه إسناد سرّ بقيمة حقيقية. تُبنى من أجزاء لنفس السبب أعلاه.
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(
        api[_-]?key | apikey | secret | password | token | private[_-]?key
    )\b
    \s* [:=] \s*
    ["']([^"'\n]{16,})["']
    """
)

#: قيم يُسمح بها: نصوص نائبة صريحة.
_PLACEHOLDER_TOKENS = (
    "your", "placeholder", "example", "changeme", "xxx", "***", "redacted",
    "fake", "dummy", "test", "<", "process.env", "${", "expo_public",
)


def _looks_like_placeholder(value: str) -> bool:
    low = value.lower()
    return any(token in low for token in _PLACEHOLDER_TOKENS)


@pytest.mark.parametrize(
    "root_name", ["backend", "mobile", "scripts"]
)
def test_no_hardcoded_secret_assignment_in_the_repository(root_name):
    root = REPO_ROOT / root_name
    files = source_files(root, (".py", ".ts", ".tsx", ".js", ".json", ".sh", ".env"))
    offenders: list[str] = []
    for path in files:
        # ملفات الاختبار تحمل مفاتيح وهمية معلَنة — تُستثنى صراحةً.
        if "test" in path.name.lower():
            continue
        for match in _SECRET_ASSIGNMENT.finditer(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            value = match.group(2)
            if not _looks_like_placeholder(value):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(1)}")
    assert not offenders, offenders


@pytest.mark.skipif(not MOBILE.exists(), reason="لا مجلد mobile/ بعد.")
def test_mobile_env_example_holds_placeholders_only():
    example = MOBILE / ".env.example"
    if not example.exists():
        pytest.skip("لا .env.example")
    # القاعدة تخصّ **الأسرار** وحدها. عنوان الخلفية المحلي ليس سرّاً، ومطالبته
    # بأن يكون «نائباً» تُنتج إنذاراً كاذباً يُدرِّب على تجاهل الفحص.
    secretish = re.compile(r"(?i)(key|secret|password|token|credential)")
    for line in example.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip("\"'")
        if value and secretish.search(name):
            assert _looks_like_placeholder(value) or len(value) < 16, line


@pytest.mark.skipif(not MOBILE.exists(), reason="لا مجلد mobile/ بعد.")
def test_no_real_env_file_is_committed():
    """`.env.example` مسموح. `.env` بقيم حقيقية ليس كذلك."""
    import subprocess

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "mobile/"],
        capture_output=True, text=True,
    ).stdout.split()
    for relative in tracked:
        name = Path(relative).name
        assert name != ".env", f"ملف بيئة حقيقي متتبَّع: {relative}"


# ===========================================================================
# 3. لا تقارير خاصة في أصول الجوال
# ===========================================================================

@pytest.mark.skipif(not MOBILE.exists(), reason="لا مجلد mobile/ بعد.")
def test_no_private_report_inside_mobile():
    forbidden = (
        "data/private", "CAPITAL_COM_LIVE_DISCOVERY",
        "capital_live_discovery", "ACTUAL_BALANCE_FEASIBILITY",
    )
    offenders: list[str] = []
    for path in MOBILE_SOURCES:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert not offenders, offenders


@pytest.mark.skipif(not MOBILE.exists(), reason="لا مجلد mobile/ بعد.")
def test_no_private_file_physically_inside_mobile():
    for path in MOBILE.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        assert "private" not in path.name.lower() or not path.is_file(), path


# ===========================================================================
# 4. الخلفية تُربَط بـlocalhost
# ===========================================================================

def test_backend_never_defaults_to_binding_all_interfaces():
    """
    `0.0.0.0` يعرض الخادم لكل الشبكة المحلية. الافتراضي **localhost**، والخروج
    عنه قرار صريح موثَّق لا سهو في ملف إعداد.
    """
    offenders: list[str] = []
    for path in source_files(REPO_ROOT, (".py", ".sh", ".yml", ".yaml", ".toml", ".json")):
        if "test" in path.name.lower():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "0.0.0.0" in line and not line.strip().startswith("#"):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {line.strip()[:80]}")
    assert not offenders, offenders


def test_settings_declare_a_loopback_host():
    from app.config import get_settings

    settings = get_settings()
    host = getattr(settings, "host", "127.0.0.1")
    assert host in ("127.0.0.1", "localhost", "::1"), host


# ===========================================================================
# 5. Tailscale — لا Funnel
# ===========================================================================

def test_no_template_enables_tailscale_funnel():
    """
    `serve` خاص بالشبكة الخاصة. `funnel` يعرض الخدمة على الإنترنت العام —
    وهو بالضبط ما لم يُؤذَن به.
    """
    offenders: list[str] = []
    for path in source_files(REPO_ROOT, (".md", ".sh", ".json", ".yml", ".yaml", ".ts")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            low = line.lower()
            if "tailscale funnel" in low or "funnel --" in low:
                # يُسمح بذكره في سياق المنع الصريح.
                if any(w in line for w in ("ممنوع", "لا ", "NOT", "never", "Do not", "لا يُستعمل")):
                    continue
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {line.strip()[:80]}")
    assert not offenders, offenders


# ===========================================================================
# 6. APNs مُقلَّد فقط
# ===========================================================================

def test_no_real_apns_implementation_exists_yet():
    """
    لا مسار في المستودع يفتح اتصالاً بـApple ولا يقرأ مفتاح `.p8`.
    """
    offenders: list[str] = []
    for path in BACKEND_SOURCES:
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("api.push.apple.com", "api.sandbox.push.apple.com"):
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {needle}")
    assert not offenders, offenders


def test_the_only_apns_provider_is_the_mock():
    from app.mobile.notifications import ApnsProvider, MockApnsProvider

    subclasses = {c.__name__ for c in ApnsProvider.__subclasses__()}
    assert subclasses == {"MockApnsProvider"}
    assert MockApnsProvider().configured is True


def test_no_p8_key_file_is_committed():
    import subprocess

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True, text=True
    ).stdout.split()
    assert not [t for t in tracked if t.endswith(".p8")]


# ===========================================================================
# 7. الشجرة الخاصة تبقى خارج git
# ===========================================================================

def test_private_tree_and_provider_cache_are_ignored():
    import subprocess

    for relative in (
        "data/private/capital_live/CAPITAL_COM_LIVE_DISCOVERY.md",
        "data/private/provider_cache/anything.json",
    ):
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", relative],
            capture_output=True,
        )
        assert result.returncode == 0, relative


def test_no_tracked_file_lives_under_data():
    import subprocess

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "data/"],
        capture_output=True, text=True,
    ).stdout.split()
    assert tracked == []


# ===========================================================================
# 8. لا اختبار يلمس الشبكة أو Keychain
# ===========================================================================

def test_no_test_module_imports_a_network_client_at_module_level():
    offenders: list[str] = []
    for path in source_files(BACKEND / "tests", (".py",)):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import httpx", "import requests", "import urllib.request")):
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, offenders


def test_no_test_invokes_the_real_macos_keychain():
    """
    الممنوع هو **استدعاء** `security` الحقيقي، لا ذكر اسمه. اختبار سكربت
    الاعتمادات يبني ثنائيّ `security` مزيَّفاً في مجلد مؤقت ويضعه في `PATH` —
    وهذا هو المطلوب تماماً، لا مخالفة له. فالفحص على الاستدعاء الفعلي:
    تمرير `/usr/bin/security` أو تشغيله عبر `subprocess` بمسار مطلق.
    """
    offenders: list[str] = []
    for path in source_files(BACKEND / "tests", (".py",)):
        if path.name == Path(__file__).name:          # لا يفحص نفسه
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "/usr/bin/security" in line:
                offenders.append(f"{path.name}: {line.strip()[:70]}")
    assert not offenders, offenders


# ===========================================================================
# 9. سكربتات الاعتمادات تكتب حيث يقرأ القارئ
# ===========================================================================

CREDENTIAL_SCRIPTS = (
    REPO_ROOT / "scripts" / "configure_capital_credentials.sh",
    REPO_ROOT / "scripts" / "configure_provider_credentials.sh",
)


@pytest.mark.parametrize("script", CREDENTIAL_SCRIPTS, ids=lambda p: p.name)
def test_credential_script_service_matches_the_reader(script):
    """
    الخلل الذي يمنعه هذا الاختبار وقع فعلاً: سكربت المزوّدين كان يكتب تحت
    `service="maather-trader-<key>"` و`account=$USER`، بينما القارئ
    (`KeychainSecretProvider`) يبحث تحت `service="maather-autonomous-trader"`
    و`account=<KEY_NAME>`.

    النتيجة كانت أسوأ من فشل صريح: السكربت يطبع **«✅ حُفظ»** — وهو صادق،
    فالقيمة حُفظت فعلاً — ثم `provider-status` يطبع **❌** لكل مفتاح. نجاحٌ
    وفشلٌ متزامنان، ولا رسالة تشير إلى السبب.

    الكاتب والقارئ **يتفقان بالاختبار**، لا بالانتباه.
    """
    from app.secretstore.provider import KEYCHAIN_SERVICE

    text = script.read_text(encoding="utf-8")
    assignments = [
        line for line in text.splitlines()
        if line.strip().startswith("SERVICE=")
    ]
    assert assignments, f"{script.name}: لا تعريف SERVICE"
    value = assignments[0].split("=", 1)[1].strip().strip('"').strip("'")
    assert value == KEYCHAIN_SERVICE, (
        f"{script.name} يكتب تحت «{value}» والقارئ يبحث في «{KEYCHAIN_SERVICE}»"
    )


@pytest.mark.parametrize("script", CREDENTIAL_SCRIPTS, ids=lambda p: p.name)
def test_credential_script_uses_the_key_name_as_the_account(script):
    """
    القارئ يمرّر `-a <KEY_NAME>`. فلو كتب السكربت `-a "$USER"` لضاعت المطابقة
    حتى مع اتفاق اسم الخدمة.
    """
    text = script.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "add-generic-password" in line and not line.strip().startswith("#"):
            assert '-a "$USER"' not in line, line.strip()
            assert '-a "$1"' in line, line.strip()


def test_provider_status_reads_the_same_names_the_script_writes():
    """أسماء المفاتيح نفسها في السكربت وفي الكود."""
    from app.providers import PROVIDER_CREDENTIALS

    text = (REPO_ROOT / "scripts" / "configure_provider_credentials.sh").read_text(
        encoding="utf-8"
    )
    for name in PROVIDER_CREDENTIALS:
        assert name in text, name
