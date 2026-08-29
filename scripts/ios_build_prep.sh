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

# العقبة الأشهر: Xcode مثبَّت لكن `xcode-select` يشير إلى CommandLineTools،
# فيفشل البناء برسالة غامضة عن SDK مفقود. يُفحَص المسار لا وجود الأمر وحده.
DEV_DIR="$(xcode-select -p 2>/dev/null || true)"
if ! command -v xcodebuild >/dev/null 2>&1; then
  bad "Xcode غير مثبَّت — نزّليه من App Store"
elif [ -z "$DEV_DIR" ] || case "$DEV_DIR" in *CommandLineTools*) true ;; *) false ;; esac; then
  bad "xcode-select يشير إلى «$DEV_DIR» بدل Xcode. صحّحيه بـ:"
  printf '     sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer\n'
elif ! xcodebuild -version >/dev/null 2>&1; then
  bad "Xcode مثبَّت لكنه لم يُشغَّل بعد. افتحيه مرة واقبلي الشروط، أو شغّلي:"
  printf '     sudo xcodebuild -license accept\n'
else
  ok "Xcode: $(xcodebuild -version 2>/dev/null | head -1)"
  ok "المسار: $DEV_DIR"
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

# **فشل مغلق.** `set -e` وحده لا يكفي: الأمر داخل `cmd && ok "..."` يُعامَل
# جزءاً من قائمة شرطية، فلا يُسقط الصدفة عند فشله — وهذا ما جعل النسخة
# السابقة تصل إلى `expo prebuild` بعد فشل اختبار. الآن كل فحص يُقيَّم صراحةً.
gate() {
  local label="$1"; shift
  if "$@"; then
    ok "$label"
  else
    printf '  ❌ %s — فشل. توقّف قبل توليد مشروع iOS.\n' "$label" >&2
    exit 1
  fi
}

gate "تثبيت الاعتماديات" npm install

gate "TypeScript" npx tsc --noEmit
gate "ESLint" npx eslint . --ext .ts,.tsx --max-warnings 0
gate "اختبارات الجوال" npx jest --silent --ci

# --- بوابة أمنية: لا ثغرة critical/high **قابلة للوصول في الإنتاج** --------
# الحكم على القابلية للوصول لا على العدد: أغلب ما يبلّغ عنه npm audit في مشروع
# Expo هو أدوات بناء لا تدخل حزمة التطبيق. `--omit=dev` وحده لا يفرّق، لأن
# `expo` و`react-native` تبعيات إنتاج تجرّ معها سلاسل بناء كاملة.
say ''
say 'الفحص الأمني:'
AUDIT_JSON="$(npm audit --json 2>/dev/null || true)"
if [ -z "$AUDIT_JSON" ]; then
  warn "تعذّر تشغيل npm audit — يُتخطّى بلا ادعاء سلامة"
else
  printf '%s' "$AUDIT_JSON" > /tmp/maather-audit.json
  if python3 "$REPO_ROOT/scripts/audit_gate.py" /tmp/maather-audit.json; then
    ok "لا ثغرة critical/high خارج قائمة أدوات البناء الموثَّقة"
  else
    printf '  ❌ الفحص الأمني — ثغرة غير موثَّقة. راجعي docs/MOBILE_DEPENDENCY_AUDIT.md\n' >&2
    exit 1
  fi
fi

# --- شجرة العمل: لا يُولَّد مشروع فوق تغييرات غير ملتزَمة ------------------
say ''
say 'شجرة العمل:'
DIRTY="$(git -C "$REPO_ROOT" status --porcelain -- mobile 2>/dev/null || true)"
if [ -n "$DIRTY" ]; then
  printf '  ❌ توجد تغييرات غير ملتزَمة تحت mobile/:\n' >&2
  printf '%s\n' "$DIRTY" | sed 's/^/       /' >&2
  printf '  التزمي بها أولاً. `expo prebuild --clean` يحذف ويعيد بناء\n' >&2
  printf '  mobile/ios/ ولا يمكن التراجع عنه بلا التزام سابق.\n' >&2
  exit 1
fi
ok "شجرة mobile/ نظيفة"

say ''
say 'توليد مشروع iOS الأصلي:'
gate "expo prebuild" npx expo prebuild --platform ios --clean

if [ -f "$MOBILE/PrivacyInfo.xcprivacy.template" ] && [ -d "$MOBILE/ios" ]; then
  target_dir="$(find "$MOBILE/ios" -maxdepth 1 -type d ! -name ios ! -name Pods | head -1)"
  if [ -n "$target_dir" ]; then
    cp "$MOBILE/PrivacyInfo.xcprivacy.template" "$target_dir/PrivacyInfo.xcprivacy"
    ok "نُسخ بيان الخصوصية إلى $(basename "$target_dir")"
  fi
fi

WORKSPACE="$(ls -d "$MOBILE"/ios/*.xcworkspace 2>/dev/null | head -1)"

say ''
say '══════════════════════════════════════════════'
if [ -n "$WORKSPACE" ]; then
  ok "المشروع الأصلي جاهز"
  say ''
  say '  افتحيه بهذا الأمر بالضبط:'
  printf '\n     open "%s"\n\n' "$WORKSPACE"
else
  bad "لم يُعثر على ملف .xcworkspace بعد prebuild"
fi
say 'ثم داخل Xcode:'
say ''
say '  1. من الشريط الجانبي اختاري المشروع (الأيقونة الزرقاء بالأعلى)'
say '  2. تبويب Signing & Capabilities'
say '  3. فعّلي Automatically manage signing'
say '  4. Team ⇐ اختاري اسمكِ (Personal Team)'
say '     إن شكا من تكرار Bundle ID، أضيفي لاحقة: com.maather.autonomoustrader.<اسمك>'
say '  5. وصّلي الآيفون بالكابل، اختاريه من قائمة الأجهزة بالأعلى'
say '  6. اضغطي ▶ Run'
say ''
say '  وأول مرة على الآيفون:'
say '    الإعدادات ← عام ← VPN وإدارة الجهاز ← وثّقي المطوّر'
say ''
say 'الرفع إلى TestFlight يحتاج عضوية Apple Developer المدفوعة،'
say 'وتسجيل دخول بهويتكِ، وموافقة على اتفاقيات قانونية.'
say '**لا يُفوَّض أيٌّ من ذلك.** التفاصيل: docs/TESTFLIGHT_RELEASE.md'
say '══════════════════════════════════════════════'
