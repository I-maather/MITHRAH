#!/usr/bin/env bash
#
# إيداع الهوية ومسار كابيتال — يُشغَّل **على الماك**:
#
#     bash scripts/commit_identity.sh
#
# يُودِع بالاسم لا بالجملة. و`_identity_bundle/` مستبعَد (في .gitignore)،
# لأنه حزمةٌ مفكوكة مصدرها المحادثة لا المستودع.
#
# ولا يدفع إلى أي مستودع بعيد.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

step "١ · إزالة أقفال git العالقة"
rm -f .git/index.lock .git/HEAD.lock 2>/dev/null
green "تمّ"

step "٢ · التجهيز — بالاسم"
PATHS=(
  # الخلفية: مسار كابيتال في مصنع الوسطاء + مسار الأسرار
  backend/app/config.py
  backend/app/brokers/factory.py
  backend/app/api/state.py
  backend/tests/test_broker_factory_capital.py

  # الهوية: الخطوط والأصول والأيقونات
  mobile/assets/fonts/Amiri-Regular.ttf
  mobile/assets/fonts/Amiri-Bold.ttf
  mobile/assets/brand
  mobile/assets/icon.png
  mobile/assets/adaptive-icon.png
  mobile/assets/splash.png
  mobile/assets/splash-icon.png
  mobile/assets/favicon.png
  brand

  # المكوّنات ونسق التصميم
  mobile/src/components/Hadd.tsx
  mobile/src/components/EmptyState.tsx
  mobile/src/components/Wordmark.tsx
  mobile/src/components/index.ts
  mobile/src/theme/tokens.ts
  mobile/app/_layout.tsx
  mobile/app.config.ts

  # الأدوات
  scripts/build_wordmark.py
  scripts/land_identity.py
  scripts/run_history_sweep.py
  scripts/run_backtest.py
  scripts/run_shadow.py
  scripts/configure_server_secrets.sh
  scripts/commit_runtime.sh
  scripts/wake_and_run.sh

  docs/ux-live-flow-2026-08-31.html
  .gitignore
)

MISSING=0
for p in "${PATHS[@]}"; do
  if [ -e "$p" ]; then
    git add -- "$p" || { red "⛔ تعذّرت إضافة: $p"; MISSING=1; }
  else
    red "⛔ غير موجود: $p"; MISSING=1
  fi
done
[ "$MISSING" -eq 0 ] || { red "⛔ توقّف قبل الإيداع. لم يُودَع شيء."; exit 1; }
green "أُضيف ${#PATHS[@]} مساراً"

step "٣ · التأكّد أن الحزمة المفكوكة لم تدخل"
SNEAK="$(git diff --cached --name-only | grep -E '^_identity_bundle/' || true)"
if [ -n "$SNEAK" ]; then
  red "⛔ _identity_bundle تسلّل إلى الإيداع:"; echo "$SNEAK" | head
  git reset >/dev/null; red "أُلغي التجهيز. لم يُودَع شيء."; exit 1
fi
green "نظيف"

step "٤ · الإيداع"
BEFORE="$(git rev-list --count HEAD 2>/dev/null || echo 0)"
git commit -q -m "هوية مثراة على الجوال + مسار كابيتال في مصنع الوسطاء

## الهوية

الشعار «مثراة» بريم كوفي ٦٠٠ محوَّلاً إلى مسارات، ونقاط الثاء الثلاث
مسارات مستقلّة تحمل الجمري وحدها — وهي الشيء الوحيد الملوَّن في العلامة.
والأيقونة هي الكلمة نفسها على أسود.

أميري صار خط العناوين (\`display\`)، وريم كوفي انتقل إلى مفتاح \`logo\`
مستقلّ فلا يدخل نصّ الواجهة أبداً.

عطلان أُصلحا في الطريق: \`app.config.ts\` كان يشير إلى \`splash.png\`
بينما الأصل الجديد باسم آخر، فكان البناء سيعرض القديمة؛ ولون خلفية
شاشة البداية كان \`#3A0CA3\` بنفسجياً من قالب قديم في أربعة مواضع.

## المكوّنات

\`Hadd\` — العنصر التوقيعي: قيمة داخل مدى بعتبات، بعلامة جمرية **تظهر
عند صفر بالمئة أيضاً**؛ مؤشّرٌ يختفي عند الصفر يجعل شاشةً سليمة تبدو
معطوبة. \`EmptyState\` — الفراغ حالة لا خطأ: ماذا · لماذا · ما التالي.

## مسار كابيتال

\`build_broker\` لم يكن يعرف كابيتال إطلاقاً — ثلاثة أوضاع فقط: وهمي
وIBKR تجريبي وحقيقي. ولهذا كان الخادم على MOCK مهما ضُبطت الإعدادات.
أُضيف \`CAPITAL_DEMO\` و\`CAPITAL_LIVE\`، وكلاهما يُبنى بقفل تنفيذ مغلق
يتقاسمه الناقل والمحوّل — كائناً واحداً لا اثنين.

وقارئ الأسرار كان يقرأ \`secrets/capital.env\` بينما تُكتب في
\`secrets/runtime.env\`؛ مفتاحٌ موجود وغير مقروء أسوأ من مفتاح غائب.

١٥ اختباراً تُثبت أنه يقرأ ولا ينفّذ. ٢١٣/٢١٣ جوال، و١٢٣٠ ناجحة في
الخلفية بلا انحدار."
AFTER="$(git rev-list --count HEAD 2>/dev/null || echo 0)"

if [ "$AFTER" -le "$BEFORE" ]; then
  red "⛔ الإيداع لم يحدث. عدد الإيداعات لم يتغيّر ($BEFORE)."
  exit 1
fi
green "✅ أُودع. الإيداعات: $BEFORE ← $AFTER"

step "٥ · الشجرة الآن"
DIRTY="$(git status --porcelain --untracked-files=no)"
if [ -n "$DIRTY" ]; then
  red "⚠️  بقي معدَّل غير مودَع:"; echo "$DIRTY"
else
  green "✅ نظيفة — prebuild لن يحذّر"
fi
echo ""
echo "  التالي:"
echo "      cd mobile && npx expo prebuild --clean"
echo ""
