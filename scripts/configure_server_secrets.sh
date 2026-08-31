#!/usr/bin/env bash
#
# نقل الأسرار إلى الخادم — يُشغَّل **على الماك**:
#
#     bash scripts/configure_server_secrets.sh 167.233.234.236
#
# ## لماذا هذا السكربت موجود
#
# `configure_provider_credentials.sh` يحفظ في سلسلة مفاتيح macOS. والخادم
# لينكس، ولا سلسلة مفاتيح فيه. فمفتاحٌ أُدخل على الماك **لا يصل الخادم**،
# وخطّ القرار هناك يفشل بـ«سرّ غير موجود» بينما المالكة متأكّدة أنها أدخلته.
#
# ## ما يفعله
#
#   يقرأ من سلسلة مفاتيح الماك إن وُجد المفتاح، وإلا يسأل عنه بإدخال صامت،
#   ثم يكتبه على الخادم في ملف بصلاحية 600 يملكه مستخدم الخدمة وحده.
#
# ## ما لا يفعله — عمداً
#
#   * لا يطبع أي قيمة، ولا يضعها في وسيطة أمر (فتظهر في `ps`)
#   * لا يكتب أي سرّ في ملف داخل المستودع على الماك
#   * لا يُبقي نسخة في سجلّ الصدفة (يُمرَّر عبر stdin لا عبر سطر الأوامر)
set -uo pipefail
umask 077

SERVER_IP="${1:-}"
KEY="${MATHRAH_SSH_KEY:-$HOME/Desktop/Trading/.ssh-maather/maather_hetzner}"
SERVICE="maather-autonomous-trader"
REMOTE_DIR="/opt/mathrah/secrets"
SERVICE_USER="mathrah"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

if [ -z "$SERVER_IP" ]; then
  red "⛔ الاستعمال:  bash scripts/configure_server_secrets.sh <عنوان الخادم>"
  exit 2
fi
[ -f "$KEY" ] || { red "⛔ مفتاح SSH غير موجود: $KEY"; exit 1; }
chmod 600 "$KEY" 2>/dev/null || true
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "root@$SERVER_IP")

# ---------------------------------------------------------------------------
step "١ · فحص الاتصال"
# ---------------------------------------------------------------------------
"${SSH[@]}" -o BatchMode=yes true 2>/dev/null || {
  red "⛔ تعذّر الاتصال. تأكّدي أن الخادم يعمل وأن المفتاح صحيح."
  exit 1
}
green "✅ الاتصال سليم"

# ---------------------------------------------------------------------------
# قراءة سرّ: من سلسلة المفاتيح إن وُجد، وإلا سؤال صامت مؤكَّد مرّتين.
# يُطبع على stdout لتلتقطه الدالة المستدعية — ولا يُطبع أبداً على الشاشة.
# ---------------------------------------------------------------------------
read_secret() {
  local name="$1" desc="$2" value=""
  value="$(security find-generic-password -s "$SERVICE" -a "$name" -w 2>/dev/null || true)"
  if [ -n "$value" ]; then
    printf '%s' "$value"
    return 0
  fi
  local a b
  while :; do
    printf '\n  %s\n' "$desc" >&2
    printf '  %s: ' "$name" >&2; read -rs a; printf '\n' >&2
    [ -n "$a" ] || { printf '  (فارغ — تخطٍّ)\n' >&2; return 1; }
    printf '  تأكيد: ' >&2;      read -rs b; printf '\n' >&2
    [ "$a" = "$b" ] && break
    printf '  ⛔ غير متطابق. أعيدي.\n' >&2
  done
  printf '%s' "$a"
}

# ---------------------------------------------------------------------------
step "٢ · جمع الأسرار"
# ---------------------------------------------------------------------------
dim "  ما وُجد في سلسلة مفاتيح الماك يُؤخذ منها بلا سؤال."
dim "  ما لم يوجد يُسأل عنه بإدخال صامت. لا قيمة تُطبع في أي حال."

BODY=""
FOUND=0
add() {  # add <NAME> <DESC>
  local v; v="$(read_secret "$1" "$2")" || { printf '  ⏭  %s — تُخطّى\n' "$1"; return 0; }
  BODY+="$1=$v"$'\n'
  FOUND=$((FOUND+1))
  printf '  ✅ %s\n' "$1"
}

add CAPITAL_API_KEY       "مفتاح Capital.com (واجهة التداول)"
add CAPITAL_IDENTIFIER    "معرّف Capital.com — البريد"
add CAPITAL_API_PASSWORD  "كلمة مرور واجهة Capital.com"
add FMP_API_KEY           "مفتاح Financial Modeling Prep — التقويم الاقتصادي"
add FINNHUB_API_KEY       "مفتاح Finnhub — الأخبار"
add FRED_API_KEY          "مفتاح FRED — البيانات الكلّية"

if [ "$FOUND" -eq 0 ]; then
  red "⛔ لم يُجمع أي سرّ. لم يُكتب شيء على الخادم."
  exit 1
fi
green "جُمع $FOUND سرّاً"

# ---------------------------------------------------------------------------
step "٣ · الكتابة على الخادم بصلاحية 600"
# ---------------------------------------------------------------------------
# السرّ يُمرَّر عبر stdin — لا في سطر أمر، فلا يظهر في `ps` على الخادم.
printf '%s' "$BODY" | "${SSH[@]}" "
  set -e
  umask 077
  mkdir -p '$REMOTE_DIR'
  cat > '$REMOTE_DIR/runtime.env'
  chmod 600 '$REMOTE_DIR/runtime.env'
  chown -R '$SERVICE_USER:$SERVICE_USER' '$REMOTE_DIR' 2>/dev/null || true
  chmod 700 '$REMOTE_DIR'
" || { red "⛔ فشلت الكتابة على الخادم."; exit 1; }
green "✅ كُتبت في $REMOTE_DIR/runtime.env"

# ---------------------------------------------------------------------------
step "٤ · تحقّق — بالوجود لا بالقيمة"
# ---------------------------------------------------------------------------
# لا يُطبع أي سرّ: تُعرض الأسماء وحدها ومعها طول القيمة كدليل أنها ليست فارغة.
"${SSH[@]}" "
  f='$REMOTE_DIR/runtime.env'
  [ -f \"\$f\" ] || { echo '⛔ الملف غير موجود'; exit 1; }
  m=\$(stat -c '%a' \"\$f\"); o=\$(stat -c '%U' \"\$f\")
  echo \"  الصلاحيات: \$m   المالك: \$o\"
  [ \"\$m\" = '600' ] || { echo '⛔ الصلاحيات ليست 600'; exit 1; }
  awk -F= '{ printf \"  ✅ %-22s (طول القيمة %d)\n\", \$1, length(\$2) }' \"\$f\"
" || { red "⛔ فشل التحقّق."; exit 1; }

# ---------------------------------------------------------------------------
step "٥ · إعادة تشغيل الخدمة لتلتقط الأسرار"
# ---------------------------------------------------------------------------
"${SSH[@]}" "systemctl restart mathrah 2>/dev/null || systemctl restart mathrah.service 2>/dev/null || true; sleep 2; systemctl is-active mathrah 2>/dev/null || echo 'unknown'"

echo ""
green "════════════════════════════════════════════"
green " تمّ. الأسرار على الخادم، والخدمة أُعيد تشغيلها."
green "════════════════════════════════════════════"
echo ""
dim " ملاحظة: هذا لا يشغّل التداول. الأقفال الأربعة ما زالت مغلقة:"
dim "   LIVE_TRADING=false · موقوف محلياً · لا استراتيجية مُجازة"
dim "   · STOP_DISTANCE_UNIT_PROVEN=False"
echo ""
