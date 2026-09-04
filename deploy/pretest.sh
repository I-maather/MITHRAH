#!/usr/bin/env bash
#
# بوابةُ ما قبل النشر: تبني نسخةً حقيقيةً من الكود المقترح — بمستودعِ git
# كامل — ثمّ تشغّل الاختبارات عليها.
#
# ## لماذا `clone` لا `git archive`
#
# ‏`git archive pre/main | tar x` ينتج شجرةَ ملفاتٍ بلا `.git`. وأربعةٌ من
# اختباراتنا الأمنية لا تسأل الكود، بل تسأل git نفسه:
#
#   • هل `data/private/**` متجاهَلةٌ فعلاً؟            (`check-ignore`)
#   • هل من ملفٍ متتبَّعٍ تحت `data/`؟                  (`ls-files`)
#   • هل `secrets/` و`.env` مستثناة؟                    (`check-ignore`)
#   • هل تسرّبت قيمةُ حسابٍ إلى ملفٍ متتبَّع؟           (`ls-files`)
#
# وسؤالُ git في مجلدٍ ليس مستودعاً يعيد فشلاً دائماً. فكانت البوابة تعدّ أربعةَ
# إخفاقاتٍ وتسمّيها «الأساس البيئي» وتتغاضى عنها — أي أنّ هذه الحراسات الأربع
# كانت **معطّلةً في كلّ نشرة**، وأربعةٌ من ميزانية الفشل مصروفةٌ سلفاً تُخفي
# فشلاً حقيقياً لو وقع تحتها.
#
# النسخة الحقيقية تُعيد الأساس إلى صفر: أيُّ فشلٍ بعد اليوم فشلٌ يمنع النشر.
#
# الاستعمال:  bash pretest.sh [<مرجع>] [<مجلد العمل>]
set -u

REF="${1:-refs/remotes/pre/main}"
WORK="${2:-/tmp/mathrah-pre}"
SRC=/opt/mathrah

rm -rf "$WORK" || exit 90
# فرعُ البداية ليس `main`: git يرفض الجلب إلى فرعٍ مُستخرَجٍ في شجرة عمل،
# و`git init -b main` يجعل HEAD يشير إلى `main` قبل وجودها.
git init -q -b _bootstrap "$WORK"                              || exit 91
git -C "$WORK" fetch -q --no-tags "$SRC" "+${REF}:refs/heads/main" || exit 92
git -C "$WORK" checkout -q main                                || exit 93

# إثباتٌ أنّ المستودع حقيقيٌّ قبل أن نثق بنتيجة الاختبارات: لو انهار الاستنساخ
# صامتاً لعادت الأربعةُ من حيث أتت، ولظننّاها «بيئية» مرّةً أخرى.
git -C "$WORK" rev-parse --git-dir >/dev/null 2>&1             || exit 94
git -C "$WORK" check-ignore -q "data/private/x" \
  || { echo "⛔ الاستنساخ بلا .gitignore فعّال — لا تُقرأ النتيجة"; exit 95; }

cd "$WORK/backend" || exit 96
exec "$SRC/.venv/bin/python" -m pytest -q --no-header -p no:cacheprovider --tb=line
