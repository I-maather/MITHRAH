"""
اختبارات المخزن الخاص للمخرجات الحسّاسة.

**لا شبكة · لا Keychain · لا اعتماد حقيقي.**
كل اختبار يبني مستودع git حقيقياً في مجلد مؤقت كي يُختبَر التجاهل والتتبّع فعلاً
لا صورياً.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.live_readonly.private_store import (
    ACTUAL_FEASIBILITY_MARKDOWN,
    CAPITAL_LIVE_PARTS,
    DIR_MODE,
    DISCOVERY_JSON,
    DISCOVERY_MARKDOWN,
    FILE_MODE,
    SENSITIVE_FILENAMES,
    PrivateStoreError,
    ensure_private_directory,
    is_git_ignored,
    is_git_tracked,
    preflight,
    private_directory,
    private_path,
    require_private_output,
    write_private_text,
)
from app.live_readonly.report import (
    compute_feasibility,
    render_actual_feasibility_markdown,
    render_public_feasibility_markdown,
)
from app.money import D

REPO_ROOT = Path(__file__).resolve().parents[2]
POSIX = os.name == "posix"

GITIGNORE = """
data/
data/private/
data/private/**
secrets/
"""


def make_repo(tmp_path: Path, *, gitignore: str = GITIGNORE) -> Path:
    """مستودع git حقيقي في مجلد مؤقت — لا محاكاة."""
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


# ---------------------------------------------------------------------------
# 1. تغطية .gitignore
# ---------------------------------------------------------------------------

def test_real_repo_ignores_the_private_tree():
    """المستودع الحقيقي — لا مؤقت — يتجاهل الشجرة الخاصة فعلاً."""
    for name in SENSITIVE_FILENAMES:
        target = private_directory(REPO_ROOT) / name
        assert is_git_ignored(REPO_ROOT, target) is True, name


def test_gitignore_declares_the_private_tree_explicitly():
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/private/" in text


def test_private_directory_is_not_tracked_in_the_real_repo():
    assert is_git_tracked(REPO_ROOT, private_directory(REPO_ROOT)) is False


def test_preflight_passes_on_a_correctly_configured_repo(tmp_path):
    repo = make_repo(tmp_path)
    ensure_private_directory(repo)
    result = preflight(repo)
    assert result.passed, result.summary_ar()


# ---------------------------------------------------------------------------
# 2. الرفض عند التتبّع
# ---------------------------------------------------------------------------

def test_tracked_target_is_rejected(tmp_path):
    """ملف خاص متتبَّع في git ⇒ فشل مغلق."""
    repo = make_repo(tmp_path, gitignore="secrets/\n")   # لا يتجاهل data/private
    directory = ensure_private_directory(repo)
    target = directory / DISCOVERY_MARKDOWN
    target.write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(target)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "oops"], cwd=repo, check=True)

    assert is_git_tracked(repo, target) is True
    result = preflight(repo)
    assert result.passed is False
    keys = {c.key for c in result.failures()}
    assert "NOT_GIT_TRACKED" in keys
    with pytest.raises(PrivateStoreError):
        require_private_output(repo)


def test_unignored_directory_is_rejected(tmp_path):
    repo = make_repo(tmp_path, gitignore="secrets/\n")
    ensure_private_directory(repo)
    result = preflight(repo)
    assert result.passed is False
    assert "GIT_IGNORED" in {c.key for c in result.failures()}


def test_cannot_prove_ignore_status_is_treated_as_failure(tmp_path):
    """مجلد ليس مستودع git ⇒ لا إثبات ⇒ فشل، لا «تحذير ونكمل»."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    ensure_private_directory(plain)
    result = preflight(plain)
    assert result.passed is False
    assert "GIT_IGNORED" in {c.key for c in result.failures()}


# ---------------------------------------------------------------------------
# 3. الروابط الرمزية
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not POSIX, reason="الروابط الرمزية تحتاج POSIX.")
def test_symlinked_directory_component_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "data").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "data" / "private").symlink_to(elsewhere, target_is_directory=True)

    result = preflight(repo)
    assert result.passed is False
    assert "NO_SYMLINK_IN_PATH" in {c.key for c in result.failures()}


@pytest.mark.skipif(not POSIX, reason="الروابط الرمزية تحتاج POSIX.")
def test_symlinked_output_file_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    directory = ensure_private_directory(repo)
    victim = tmp_path / "victim.md"
    victim.write_text("", encoding="utf-8")
    (directory / DISCOVERY_MARKDOWN).symlink_to(victim)

    result = preflight(repo)
    assert result.passed is False
    assert "NO_SYMLINK_TARGET" in {c.key for c in result.failures()}


@pytest.mark.skipif(not POSIX, reason="الروابط الرمزية تحتاج POSIX.")
def test_write_refuses_to_follow_a_symlink_planted_after_preflight(tmp_path):
    """رابط يُزرع بين الفحص والكتابة — `O_NOFOLLOW` يمنع اتباعه."""
    repo = make_repo(tmp_path)
    directory = ensure_private_directory(repo)
    victim = tmp_path / "victim.md"
    victim.write_text("original", encoding="utf-8")
    (directory / DISCOVERY_MARKDOWN).symlink_to(victim)

    with pytest.raises(PrivateStoreError):
        write_private_text(repo, DISCOVERY_MARKDOWN, "leaked balance 212.34")
    assert victim.read_text(encoding="utf-8") == "original"


# ---------------------------------------------------------------------------
# 4. اجتياز المسار
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "../escaped.md",
    "../../escaped.md",
    "sub/dir.md",
    "..",
    ".",
    "CAPITAL_COM_LIVE_DISCOVERY.md.bak",
    "arbitrary.md",
])
def test_path_traversal_and_unknown_filenames_are_rejected(name):
    with pytest.raises(PrivateStoreError):
        private_path(REPO_ROOT, name)


def test_only_the_three_declared_filenames_are_allowed():
    assert SENSITIVE_FILENAMES == {
        DISCOVERY_MARKDOWN, DISCOVERY_JSON, ACTUAL_FEASIBILITY_MARKDOWN,
    }
    for name in SENSITIVE_FILENAMES:
        assert private_path(REPO_ROOT, name).parent == private_directory(REPO_ROOT)


def test_private_directory_is_exactly_the_declared_path():
    assert CAPITAL_LIVE_PARTS == ("data", "private", "capital_live")
    directory = private_directory(REPO_ROOT)
    assert directory.relative_to(REPO_ROOT).parts == CAPITAL_LIVE_PARTS


def test_directory_outside_the_project_fails_the_inside_check(tmp_path):
    repo = make_repo(tmp_path)
    ensure_private_directory(repo)
    other = tmp_path / "other"
    other.mkdir()
    result = preflight(other)
    assert result.passed is False


# ---------------------------------------------------------------------------
# 5. الصلاحيات
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not POSIX, reason="الصلاحيات تحتاج POSIX.")
def test_directory_is_created_with_mode_700(tmp_path):
    repo = make_repo(tmp_path)
    directory = ensure_private_directory(repo)
    assert stat.S_IMODE(directory.stat().st_mode) == DIR_MODE
    assert stat.S_IMODE((repo / "data" / "private").stat().st_mode) == DIR_MODE


@pytest.mark.skipif(not POSIX, reason="الصلاحيات تحتاج POSIX.")
def test_files_are_written_with_mode_600(tmp_path):
    repo = make_repo(tmp_path)
    ensure_private_directory(repo)
    path = write_private_text(repo, DISCOVERY_MARKDOWN, "محتوى")
    assert stat.S_IMODE(path.stat().st_mode) == FILE_MODE


@pytest.mark.skipif(not POSIX, reason="الصلاحيات تحتاج POSIX.")
def test_world_readable_directory_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    directory = ensure_private_directory(repo)
    directory.chmod(0o755)
    result = preflight(repo)
    assert result.passed is False
    assert "DIR_PERMISSIONS" in {c.key for c in result.failures()}


@pytest.mark.skipif(not POSIX, reason="الصلاحيات تحتاج POSIX.")
def test_group_readable_directory_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    directory = ensure_private_directory(repo)
    directory.chmod(0o740)
    result = preflight(repo)
    assert result.passed is False
    assert "DIR_PERMISSIONS" in {c.key for c in result.failures()}


@pytest.mark.skipif(not POSIX, reason="الصلاحيات تحتاج POSIX.")
def test_world_or_group_readable_file_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    ensure_private_directory(repo)
    path = write_private_text(repo, DISCOVERY_JSON, "{}")
    for mode in (0o644, 0o640):
        path.chmod(mode)
        result = preflight(repo)
        assert result.passed is False
        assert "FILE_PERMISSIONS" in {c.key for c in result.failures()}


@pytest.mark.skipif(not POSIX, reason="الصلاحيات تحتاج POSIX.")
def test_require_private_output_returns_a_passing_result(tmp_path):
    repo = make_repo(tmp_path)
    result = require_private_output(repo)
    assert result.passed is True
    assert "اجتاز" in result.summary_ar()


# ---------------------------------------------------------------------------
# 6. لا قيم حساب تحت docs/
# ---------------------------------------------------------------------------

ACCOUNT_VALUE_PATTERNS = (
    re.compile(r"الرصيد\s*\|"),
    re.compile(r"المتاح\s*\|"),
    re.compile(r"الربح/الخسارة\s*\|"),
    re.compile(r"\*{4}\d{4}"),          # معرّف مُقنَّع مثل ****6655
    # بريد — النطاق يبدأ بحرف وينتهي بامتداد حروف، كي لا يلتقط النمطُ
    # معرّفات مثل `TREND_PULLBACK@1.0.0` وهي ليست بريداً.
    re.compile(r"[\w.+-]+@[A-Za-z][\w-]*(?:\.[\w-]+)*\.[A-Za-z]{2,}"),
)


def test_no_tracked_doc_contains_an_account_value():
    """
    فحص على **الملفات المتتبَّعة فعلاً** تحت docs/ — لا على القرص وحده،
    كي يشمل ما دخل السجل.
    """
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "docs/"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    for relative in tracked:
        path = REPO_ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in ACCOUNT_VALUE_PATTERNS:
            match = pattern.search(text)
            assert match is None, f"{relative} يحتوي قيمة حساب: {match.group(0)!r}"


def test_public_feasibility_report_carries_no_account_value():
    from tests.test_live_readonly import (
        authenticated_session, run_live_discovery,
    )

    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()
    eurusd = report.instrument("EURUSD")

    planned = compute_feasibility(eurusd, equity=D("150.00"))
    public = render_public_feasibility_markdown(planned=planned)

    assert "212.34" not in public          # الرصيد الفعلي في التجهيزة
    assert "210.00" not in public          # المتاح
    assert "****6655" not in public        # المعرّف المُقنَّع
    assert "@" not in public
    assert "150.00" in public
    assert "تقرير عام" in public


def test_private_actual_report_is_marked_private_and_may_carry_the_balance():
    from tests.test_live_readonly import (
        authenticated_session, run_live_discovery,
    )

    session, _ = authenticated_session()
    report = run_live_discovery(session)
    session.discard()
    eurusd = report.instrument("EURUSD")

    actual = compute_feasibility(eurusd, equity=D("212.34"))
    private = render_actual_feasibility_markdown(report, actual=actual)

    assert "212.34" in private             # مسموح — ملف خاص
    assert "ملف خاص" in private
    assert "data/private/capital_live/" in private
    assert "لا يُرفع" in private


# ---------------------------------------------------------------------------
# 7. مخرَج الطرفية
# ---------------------------------------------------------------------------

def test_cli_prints_no_account_value(monkeypatch, capsys, tmp_path):
    """
    يُشغَّل الأمر بمصادقة مُقلَّدة تماماً، ويُتحقَّق أن الطرفية لا تحمل
    رصيداً ولا متاحاً ولا ربحاً/خسارة ولا معرّف حساب.
    """
    import app.cli as cli
    from tests.test_live_readonly import (
        FAKE_ACCOUNT_ID, MockLiveTransport, full_routes, rsa_key_b64, secrets,
    )
    from app.live_readonly.session import LiveSession

    repo = make_repo(tmp_path)
    (repo / "docs").mkdir()
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    monkeypatch.setattr(cli, "build_secret_provider", lambda **_: secrets())

    transport = MockLiveTransport(full_routes(rsa_key_b64()))
    monkeypatch.setattr(cli, "LiveReadOnlyTransport", lambda *a, **k: transport)
    monkeypatch.setattr(
        cli, "LiveSession",
        lambda **kw: LiveSession(transport=transport, secrets=kw["secrets"]),
    )

    args = cli.build_parser().parse_args(
        ["capital-live-discover", "--acknowledge-live-read-only"]
    )
    code = cli.cmd_capital_live_discover(args)
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert code == 0, combined
    for forbidden in ("212.34", "210.00", "-2.34", FAKE_ACCOUNT_ID, "****6655"):
        assert forbidden not in combined, f"تسرّب إلى الطرفية: {forbidden}"

    # المسموح فقط
    assert "المصادقة: ✅ نجحت" in combined
    assert "عملة الحساب: USD" in combined
    assert "اكتشاف الأدوات:" in combined
    assert "data/private/capital_live" in combined
    assert "GO" in combined


def test_cli_refuses_before_authentication_when_the_target_is_not_private(
    monkeypatch, capsys, tmp_path
):
    """فحص الخصوصية يسبق المصادقة: لا شبكة إن سقط الفحص."""
    import app.cli as cli
    from tests.test_live_readonly import MockLiveTransport, full_routes, rsa_key_b64

    repo = make_repo(tmp_path, gitignore="secrets/\n")   # data/private غير متجاهَل
    monkeypatch.setattr(cli, "REPO_ROOT", repo)

    transport = MockLiveTransport(full_routes(rsa_key_b64()))
    monkeypatch.setattr(cli, "LiveReadOnlyTransport", lambda *a, **k: transport)

    args = cli.build_parser().parse_args(
        ["capital-live-discover", "--acknowledge-live-read-only"]
    )
    code = cli.cmd_capital_live_discover(args)
    err = capsys.readouterr().err

    assert code == 4
    assert "لم تُجرَ أي مصادقة" in err
    assert transport.sent == []          # لم يُرسَل أي طلب إطلاقاً


# ---------------------------------------------------------------------------
# 8. أرشيف التسليم
# ---------------------------------------------------------------------------

ARCHIVE_SCRIPT = REPO_ROOT / "scripts" / "make_delivery_archive.sh"


def test_delivery_archive_script_exists_and_is_executable():
    assert ARCHIVE_SCRIPT.exists()
    if POSIX:
        assert os.access(ARCHIVE_SCRIPT, os.X_OK)


@pytest.mark.skipif(not POSIX, reason="السكربت يحتاج bash.")
def test_delivery_archive_excludes_private_files(tmp_path):
    """
    يُبنى أرشيف من مشروع يحتوي ملفاً خاصاً بمحتوى مميّز، ويُتحقَّق أن الأرشيف
    لا يحتوي المسار ولا المحتوى.
    """
    project = tmp_path / "Maather-Autonomous-Trader"
    (project / "scripts").mkdir(parents=True)
    (project / "docs").mkdir()
    (project / "data" / "private" / "capital_live").mkdir(parents=True)
    (project / "secrets").mkdir()

    (project / "docs" / "public.md").write_text("عام", encoding="utf-8")
    marker = "BALANCE-MARKER-212-34"
    (project / "data" / "private" / "capital_live" / DISCOVERY_MARKDOWN).write_text(
        marker, encoding="utf-8"
    )
    (project / "secrets" / "capital.env").write_text("SECRET=1", encoding="utf-8")

    script = project / "scripts" / "make_delivery_archive.sh"
    script.write_text(ARCHIVE_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o700)

    output = tmp_path / "delivery.tar.gz"
    result = subprocess.run(
        ["bash", str(script), str(output)],
        capture_output=True, text=True, cwd=str(project),
    )
    assert result.returncode == 0, result.stderr
    assert output.exists()

    listing = subprocess.run(
        ["tar", "-tzf", str(output)], capture_output=True, text=True, check=True
    ).stdout
    assert "data/private" not in listing
    assert "secrets/" not in listing
    assert "docs/public.md" in listing

    raw = output.read_bytes()
    import gzip

    assert marker.encode() not in gzip.decompress(raw)


@pytest.mark.skipif(not POSIX, reason="السكربت يحتاج bash.")
def test_delivery_archive_script_parses_under_bash():
    result = subprocess.run(
        ["bash", "-n", str(ARCHIVE_SCRIPT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
