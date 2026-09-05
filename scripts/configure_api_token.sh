#!/usr/bin/env bash
#
# رمزُ مجال الواجهة `/api` — إنشاؤه وفحصه بلا كشفه.
#
#   ./scripts/configure_api_token.sh --generate   يولّد رمزاً عشوائياً ويخزّنه
#   ./scripts/configure_api_token.sh              يُدخَل يدوياً (مخفيّ)
#   ./scripts/configure_api_token.sh --check      يقول موجود/غائب فقط
#   ./scripts/configure_api_token.sh --show       يطبع الرمز — للاستعمال في سكربت
#
# ## لماذا هذا الرمز موجود
#
# مجالُ `/api` كان مفتوحاً بلا مصادقة ومنشوراً على الشبكة الخاصة، وفيه
# ثلاثةُ مساراتٍ **تزيد المخاطرة**: استئنافُ التداول، وإطفاءُ قاطع الطوارئ،
# ورفعُ ملف المخاطرة. وطبقةُ الجوال المحصَّنة إلى جانبه كانت تحرس باباً
# وبجواره نافذة.
#
# ## ضمانات
#
#   * لا يقبل الرمز وسيطاً في سطر الأوامر (لئلا يظهر في ps أو history).
#   * الإدخال اليدوي مخفيّ، ولا يُطبع شيء إلا مع `--show` الصريحة.
#   * يفضّل macOS Keychain، ويتراجع إلى ملف بصلاحية 600.
#   * `--generate` يستعمل عشوائيةً تشفيرية (openssl / urandom).
#
# التوافق: bash 3.2 فأحدث — لا مصفوفات ترابطية.
set -euo pipefail
set +o history 2>/dev/null || true

NAME="MATHRAH_API_TOKEN"
SERVICE="maather-autonomous-trader"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# **الاسم هو الاسم الذي يقرأه التطبيق.**
#
# كتبتُه أوّلاً `capital.env` — وهو اسم ملف اعتمادات الوسيط — والتطبيق يقرأ
# `runtime.env` (`Settings.secrets_file`). فكان السكربت سيقول «✅ خُزّن»
# وهو صادق، ثم يقول الخادم «الرمز غائب» وهو صادق أيضاً: نجاحٌ وفشلٌ
# متزامنان ولا رسالة تدلّ على السبب.
#
# وهو العطل نفسه الذي وقع من قبل بين كاتب الاعتمادات وقارئها، وله اختبارٌ
# دائم. فأُضيف له أخٌ يفحص هذا المسار.
SECRETS_FILE="${MATHRAH_SECRETS_FILE:-$REPO_ROOT/secrets/runtime.env}"

use_keychain() { [ "$(uname)" = "Darwin" ] && command -v security >/dev/null 2>&1; }

read_stored() {
  if use_keychain; then
    security find-generic-password -s "$SERVICE" -a "$NAME" -w 2>/dev/null || true
  elif [ -f "$SECRETS_FILE" ]; then
    sed -n "s/^${NAME}=//p" "$SECRETS_FILE" | head -1
  fi
}

write_stored() {
  # القيمة على المدخل القياسي — **لا في وسيط**، فلا تظهر في ps.
  local value; value="$(cat)"
  [ -n "$value" ] || { echo "⛔ رمزٌ فارغ — لم يُخزَّن." >&2; exit 2; }
  if use_keychain; then
    security add-generic-password -U -s "$SERVICE" -a "$NAME" -w "$value" >/dev/null
    echo "✅ خُزّن في macOS Keychain."
  else
    mkdir -p "$(dirname "$SECRETS_FILE")"
    touch "$SECRETS_FILE"; chmod 600 "$SECRETS_FILE"
    # يُستبدَل السطر إن وُجد، ويُضاف إن غاب — بلا تكرار.
    if grep -q "^${NAME}=" "$SECRETS_FILE" 2>/dev/null; then
      local tmp; tmp="$(mktemp)"
      grep -v "^${NAME}=" "$SECRETS_FILE" > "$tmp"
      printf '%s=%s\n' "$NAME" "$value" >> "$tmp"
      mv "$tmp" "$SECRETS_FILE"; chmod 600 "$SECRETS_FILE"
    else
      printf '%s=%s\n' "$NAME" "$value" >> "$SECRETS_FILE"
    fi
    echo "✅ خُزّن في ملف محلي بصلاحية 600."
  fi
}

case "${1:-}" in
  --check)
    if [ -n "$(read_stored)" ]; then
      echo "✅ $NAME موجود$(use_keychain && echo ' (macOS Keychain)' || echo ' (ملف محلي)')."
    else
      echo "❌ $NAME غائب — مجال /api مغلق حتى يُضبَط."; exit 1
    fi
    ;;
  --show)
    # للسكربتات وحدها (فحصُ ما بعد النشر). لا تُشغَّل في طرفيةٍ مسجَّلة.
    read_stored
    ;;
  --generate)
    if [ -n "$(read_stored)" ]; then
      echo "رمزٌ موجود بالفعل. لاستبداله: احذفيه أولاً، أو أدخلي واحداً يدوياً." >&2
      exit 3
    fi
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -base64 33 | tr -d '\n=+/' | cut -c1-40 | write_stored
    else
      LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 | write_stored
    fi
    echo "   لم يُطبع الرمز. لقراءته لاحقاً: --show"
    ;;
  "")
    [ -t 0 ] || { echo "⛔ لا يُقرأ رمزٌ من أنبوب — استعملي --generate." >&2; exit 2; }
    printf 'الصقي رمز مجال /api (لن يظهر): '
    read -r -s entered; echo
    printf 'أعيدي الإدخال للتأكيد: '
    read -r -s again; echo
    [ "$entered" = "$again" ] || { echo "⛔ القيمتان غير متطابقتين."; exit 2; }
    printf '%s' "$entered" | write_stored
    ;;
  *)
    echo "⛔ لا يُقبل تمرير الرمز في سطر الأوامر." >&2; exit 2 ;;
esac
