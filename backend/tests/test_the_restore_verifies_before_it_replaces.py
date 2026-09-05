"""نسخةٌ لا تُختبَر ليست نسخة، هي رجاء.

الاسترجاع هو اللحظة التي تُكتشف فيها النسخة الفاسدة. فإن كان الطريق
«انسخ فوق الحيّة ثم انظر» فقد فُقد الأصل والبديل معاً في الخطوة نفسها.
ولذلك يفحص هذا الملف **شكل** السكربتات لا نتيجتها: أنّ التحقّق يسبق
اللمس، وأنّ شيئاً لا يُحذف، وأنّ الأسرار لا تُسحَب إلى قرصٍ ثانٍ.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "deploy" / "backup.sh"
RESTORE = ROOT / "deploy" / "restore.sh"
PULL = ROOT / "scripts" / "pull_backups.sh"
TIMER = ROOT / "deploy" / "templates" / "mathrah-backup.timer"


def _code(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_all_three_scripts_exist_and_run():
    for path in (BACKUP, RESTORE, PULL):
        assert path.is_file(), f"مفقود: {path.name}"
        assert path.stat().st_mode & 0o111, f"غير قابل للتنفيذ: {path.name}"


def test_the_backup_is_a_consistent_snapshot_not_a_file_copy():
    code = _code(BACKUP)
    assert "source.backup(target)" in code, (
        "نسخُ ملفٍ حيّ يلتقط صفحاتٍ نصفَ مكتوبة — تُستعمل لقطة sqlite"
    )
    assert "integrity_check" in code, "نسخةٌ تُؤخذ بلا فحصٍ فوري"
    assert "sha256sum" in code, "بلا بصمةٍ لا يُعرَف أنّ النسخة لم تتبدّل"


def test_the_restore_checks_before_it_touches_anything():
    code = _code(RESTORE)
    apply_at = code.index("--apply")
    integrity_at = code.index("integrity_check")
    assert integrity_at < code.index("systemctl stop"), "الإيقاف قبل الفحص"
    assert apply_at >= 0
    assert "mv \"$DATA/maather.db\"" in code, "الحيّة تُستبدل بلا إزاحة"


def test_nothing_in_the_restore_deletes_the_live_database():
    code = _code(RESTORE)
    assert "rm -f \"$DATA/maather.db\"" not in code
    assert "rm -rf \"$DATA" not in code


def test_the_default_is_dry_and_says_so():
    code = _code(RESTORE)
    assert 'if [ "$APPLY" != "--apply" ]' in code, "الاستبدال هو الافتراضي"


def test_secrets_are_not_pulled_off_the_server():
    code = _code(PULL)
    assert "secrets" not in code, "الأسرار تُسحَب إلى قرصٍ ثانٍ"


def test_the_hourly_timer_is_declared():
    text = TIMER.read_text(encoding="utf-8")
    assert "OnCalendar=hourly" in text
    assert "Persistent=true" in text, "مؤقّتٌ يفوت بعد إطفاءٍ ولا يُعوَّض"
