#!/usr/bin/env bash
#
# نقل مَثْراة إلى الخادم — يُشغَّل **على الماك**.
#
#     bash scripts/deploy_to_server.sh 167.233.234.236
#
# ## ما ينقله
#
#   الكود        عبر `git bundle` — لا دفع إلى remote، ولا مستودع عام.
#   حالة الجوال  `data/mobile-state.json` فقط، كي **يبقى جهازك مسجَّلاً**
#                فلا تعيدين مسح رمز اقتران.
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
green "✅ حزمة بحجم $(du -h "$BUNDLE" | cut -f1) · $(git -C "$ROOT" rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
step "٣ · النقل"
# ---------------------------------------------------------------------------
"${SCP[@]}" -q "$BUNDLE" "root@$SERVER_IP:/tmp/mathrah.bundle" \
  || { red "⛔ تعذّر نقل الحزمة."; rm -f "$BUNDLE"; exit 1; }
"${SCP[@]}" -q "$ROOT/deploy/server_bootstrap.sh" "root@$SERVER_IP:/tmp/bootstrap.sh" \
  || { red "⛔ تعذّر نقل سكربت التهيئة."; rm -f "$BUNDLE"; exit 1; }

STATE="$ROOT/data/mobile-state.json"
if [ -f "$STATE" ]; then
  "${SCP[@]}" -q "$STATE" "root@$SERVER_IP:/tmp/mobile-state.json" \
    && green "✅ حالة الجوال نُقلت — لن تحتاجي إعادة اقتران"
fi
rm -f "$BUNDLE"
green "✅ النقل تمّ"

# ---------------------------------------------------------------------------
step "٤ · التهيئة على الخادم"
# ---------------------------------------------------------------------------
"${SSH[@]}" -t "root@$SERVER_IP" "bash /tmp/bootstrap.sh"
status=$?

echo
if [ "$status" -ne 0 ]; then
  red "⛔ توقّفت التهيئة عند خطأ (الرمز $status). الرسالة أعلاه تسمّي الموضع."
  exit "$status"
fi

green "تمّ. الخطوة الأخيرة — ربط الخادم بشبكتك الخاصة:"
echo
echo "  ssh -i $KEY root@$SERVER_IP"
echo "  tailscale up --hostname=mathrah"
echo "  tailscale serve --bg 8000"
echo
echo "ثم يصير عنوان الخادم:  https://mathrah.<شبكتك>.ts.net"
echo "وبعدها نعيد بناء التطبيق على العنوان الجديد."
