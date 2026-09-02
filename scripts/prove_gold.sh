#!/usr/bin/env bash
#
# إثبات اقتصاديات الذهب — **يُشغَّل على الماك**، والقياس يجري على الخادم.
#
#     bash scripts/prove_gold.sh                          # قياسٌ وحساب، بلا إرسال
#     bash scripts/prove_gold.sh --prove "مرجع موافقتك"    # التجربة على التجريبي
#     bash scripts/prove_gold.sh --epic EURUSD            # أداةٌ أخرى
#
# ## لماذا هذا الملفّ موجود
#
# `discover_instrument_economics.py` و`prove_gold_economics.py` **بايثون
# يعمل على الخادم**: هناك الأسرار، وهناك بيئة `/opt/mathrah/.venv`، ومن هناك
# وحده يُرى الوسيط. وتشغيلهما على الماك يعطي `no such file or directory` —
# وهو ما وقع فعلاً، لأن الإرشاد قال «شغّلي» ولم يقل «أين».
#
# فالقاعدة هنا كما في `start_demo_trial.sh`: **كل ما تكتبينه يُكتب على
# الماك**، والسكربت يعبر بـSSH نيابةً عنك.
#
# ## ما يفعله
#
#   ١. يتحقّق أن الخدمة تعمل.
#   ٢. يقيس اقتصاديات الأدوات من حساب Demo (قراءةٌ محضة).
#   ٣. يطبع جدول «أيّ وقفٍ وأيّ هدفٍ يمرّان» عند مرجعك.
#   ٤. ومع `--prove` وحدها: أمران على التجريبي، الثاني يُغلق فوراً.
#
# ## ما لا يفعله
#
# لا يمسّ الحساب الحقيقي، ولا `LIVE_TRADING`، ولا قاطع الطوارئ، ولا يفتح
# قفل تنفيذٍ إلا بمرجع موافقةٍ تكتبينه أنت.
set -uo pipefail

EPIC="GOLD"
BASELINE="300"
PROVE=""
APPROVAL=""
SERVER_IP="${MATHRAH_SERVER:-167.233.234.236}"

while [ $# -gt 0 ]; do
  case "$1" in
    --epic)     EPIC="${2:-GOLD}"; shift 2 ;;
    --baseline) BASELINE="${2:-300}"; shift 2 ;;
    --server)   SERVER_IP="${2:-$SERVER_IP}"; shift 2 ;;
    --prove)    PROVE="1"; APPROVAL="${2:-}"; shift 2 ;;
    *)          printf '\033[31m⛔ خيار غير معروف: %s\033[0m\n' "$1"; exit 2 ;;
  esac
done

KEY="${MATHRAH_SSH_KEY:-$HOME/Desktop/Trading/.ssh-maather/maather_hetzner}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

[ -f "$KEY" ] || { red "⛔ مفتاح SSH غير موجود: $KEY"; exit 1; }
chmod 600 "$KEY" 2>/dev/null || true
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "root@$SERVER_IP")

REMOTE='cd /opt/mathrah/backend && sudo -u mathrah /opt/mathrah/.venv/bin/python'

step "١ · الخادم"
"${SSH[@]}" 'systemctl is-active --quiet mathrah && echo ok' >/dev/null 2>&1 \
  || { red "⛔ الخدمة لا تعمل. انشري أولاً:"; echo "   bash scripts/deploy_to_server.sh $SERVER_IP"; exit 1; }
green "✅ الخدمة تعمل على $SERVER_IP"

step "٢ · قياس اقتصاديات الأدوات (قراءةٌ محضة — لا أمر يُرسَل)"
"${SSH[@]}" "$REMOTE ../scripts/discover_instrument_economics.py --source demo" || {
  red "⛔ تعذّر القياس. بلا قياسٍ لا يُحسَب شيء — ولا يُبنى على تخمين."
  exit 1
}

step "٣ · ماذا يعني ذلك لحدودك عند مرجع $BASELINE دولار"
"${SSH[@]}" "$REMOTE ../scripts/prove_gold_economics.py --epic $EPIC --baseline $BASELINE" || {
  red "⛔ تعذّر الحساب."
  exit 1
}

if [ -z "$PROVE" ]; then
  dim ""
  dim "هذه قراءةٌ وحساب. للإثبات بالتجربة (أمران على التجريبي، والثاني يُغلق فوراً):"
  dim "  bash scripts/prove_gold.sh --prove \"مرجع موافقتك المكتوب\""
  exit 0
fi

if [ -z "${APPROVAL// }" ]; then
  red "⛔ --prove تتطلب مرجع موافقتك المكتوب — يُسجَّل في قفل التنفيذ."
  echo "   bash scripts/prove_gold.sh --prove \"مرجع موافقتك المكتوب\""
  exit 2
fi

step "٤ · التجربة على الحساب التجريبي"
dim "أمران: وقفٌ أضيق من المُعلَن (يُنتظر رفضه)، ووقفٌ عنده (يُنتظر قبوله ثم يُغلق فوراً)."
"${SSH[@]}" "$REMOTE ../scripts/prove_gold_economics.py --epic $EPIC --baseline $BASELINE \
  --prove --approval-ref $(printf '%q' "$APPROVAL")"
STATUS=$?

if [ $STATUS -ne 0 ]; then
  red "⛔ لم يكتمل الإثبات (رمز $STATUS). اقرئي السبب أعلاه قبل البناء على أرقام الذهب."
  dim "وإن كان قد فُتح مركزٌ ولم يُغلق، أغلقيه من تطبيق كابيتال الآن."
  exit $STATUS
fi
green "✅ اكتمل الإثبات."
