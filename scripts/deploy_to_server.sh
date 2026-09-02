#!/usr/bin/env bash
#
# نقل مَثْراة إلى الخادم — يُشغَّل **على الماك**.
#
#     bash scripts/deploy_to_server.sh 167.233.234.236
#
# ## ما ينقله
#
#   الكود        عبر `git bundle` — لا دفع إلى remote، ولا مستودع عام.
#   حالة الجوال  `data/mobile-state.json` **بذرةً أولى فقط**. إن كان على
#                الخادم حالة فهي المرجع ولا يُكتب فوقها — الكتابة فوقها
#                تُفقده رمز التجديد المُدوَّر فيطلب الجوال اقتراناً جديداً.
#
# ## وما لا ينقله — عمداً
#
#   `secrets/`         · `data/private/`  · `.env` بأنواعه
#   البيئة الافتراضية  · `node_modules`   · مجلّد `ios/`
#
# الأسرار تُنشأ على الخادم بيدك لا تُنسخ إليه: مفتاح منسوخ هو مفتاح موجود
# في مكانين، والقديم يبقى صالحاً في الأول بعد أن تنسيه.
set -uo pipefail

SERVER_IP="${1:-}"
KEY="${MATHRAH_SSH_KEY:-$HOME/Desktop/Trading/.ssh-maather/maather_hetzner}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

if [ -z "$SERVER_IP" ]; then
  red "⛔ الاستعمال:  bash scripts/deploy_to_server.sh <عنوان الخادم>"
  exit 2
fi
[ -f "$KEY" ] || { red "⛔ مفتاح SSH غير موجود: $KEY"; exit 1; }
chmod 600 "$KEY" 2>/dev/null || true

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
SCP=(scp -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

# ---------------------------------------------------------------------------
step "١ · فحص الاتصال"
# ---------------------------------------------------------------------------
if ! "${SSH[@]}" -o BatchMode=yes "root@$SERVER_IP" true 2>/dev/null; then
  red "⛔ تعذّر الاتصال بالخادم عبر SSH."
  echo "   تأكّدي أن الخادم يعمل، وأن المفتاح المضاف في Hetzner هو:"
  echo "   $KEY.pub"
  exit 1
fi
green "✅ الاتصال سليم"

# ---------------------------------------------------------------------------
step "٢ · تجهيز حزمة الكود"
# ---------------------------------------------------------------------------
if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
  red "⛔ الشجرة غير نظيفة. أودعي التغييرات أولاً كي يكون المنقول محدَّداً."
  git -C "$ROOT" status --short --untracked-files=no | head
  exit 1
fi
BUNDLE="$(mktemp -t mathrah).bundle"
git -C "$ROOT" bundle create "$BUNDLE" --all >/dev/null 2>&1 \
  || { red "⛔ تعذّر إنشاء الحزمة."; exit 1; }
# الكوميت المتوقَّع يُمرَّر إلى الخادم كي **يقارن ما وصل بما أُرسل**.
EXPECTED_SHA="$(git -C "$ROOT" rev-parse HEAD)"
green "✅ حزمة بحجم $(du -h "$BUNDLE" | cut -f1) · ${EXPECTED_SHA:0:7}"

# ---------------------------------------------------------------------------
step "٣ · النقل"
# ---------------------------------------------------------------------------
"${SCP[@]}" -q "$BUNDLE" "root@$SERVER_IP:/tmp/mathrah.bundle" \
  || { red "⛔ تعذّر نقل الحزمة."; rm -f "$BUNDLE"; exit 1; }
"${SCP[@]}" -q "$ROOT/deploy/server_bootstrap.sh" "root@$SERVER_IP:/tmp/bootstrap.sh" \
  || { red "⛔ تعذّر نقل سكربت التهيئة."; rm -f "$BUNDLE"; exit 1; }

STATE="$ROOT/data/mobile-state.json"
if [ -f "$STATE" ]; then
  # تُرسَل **بذرةً** فقط: الخادم يرفضها إن كان لديه حالة حيّة. الكتابة فوقها
  # كانت تُفقده رمز التجديد المُدوَّر فيطلب الجوال اقتراناً جديداً كل نشر.
  "${SCP[@]}" -q "$STATE" "root@$SERVER_IP:/tmp/mobile-state.json" \
    && green "✅ بذرة حالة الجوال أُرسلت (تُستعمل فقط إن لم يكن على الخادم حالة)"
fi
rm -f "$BUNDLE"
green "✅ النقل تمّ"

# ---------------------------------------------------------------------------
step "٤ · التهيئة على الخادم"
# ---------------------------------------------------------------------------
"${SSH[@]}" -t "root@$SERVER_IP" "bash /tmp/bootstrap.sh $EXPECTED_SHA"
status=$?

echo
if [ "$status" -ne 0 ]; then
  red "⛔ توقّفت التهيئة عند خطأ (الرمز $status). الرسالة أعلاه تسمّي الموضع."
  exit "$status"
fi

# ---------------------------------------------------------------------------
step "٥ · هل يصل الجوال إلى الخادم؟"
# ---------------------------------------------------------------------------
# **الأثر يُقرأ بعد التهيئة، لا يُصدَّق من مخرَجها.** كان هذا الموضع يقول
# للمالكة «الحالة مذكورة في مخرَج الخادم أعلاه» — أي يحوّل إليها قراءةً
# يقدر السكربت عليها. والسؤال الوحيد المهم هنا: هل المنفذ ٨٠٠٠ منشور على
# الشبكة الخاصة؟ لأن التطبيق على الجوال لا يصل إلى الخادم بغيره.
NET="$("${SSH[@]}" -o BatchMode=yes "root@$SERVER_IP" \
  "tailscale serve status 2>/dev/null | grep -q 8000 && echo SERVED || echo MISSING" \
  2>/dev/null || echo UNREACHABLE)"
HOSTNAME_TS="$("${SSH[@]}" -o BatchMode=yes "root@$SERVER_IP" \
  "tailscale status 2>/dev/null | awk 'NR==1{print \$2}'" 2>/dev/null || true)"

case "$NET" in
  SERVED)
    green "✅ الخدمة منشورة على شبكتك الخاصة — التطبيق يصل إلى الخادم."
    if [ -n "$HOSTNAME_TS" ]; then echo "   العنوان:  https://${HOSTNAME_TS}"; fi
    ;;
  MISSING)
    red "⛔ الخدمة غير منشورة على الشبكة الخاصة بعد التهيئة."
    red "   التطبيق على الجوال لن يصل إلى الخادم. السطر أعلاه من الخادم يسمّي السبب."
    exit 1
    ;;
  *)
    red "⛔ تعذّر التحقّق من الشبكة الخاصة (لم يُقرأ شيء من الخادم)."
    red "   لا أدّعي أن التطبيق يصل ولا أنه لا يصل — لم أقرأ."
    exit 1
    ;;
esac

echo
green "تمّ."
