"""رقمُ النسخة واحدٌ — في المصدر وفي **الحزمة المشحونة**.

الشاشة كانت تقول `0.6.2` وهي تقرأ `package.json`، والحزمة تقول `0.4.0`.
ولم يكن ذلك خطأً في رقمٍ مكتوب: `mobile/ios/` **مولَّدٌ وغير متتبَّع** —
ينشئه `expo prebuild` من `app.config.ts`. فالمشروع الأصليّ المولَّد أيام
0.4.0 بقي على حاله بينما بلغ المصدر 0.6.2، فشُحنت حزمةٌ **لا يدّعي رقمَها
أيُّ ملفِ مصدر**. وفحصُ المصادر وحده كان يمرّ، لأنّ المصادر متّسقةٌ فيما
بينها؛ المتخلّف هو المولَّد.

ولذلك يفصل هذا الملف ثلاثة أسئلة:

1. أيشتقّ `app.config.ts` الرقم من `package.json`؟ — يُفحص في كل بيئة،
   فهو المتتبَّع وهو الضمانة التي تنجو من إعادة التوليد.
2. أيتّفق المولَّد مع المصدر؟ — حيث يوجد المولَّد فقط. وغيابه على الخادم
   ليس عطلاً؛ ادّعاءُ فحصِه وهو غائب هو العطل.
3. أتحمل الحزمة الناتجة الرقم نفسه؟ — وهو السؤال الذي كان مفقوداً.
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
APP_CONFIG = ROOT / "mobile" / "app.config.ts"
IOS = ROOT / "mobile" / "ios"
PBXPROJ = IOS / "MaatherTrader.xcodeproj" / "project.pbxproj"
INFO = IOS / "MaatherTrader" / "Info.plist"
SYNC = ROOT / "scripts" / "sync_ios_version.sh"


def declared_version() -> str:
    return json.loads(PACKAGE.read_text(encoding="utf-8"))["version"]


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


def _needs_native() -> None:
    if not PBXPROJ.is_file() or not INFO.is_file():
        if os.environ.get("MATHRAH_REQUIRE_BUILT_APP") == "1":
            pytest.fail("بوابةُ الإصدار تطلب مشروعاً أصلياً ولا مشروع — نفّذ prebuild")
        pytest.skip("لا مشروع أصليّ هنا (mobile/ios مولَّدٌ وغير متتبَّع)")


# ١ — الضمانة المتتبَّعة، تُفحص في كل بيئة


def test_the_config_derives_the_version_from_the_package():
    source = APP_CONFIG.read_text(encoding="utf-8")
    assert "require('./package.json').version" in source, (
        "app.config.ts لا يشتقّ الرقم من package.json — فالتوليد التالي "
        "قد يحمل رقماً آخر"
    )
    assert "version: appVersion" in source
    assert "buildNumber," in source


def test_the_sync_script_is_reachable():
    assert SYNC.is_file() and SYNC.stat().st_mode & 0o111


def test_the_sync_script_is_silent_without_a_native_project(tmp_path):
    result = subprocess.run(["bash", str(SYNC)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ٢ — المولَّد، حيث يوجد


def test_the_generated_project_agrees_with_the_source():
    _needs_native()
    found = set(re.findall(r"MARKETING_VERSION = ([^;]+);", PBXPROJ.read_text(encoding="utf-8")))
    assert found == {declared_version()}, (
        f"المولَّد يقول {found} والمصدر يقول {declared_version()} — "
        "شغّل scripts/sync_ios_version.sh أو أعد التوليد"
    )


def test_the_plist_points_instead_of_repeating():
    _needs_native()
    info = _plist(INFO)
    assert info["CFBundleShortVersionString"] == "$(MARKETING_VERSION)", (
        "Info.plist يحمل رقماً حرفياً — وهو ما يُنتج رقمين متناقضين"
    )
    assert info["CFBundleVersion"] == "$(CURRENT_PROJECT_VERSION)"


def test_running_the_sync_twice_changes_nothing():
    _needs_native()
    before = PBXPROJ.read_bytes()
    subprocess.run(["bash", str(SYNC)], cwd=ROOT, check=True, capture_output=True)
    assert PBXPROJ.read_bytes() == before


# ٣ — الحزمة المشحونة، وهو السؤال الذي كان مفقوداً


def test_the_built_bundle_carries_the_declared_version():
    apps = [app for app in _built_apps() if (app / "Info.plist").is_file()]
    if not apps:
        if os.environ.get("MATHRAH_REQUIRE_BUILT_APP") == "1":
            pytest.fail("بوابةُ الإصدار تطلب حزمةً مبنيّة ولا حزمة — ابنِ ثم أعد الاختبار")
        pytest.skip("لا حزمة مبنيّة على هذا الجهاز")
    want = declared_version()
    for app in apps:
        info = _plist(app / "Info.plist")
        assert info.get("CFBundleShortVersionString") == want, (
            f"الحزمة {app} تقول {info.get('CFBundleShortVersionString')} "
            f"والمصدر يقول {want}"
        )
