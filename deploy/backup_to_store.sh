#!/usr/bin/env bash
#
# دفعُ المستودع إلى المخزن على القرص الخارجي — **جزءٌ من النشر لا خطوةٌ تُنسى.**
#
# ## لماذا سكربتٌ مستقلّ
#
# المخزن يعيش داخل وعاء APFS على قرصٍ خارجي، والوعاء **يُفصَل حين ينام
# الماك**. فأوّل دفعةٍ بعد نومٍ تفشل برسالة «تأكّدي أن المستودع موجود» —
# وهي رسالةٌ تُقرَأ على أنها خطأ إعداد، لا على أنها «القرص غير مركَّب».
#
# ووقع ذلك فعلاً: نشرةٌ ناجحة تلتها دفعةٌ فاشلة، ولولا أنّ المخرَج قُرئ
# لبقي المخزن متأخّراً بكوميتٍ كامل ونحن نظنّه محدَّثاً. ونسخةٌ احتياطية
# يُظنّ أنها تعمل أسوأ من غيابها: الغياب معلوم.
#
# فيُركَّب الوعاء إن لزم، ويُدفَع، ويُتحقَّق من تطابق المخزن بعد الدفع —
# ولا يُقال «تمّ» إلا بعد المطابقة.

# الوعاء الخارجي أولاً — لا كتابةَ على مستودعٍ غائب.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/mathrah_mount.sh" 2>/dev/null \
  && mathrah_require || { echo "⛔ المستودع العامل غير متاح."; exit 90; }

set -u

REPO="${1:-$HOME/Developer/Maather-Autonomous-Trader}"
SPARSE="${2:-/Volumes/TOSHIBA/MATHRAH.sparsebundle}"
STORE=/Volumes/MATHRAH/mathrah.git

if [ ! -d "$STORE" ]; then
  if [ ! -e "$SPARSE" ]; then
    echo "⛔ القرص الخارجي غير موصول — لم يُحدَّث المخزن."
    echo "   المستودع سليم، لكنّ النسخة الاحتياطية متأخّرة. صِلي القرص وأعيدي."
    exit 2
  fi
  hdiutil attach "$SPARSE" -nobrowse >/dev/null 2>&1
  sleep 3
fi
[ -d "$STORE" ] || { echo "⛔ تعذّر تركيب المخزن."; exit 2; }

WANT=$(git -C "$REPO" rev-parse HEAD)
git -C "$REPO" push disk main >/dev/null 2>&1 || { echo "⛔ فشل الدفع."; exit 1; }

HAVE=$(git -C "$STORE" rev-parse refs/heads/main 2>/dev/null)
if [ "$HAVE" != "$WANT" ]; then
  echo "⛔ المخزن عند ${HAVE:0:7} والمطلوب ${WANT:0:7} — لا يُقال «تمّ»."
  exit 1
fi
echo "✅ المخزن محدَّث عند ${WANT:0:7}"
