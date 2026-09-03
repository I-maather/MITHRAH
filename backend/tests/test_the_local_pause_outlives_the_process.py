"""
قرارٌ يُمحى بإعادة تشغيل — ويُعرَض على أنه قرار المالكة.

## ما وقع

`locally_paused` كانت `True` في كل بناء، وقاطع الطوارئ يُحفَظ على القرص.
فبعد كل نشر:

    الخدمة: active · الحلقة: تدور · الحكم: «لا تداول اليوم — التداول
    موقوف محلياً بقرارك»

وهو ليس قرارها؛ هو قيمةُ إقلاع. والفرق أن القرار يُراجَع وقيمةَ الإقلاع
لا يعرف أحدٌ أنها هناك — فيبقى النظام واقفاً أياماً وهو «يعمل».

ورُصد ذلك مباشرةً في نشر 2026-09-03: الحلقة دارت مرّتين بعد النشر
وأخرجت الجملة نفسها، وقد كان الإيقاف مرفوعاً قبله بدقائق.

## القاعدة المفروضة هنا

١. الحالة تُكتب عند كل تغيير وتُقرأ عند الإقلاع.
٢. الغياب = إيقاف (المجهول «لا»).
٣. ملفٌ تالف = غياب، لا تخمين.
٤. **موضع كتابةٍ واحد**: `set_local_pause`. وأي إسنادٍ مباشر خارجها يترك
   القرص متخلّفاً عن الذاكرة — يحرسه فحصٌ ساكن هنا.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.runtime import local_pause


class _Sys:
    locally_paused = True


def test_absence_means_paused(tmp_path: Path):
    state = local_pause.load(tmp_path / "nope.json")
    assert state.paused is True
    assert state.source == "default"


def test_a_corrupt_file_is_treated_as_absent(tmp_path: Path):
    target = tmp_path / "local-pause.json"
    target.write_text("{ليس جيسون", encoding="utf-8")
    assert local_pause.load(target).paused is True


def test_a_file_without_the_key_is_treated_as_absent(tmp_path: Path):
    target = tmp_path / "local-pause.json"
    target.write_text(json.dumps({"note": "hi"}), encoding="utf-8")
    assert local_pause.load(target).paused is True


def test_a_resume_survives_a_restart(tmp_path: Path):
    """**الفحص الذي يعضّ.** رفعُ الإيقاف يجب أن يبقى مرفوعاً بعد إقلاعٍ جديد."""
    target = tmp_path / "local-pause.json"
    sys_state = _Sys()
    local_pause.set_local_pause(
        sys_state, False, reason_ar="تجربة الحساب التجريبي", source="ui", path=target
    )
    assert sys_state.locally_paused is False
    # «إقلاعٌ جديد» = قراءةٌ من القرص بلا ذاكرة.
    restored = local_pause.load(target)
    assert restored.paused is False
    assert restored.reason_ar == "تجربة الحساب التجريبي"
    assert restored.source == "ui"
    assert restored.at_utc


def test_a_pause_survives_a_restart_too(tmp_path: Path):
    target = tmp_path / "local-pause.json"
    sys_state = _Sys()
    local_pause.set_local_pause(sys_state, True, reason_ar="أوقفي", source="mobile", path=target)
    assert local_pause.load(target).paused is True


def test_the_write_is_atomic_and_leaves_no_partial_file(tmp_path: Path):
    target = tmp_path / "local-pause.json"
    for i in range(20):
        local_pause.save(bool(i % 2), reason_ar=f"n{i}", source="t", path=target)
        json.loads(target.read_text(encoding="utf-8"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".local-pause-")]
    assert leftovers == []


def test_only_one_place_writes_the_flag():
    """
    حارسٌ ساكن. إسنادٌ مباشر في أي وحدةٍ أخرى يعيد العطل: الذاكرة تتغيّر
    والقرص لا، فيعود «الإيقاف يُمحى بإعادة التشغيل» من بابٍ آخر.
    """
    root = Path(local_pause.__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "local_pause.py" or "__pycache__" in str(path):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".locally_paused =" in stripped or ".locally_paused=" in stripped:
                offenders.append(f"{path.relative_to(root)}:{number}: {stripped}")
    assert offenders == [], (
        "إسنادٌ مباشر لـlocally_paused خارج set_local_pause — "
        "الذاكرة ستتغيّر والقرص لا:\n" + "\n".join(offenders)
    )


def test_the_boot_reads_the_file_not_a_constant():
    """
    وحارسٌ على البناء نفسه: `locally_paused=True` ثابتةً في `build_system`
    هي بالضبط ما كان.
    """
    from app.api import state as state_module

    text = Path(state_module.__file__).read_text(encoding="utf-8")
    assert "locally_paused=_local_pause.paused" in text
    assert "locally_paused=True," not in text


def test_the_file_lives_where_the_service_may_write():
    """
    **حارسٌ على المكان لا على المنطق.**

    وحدة الخدمة تُقيّد الكتابة: `ProtectSystem=strict` مع
    `ReadWritePaths=/opt/mathrah/data`. فملفٌ تحت `backend/data` يُكتب في
    الاختبارات ويُرفض على الخادم — وهي أسوأ صور العطل: خضراءُ محلياً،
    صامتةٌ في الإنتاج، وأثرُها أن قرار المالكة لا يُحفَظ.

    والمرجع هنا وحدة الخدمة نفسها، لا قياسٌ منقول.
    """
    repo = Path(local_pause.__file__).resolve().parents[3]
    assert local_pause.DEFAULT_PATH == repo / "data" / "local-pause.json"

    unit = repo / "deploy" / "server_bootstrap.sh"
    if unit.exists():
        text = unit.read_text(encoding="utf-8")
        assert "ReadWritePaths=$APP_DIR/data" in text, (
            "تغيّر المسار المسموح في وحدة الخدمة — يُراجَع مكان الملف معه."
        )
        assert "ProtectSystem=strict" in text


def test_the_mobile_state_and_the_pause_share_the_writable_directory():
    """الملفّان اللذان تكتبهما الخدمة يسكنان معاً — فلا يُنسى أحدهما."""
    from app import main as main_module

    assert main_module._MOBILE_STATE_PATH.parent == local_pause.DEFAULT_PATH.parent
