#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
#  نسخةٌ احتياطية للخادم — **متّسقة، لا نسخُ ملفٍ حيّ**.
#
#  `cp` على قاعدة SQLite تعمل قد يلتقط صفحاتٍ نصفَ مكتوبة: ملفٌ بحجمٍ
#  صحيح وسلامةٍ فاسدة، لا يُكتشف إلا يوم الاسترجاع — وهو أسوأ يومٍ
#  للاكتشاف. فتُستعمل `sqlite3 .backup` التي تأخذ لقطةً متّسقة من قاعدةٍ
#  مفتوحة.
#
#  والأسرار تُنسخ **على الخادم وحده** بصلاحية 600. لا تُرفع مع القاعدة
#  ولا تُسحب إلى جهازٍ آخر إلا بقرارٍ صريح.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="${MATHRAH_ROOT:-/opt/mathrah}"
DATA="$ROOT/data"
DEST="${MATHRAH_BACKUP_DIR:-$DATA/backups}"
KEEP_HOURLY="${MATHRAH_KEEP_HOURLY:-24}"
KEEP_DAILY="${MATHRAH_KEEP_DAILY:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PY="$ROOT/.venv/bin/python"

mkdir -p "$DEST/hourly" "$DEST/daily"

DB="$DATA/maather.db"
OUT="$DEST/hourly/maather-$STAMP.db"

"$PY" - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
source = sqlite3.connect(src)
target = sqlite3.connect(dst)
with target:
    source.backup(target)
# **تُفحَص اللقطة فور أخذها.** نسخةٌ لا تُفحَص ليست نسخة، هي رجاء.
problem = target.execute("PRAGMA integrity_check").fetchone()[0]
target.close(); source.close()
if problem != "ok":
    raise SystemExit(f"integrity_check: {problem}")
PY
chmod 600 "$OUT"
sha256sum "$OUT" | awk '{print $1}' > "$OUT.sha256"

# الأسرار — على الخادم وحده.
if [ -d "$ROOT/secrets" ]; then
  tar -czf "$DEST/hourly/secrets-$STAMP.tgz" -C "$ROOT" secrets
  chmod 600 "$DEST/hourly/secrets-$STAMP.tgz"
fi

# ترقيةٌ يومية: أوّل نسخةٍ في اليوم تُنسخ إلى daily.
DAY="$(date -u +%Y%m%d)"
if ! ls "$DEST/daily/maather-$DAY"* >/dev/null 2>&1; then
  cp -p "$OUT" "$DEST/daily/maather-$DAY-$STAMP.db"
  cp -p "$OUT.sha256" "$DEST/daily/maather-$DAY-$STAMP.db.sha256"
fi

# التقليم — بالعدد لا بالعمر: قرصٌ ممتلئ يوقف الخدمة.
prune() {
  local dir="$1" keep="$2" pattern="$3"
  ls -1t "$dir"/$pattern 2>/dev/null | tail -n +$((keep + 1)) | while read -r old; do
    rm -f "$old" "$old.sha256"
  done
}
prune "$DEST/hourly" "$KEEP_HOURLY" 'maather-*.db'
prune "$DEST/hourly" "$KEEP_HOURLY" 'secrets-*.tgz'
prune "$DEST/daily"  "$KEEP_DAILY"  'maather-*.db'

echo "✅ $OUT ($(du -h "$OUT" | cut -f1)) · sha256 مُثبَت · integrity ok"
