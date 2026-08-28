"""
PRIVATE STORE — مخزن المخرجات الحسّاسة، يُثبت خصوصيته قبل الكتابة.

## لماذا لا يكفي «لا تعمليه commit»

الاتفاق ليس ضابطاً. الرصيد الحقيقي كان يُكتب في `docs/` وهو مسار **متتبَّع**،
فيكفي `git add -A` واحد ليدخل السجل إلى الأبد. الضابط الصحيح أن يكون المسار
**مُثبَتاً** أنه خاص ومتجاهَل وغير متتبَّع **قبل** أن يُكتب فيه حرف واحد.

## المسار الوحيد للمخرجات الحسّاسة

    data/private/capital_live/

## يفشل مغلقاً (fail closed)

أي من هذه يمنع الكتابة، ولا يُفترض حسن النية في أي منها:

  * الهدف **متتبَّع** في git
  * الهدف **غير مشمول** بـ`.gitignore`
  * أي مقطع في المسار **رابط رمزي**
  * الهدف **خارج** شجرة المشروع المتوقَّعة
  * الملف أو المجلد **مقروء للعالم**
  * الملف أو المجلد **مقروء للمجموعة** (حيث تُدعَم الصلاحيات)
  * تعذّر إثبات أي مما سبق (git غير متاح مثلاً)

عدم القدرة على الإثبات = فشل. لا استثناء «تحذير ونكمل».
"""
from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: المجلد الخاص الوحيد للمخرجات الحسّاسة، نسبةً إلى جذر المستودع.
PRIVATE_ROOT_PARTS: tuple[str, ...] = ("data", "private")
CAPITAL_LIVE_PARTS: tuple[str, ...] = PRIVATE_ROOT_PARTS + ("capital_live",)

#: أسماء الملفات الحسّاسة المسموح كتابتها هناك.
DISCOVERY_MARKDOWN = "CAPITAL_COM_LIVE_DISCOVERY.md"
DISCOVERY_JSON = "capital_live_discovery.json"
ACTUAL_FEASIBILITY_MARKDOWN = "CAPITAL_COM_ACTUAL_BALANCE_FEASIBILITY.md"

SENSITIVE_FILENAMES: frozenset[str] = frozenset({
    DISCOVERY_MARKDOWN, DISCOVERY_JSON, ACTUAL_FEASIBILITY_MARKDOWN,
})

DIR_MODE = 0o700
FILE_MODE = 0o600
#: الملف العام تحت `docs/` ليس حسّاساً — لكنه يُكتب ذرّياً كذلك.
PUBLIC_FILE_MODE = 0o644

#: بتّات لا يجوز أن تكون مضبوطة على أي مخرَج حسّاس (المجموعة والعالم).
FORBIDDEN_MODE_BITS = 0o077

_PERMISSIONS_SUPPORTED = os.name == "posix"


class PrivateStoreError(RuntimeError):
    """فشل إثبات الخصوصية. لا تُكتب أي بيانات."""


@dataclass(frozen=True)
class PreflightCheck:
    key: str
    passed: bool
    detail_ar: str

    def as_dict(self) -> dict:
        return {"key": self.key, "passed": self.passed, "detail_ar": self.detail_ar}


@dataclass(frozen=True)
class PreflightResult:
    directory: Path
    checks: tuple[PreflightCheck, ...]
    permissions_supported: bool

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def as_dict(self) -> dict:
        return {
            "directory": str(self.directory),
            "passed": self.passed,
            "permissions_supported": self.permissions_supported,
            "checks": [c.as_dict() for c in self.checks],
        }

    def summary_ar(self) -> str:
        lines = [f"فحص خصوصية المخرجات: {'✅ اجتاز' if self.passed else '⛔ فشل'}"]
        for c in self.checks:
            lines.append(f"  {'✅' if c.passed else '❌'} {c.key} — {c.detail_ar}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# أدوات git
# ---------------------------------------------------------------------------

def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, timeout=15,
    )


def is_git_tracked(repo_root: Path, path: Path) -> Optional[bool]:
    """
    True متتبَّع · False غير متتبَّع · None تعذّر الإثبات.
    `None` تُعامَل معاملة الفشل في المسار الصارم.
    """
    try:
        result = _git(repo_root, "ls-files", "--error-unmatch", str(path))
    except (OSError, subprocess.SubprocessError):
        return None
    return result.returncode == 0


def is_git_ignored(repo_root: Path, path: Path) -> Optional[bool]:
    """True متجاهَل · False غير متجاهَل · None تعذّر الإثبات."""
    try:
        result = _git(repo_root, "check-ignore", "-q", str(path))
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


# ---------------------------------------------------------------------------
# المسارات
# ---------------------------------------------------------------------------

def private_directory(repo_root: Path) -> Path:
    return repo_root.joinpath(*CAPITAL_LIVE_PARTS)


def private_path(repo_root: Path, filename: str) -> Path:
    """
    يبني مساراً حسّاساً. **لا يقبل اسماً خارج القائمة** ولا اسماً يحمل مقاطع
    مسار — فلا يمكن الخروج من المجلد الخاص عبر الاسم.
    """
    if filename not in SENSITIVE_FILENAMES:
        raise PrivateStoreError(f"اسم ملف غير مسموح في المخزن الخاص: {filename}")
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise PrivateStoreError("اسم الملف يحتوي مقاطع مسار.")
    return private_directory(repo_root) / filename


def _has_symlink_component(repo_root: Path, target: Path) -> Optional[str]:
    """يفحص كل مقطع من جذر المستودع حتى الهدف. يعيد اسم أول رابط رمزي."""
    current = repo_root
    if current.is_symlink():
        return str(current)
    try:
        relative = target.relative_to(repo_root)
    except ValueError:
        return None
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return str(current)
        if not current.exists():
            break
    return None


def _mode_of(path: Path) -> Optional[int]:
    try:
        return stat.S_IMODE(path.lstat().st_mode)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# التهيئة والفحص
# ---------------------------------------------------------------------------

def ensure_private_directory(repo_root: Path) -> Path:
    """ينشئ المجلد بصلاحية 700 ويشدّد صلاحيات الأصل `data/private`."""
    directory = private_directory(repo_root)
    parent = repo_root.joinpath(*PRIVATE_ROOT_PARTS)
    for path in (parent, directory):
        path.mkdir(parents=True, exist_ok=True)
        if _PERMISSIONS_SUPPORTED:
            try:
                path.chmod(DIR_MODE)
            except OSError:
                pass
    return directory


def preflight(
    repo_root: Path, *, filenames: Optional[tuple[str, ...]] = None
) -> PreflightResult:
    """
    يُثبت أن الهدف خاص ومتجاهَل وغير متتبَّع — **قبل أي مصادقة أو كتابة**.
    """
    repo_root = repo_root.resolve()
    directory = private_directory(repo_root)
    targets = tuple(
        private_path(repo_root, name) for name in (filenames or tuple(SENSITIVE_FILENAMES))
    )
    checks: list[PreflightCheck] = []

    def add(key: str, ok: bool, detail: str) -> None:
        checks.append(PreflightCheck(key, ok, detail))

    # 1) داخل شجرة المشروع المتوقَّعة
    try:
        resolved_dir = directory.resolve()
        inside = resolved_dir.is_relative_to(repo_root) and (
            resolved_dir.relative_to(repo_root).parts == CAPITAL_LIVE_PARTS
        )
    except (OSError, ValueError):
        resolved_dir, inside = directory, False
    add(
        "INSIDE_PROJECT",
        inside,
        f"المجلد {'داخل' if inside else 'خارج'} المسار المتوقَّع "
        f"{'/'.join(CAPITAL_LIVE_PARTS)}.",
    )

    # 2) لا روابط رمزية في أي مقطع
    symlink = _has_symlink_component(repo_root, directory)
    add(
        "NO_SYMLINK_IN_PATH",
        symlink is None,
        "لا رابط رمزي في المسار." if symlink is None
        else f"مقطع رابط رمزي: {symlink}",
    )
    for target in targets:
        if target.is_symlink():
            add("NO_SYMLINK_TARGET", False, f"الهدف رابط رمزي: {target.name}")
            break
    else:
        add("NO_SYMLINK_TARGET", True, "لا هدف رابط رمزي.")

    # 3) مشمول بـ.gitignore
    ignored = is_git_ignored(repo_root, directory)
    add(
        "GIT_IGNORED",
        ignored is True,
        "المجلد مشمول بـ.gitignore." if ignored is True
        else ("المجلد **غير** مشمول بـ.gitignore." if ignored is False
              else "تعذّر إثبات التجاهل (git غير متاح؟) — يُعامَل فشلاً."),
    )

    # 4) غير متتبَّع — المجلد وكل هدف
    tracked_problem: Optional[str] = None
    for path in (directory, *targets):
        tracked = is_git_tracked(repo_root, path)
        if tracked is None:
            tracked_problem = f"تعذّر إثبات حالة التتبّع لـ{path.name}."
            break
        if tracked:
            tracked_problem = f"{path.name} **متتبَّع** في git."
            break
    add(
        "NOT_GIT_TRACKED",
        tracked_problem is None,
        tracked_problem or "لا شيء من الأهداف متتبَّع في git.",
    )

    # 5) صلاحيات المجلد
    if not _PERMISSIONS_SUPPORTED:
        add("DIR_PERMISSIONS", True, "النظام لا يدعم صلاحيات POSIX — الفحص متجاوَز.")
        add("FILE_PERMISSIONS", True, "النظام لا يدعم صلاحيات POSIX — الفحص متجاوَز.")
    else:
        mode = _mode_of(directory) if directory.exists() else None
        if mode is None:
            add("DIR_PERMISSIONS", False, "المجلد غير موجود أو تعذّرت قراءة صلاحياته.")
        else:
            ok = (mode & FORBIDDEN_MODE_BITS) == 0
            add(
                "DIR_PERMISSIONS",
                ok,
                f"صلاحيات المجلد {oct(mode)}"
                + ("" if ok else " — مقروء للمجموعة أو للعالم."),
            )

        bad: list[str] = []
        for target in targets:
            if not target.exists():
                continue
            fmode = _mode_of(target)
            if fmode is None or (fmode & FORBIDDEN_MODE_BITS) != 0:
                bad.append(f"{target.name}={oct(fmode) if fmode else '?'}")
        add(
            "FILE_PERMISSIONS",
            not bad,
            "صلاحيات كل الملفات الموجودة 600." if not bad
            else "ملفات بصلاحيات مفتوحة: " + "، ".join(bad),
        )

    return PreflightResult(
        directory=directory,
        checks=tuple(checks),
        permissions_supported=_PERMISSIONS_SUPPORTED,
    )


def require_private_output(repo_root: Path) -> PreflightResult:
    """
    ينشئ المجلد ثم يُثبت خصوصيته. يرفع عند أي فشل — **قبل أي مصادقة**.
    """
    ensure_private_directory(repo_root)
    result = preflight(repo_root)
    if not result.passed:
        details = "؛ ".join(c.detail_ar for c in result.failures())
        raise PrivateStoreError(
            "المخرجات الحسّاسة لن تُكتب: تعذّر إثبات خصوصية الهدف. " + details
        )
    return result


def _atomic_write_text(path: Path, text: str, *, mode: int) -> Path:
    """
    كتابة **ذرّية**: ملف مؤقت في المجلد نفسه، ثم `os.replace`.

    لماذا: الكتابة المباشرة بـ`O_TRUNC` تُفرغ الملف أولاً. لو انقطع التنفيذ
    بعدها — استثناء، أو قرص ممتلئ، أو Ctrl-C — بقي في مكانه تقريرٌ **مبتور**
    يبدو صالحاً. `os.replace` ذرّي على المستوى نفسه: إما المحتوى القديم كاملاً
    أو الجديد كاملاً، ولا حالة ثالثة.

    الملف المؤقت يُفتح بـ`O_EXCL` (فلا يُكتب فوق شيء) و`O_NOFOLLOW` (فلا يُتبَع
    رابط زُرع)، ويُحذف في `finally` إن لم يُنقل.
    """
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        os.unlink(tmp)
    except OSError:
        pass
    try:
        fd = os.open(tmp, flags, mode)
    except OSError as exc:
        raise PrivateStoreError(
            f"تعذّرت الكتابة الآمنة إلى {path.name}: {exc.errno}"
        ) from None
    moved = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if _PERMISSIONS_SUPPORTED:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        os.replace(tmp, path)
        moved = True
    finally:
        if not moved:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return path


def write_private_text(repo_root: Path, filename: str, text: str) -> Path:
    """
    يكتب ملفاً حسّاساً بصلاحية 600، ذرّياً، بعد التأكد أنه ليس رابطاً رمزياً.
    """
    path = private_path(repo_root, filename)
    if path.is_symlink():
        raise PrivateStoreError(f"الهدف رابط رمزي: {path.name}")
    return _atomic_write_text(path, text, mode=FILE_MODE)


def write_public_text(path: Path, text: str) -> Path:
    """
    كتابة ذرّية لملف **عام** (تحت `docs/`) — بصلاحيات عادية `644`.

    ليس حسّاساً، لكن البتر يصيبه كما يصيب غيره: تقرير جدوى نصفه مكتوب أسوأ من
    غياب التقرير، لأنه يبدو مكتملاً.
    """
    if path.is_symlink():
        raise PrivateStoreError(f"الهدف رابط رمزي: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return _atomic_write_text(path, text, mode=PUBLIC_FILE_MODE)


__all__ = [
    "PRIVATE_ROOT_PARTS",
    "CAPITAL_LIVE_PARTS",
    "DISCOVERY_MARKDOWN",
    "DISCOVERY_JSON",
    "ACTUAL_FEASIBILITY_MARKDOWN",
    "SENSITIVE_FILENAMES",
    "DIR_MODE",
    "FILE_MODE",
    "PUBLIC_FILE_MODE",
    "PrivateStoreError",
    "PreflightCheck",
    "PreflightResult",
    "private_directory",
    "private_path",
    "ensure_private_directory",
    "preflight",
    "require_private_output",
    "write_private_text",
    "write_public_text",
    "is_git_tracked",
    "is_git_ignored",
]
