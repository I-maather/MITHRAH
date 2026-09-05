#!/bin/bash
# نسخةُ iOS تُشتقّ ولا تُكتَب مرّتين.
#
# `package.json` هو المصدر (D-22). هذا السكربت يحمله إلى إعدادات البناء،
# و`Info.plist` يشير إلى الإعدادات بدل أن يحمل نسخةً ثانية. فمن غيّر
# `package.json` وحده لا يترك خلفه حزمةً تقول رقماً آخر.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="$(python3 -c "import json;print(json.load(open('$ROOT/mobile/package.json'))['version'])")"
BNO="${EXPO_PUBLIC_BUILD_NUMBER:-2}"
PBX="$ROOT/mobile/ios/MaatherTrader.xcodeproj/project.pbxproj"
PL="$ROOT/mobile/ios/MaatherTrader/Info.plist"
python3 - "$PBX" "$VER" "$BNO" <<'PY'
import re, sys, io
p, ver, bno = sys.argv[1:4]
s = io.open(p, encoding='utf-8').read()
s = re.sub(r'MARKETING_VERSION = [^;]+;', f'MARKETING_VERSION = {ver};', s)
s = re.sub(r'CURRENT_PROJECT_VERSION = [^;]+;', f'CURRENT_PROJECT_VERSION = {bno};', s)
io.open(p, 'w', encoding='utf-8').write(s)
PY
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString \$(MARKETING_VERSION)" "$PL" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion \$(CURRENT_PROJECT_VERSION)" "$PL" >/dev/null 2>&1 || true
echo "نسخة iOS: $VER ($BNO)"
