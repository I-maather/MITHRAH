#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
#  سحبُ النسخ من الخادم إلى الوعاء الخارجي.
#
#  نسخةٌ على القرص نفسه ليست نسخةً احتياطية من فقد المضيف — هي حمايةٌ من
#  الخطأ لا من الكارثة. فتُسحَب إلى قرصٍ آخر تحت يد المالكة.
#
#  **والأسرار لا تُسحَب.** `secrets-*.tgz` يبقى على الخادم بصلاحية 600:
#  نقلُه يضاعف مواضع تسرّبه، ولا يلزم لاسترجاع البيانات — يلزم لإعادة
#  بناء الخادم، وذلك قرارٌ يُتّخذ وقتَه لا يُحضَّر له بنسخٍ متناثر.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/mathrah_mount.sh"
mathrah_require || exit 90

KEY="${MATHRAH_SSH_KEY:-$HOME/Desktop/Trading/.ssh-maather/maather_hetzner}"
HOST="${MATHRAH_HOST:-root@167.233.234.236}"
DEST="${MATHRAH_BACKUP_STORE:-/Volumes/MATHRAH/backups}"
mkdir -p "$DEST"

echo "الوجهة: $DEST"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
  "$HOST:/opt/mathrah/data/backups/daily/maather-*.db"        "$DEST/" 2>/dev/null || true
scp -i "$KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
  "$HOST:/opt/mathrah/data/backups/daily/maather-*.db.sha256" "$DEST/" 2>/dev/null || true
LATEST=$(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes "$HOST" \
  'ls -1t /opt/mathrah/data/backups/hourly/maather-*.db | head -1' < /dev/null | tr -d '\r')
if [ -n "$LATEST" ]; then
  scp -i "$KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes "$HOST:$LATEST"        "$DEST/" 
  scp -i "$KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes "$HOST:$LATEST.sha256" "$DEST/" 2>/dev/null || true
fi

echo "── التحقّق من البصمات بعد النقل ──"
ok=0; bad=0
for f in "$DEST"/maather-*.db; do
  [ -f "$f" ] || continue
  [ -f "$f.sha256" ] || { echo "  ⚠️ بلا بصمة: $(basename "$f")"; continue; }
  want="$(cat "$f.sha256")"
  have="$(shasum -a 256 "$f" | awk '{print $1}')"
  if [ "$want" = "$have" ]; then ok=$((ok+1)); else bad=$((bad+1)); echo "  ⛔ بصمة لا تطابق: $(basename "$f")"; fi
done
echo "  مطابقة: $ok · فاسدة: $bad"
[ "$bad" -eq 0 ] || exit 4
du -sh "$DEST" | sed 's/^/  الحجم: /'
