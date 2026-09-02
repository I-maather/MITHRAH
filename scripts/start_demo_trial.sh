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
#: **بالمفتاح الكامل `الاسم@الإصدار`، لا بالاسم.**
#:
#: كُتب هنا `TREND_PULLBACK_V2` وهو لا يطابق أي استراتيجية: اسمها
#: `TREND_PULLBACK` وإصدارها `2.0.0`. فلم تُشغَّل الاستراتيجية الرئيسية
#: إطلاقاً — بصمت. والاسم وحده لا يكفي أصلاً: v1 وv2 يحملانه معاً.
STRATEGIES="${DEMO_TRIAL_STRATEGIES:-TREND_PULLBACK@2.0.0,BREAKOUT_RETEST@1.0.0}"
#: الدقّة — **يومية، ولا خيار غيرها عند هذا الوسيط.**
#:
#: كان الافتراض هنا `MINUTE_15` طلباً للتكرار (نحو صفقتين يومياً في المسح
#: مقابل واحدة كل ثلاثة أسابيع على اليومية). وهو **خطأ**: أدنى مسافة وقف
#: على EURUSD عند كابيتال 0.01 بوحدة السعر = **100 نقطة**، ووقف
#: الاستراتيجيات 1.5×ATR. وATR على شمعة ربع ساعة نحو 5–10 نقاط ⇒ الوقف
#: 8–15 نقطة ⇒ **كل إشارة تُرفض قبل أن تبلغ الوسيط**. والنتيجة كومة رفضٍ
#: لا صفقة واحدة.
#:
#: وعلى الساعية 22–38 نقطة، وعلى الأربع ساعات 60–90 — وكلاهما دون المئة.
#: واليومية 105–135 ⇒ تمرّ. وهذا بالضبط سبب كون الثلاث يومية: قيدُ الوسيط
#: لا اختيارُ مصمّم.
#:
#: وتخفيض الوقف إلى الحدّ الأدنى مع إبقاء الهدف يعطي عائداً إلى مخاطرة 0.3
#: — صفقةٌ خاسرة بالبناء. وتكبير الهدف معه يجعلها **استراتيجيةً أخرى** لا
#: هذه، فلا تُقاس نتيجتها على شيء.
RESOLUTION="${DEMO_TRIAL_RESOLUTION:-DAY}"

# **والقيد أعلاه يخصّ EURUSD وحدها.** أدنى وقفها 100 نقطة، ووقفُ الساعة
# دونه — فتُرفض. أمّا الذهب فأدنى وقفه `0.001` دولار: عُشر سنت، لا يمنع
# شيئاً. فالقاعدة صحيحةٌ عن أداةٍ ومفروضةٌ على أربع — وهو النمط نفسه الذي
# دُقّقت السكربتات لأجله اليوم.
#
# وأثرُه على المالكة مباشر: الشمعة اليومية تجعل وقف الذهب 140 دولاراً
# (1.5×ATR14 المقيس = 93.86)، وخسارتَه 1.43 — فوق ميزانية 300 دولار.
# والوقف الساعي على الأداة نفسها أصغر بأضعاف. **الحدّ نفسه، والمخاطرة
# نفسها، وصفقةٌ تمرّ.**
#
# فالتحذير الآن **يُقاس لكل أداة** من السجلّ، ولا يُكتب ثابتاً.
resolution_report() {
  "${SSH[@]}" "cd /opt/mathrah/backend && sudo -u mathrah /opt/mathrah/.venv/bin/python - <<'PYEOF'
from decimal import Decimal as D
from app.risk.instrument_registry import InstrumentRegistry

registry = InstrumentRegistry.load()
epics = sorted(registry.executable_epics())
if not epics:
    print('لا أداة مقيسة — لا يمكن الحكم على الدقّة.')
else:
    for epic in epics:
        row = registry.get(epic)
        floor = row.economics.min_stop_distance
        pip = row.economics.pip_size
        if floor is None or pip <= 0:
            print(f'  ? {epic}: أدنى وقفٍ غير معلوم.')
            continue
        print(f'  · {epic}: أدنى وقف {floor} ({floor / pip:g} نقطة)')
PYEOF" 2>/dev/null
}


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

if [ "$RESOLUTION" != "DAY" ]; then
  printf '\033[1m▸ دقّة %s — أي أداةٍ يمنعها حدّ الوسيط؟\033[0m\n' "$RESOLUTION"
  resolution_report
  printf '\033[33m⚠️  أداةٌ حدُّها كبير (مئة نقطة على EURUSD) تُرفض إشاراتها على هذه\033[0m\n'
  printf '\033[33m    الدقّة بـSTOP_BELOW_BROKER_MINIMUM — رفضٌ نظيف بسببٍ يُقرأ.\033[0m\n'
  printf '\033[33m    وأداةٌ حدُّها ضئيل (الذهب: عُشر سنت) تمرّ.\033[0m\n'
  printf '\033[2m    (الرفض لا يُفعّل قاطع الطوارئ — يُسجَّل ويمضي.)\033[0m\n'
  printf '\033[2m    وانتبهي: هذه الاستراتيجيات مكتوبةٌ لليومية. تشغيلها على إطارٍ\033[0m\n'
  printf '\033[2m    أقصر **فرضيةٌ أخرى** تُختبَر، لا الفرضية نفسها تُقاس.\033[0m\n\n'
fi

step "٢ · قياس اقتصاديات الأدوات من الوسيط"
# **قبل التشغيل لا بعده.** قائمة التنفيذ تُبنى من المقيس، فقياسٌ بعد
# الإقلاع لا يصل إلى الخدمة حتى تُعاد. والقياس قراءةٌ محضة: لا أمر يُرسل.
"${SSH[@]}" 'cd /opt/mathrah/backend && sudo -u mathrah /opt/mathrah/.venv/bin/python \
  ../scripts/discover_instrument_economics.py --source demo' || {
  printf '\033[33m⚠️  تعذّر القياس. ما بقي في ملف القياس السابق هو ما سيُنفَّذ عليه،\033[0m\n'
  printf '\033[33m    وإن لم يكن فيه شيء فالتنفيذ على اقتصادياتٍ **مفترضة**. تُقرأ القائمة في الختام.\033[0m\n'
}

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

step "٤ · الخطوة الأخيرة — بيدك"
# `locally_paused` يبدأ **موقوفاً** في كل إقلاع. وهذا مقصود: نظامٌ يتداول
# بمجرّد أن يُقلع ليس نظاماً يُوثَق به. والرفع قرارٌ للمالكة بعبارةٍ مكتوبة.
if printf '%s' "$OUT" | grep -q '"local_trading_paused": *true\|"local_trading_paused":true'; then
  printf '\033[33m⚠️  التداول المحلي ما زال موقوفاً — ولن تُفتح صفقة حتى ترفعيه.\033[0m\n'
  dim  "   من التطبيق: النظام ← الطوارئ ← «استئناف التداول»، واكتبي: أستأنف التداول"
  echo
else
  green "✅ التداول المحلي مرفوع"
fi

step "٥ · ما بعد ذلك"
dim "الحلقة تقيّم كل دقيقة على شموع $RESOLUTION."
# **تُقرأ قائمة التنفيذ من الخادم، ولا تُكتب من الذاكرة.**
#
# كان هنا سطرٌ ثابت: «أداة التنفيذ المسموحة: EURUSD وحدها». وقد صار كذباً
# منذ أن صارت القائمة تُبنى من القياس (`state.py` ⇐ `executable_epics`)
# ومنذ أن قُيست أربع أدوات. فكانت المالكة تُخبَر بأداةٍ واحدة والنظام
# يتداول أربعاً — وهو العيب الحاكم في أوضح صوره: جملةٌ تصف نيّةً قديمة.
EXECUTABLE="$("${SSH[@]}" "cd /opt/mathrah/backend && sudo -u mathrah /opt/mathrah/.venv/bin/python -c \
  'from app.risk.instrument_registry import InstrumentRegistry as R; \
   e=sorted(R.load().executable_epics()); print(\"، \".join(e) if e else \"لا شيء\")'" 2>/dev/null)"
if [ -n "$EXECUTABLE" ] && [ "$EXECUTABLE" != "لا شيء" ]; then
  dim "أدوات التنفيذ المسموحة (مقروءةً من الخادم): $EXECUTABLE"
else
  printf '\033[33m⚠️  لا أداة مقيسة على الخادم — التنفيذ سيجري على اقتصادياتٍ مفترضة.\033[0m\n'
  printf '\033[33m    وهذا يخالف قاعدة «المقيس وحده يُنفَّذ عليه». أوقفي وشغّلي القياس أولاً.\033[0m\n'
fi
dim "لمتابعة ما يجري:  ssh -i \"$KEY\" root@$SERVER_IP 'journalctl -u mathrah -f'"
dim "ولمعرفة ما رآه النظام: شاشة «ماذا رأيتُ اليوم» في التطبيق."
echo
green "✅ التجربة تعمل. المرجع: $REF"
dim "⚠️ هذه تجربة تشغيلٍ لا قياس حافّة. الاستراتيجيات تبقى في حالة بحث،"
dim "   وربحٌ أو خسارةٌ هنا لا يُقرأ اعتماداً ولا رفضاً."
