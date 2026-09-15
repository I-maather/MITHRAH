# -*- coding: utf-8 -*-
"""
راصدُ الأحداث — يُنبّه **لحظةَ** وقوع ما يهمّ، لا صباحاً فقط.

يحفظ آخر `sequence` قرأه في ملفٍّ، فلا يُعيد تنبيهاً أُرسل. وأوّلُ تشغيلٍ
لا يُرسل التاريخَ كلَّه: يبدأ من الآن ويسجّل الموضع.
"""
import os, sqlite3, subprocess, sys

STATE = "/opt/mathrah/data/.watch_seq"
NOTIFY = "/opt/mathrah/ops/mathrah_notify.sh"
WATCHED = {
    ("ORDER_CONFIRMED", "FILLED"):            "✅ نُفِّذ أمر",
    ("ORDER_SUBMITTED", None):                "→ أُرسل أمر",
    ("ORDER_REJECTED", None):                 "⛔ رُفض أمر",
    ("KILL_SWITCH_TRIGGERED", None):          "🚨 انطلق قاطعُ الطوارئ",
    ("KILL_SWITCH_RESET", None):              "🔄 أُعيد ضبطُ القاطع",
    ("RECONCILIATION", "MISMATCH"):           "⚠ عدمُ مطابقةٍ مع الوسيط",
    ("RISK_DECISION", "TRADE"):               "👍 وافقت المخاطرة",
    ("SYSTEM_START", None):                   "♻ أُعيد تشغيلُ النظام",
}
c = sqlite3.connect("file:/opt/mathrah/data/maather.db?mode=ro", uri=True).cursor()
last = c.execute("select max(sequence) from audit_events").fetchone()[0] or 0

if not os.path.exists(STATE):
    open(STATE, "w").write(str(last))
    sys.exit(0)
try:
    seen = int(open(STATE).read().strip() or 0)
except Exception:
    seen = last

rows = c.execute(
    "select sequence, timestamp_utc, action, decision, reason_ar from audit_events "
    "where sequence > ? order by sequence limit 40", (seen,)).fetchall()

lines = []
for seq, ts, act, dec, why in rows:
    label = WATCHED.get((act, dec)) or WATCHED.get((act, None))
    if not label:
        continue
    lines.append("%s — %s\n%s" % (label, str(ts)[:16], (why or "")[:220]))

if rows:
    open(STATE, "w").write(str(rows[-1][0]))

if lines:
    msg = "مِثْراة — تنبيه\n\n" + "\n\n".join(lines[:6])
    if len(lines) > 6:
        msg += "\n\n… و%d حدثاً آخر." % (len(lines) - 6)
    subprocess.run([NOTIFY], input=msg.encode("utf-8"), check=False)
