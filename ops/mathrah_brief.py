# -*- coding: utf-8 -*-
"""تقريرُ مِثْراة — قراءةٌ فقط من قاعدة البيانات. يطبع نصّاً عربيّاً."""
import sqlite3, datetime, sys

DB = "file:/opt/mathrah/data/maather.db?mode=ro"
c = sqlite3.connect(DB, uri=True).cursor()
now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
d1 = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
d7 = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
out = []
def p(s=""): out.append(s)
def q(s, a=()):
    try:
        c.execute(s, a); return c.fetchall()
    except Exception as e:
        return [("!", str(e)[:110])]
def one(s, a=()):
    r = q(s, a); return r[0][0] if r and r[0] else None
def m(v): return "—" if v is None else "%.2f" % float(v)

riyadh = (now + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
p("مِثْراة — تقريرُ %s (الرياض)" % riyadh)

n = 0
for (x,) in q("select realised_pnl from position_book where state='CLOSED' and reconciliation='CONFIRMED' and closed_at_utc is not null and closed_at_utc>=? order by closed_at_utc desc limit 50", (d1,)):
    if x is None or float(x) >= 0: break
    n += 1
ks = one("select kill_switch_active from system_state")
opn = one("select count(*) from position_book where state='OPEN'") or 0
if ks:
    p("⛔ الحكم: قاطعُ الطوارئ مفعَّل — لا دخولَ جديد.")
elif n >= 2:
    p("⏸ الحكم: تهدئةُ الخسائر فاعلة (%d خسائر/٢٤س) — لا دخولَ حتى تخرج خسارةٌ من النافذة." % n)
else:
    p("✅ الحكم: النظامُ يعمل ويبحث عن فرص. مراكزُ مفتوحة: %d" % opn)

p()
p("— المراكزُ المفتوحة —")
rows = q("select symbol, quantity, entry_price, stop_price, take_profit_price, last_confirmed_utc from position_book where state='OPEN' order by id")
if not rows: p("  لا مركزَ مفتوح.")
for sym, qty, ep, sp, tp, conf in rows:
    side = "بيع" if float(qty) < 0 else "شراء"
    try: risk = "%.2f" % (abs(float(sp) - float(ep)) * abs(float(qty)))
    except Exception: risk = "؟"
    p("  %s %s %s · دخول %s · وقف %s · هدف %s · مخاطرة %s" % (sym, side, qty, ep, sp, tp, risk))

p()
p("— ما أُغلق (٧ أيام) —")
rows = q("select symbol, realised_pnl, closed_at_utc from position_book where state='CLOSED' and closed_at_utc>=? order by closed_at_utc desc", (d7,))
if not rows: p("  لا إغلاق.")
for sym, pn, t in rows:
    mark = "✅" if pn is not None and float(pn) > 0 else ("❌" if pn is not None else "؟")
    p("  %s %s  %s  %s" % (mark, sym, m(pn), str(t)[:16]))
tot = one("select sum(realised_pnl) from position_book where realised_pnl is not null")
dt = one("select sum(realised_pnl) from position_book where realised_pnl is not null and closed_at_utc>=?", (d1,))
w = one("select count(*) from position_book where realised_pnl>0") or 0
lo = one("select count(*) from position_book where realised_pnl<0") or 0
p("  المحقَّق الكلّي %s · آخر ٢٤س %s · رابحة %d / خاسرة %d" % (m(tot), m(dt or 0), w, lo))

p()
p("— مسارُ الفرص (٢٤س) —")
def cnt(act, dec=None):
    if dec: return one("select count(*) from audit_events where action=? and decision=? and timestamp_utc>=?", (act, dec, d1)) or 0
    return one("select count(*) from audit_events where action=? and timestamp_utc>=?", (act, d1)) or 0
p("  فُحصت %d · مؤهَّلة %d · إشارات %d · وافقت المخاطرة %d · أُرسلت %d · نُفِّذت %d" % (
    cnt("PIPELINE_RUN"), cnt("ELIGIBILITY_DECISION", "ELIGIBLE"), cnt("SIGNAL_GENERATED"),
    cnt("RISK_DECISION", "TRADE"), cnt("ORDER_SUBMITTED"), cnt("ORDER_CONFIRMED", "FILLED")))
rows = q("select decision, count(*) from audit_events where action='RISK_DECISION' and decision!='TRADE' and timestamp_utc>=? group by 1 order by 2 desc limit 3", (d1,))
for r in rows: p("  رفض: %s ×%s" % r)

p()
p("— ما يستحقّ نظرة —")
flags = []
if ks: flags.append("قاطعُ الطوارئ مفعَّل.")
if n >= 2: flags.append("التهدئة فاعلة.")
u = one("select count(*) from execution_attempts where resolved=0") or 0
if u: flags.append("%d محاولةَ تنفيذٍ غير محسومة." % u)
cc = one("select count(*) from audit_events where decision='CONVERSION_COST_UNMEASURED' and timestamp_utc>=?", (d1,)) or 0
if cc: flags.append("USDJPY موقوفٌ على كلفة التحويل.")
if not flags: flags.append("لا شيء لافت.")
for f in flags: p("  · " + f)

sys.stdout.write("\n".join(out) + "\n")
