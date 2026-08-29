#!/usr/bin/env bash
#
# تحضير بناء iOS محلياً — كل ما يمكن أتمتته قبل Xcode.
#
#   ./scripts/ios_build_prep.sh            # فحص + تثبيت + prebuild
#   ./scripts/ios_build_prep.sh --check    # فحص فقط، بلا تعديل
#
# ما **لا** يفعله — عمداً:
#   * لا يسجّل الدخول إلى حساب Apple
#   * لا يُنشئ Bundle ID ولا شهادة ولا ملف تزويد
#   * لا يرفع بناءً إلى TestFlight
#   * لا يلمس App Store Connect
#
# تلك الخطوات تحتاج **هويتكِ** و**موافقتكِ على اتفاقيات قانونية**، ولا
# تُفوَّض. السكربت يوصلكِ إلى باب Xcode ويتوقف هناك.
#
# التوافق: bash 3.2 (إصدار macOS الافتراضي).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE="$REPO_ROOT/mobile"
CHECK_ONLY=0
if [ $# -gt 0 ] && [ "$1" = "--check" ]; then
  CHECK_ONLY=1
fi

fail=0
say()  { printf '%s\n' "$1"; }
ok()   { printf '  ✅ %s\n' "$1"; }
bad()  { printf '  ❌ %s\n' "$1"; fail=1; }
warn() { printf '  ⚠️  %s\n' "$1"; }

say ''
say 'تحضير بناء iOS'
say '══════════════'
say ''
say 'المتطلبات:'

if [ "$(uname -s)" = "Darwin" ]; then
  ok "نظام macOS"
else
  bad "بناء iOS يتطلب macOS. النظام الحالي: $(uname -s)"
fi

if command -v xcodebuild >/dev/null 2>&1; then
  ok "Xcode: $(xcodebuild -version 2>/dev/null | head -1)"
else
  bad "Xcode غير مثبَّت — نزّليه من App Store ثم شغّلي: sudo xcode-select --switch /Applications/Xcode.app"
fi

if command -v node >/dev/null 2>&1; then
  ok "Node: $(node -v)"
else
  bad "Node غير مثبَّت"
fi

if command -v pod >/dev/null 2>&1; then
  ok "CocoaPods: $(pod --version 2>/dev/null)"
else
  warn "CocoaPods غير مثبَّت — سيثبّته expo prebuild، أو: sudo gem install cocoapods"
fi

say ''
say 'الأصول:'
for asset in icon.png splash.png adaptive-icon.png; do
  if [ -f "$MOBILE/assets/$asset" ]; then
    ok "assets/$asset"
  else
    bad "assets/$asset مفقود — شغّلي: python3 mobile/scripts/generate-app-icon.py"
  fi
done

# أيقونة المتجر يجب أن تكون بلا قناة ألفا — App Store Connect يرفضها بألفا.
if command -v python3 >/dev/null 2>&1 && [ -f "$MOBILE/assets/icon.png" ]; then
  if python3 - "$MOBILE/assets/icon.png" <<'PY' 2>/dev/null
import sys
try:
    from PIL import Image
except ImportError:
    sys.exit(0)          # لا Pillow ⇒ يُتخطّى الفحص بلا إسقاط
sys.exit(0 if Image.open(sys.argv[1]).mode == "RGB" else 1)
PY
  then
    ok "أيقونة المتجر بلا قناة ألفا"
  else
    bad "أيقونة المتجر تحمل ألفا — أعيدي توليدها"
  fi
fi

say ''
say 'الإعداد:'
if grep -q "com.maather.autonomoustrader" "$MOBILE/app.config.ts" 2>/dev/null; then
  warn "Bundle ID ما زال المبدئي: com.maather.autonomoustrader"
  warn "  إن كان مسجَّلاً لديكِ في Apple، اتركيه. وإلا صدّري EXPO_PUBLIC_IOS_BUNDLE_ID"
fi
if grep -q "'aps-environment'" "$MOBILE/app.config.ts" 2>/dev/null; then
  ok "استحقاق الإشعارات مُعلَن"
else
  bad "استحقاق aps-environment غير مُعلَن"
fi

say ''
if [ "$fail" -ne 0 ]; then
  say '⛔ المتطلبات ناقصة. عالجي ما سبق ثم أعيدي التشغيل.'
  exit 1
fi
say '✅ كل المتطلبات متوفرة.'

if [ "$CHECK_ONLY" -eq 1 ]; then
  say ''
  say 'فحص فقط — لم يُعدَّل شيء.'
  exit 0
fi

say ''
say 'التثبيت والفحوص:'
cd "$MOBILE"
npm install
npx tsc --noEmit && ok "TypeScript نظيف"
npx eslint . --ext .ts,.tsx --max-warnings 0 && ok "ESLint نظيف"
npx jest --silent && ok "اختبارات الجوال ناجحة"

say ''
say 'توليد مشروع iOS الأصلي:'
npx expo prebuild --platform ios --clean

if [ -f "$MOBILE/PrivacyInfo.xcprivacy.template" ] && [ -d "$MOBILE/ios" ]; then
  target_dir="$(find "$MOBILE/ios" -maxdepth 1 -type d ! -name ios ! -name Pods | head -1)"
  if [ -n "$target_dir" ]; then
    cp "$MOBILE/PrivacyInfo.xcprivacy.template" "$target_dir/PrivacyInfo.xcprivacy"
    ok "نُسخ بيان الخصوصية إلى $(basename "$target_dir")"
  fi
fi

say ''
say '══════════════════════════════════════════════'
say '✅ المشروع الأصلي جاهز في mobile/ios/'
say ''
say 'الخطوة التالية — **بيدكِ أنتِ**:'
say ''
say '  1. افتحي المشروع:'
say '       open mobile/ios/*.xcworkspace'
say '  2. في Xcode: Signing & Capabilities ⇐ اختاري فريقكِ'
say '  3. أضيفي Push Notifications إن لم تظهر تلقائياً'
say '  4. وصّلي الآيفون واضغطي Run لبناء تطوير'
say ''
say 'الرفع إلى TestFlight يحتاج عضوية Apple Developer المدفوعة،'
say 'وتسجيل دخول بهويتكِ، وموافقة على اتفاقيات قانونية.'
say '**لا يُفوَّض أيٌّ من ذلك.** التفاصيل: docs/TESTFLIGHT_RELEASE.md'
say '══════════════════════════════════════════════'
