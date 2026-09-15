#!/usr/bin/env bash
# مِثْراة — مُرسِلُ التنبيهات. يقرأ الرمزَ من الأسرار ولا يطبعه أبداً.
# يخرج بالرمز 3 بصمتٍ إن لم تُضبَط القناة: لا يُفشِل المُنادي ولا يدّعي إرسالاً.
set -uo pipefail
ENV_FILE="${MATHRAH_SECRETS:-/opt/mathrah/secrets/runtime.env}"
[ -r "$ENV_FILE" ] || exit 3
TOKEN="$(grep -m1 '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' \r')"
CHAT="$(grep -m1 '^TELEGRAM_CHAT_ID='   "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' \r')"
[ -n "${TOKEN:-}" ] && [ -n "${CHAT:-}" ] || exit 3
if [ "$#" -gt 0 ]; then TEXT="$*"; else TEXT="$(cat)"; fi
[ -n "${TEXT:-}" ] || exit 0
send() {
  curl -s -m 25 -o /dev/null -X POST \
    "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d "chat_id=${CHAT}" -d "disable_web_page_preview=true" \
    --data-urlencode "text=$1"
}
LEN=${#TEXT}
if [ "$LEN" -le 3900 ]; then send "$TEXT"; else
  i=0; part=1
  while [ "$i" -lt "$LEN" ]; do
    send "($part) ${TEXT:$i:3900}"; i=$((i+3900)); part=$((part+1)); sleep 1
  done
fi
