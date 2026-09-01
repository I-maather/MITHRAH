#!/usr/bin/env bash
#
# تهيئة خادم مَثْراة — يُنفَّذ **على الخادم** لا على الماك.
#
# يُستدعى من `scripts/deploy_to_server.sh`، ولا يُشغَّل يدوياً.
#
# ## المبدأ
#
# **يفشل مغلقاً، ويتحقّق من الأثر لا من نيّة الأمر.** نفس الدرس الذي علّمنا
# إياه رمز خروج `expo prebuild`: أمرٌ ينجح ظاهرياً وقد لا يترك شيئاً.
#
# ## وما لا يفعله
#
# * **لا يفعّل التداول.** `LIVE_TRADING=false` وهو الافتراضي، ولا يُلمَس.
# * **لا ينقل أي سرّ.** مجلّد `secrets/` و`data/private/` لا يُنسخان.
# * **لا يفتح الخادم على الإنترنت.** يستمع على `127.0.0.1` وحدها، والوصول
#   عبر الشبكة الخاصة فقط. والجدار يرفض كل وارد عدا SSH.
set -uo pipefail

APP_USER="mathrah"
APP_DIR="/opt/mathrah"
BUNDLE="/tmp/mathrah.bundle"
SERVICE="/etc/systemd/system/mathrah.service"

#: الكوميت المتوقَّع، يمرّره سكربت النقل. **يُقارَن بما وصل فعلاً.**
EXPECTED_SHA="${1:-}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

die() { red "⛔ $*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "لا بدّ من الجذر."
[ -f "$BUNDLE" ] || die "حزمة الكود غير موجودة: $BUNDLE"

# ---------------------------------------------------------------------------
step "١ · الحزم الأساسية"
# ---------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || die "تعذّر تحديث قوائم الحزم."
apt-get install -y -qq git python3 python3-venv python3-pip curl ufw jq \
  >/dev/null || die "تعذّر تثبيت الحزم الأساسية."
green "✅ git · python3 · venv · ufw"

python3 --version

# ---------------------------------------------------------------------------
step "٢ · مستخدم لا يملك الجذر"
# ---------------------------------------------------------------------------
# الخدمة **لا تعمل بصلاحية الجذر**: ثغرةٌ في اعتمادية ما تصير عندها ثغرة
# في النظام كلّه. والمستخدم بلا صدفة دخول ولا كلمة مرور.
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$APP_USER" \
          --shell /usr/sbin/nologin "$APP_USER" || die "تعذّر إنشاء المستخدم."
fi
green "✅ المستخدم $APP_USER"

# ---------------------------------------------------------------------------
step "٣ · الكود"
# ---------------------------------------------------------------------------
mkdir -p "$APP_DIR"
# الجذر يقرأ مستودعاً يملكه مستخدم آخر، فيرفض git ذلك افتراضاً
# («dubious ownership»). ولولا هذا السطر لفشل كل أمر git صامتاً بعد
# تغيير الملكية — وقد فشل فعلاً، وطُبع «✅» فوق فشل.
git config --global --add safe.directory "$APP_DIR" >/dev/null 2>&1 || true

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch "$BUNDLE" 'refs/heads/*:refs/remotes/bundle/*' -f \
    >/dev/null 2>&1 || die "تعذّر جلب التحديث من الحزمة."
  git -C "$APP_DIR" reset --hard bundle/main >/dev/null 2>&1 \
    || git -C "$APP_DIR" reset --hard bundle/master >/dev/null 2>&1 \
    || die "تعذّر تحديث الشجرة."
else
  git clone -q "$BUNDLE" "$APP_DIR" || die "تعذّر استنساخ الكود."
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# **يُقرأ ما وصل، ويُقارَن بما كان يجب أن يصل.**
#
# السطر السابق كان `green "… ($(git rev-parse …))"` — فحين فشل الأمر طُبع
# قوسان فارغان تحت علامة ✅. لا يُعلَن نجاح بلا دليل، والدليل يُقرأ لا يُفترض.
DEPLOYED_SHA="$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || true)"
[ -n "$DEPLOYED_SHA" ] || die "تعذّرت قراءة الكوميت المنقول — لا يُعلَن نجاح بلا دليل."
if [ -n "$EXPECTED_SHA" ] && [ "$DEPLOYED_SHA" != "$EXPECTED_SHA" ]; then
  die "الكوميت المنقول ${DEPLOYED_SHA:0:7} يخالف المتوقَّع ${EXPECTED_SHA:0:7}."
fi
green "✅ الكود في $APP_DIR (${DEPLOYED_SHA:0:7}${EXPECTED_SHA:+ · مطابق للمتوقَّع})"

# ---------------------------------------------------------------------------
step "٤ · بيئة بايثون"
# ---------------------------------------------------------------------------
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv" >/dev/null 2>&1 \
  || die "تعذّر إنشاء البيئة الافتراضية."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip >/dev/null
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q \
  -r "$APP_DIR/backend/requirements.txt" || die "تعذّر تثبيت الاعتماديات."
green "✅ البيئة جاهزة"

# ---------------------------------------------------------------------------
step "٥ · مجلّد الحالة بصلاحيات مغلقة"
# ---------------------------------------------------------------------------
# `MobileStateStore` يرفض ملفاً مقروءاً لغير مالكه — فالصلاحيات هنا شرط
# تشغيل لا تزيين.
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$APP_DIR/data"
# **حالة الجوال تُبذَر ولا تُستبدَل.**
#
# كان هذا السطر ينسخ ملف الماك فوق ملف الخادم في **كل نشر**. ورمز التجديد
# يُدوَّر عند كل استعمال، فالنسخة القادمة من الماك تحمل رمزاً قديماً: يفقد
# الخادم الرمز الحيّ، فيردّ 401 على الجوال، فيمسح الجوال جلسته ويطلب مسح
# رمز اقتران جديد.
#
# أي أن السطر الذي كُتب ليقول «لن تحتاجي إعادة اقتران» كان **هو** الذي
# يفرضها في كل مرة — والرسالة المطمئنة تُقال بينما يقع عكسها.
#
# فالخادم هو مرجع الاقتران بعد أوّل بذرة، ولا يُكتب فوقه.
if [ -f "$APP_DIR/data/mobile-state.json" ]; then
  rm -f /tmp/mobile-state.json
  green "✅ حالة الجوال على الخادم كما هي — لم تُلمس"
elif [ -f /tmp/mobile-state.json ]; then
  install -o "$APP_USER" -g "$APP_USER" -m 600 \
    /tmp/mobile-state.json "$APP_DIR/data/mobile-state.json"
  shred -u /tmp/mobile-state.json 2>/dev/null || rm -f /tmp/mobile-state.json
  green "✅ حالة الجوال بُذرت لأوّل مرّة"
else
  green "✅ مجلّد الحالة (بلا حالة سابقة)"
fi

# ---------------------------------------------------------------------------
step "٦ · خدمة تعيد تشغيل نفسها"
# ---------------------------------------------------------------------------
cat > "$SERVICE" <<UNIT
[Unit]
Description=Mathrah Autonomous Trader — backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/backend
Environment=PYTHONUNBUFFERED=1
# التنفيذ الحقيقي مُطفأ. لا يُغيَّر هنا ولا في أي مكان بلا قرار مكتوب.
Environment=LIVE_TRADING=false
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

# تضييق الصلاحيات: الخدمة لا تحتاج شيئاً من النظام خارج مجلّدها.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/data
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable mathrah >/dev/null 2>&1 || die "تعذّر تمكين الخدمة."

# ---------------------------------------------------------------------------
# **إعادة تشغيل، لا `enable --now`.**
#
# كان هنا `systemctl enable --now mathrah`. و`--now` **يشغّل الخدمة إن لم
# تكن تعمل، ولا يعيد تشغيلها إن كانت تعمل**. فكل نشرة بعد أوّل إقلاع كانت
# تنقل الكود الجديد إلى القرص و**تترك العملية القديمة تخدم بالكود القديم**.
#
# وأخفاه فحصُ الجاهزية تحته: يسأل «هل يردّ أحدٌ على 8000؟» — والعملية
# القديمة تردّ. فيُطبع «✅ الخدمة تعمل وتستجيب» عن خدمةٍ تعمل بكودٍ عمره
# ساعات. فحصُ حياة، لا فحصُ إصدار.
#
# وكلّف ذلك ليلةً كاملة: كل إصلاح كان يُنشر ولا يعمل، بينما المسابر —
# وهي عمليات منفصلة تقرأ الكود من القرص — تُظهر الإصلاحات وتعمل. فبدا
# النظام يتناقض مع نفسه: المسبار يقول التقويم يعمل، والخدمة تقول لا.
#
# فيُقارَن **المعرّف الرقمي للعملية** قبلَ وبعد: تغيُّره هو الدليل الوحيد
# على أن الكود الجديد هو الذي يعمل الآن.
# ---------------------------------------------------------------------------
pid_before="$(systemctl show -p MainPID --value mathrah 2>/dev/null || echo 0)"
systemctl restart mathrah || die "تعذّر إعادة تشغيل الخدمة."

ready=0
for _ in $(seq 1 40); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 \
        http://127.0.0.1:8000/api/mobile/v1/describe 2>/dev/null)" = "200" ]; then
    ready=1; break
  fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  red "⛔ الخدمة لم تستجب خلال 20 ثانية. آخر السجل:"
  journalctl -u mathrah -n 25 --no-pager
  exit 1
fi
# **الدليل على أن الكود الجديد هو العامل.** الاستجابة وحدها لا تُثبت ذلك:
# عمليةٌ قديمة تستجيب بالقدر نفسه.
pid_after="$(systemctl show -p MainPID --value mathrah 2>/dev/null || echo 0)"
if [ "$pid_after" = "$pid_before" ] || [ -z "$pid_after" ] || [ "$pid_after" = "0" ]; then
  red "⛔ العملية لم تتغيّر (PID $pid_before) — الكود الجديد **لا يعمل**."
  red "   نُقل إلى القرص وبقيت العملية القديمة تخدم. لا تعتمدي هذه النشرة."
  journalctl -u mathrah -n 25 --no-pager
  exit 1
fi
green "✅ أُعيد تشغيل الخدمة — العملية $pid_before ⇐ $pid_after"

# ويُقرأ الكوميت من داخل الخدمة نفسها: القرص قد يحمل شيئاً والذاكرة غيره.
running_sha="$(curl -s --max-time 3 http://127.0.0.1:8000/api/version 2>/dev/null \
  | sed -n 's/.*"commit":"\([^"]*\)".*/\1/p')"
if [ -n "$running_sha" ] && [ "$running_sha" != "$EXPECTED_SHA" ]; then
  red "⛔ الخدمة تعمل بكوميت $running_sha والمنشور $EXPECTED_SHA."
  exit 1
fi
[ -n "$running_sha" ] && green "✅ الخدمة تعمل بالكوميت المنشور ($running_sha)"

# ---------------------------------------------------------------------------
step "٧ · الجدار الناري"
# ---------------------------------------------------------------------------
ufw --force reset >/dev/null 2>&1
ufw default deny incoming  >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp           >/dev/null
# واجهة الشبكة الخاصة موثوقة — لا منفذ عام يُفتح للتطبيق.
ufw allow in on tailscale0 >/dev/null 2>&1 || true
ufw --force enable         >/dev/null
green "✅ الوارد مرفوض عدا SSH · لا منفذ عام للتطبيق"

# ---------------------------------------------------------------------------
step "٨ · الشبكة الخاصة"
# ---------------------------------------------------------------------------
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh >/dev/null 2>&1 \
    || die "تعذّر تثبيت Tailscale."
fi
green "✅ Tailscale مثبَّت"

echo
echo "════════════════════════════════════════════════════════"
green "تمّت التهيئة."
echo "════════════════════════════════════════════════════════"
echo
echo "بقيت خطوة واحدة تحتاج موافقتك بالمتصفّح — ربط الخادم بشبكتك الخاصة:"
echo
echo "    ssh -i ~/Desktop/Trading/.ssh-maather/maather_hetzner root@SERVER_IP"
echo "    tailscale up --hostname=mathrah"
echo "    tailscale serve --bg 8000"
echo
echo "سيطبع رابطاً افتحيه في المتصفّح لتأكيد انضمام الخادم."
echo "وبعدها يصير عنوان الخادم:  https://mathrah.<شبكتك>.ts.net"
echo
