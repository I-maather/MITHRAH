"""المستودع العامل بيتٌ واحد — لا نسخةٌ ثانيةٌ صامتة.

المستودع يعيش على وعاءٍ خارجيّ يُفصَل حين ينام الماك. والخطر ليس التوقّف:
الخطر أن تُنشئ أداةٌ مجلداً داخلياً بالاسم نفسه، فتصير نسختان تتباعدان بلا
أن يعلم أحد. فالحارس يجب أن **يفشل** لا أن يبتكر بديلاً — وهذا ما تقيسه
هذه الاختبارات على نصّه، لأنّ الجهاز الذي تجري عليه قد لا يكون ماكها.
"""

from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "scripts" / "mathrah_mount.sh"


def _source() -> str:
    return GUARD.read_text(encoding="utf-8")


def _code_only() -> str:
    # حارسٌ يقرأ التعليقات يمنع شرحَ ما أُصلح.
    return "\n".join(
        line for line in _source().splitlines() if not line.lstrip().startswith("#")
    )


def test_the_guard_exists_and_runs():
    assert GUARD.is_file(), "حارس الوعاء مفقود"
    assert GUARD.stat().st_mode & 0o111, "الحارس غير قابل للتنفيذ"


def test_the_guard_never_creates_a_replacement():
    code = _code_only()
    for forbidden in ("mkdir -p \"$MATHRAH_REPO", "mkdir -p $MATHRAH_REPO"):
        assert forbidden not in code, "الحارس ينشئ بديلاً — وهذا ما يمنعه وجودُه"


def test_a_real_directory_where_a_link_belongs_is_refused():
    code = _code_only()
    assert "! -L" in code, "الحارس لا يفحص أنّ المسار رابطٌ رمزي"


def test_the_volume_is_identified_by_fingerprint_not_name():
    code = _code_only()
    assert ".mathrah-volume" in code and ".mathrah-expected-volume" in code, (
        "الاسم وحده لا يميّز وعاءً — البصمة تفصل"
    )


def test_the_volume_must_be_external():
    assert "External" in _code_only(), "الحارس لا يتحقّق أنّ الوعاء خارجيّ"


def test_failure_returns_nonzero():
    code = _code_only()
    assert "return 1" in code, "الحارس لا يُرجع فشلاً"
