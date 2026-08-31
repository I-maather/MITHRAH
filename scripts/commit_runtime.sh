#!/usr/bin/env bash
#
# إيداع النبض + الواجهة + الخطوط — يُشغَّل **على الماك** من داخل مجلد المشروع:
#
#     bash scripts/commit_runtime.sh
#
# لا يُودِع شيئاً لم يُذكر هنا بالاسم. والملفّات المكرّرة من Finder
# («… 2.py» و«… 3.ts» وأمثالها) وملفّات zip مستبعدة صراحةً.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
step "١ · إزالة أقفال git العالقة"
# ---------------------------------------------------------------------------
rm -f .git/index.lock .git/HEAD.lock 2>/dev/null
green "تمّ"

# ---------------------------------------------------------------------------
step "٢ · حماية من الملفّات المكرّرة"
# ---------------------------------------------------------------------------
# نُسخ Finder تنتهي بـ « 2» أو « 3» قبل الامتداد. لا تدخل المستودع أبداً.
if ! grep -q 'نسخ Finder' .gitignore 2>/dev/null; then
  {
    echo ''
    echo '# نسخ Finder المكرّرة — تُستورَد بالخطأ فتُنتج سلوكاً غامضاً'
    echo '* [0-9].py'
    echo '* [0-9].ts'
    echo '* [0-9].tsx'
    echo '* [0-9].md'
    echo 'mobile/assets/fonts/*.zip'
  } >> .gitignore
  green "أُضيفت قواعد الاستبعاد إلى .gitignore"
else
  green "قواعد الاستبعاد موجودة"
fi

# ---------------------------------------------------------------------------
step "٣ · تجهيز الملفّات — بالاسم، لا بالجملة"
# ---------------------------------------------------------------------------
BACKEND=(
  backend/app/main.py
  backend/app/runtime/__init__.py
  backend/app/runtime/heartbeat.py
  backend/tests/test_runtime_heartbeat.py
)
MOBILE=(
  mobile/app.config.ts
  mobile/app/_layout.tsx
  "mobile/app/(app)/_layout.tsx"
  "mobile/app/(app)/home.tsx"
  mobile/src/components/AnimatedNumber.tsx
  mobile/src/components/RiskMeter.tsx
  mobile/src/components/TabBar.tsx
  mobile/src/components/Text.tsx
  mobile/src/components/index.ts
  mobile/src/theme/tokens.ts
  mobile/jest.setup.ts
  mobile/package.json
  mobile/package-lock.json
  "mobile/__tests__/home-dashboard.test.tsx"
  mobile/assets/fonts/IBMPlexSansArabic-Regular.ttf
  mobile/assets/fonts/IBMPlexSansArabic-Medium.ttf
  mobile/assets/fonts/IBMPlexSansArabic-SemiBold.ttf
  mobile/assets/fonts/IBMPlexSansArabic-Bold.ttf
  mobile/assets/fonts/Newsreader.ttf
  mobile/assets/fonts/ReemKufi.ttf
)
DOCS=( .gitignore docs/ux-proposal-2026-08-31.html )

MISSING=0
for f in "${BACKEND[@]}" "${MOBILE[@]}" "${DOCS[@]}"; do
  if [ -e "$f" ]; then
    git add -- "$f" || { red "⛔ تعذّرت إضافة: $f"; MISSING=1; }
  else
    red "⛔ غير موجود: $f"; MISSING=1
  fi
done
[ "$MISSING" -eq 0 ] || { red "⛔ توقّف قبل الإيداع. لم يُودَع شيء."; exit 1; }
green "أُضيف $(( ${#BACKEND[@]} + ${#MOBILE[@]} + ${#DOCS[@]} )) ملفاً"

# ---------------------------------------------------------------------------
step "٤ · التأكّد أن لا مكرّر تسلّل"
# ---------------------------------------------------------------------------
SNEAK="$(git diff --cached --name-only | grep -E ' [0-9]\.(py|ts|tsx|md)$' || true)"
if [ -n "$SNEAK" ]; then
  red "⛔ ملفّات مكرّرة في منطقة الإيداع:"; echo "$SNEAK"
  git reset >/dev/null; red "أُلغي التجهيز كلّه. لم يُودَع شيء."; exit 1
fi
green "نظيف"

# ---------------------------------------------------------------------------
step "٥ · الإيداع"
# ---------------------------------------------------------------------------
BEFORE="$(git rev-list --count HEAD 2>/dev/null || echo 0)"
git commit -q -m "نبض التشغيل ٢٤/٧ + شريط التبويب + الأرقام المتحرّكة + الخطوط

الخادم لم يكن يستدعي pipeline.run() في أي موضع. Heartbeat يشغّله كل ٦٠
ثانية داخل دورة asyncio تبدأ مع التطبيق، بثلاثة حرّاس كلٌّ منها يكتب سببه:
موقوف محلياً · الوسيط غير مبلوغ · قاطع مُفعَّل. والوسيط غير المبلوغ لا
يُمرَّر إلى الخط أبداً كي لا يُشعل القاطع بخطأ شبكة.

الواجهة: الحكم أولاً، والمتبقّي من المخاطرة هو الرقم البطل، وشريط تبويب
بأربع كلمات، وأرقام تعدّ صعوداً بالأخضر والأحمر مع الإشارة دائماً.
الخطوط: بلكس للواجهة، ونيوزريدر للأرقام، وريم كوفي محمّل للّوجو وحده."
AFTER="$(git rev-list --count HEAD 2>/dev/null || echo 0)"

if [ "$AFTER" -le "$BEFORE" ]; then
  red "⛔ الإيداع لم يحدث. عدد الإيداعات لم يتغيّر ($BEFORE)."
  exit 1
fi
green "✅ أُودع. الإيداعات: $BEFORE ← $AFTER"

# ---------------------------------------------------------------------------
step "٦ · هل الشجرة نظيفة الآن؟ (شرط النشر)"
# ---------------------------------------------------------------------------
DIRTY="$(git status --porcelain --untracked-files=no)"
if [ -n "$DIRTY" ]; then
  red "⚠️  ما زال هناك معدَّل غير مودَع — النشر سيرفض:"
  echo "$DIRTY"
  exit 1
fi
green "✅ الشجرة نظيفة. النشر ممكن الآن:"
echo ""
echo "    bash scripts/deploy_to_server.sh 167.233.234.236"
echo ""
