#!/bin/bash
# نسخةُ iOS تُشتقّ ولا تُكتَب مرّتين.
#
# `mobile/ios/` **مولَّد وغير متتبَّع** (توليدٌ أصليّ متّصل: `expo prebuild`
# يُنشئه من `app.config.ts`). فالمصدر الحقيقي هو `package.json` — يقرؤه
# `app.config.ts` — والمولَّد قد يتخلّف عنه إن لم يُعَد توليده. وهذا ما
# وقع: مشروعٌ أصليٌّ مولَّدٌ أيام 0.4.0 بقي على حاله بينما بلغ المصدر 0.6.2،
# فشُحنت حزمةٌ لا يدّعي رقمَها أيُّ ملفِ مصدر.
#
# هذا السكربت يحمل الرقم إلى المولَّد إن وُجد، ويصمت إن لم يوجد — فالخادم
# لا مشروعَ أصليّ عليه، وغيابُه ليس عطلاً.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="$(python3 -c "import json;print(json.load(open('$ROOT/mobile/package.json'))['version'])")"
BNO="${EXPO_PUBLIC_BUILD_NUMBER:-2}"
PBX="$ROOT/mobile/ios/MaatherTrader.xcodeproj/project.pbxproj"
PL="$ROOT/mobile/ios/MaatherTrader/Info.plist"

if [ ! -d "$ROOT/mobile/ios" ]; then
  echo "لا مشروع أصليّ في mobile/ios — لا شيء يُزامَن (المصدر: $VER)"
  exit 0
fi
[ -f "$PBX" ] || { echo "⛔ mobile/ios موجود بلا project.pbxproj — مشروعٌ ناقص." >&2; exit 1; }
[ -f "$PL" ]  || { echo "⛔ mobile/ios موجود بلا Info.plist — مشروعٌ ناقص." >&2; exit 1; }

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
