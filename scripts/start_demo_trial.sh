#!/usr/bin/env bash
#
# تشغيل التداول على الحساب التجريبي — **يُشغَّل على الماك**، بأمرٍ واحد.
#
#     bash scripts/start_demo_trial.sh "أوافق على تشغيل التداول التجريبي"
#
# ## ما يفعله
#
#   ١. يتحقّق أن الخادم يعمل بالكوميت المنشور.
#   ٢. يكتب إعدادات التجربة في drop-in لـsystemd (لا يمسّ ملف الخدمة الأصلي).
#   ٣. يضبط الوسيط على **الحساب التجريبي** — وهذا شرط التجربة لا تحسيناً.
#   ٤. يعيد التشغيل، ثم **يقرأ من الخادم** أنه فعلاً على التجريبي وأن
#      الاستراتيجيات تعمل. لا يقول «تمّ» عن شيء لم يقرأه.
#
# ## ما لا يفعله
#
#   * لا يمسّ `LIVE_TRADING` ولا `LIVE_API_ENABLED` ولا قاطع الطوارئ.
#   * لا يعتمد استراتيجية: حالتهنّ تبقى `RESEARCH` في السجلّ، والتقرير يبقى
#     هو الدليل. التجربة تجمع إشاراتٍ أمامية، ولا تُقرأ حافّةً.
#   * لا يكتب العبارة عنك.
#
# ## للإيقاف
#
#     bash scripts/start_demo_trial.sh --stop
#
set -uo pipefail

APPROVAL="${1:-}"
SERVER_IP="${2:-167.233.234.236}"
KEY="${MATHRAH_SSH_KEY:-$HOME/Desktop/Trading/.ssh-maather/maather_hetzner}"
PHRASE="أوافق على تشغيل التداول التجريبي"

#: الاستراتيجيتان اللتان أعطتا إشارةً أوّلية في مسح التاريخ. **لا اعتماد.**
STRATEGIES="${DEMO_TRIAL_STRATEGIES:-TREND_PULLBACK_V2,BREAKOUT_RETEST}"
#: الدقّة. اليومية تعطي إشارةً كل ثلاثة أسابيع تقريباً؛ والساعية نحو واحدة
#: كل يوم ونصف؛ والربع ساعة اثنتين في اليوم. والغرض هنا **تشغيل الآلة
#: ورؤيتها تفتح وتغلق**، لا قياس حافّة — والقياس يبقى في المسح.
RESOLUTION="${DEMO_TRIAL_RESOLUTION:-MINUTE_15}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "root@$SERVER_IP")

if [ "$APPROVAL" = "--stop" ]; then
  step "إيقاف التجربة"
  "${SSH[@]}" 'rm -f /etc/systemd/system/mathrah.service.d/demo-trial.conf \
    && systemctl daemon-reload && systemctl restart mathrah \
    && echo "أُزيلت التجربة وأُعيد تشغيل الخدمة."' || exit 1
  green "✅ التجربة موقوفة. النظام عاد إلى وضعه الافتراضي: لا استراتيجية معتمدة."
  exit 0
fi

if [ "$APPROVAL" != "$PHRASE" ]; then
  red "⛔ لا تشغيل بلا موافقة صريحة بنصّها."
  echo "   bash scripts/start_demo_trial.sh \"$PHRASE\""
  dim  "   التجربة تجعل النظام يفتح صفقات **حقيقية على حساب تجريبي**، بلا تدخّل منك."
  dim  "   لا يمسّ ذلك حسابك الحقيقي بحال — والسكربت يتحقّق من ذلك قبل التشغيل."
  exit 2
fi

step "١ · الخادم"
"${SSH[@]}" 'systemctl is-active --quiet mathrah && echo ok' >/dev/null 2>&1 \
  || { red "⛔ الخدمة لا تعمل. انشري أولاً: bash scripts/deploy_to_server.sh $SERVER_IP"; exit 1; }
green "✅ الخدمة تعمل"

step "٢ · كتابة إعدادات التجربة"
REF="MAATHER-$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"${SSH[@]}" "mkdir -p /etc/systemd/system/mathrah.service.d && cat > /etc/systemd/system/mathrah.service.d/demo-trial.conf <<EOF
[Service]
# تجربة الحساب التجريبي — تُزال بـ: bash scripts/start_demo_trial.sh --stop
# لا تمسّ LIVE_TRADING ولا LIVE_API_ENABLED ولا قاطع الطوارئ.
Environment=BROKER_MODE=CAPITAL_DEMO
Environment=DEMO_TRIAL_ENABLED=1
Environment=DEMO_TRIAL_STRATEGIES=$STRATEGIES
Environment=DEMO_TRIAL_RESOLUTION=$RESOLUTION
Environment=DEMO_TRIAL_APPROVAL_REF=$REF
EOF
systemctl daemon-reload && systemctl restart mathrah && sleep 6" || exit 1
green "✅ كُتبت وأُعيد التشغيل"

step "٣ · القراءة من الخادم — لا ادّعاء"
# **يُقرأ الأثر لا النيّة.** كتابةُ إعدادٍ ليست تشغيلاً، وإعادةُ تشغيلٍ ليست
# نجاحاً: الخدمة قد تُقلع وتسقط. فيُسأل الخادم نفسه.
OUT="$("${SSH[@]}" 'curl -s --max-time 10 http://127.0.0.1:8000/api/broker; echo; curl -s --max-time 10 http://127.0.0.1:8000/api/strategies' 2>/dev/null)"
printf '%s\n' "$OUT" | head -40

if printf '%s' "$OUT" | grep -q '"is_demo": *true\|"is_demo":true'; then
  green "✅ الوسيط على الحساب التجريبي"
else
  red "⛔ الخادم لا يقول إنه على التجريبي. **أوقفي التجربة وراجعي** قبل أي شيء:"
  echo "   bash scripts/start_demo_trial.sh --stop"
  exit 1
fi

step "٤ · ما بعد ذلك"
dim "الحلقة تقيّم كل دقيقة على شموع $RESOLUTION."
dim "لمتابعة ما يجري:  ssh -i \"$KEY\" root@$SERVER_IP 'journalctl -u mathrah -f'"
dim "ولمعرفة ما رآه النظام: شاشة «ماذا رأيتُ اليوم» في التطبيق."
echo
green "✅ التجربة تعمل. المرجع: $REF"
dim "⚠️ هذه تجربة تشغيلٍ لا قياس حافّة. الاستراتيجيات تبقى في حالة بحث،"
dim "   وربحٌ أو خسارةٌ هنا لا يُقرأ اعتماداً ولا رفضاً."
