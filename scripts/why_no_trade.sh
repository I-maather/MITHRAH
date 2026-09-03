#!/usr/bin/env bash
#
# لماذا لم يتداول النظام بعد؟ — يُقرأ من الخادم الحيّ، لا يُستنتج.
#
#     bash scripts/why_no_trade.sh 167.233.234.236
#
# ## لماذا وُجد هذا السكربت
#
# قالت المالكة بعد يومٍ من التشغيل: «للآن ما تم التداول». ولم يكن في
# النظام كلّه ما يجيب: `/api/today` يعرض **آخر** قرار وحده، و`/api/health`
# يعرض راية «المجدول سليم» — وهي صادقةٌ تماماً عن مجدولٍ لم يدر ولا مرّة.
#
# والسؤال ينحلّ إلى أربعة، بهذا الترتيب، ولا يُقفز عن أوّلها:
#
#   ١ · هل دارت حلقة القرار أصلاً؟ (وكم مرة، ومتى آخرها، وهل أخطأت؟)
#   ٢ · هل كانت بوابةٌ عامة مغلقة؟ (سوق، قاطع طوارئ، إيقاف محلي، وسيط)
#   ٣ · ماذا رأى على كل أداة، ولماذا رفضها؟
#   ٤ · وعلى مدى السجل كلّه: ما توزيع أسباب الرفض؟
#
# ## المبدأ
#
# **الغياب يُقال غياباً.** حقلٌ لم يُقرأ لا يُترجَم إلى «لا مشكلة»؛ يُطبع
# «لم يُقرأ» ويُكمَل. وهذا السكربت لا يرسل أمراً ولا يغيّر إعداداً.
set -uo pipefail

SERVER_IP="${1:-}"
KEY="${MATHRAH_SSH_KEY:-$HOME/Desktop/Trading/.ssh-maather/maather_hetzner}"
API="http://127.0.0.1:8000"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
warn()  { printf '\033[33m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

if [ -z "$SERVER_IP" ]; then
  red "⛔ الاستعمال:  bash scripts/why_no_trade.sh <عنوان الخادم>"
  exit 1
fi

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "root@$SERVER_IP")
if ! "${SSH[@]}" -o BatchMode=yes true 2>/dev/null; then
  red "⛔ تعذّر الاتصال بالخادم. لا أدّعي شيئاً عن حالته — لم أقرأ."
  exit 1
fi

get() { "${SSH[@]}" "curl -s --max-time 12 $API$1" 2>/dev/null; }

HEALTH="$(get /api/health)"
TODAY="$(get /api/today)"
INTEL="$(get /api/intelligence)"
AUDIT="$(get '/api/audit?limit=2000')"

if [ -z "$HEALTH" ]; then
  red "⛔ الخدمة لا تردّ على $API — لا قراءة ولا حكم."
  exit 1
fi

# ---------------------------------------------------------------------------
step "١ · هل دارت حلقة القرار أصلاً؟"
# ---------------------------------------------------------------------------
echo "$HEALTH" | python3 -c '
import json, sys
try:
    h = json.load(sys.stdin)
except Exception:
    print("  \u26d4 ردٌّ غير صالح — لم يُقرأ."); sys.exit(0)
jobs = h.get("scheduler")
if jobs is None:
    print("  \u25cb الخادم لا يعرض حالة المجدول — إصدارٌ أقدم من هذا الفحص.")
    print("    (انشري آخر كوميت ثم أعيدي هذا السكربت.)")
    sys.exit(0)
if not jobs:
    print("  \u26d4 لا مهمة مسجّلة إطلاقاً — النظام لا يقرّر، وهذا هو السبب.")
    sys.exit(0)
for j in jobs:
    runs = j.get("runs", 0)
    fails = j.get("failures", 0)
    name = j.get("name", "?")
    mark = "\u26d4" if runs == 0 else ("\u25cb" if fails else "\u00b7")
    print("  {0} {1:<22} دورات {2:<6} أخطاء {3:<5} كل {4}ث".format(
        mark, name, runs, fails, j.get("interval_seconds")))
    print("      آخر دورة: {0}  ·  التالية: {1}".format(
        j.get("last_run_riyadh") or "لم تدر بعد", j.get("next_run_riyadh")))
    if j.get("last_error"):
        print("      آخر خطأ: {0}".format(j["last_error"]))
'

# ---------------------------------------------------------------------------
step "٢ · هل كانت بوابةٌ عامة مغلقة؟"
# ---------------------------------------------------------------------------
echo "$TODAY" | python3 -c '
import json, sys
try:
    t = json.load(sys.stdin)
except Exception:
    print("  \u26d4 /api/today لم يُقرأ."); sys.exit(0)
m = t.get("market") or {}
ks = t.get("kill_switch") or {}
b = t.get("broker") or {}
print("  · السوق:            {0} — {1}".format(
    "مفتوح" if m.get("is_open") else "مغلق", m.get("reason_ar", "")))
print("  · الوسيط:           {0} — {1} · تجريبي={2}".format(
    b.get("name"), "موصول" if b.get("connected") else "غير موصول",
    not b.get("is_live")))
print("  · قاطع الطوارئ:     {0}".format(
    "مفعّل — " + str(ks.get("reason_ar")) if ks.get("active") else "غير مفعّل"))
blocked = t.get("blocked_by")
if blocked:
    print("  \u26d4 البوابات المانعة: {0}".format(blocked))
else:
    print("  · لا بوابة عامة مانعة.")
print("  · الحكم الأخير:     {0}".format(t.get("verdict_ar")))
if t.get("no_trade_reason_ar"):
    print("    السبب:          {0}".format(t["no_trade_reason_ar"]))
eq = t.get("equity") or {}
lim = t.get("limits") or {}
print("  · رأس المال {0} · ميزانية الصفقة {1} · مراكز مفتوحة {2}".format(
    eq.get("baseline"), lim.get("target_risk_per_trade"), t.get("open_positions")))
'

# ---------------------------------------------------------------------------
step "٣ · ماذا رأى على كل أداة؟"
# ---------------------------------------------------------------------------
echo "$INTEL" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("  \u26d4 /api/intelligence لم يُقرأ."); sys.exit(0)
if not d.get("available"):
    print("  \u25cb {0}".format(d.get("reason_ar"))); sys.exit(0)
for st in (d.get("stages") or []):
    passed = st.get("passed")
    mark = "\u00b7" if passed else ("\u25cb" if passed is None else "\u2717")
    label = st.get("name_ar") or st.get("stage")
    print("  {0} {1}: {2}".format(mark, label, (st.get("reason_ar") or "")[:110]))
'

# ---------------------------------------------------------------------------
step "٤ · توزيع أسباب الرفض في السجل"
# ---------------------------------------------------------------------------
echo "$AUDIT" | python3 -c '
import json, re, sys
from collections import Counter
try:
    a = json.load(sys.stdin)
except Exception:
    print("  \u26d4 /api/audit لم يُقرأ."); sys.exit(0)
events = a.get("events") or []
if not events:
    print("  \u26d4 السجل فارغ — لا قرار كُتب. وهذا نفسه جواب.")
    sys.exit(0)
chain = "سليمة" if a.get("chain_ok") else "مكسورة — " + str(a.get("chain_problem_ar"))
print("  {0} حدثاً مقروءاً · سلسلة التدقيق: {1}".format(len(events), chain))
codes = Counter()
decisions = Counter()
for e in events:
    decisions[e.get("decision") or "—"] += 1
    # **الحدّ الأدنى ثلاثة أحرف لا ستّة.** أوّل نسخة اشترطت ستّة، فاختفى
    # GOLD من كل تقرير — وهو الأداة الوحيدة التي تعمل اقتصادياتها على
    # 300 دولار. وكِدتُ أقرأ غيابه من الجدول غياباً من المسح: تشخيصٌ
    # كامل مبنيٌّ على قصور المِسطرة، وهو صنف اليوم داخل أداة تشخيصه.
    for code in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", e.get("reason_ar") or ""):
        codes[code] += 1
print("")
print("  القرارات:")
for name, n in decisions.most_common(8):
    print("    {0:>5}  {1}".format(n, name))
print("")
if codes:
    print("  أكثر رموز الرفض ذكراً:")
    for code, n in codes.most_common(10):
        print("    {0:>5}  {1}".format(n, code))
else:
    print("  \u25cb لا رمز رفضٍ مذكور في نصوص السجل — الأسباب نثريةٌ فقط.")
'

# ---------------------------------------------------------------------------
step "٥ · هدف المشاركة اليومية"
# ---------------------------------------------------------------------------
#
# القسم الرابع يعدّ رموز الرفض في **نصوص** السجل — تقديرٌ مفيد وغير دقيق:
# رمزٌ يُذكر في جملة شرحٍ يُعدّ مرّتين، ورمزٌ لا يُكتب حرفياً لا يُعدّ.
#
# وهذا القسم يقرأ القمع **مبنياً من الأحداث نفسها** لا من نصوصها، ويقيس
# ما تسأل عنه المالكة: كم يوماً كان مؤهَّلاً، وكم منها وقعت فيه صفقة
# استراتيجية، وأين انهار المسار في كلٍّ منها، ومَن الجهة المسؤولة.
"${SSH[@]}" "curl -s --max-time 10 $API/api/participation?days=14" 2>/dev/null | python3 -c '
import json, sys
try:
    p = json.load(sys.stdin)
except Exception:
    print("  \u26d4 لم تُقرأ نقطة المشاركة — قد تكون النسخة المنشورة أقدم من إضافتها.")
    sys.exit(0)
rate = p.get("daily_participation_rate")
print("  الهدف: " + str(p.get("objective_ar", "")))
print("")
print("  أيام مؤهَّلة: {0}  ·  أيام بصفقة استراتيجية: {1}".format(
    p.get("eligible_trading_days"), p.get("days_with_strategy_trades")))
print("  معدّل المشاركة: {0}".format("—" if rate is None else "{0:.0%}".format(rate)))
print("  متوسط الإشارات المؤهَّلة/يوم: {0}".format(p.get("avg_qualified_signals_per_day")))
print("  صفقات منفَّذة/يوم: {0}".format(p.get("filled_strategy_trades_per_day")))
exp = p.get("net_expectancy_after_costs")
print("  صافي التوقّع بعد التكاليف: {0}".format(
    "لا عيّنة" if exp is None else exp + " $ لكل صفقة مغلقة"))
print("")
reasons = p.get("no_trade_reasons") or {}
if reasons:
    print("  أسباب الأيام المؤهَّلة بلا صفقة:")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("    {0:>4}  {1}".format(v, k))
    print("")
totals = p.get("stage_totals") or {}
if totals:
    print("  مجاميع المراحل:")
    for k in ("scans","eligible","assessed","signals","instrument_economics_ok",
              "risk_approved","intents","submitted","acknowledged","filled","reconciled"):
        print("    {0:>7}  {1}".format(totals.get(k, 0), k))
    print("")
funnel = p.get("rejection_funnel") or {}
if funnel:
    print("  قمع الرفض (من الأحداث لا من النصوص):")
    for stage, codes in funnel.items():
        for code, n in sorted(codes.items(), key=lambda kv: -kv[1])[:4]:
            print("    {0:>7}  {1} / {2}".format(n, stage, code))
excluded = p.get("excluded_days") or []
if excluded:
    print("")
    print("  أيامٌ خارج المقام (لا تُحسَب إخفاق مشاركة):")
    for d in excluded[-7:]:
        print("    {0}  {1}".format(d.get("trading_day"), d.get("because")))
'

echo
dim "لا شيء أُرسل ولا غُيّر. قراءةٌ فقط."
echo
