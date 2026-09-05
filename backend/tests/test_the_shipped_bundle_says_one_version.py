"""رقمُ النسخة واحدٌ — في المصدر وفي **الحزمة المشحونة**.

الشاشة كانت تقول `0.6.2` وهي تقرأ `package.json`، والحزمة تقول `0.4.0` وهي
تحمل قيمةً حرفيّةً متجمّدة في `Info.plist`. فحصُ المصادر وحده كان يمرّ —
لأنّ المصدرين لم يكونا يتقاطعان. لذلك يقرأ هذا الملف **ما يُشحن فعلاً**:
`Info.plist` داخل `MaatherTrader.app` بعد البناء.

وحين لا توجد حزمة، يُصرَّح بذلك بدل أن يُدَّعى نجاح. وفي بوابة الإصدار
تُضبَط `MATHRAH_REQUIRE_BUILT_APP=1` فيصير غيابُ الحزمة **فشلاً**.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "mobile" / "package.json"
PBXPROJ = ROOT / "mobile" / "ios" / "MaatherTrader.xcodeproj" / "project.pbxproj"
INFO = ROOT / "mobile" / "ios" / "MaatherTrader" / "Info.plist"


def declared_version() -> str:
    return json.loads(PACKAGE.read_text(encoding="utf-8"))["version"]


def _marketing_versions() -> set[str]:
    text = PBXPROJ.read_text(encoding="utf-8")
    return set(re.findall(r"MARKETING_VERSION = ([^;]+);", text))


def _plist(path: Path) -> dict:
    with path.open("rb") as handle:
        return plistlib.load(handle)


def _built_apps() -> list[Path]:
    named = os.environ.get("MATHRAH_BUILT_APP")
    if named:
        return [Path(named)]
    derived = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"
    if not derived.is_dir():
        return []
    return sorted(derived.glob("MaatherTrader-*/Build/Products/*/MaatherTrader.app"))


def test_the_source_of_the_version_is_one_file():
    assert _marketing_versions() == {declared_version()}, (
        "MARKETING_VERSION لا يطابق package.json — "
        f"{_marketing_versions()} مقابل {declared_version()}"
    )


def test_the_plist_points_instead_of_repeating():
    info = _plist(INFO)
    assert info["CFBundleShortVersionString"] == "$(MARKETING_VERSION)", (
        "Info.plist يحمل رقماً حرفياً — وهو ما يُنتج رقمين متناقضين"
    )
    assert info["CFBundleVersion"] == "$(CURRENT_PROJECT_VERSION)"


def test_the_built_bundle_carries_the_declared_version():
    apps = [app for app in _built_apps() if (app / "Info.plist").is_file()]
    if not apps:
        if os.environ.get("MATHRAH_REQUIRE_BUILT_APP") == "1":
            pytest.fail(
                "بوابةُ الإصدار تطلب حزمةً مبنيّة ولا حزمة — ابنِ ثم أعد الاختبار"
            )
        pytest.skip("لا حزمة مبنيّة على هذا الجهاز — يُقرأ المصدر وحده")
    want = declared_version()
    for app in apps:
        info = _plist(app / "Info.plist")
        assert info.get("CFBundleShortVersionString") == want, (
            f"الحزمة {app} تقول {info.get('CFBundleShortVersionString')} "
            f"والمصدر يقول {want}"
        )


def test_the_sync_script_is_reachable_and_idempotent():
    script = ROOT / "scripts" / "sync_ios_version.sh"
    assert script.is_file() and script.stat().st_mode & 0o111
    before = PBXPROJ.read_bytes()
    subprocess.run(["bash", str(script)], cwd=ROOT, check=True, capture_output=True)
    assert PBXPROJ.read_bytes() == before, "تشغيلُه مرّتين يجب ألّا يغيّر شيئاً"
