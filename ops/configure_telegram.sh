#!/usr/bin/env bash
# ضبطُ قناة التنبيهات — يُشغَّل بيد المالكة. الرمزُ لا يُطبَع ولا يُنسخ.
set -uo pipefail
ENV_FILE="${MATHRAH_SECRETS:-/opt/mathrah/secrets/runtime.env}"
green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
cat <<'HOWTO'
────────────────────────────────────────────────────────────
 ١ · في Telegram ابحثي عن  @BotFather  وأرسلي:  /newbot
 ٢ · اختاري اسماً ثم معرّفاً ينتهي بـ bot  ⇒ يردّ برمزٍ طويل
 ٣ · افتحي روبوتك، اضغطي Start، وأرسلي أيّ كلمة
 ٤ · ألصقي الرمز أدناه (لن يظهر أثناء الكتابة)
────────────────────────────────────────────────────────────
HOWTO
printf 'الرمز: '; read -rs TG; echo
[ -n "${TG:-}" ] || { red "⛔ لا رمز."; exit 1; }
WHO="$(curl -s -m 20 "https://api.telegram.org/bot${TG}/getMe")"
printf '%s' "$WHO" | grep -q '"ok":true' || { red "⛔ الرمز مرفوض."; exit 1; }
green "✅ الروبوت: @$(printf '%s' "$WHO" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
CH="$(curl -s -m 20 "https://api.telegram.org/bot${TG}/getUpdates" | sed -n 's/.*"chat":{"id":\(-\?[0-9]*\).*/\1/p' | head -1)"
[ -n "${CH:-}" ] || { red "⛔ لم أجد محادثة — اضغطي Start وأرسلي كلمة ثم أعيدي التشغيل."; exit 1; }
green "✅ معرّف المحادثة: $CH"
umask 077; touch "$ENV_FILE"
tmp="$(mktemp)"
grep -vE '^(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=' "$ENV_FILE" > "$tmp" 2>/dev/null || true
printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TG" "$CH" >> "$tmp"
mv "$tmp" "$ENV_FILE"; chmod 600 "$ENV_FILE"; chown mathrah:mathrah "$ENV_FILE" 2>/dev/null || true
green "✅ كُتب بصلاحيات 600 — ولم يُطبَع."
curl -s -m 20 -o /dev/null -X POST "https://api.telegram.org/bot${TG}/sendMessage" \
  -d "chat_id=${CH}" --data-urlencode "text=مِثْراة: قناةُ التنبيهات تعمل ✅ — من الخادم مباشرةً، بلا ماك وبلا VPN."
green "✅ أُرسلت رسالةُ تجربة."
unset TG
