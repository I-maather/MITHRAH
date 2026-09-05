#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
#  استرجاعٌ **يُتحقَّق منه قبل أن يمسّ شيئاً**.
#
#  الاسترجاع هو اللحظة التي تُكتشف فيها النسخة الفاسدة. فإن كان الطريق
#  «انسخ فوق الحيّة ثم انظر» فقد فُقد الأصل والبديل معاً. لذلك:
#
#      ١ · تُفحَص البصمة   ٢ · تُفحَص السلامة   ٣ · تُقرأ الجداول
#      ٤ · ثم — وبعلمٍ صريح — تُوضع مكان الحيّة، والحيّة تُزاح لا تُحذف
#
#  بلا `--apply` لا يُلمس شيء: يُسترجَع إلى مسارٍ جانبيّ ويُقال ما فيه.
#  وهذا هو الوضع الافتراضي، لأنّ أكثر ما يُطلَب هو **التأكّد** لا الاستبدال.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="${MATHRAH_ROOT:-/opt/mathrah}"
DATA="$ROOT/data"
PY="$ROOT/.venv/bin/python"
SRC="${1:-}"
APPLY="${2:-}"

[ -n "$SRC" ] || { echo "الاستعمال: restore.sh <ملف-النسخة> [--apply]" >&2; exit 2; }
[ -f "$SRC" ] || { echo "⛔ لا نسخة عند $SRC" >&2; exit 2; }

echo "═══ ١ · البصمة ═══"
if [ -f "$SRC.sha256" ]; then
  want="$(cat "$SRC.sha256")"
  have="$(sha256sum "$SRC" | awk '{print $1}')"
  [ "$want" = "$have" ] || { echo "⛔ البصمة لا تطابق — النسخة تغيّرت على القرص." >&2; exit 3; }
  echo "  ✅ مطابقة"
else
  echo "  ⚠️ لا بصمة محفوظة — يُواصَل بالفحص وحده"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -p "$SRC" "$WORK/candidate.db"

echo "═══ ٢ · السلامة والمحتوى ═══"
"$PY" - "$WORK/candidate.db" "$DATA/maather.db" <<'PY'
import sqlite3, sys
cand, live = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"file:{cand}?mode=ro", uri=True)
problem = c.execute("PRAGMA integrity_check").fetchone()[0]
if problem != "ok":
    raise SystemExit(f"⛔ integrity_check: {problem}")
print("  ✅ integrity ok")
tables = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("  جداول:", len(tables))
interesting = ["position_book", "order_intents", "execution_attempts",
               "broker_orders", "risk_decisions", "audit_log"]
for t in interesting:
    if t in tables:
        print(f"    {t}: {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
try:
    l = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    print("  ── مقابل الحيّة ──")
    for t in interesting:
        if t in tables:
            a = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            b = l.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            mark = "=" if a == b else "≠"
            print(f"    {t}: نسخة={a} {mark} حيّة={b}")
    l.close()
except Exception as exc:
    print("  (تعذّرت المقارنة بالحيّة:", type(exc).__name__, ")")
c.close()
PY

if [ "$APPLY" != "--apply" ]; then
  OUT="$DATA/restored-$(date -u +%Y%m%dT%H%M%SZ).db"
  cp -p "$WORK/candidate.db" "$OUT"
  chmod 600 "$OUT"
  echo "═══ ٣ · بلا --apply: لم تُمَسّ الحيّة ═══"
  echo "  النسخة المُتحقَّق منها: $OUT"
  exit 0
fi

echo "═══ ٣ · التطبيق ═══"
systemctl stop mathrah || true
ASIDE="$DATA/maather-replaced-$(date -u +%Y%m%dT%H%M%SZ).db"
mv "$DATA/maather.db" "$ASIDE"
echo "  الحيّة أُزيحت إلى: $ASIDE (لا تُحذف)"
cp -p "$WORK/candidate.db" "$DATA/maather.db"
chown mathrah:mathrah "$DATA/maather.db"
chmod 640 "$DATA/maather.db"
systemctl start mathrah
sleep 8
echo "  الخدمة: $(systemctl is-active mathrah)"
echo "  النبض: $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8000/api/health/live)"
