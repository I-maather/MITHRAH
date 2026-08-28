#!/usr/bin/env bash
#
# إعداد اعتمادات Capital.com محلياً وبأمان.
#
#   ./scripts/configure_capital_credentials.sh          إعداد أو تحديث
#   ./scripts/configure_capital_credentials.sh --check   فحص الوجود بلا كشف
#   ./scripts/configure_capital_credentials.sh --remove  حذف المخزَّن
#
# ضمانات هذا السكربت:
#   * لا يقبل أي سرّ كوسيط في سطر الأوامر (لئلا يظهر في ps أو history).
#   * الإدخال مخفي دائماً (read -s).
#   * لا يطبع أي قيمة، ولا حتى مقنّعة جزئياً.
#   * يُعطّل سجل الصدفة لنفسه أثناء التشغيل.
#   * يفضّل macOS Keychain، ويتراجع إلى ملف بصلاحية 600 عند غيابه.
#   * يطلب تأكيداً صريحاً قبل استبدال قيمة موجودة.
#
# هذا السكربت لا يتصل بالإنترنت ولا يرسل شيئاً إلى أي جهة.
#
# التوافق: bash 3.2 فأحدث — وهو إصدار macOS الافتراضي (/bin/bash).
#   لا تُستعمل هنا مصفوفات ترابطية (declare -A) لأنها من bash 4.0،
#   وتحت `set -u` في bash 3.2 يُفسَّر [KEY] رمزاً حسابياً فيسقط السكربت
#   بـ«unbound variable» قبل أن يظهر أي سؤال. انظري prompt_for أدناه.

set -euo pipefail
set +o history 2>/dev/null || true
umask 077

SERVICE="maather-autonomous-trader"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${REPO_ROOT}/secrets"
SECRETS_FILE="${SECRETS_DIR}/capital.env"

KEYS=(CAPITAL_API_KEY CAPITAL_IDENTIFIER CAPITAL_API_PASSWORD)

# بديل المصفوفة الترابطية: دالة بحث تعمل على bash 3.2 و4 و5 بلا فرق.
prompt_for() {
  case "$1" in
    CAPITAL_API_KEY)
      printf '%s' "مفتاح Capital.com API (X-CAP-API-KEY)" ;;
    CAPITAL_IDENTIFIER)
      printf '%s' "معرّف الدخول لدى Capital.com (البريد المسجَّل)" ;;
    CAPITAL_API_PASSWORD)
      printf '%s' "كلمة المرور المخصّصة للمفتاح (وليست كلمة مرور حسابك)" ;;
    *)
      printf '%s' "$1" ;;
  esac
}

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }

# رفض أي سرّ مُمرَّر كوسيط ------------------------------------------------
# ملاحظة توافق: في bash < 4.4 يُعتبر "$@" غير مُعرَّف تحت `set -u` حين لا توجد
# وسائط، فيسقط السكربت في مساره الطبيعي (بلا وسائط). لذلك يُفحص $# أولاً.
if [[ $# -gt 0 ]]; then
  for arg in "$@"; do
    case "$arg" in
      --check|--remove|--help|-h|--file) ;;
      *)
        red "⛔ هذا السكربت لا يقبل قيماً في سطر الأوامر."
        red "   السبب: الوسائط تظهر في ps وفي سجل الصدفة."
        red "   شغّليه بلا وسائط وسيسألك تفاعلياً."
        exit 2
        ;;
    esac
  done
fi

have_keychain() { [[ "$(uname -s)" == "Darwin" ]] && command -v security >/dev/null 2>&1; }

keychain_has() {
  security find-generic-password -s "$SERVICE" -a "$1" >/dev/null 2>&1
}

keychain_set() {
  # القيمة تُمرَّر عبر -w بقيمة من متغيّر محلي فقط داخل هذه العملية.
  # لا echo ولا تسجيل. -U يحدّث القيد الموجود.
  security add-generic-password -U -s "$SERVICE" -a "$1" -w "$2" >/dev/null 2>&1
}

keychain_remove() {
  security delete-generic-password -s "$SERVICE" -a "$1" >/dev/null 2>&1 || true
}

file_has() {
  [[ -f "$SECRETS_FILE" ]] && grep -q "^$1=" "$SECRETS_FILE" 2>/dev/null
}

file_set() {
  mkdir -p "$SECRETS_DIR"
  touch "$SECRETS_FILE"
  chmod 600 "$SECRETS_FILE"
  local tmp
  tmp="$(mktemp "${SECRETS_DIR}/.capital.XXXXXX")"
  chmod 600 "$tmp"
  grep -v "^$1=" "$SECRETS_FILE" 2>/dev/null > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$SECRETS_FILE"
  chmod 600 "$SECRETS_FILE"
}

file_remove() {
  [[ -f "$SECRETS_FILE" ]] || return 0
  local tmp
  tmp="$(mktemp "${SECRETS_DIR}/.capital.XXXXXX")"
  chmod 600 "$tmp"
  grep -v "^$1=" "$SECRETS_FILE" > "$tmp" || true
  mv "$tmp" "$SECRETS_FILE"
  chmod 600 "$SECRETS_FILE"
}

# صلاحيات الملف بصيغة ثُمانية.
# ⚠️ `stat -f` يعني «تنسيق» في BSD/macOS و«نظام الملفات» في GNU — أي أنه
# ينجح على لينكس بمخرَج لا علاقة له بالصلاحيات. لذلك يُقبل المخرَج فقط
# إن كان ثلاث أو أربع خانات ثُمانية، وإلا تُجرَّب الصيغة الأخرى.
file_mode() {
  local out=""
  out="$(stat -f '%Lp' "$1" 2>/dev/null || true)"
  if [[ "$out" =~ ^[0-7]{3,4}$ ]]; then
    printf '%s' "${out: -3}"
    return 0
  fi
  out="$(stat -c '%a' "$1" 2>/dev/null || true)"
  if [[ "$out" =~ ^[0-7]{3,4}$ ]]; then
    printf '%s' "${out: -3}"
    return 0
  fi
  printf ''
}

secret_exists() {
  if have_keychain && keychain_has "$1"; then return 0; fi
  file_has "$1"
}

store_secret() {
  local key="$1" value="$2"
  if have_keychain; then
    if keychain_set "$key" "$value"; then
      green "  ✅ ${key} حُفظ في macOS Keychain."
      return 0
    fi
    red "  ⚠️  تعذّر الحفظ في Keychain — سيُستعمل الملف المحلي."
  fi
  file_set "$key" "$value"
  green "  ✅ ${key} حُفظ في ${SECRETS_FILE} بصلاحية 600."
}

# ---------------------------------------------------------------- الأوامر
cmd_check() {
  echo "فحص وجود الاعتمادات — لن تُعرض أي قيمة."
  echo
  local missing=0 key where mode
  for key in "${KEYS[@]}"; do
    if secret_exists "$key"; then
      where="ملف محلي"
      if have_keychain && keychain_has "$key"; then where="macOS Keychain"; fi
      green "  ✅ ${key}  (${where})"
    else
      red "  ❌ ${key}  غير موجود"
      missing=1
    fi
  done
  echo
  if [[ -f "$SECRETS_FILE" ]]; then
    mode="$(file_mode "$SECRETS_FILE")"
    if [[ -n "$mode" && "$mode" != "600" ]]; then
      red "  ⚠️  صلاحيات ${SECRETS_FILE} هي ${mode} — يجب أن تكون 600."
      red "      نفّذي: chmod 600 ${SECRETS_FILE}"
      missing=1
    fi
  fi
  if [[ $missing -eq 0 ]]; then
    green "كل الاعتمادات المطلوبة موجودة."
    echo
    dim "الخطوة التالية: أخبري كلود أن الإعداد اكتمل — بلا إرسال أي قيمة."
    return 0
  fi
  echo "شغّلي السكربت بلا وسائط لضبط الناقص."
  return 1
}

cmd_remove() {
  local confirm="" key
  echo "حذف الاعتمادات المخزَّنة محلياً."
  read -r -p "هل أنتِ متأكدة؟ اكتبي yes للتأكيد: " confirm || true
  [[ "$confirm" == "yes" ]] || { echo "أُلغي."; exit 0; }
  for key in "${KEYS[@]}"; do
    # `if` لا `&&`: تحت `set -e` تُسقِط قائمة `a && b` الفاشلة السكربت
    # على نظام بلا Keychain.
    if have_keychain; then keychain_remove "$key"; fi
    file_remove "$key"
    green "  ✅ ${key} حُذف."
  done
  echo
  dim "ملاحظة: هذا لا يُلغي المفتاح لدى Capital.com."
  dim "لإيقافه فعلياً، احذفيه أو أوقفيه من إعدادات API في حسابك."
}

cmd_setup() {
  cat <<'INTRO'
إعداد اعتمادات Capital.com
──────────────────────────
* لن تظهر القيم أثناء الكتابة، ولن تُطبع بعدها.
* لن تُحفظ في سجل الصدفة ولن تظهر في ps.
* الوجهة المفضّلة: macOS Keychain.
* هذه القيم تخص بيئة **Demo** — التداول الحقيقي مقفل في الكود.

المطلوب ثلاثة عناصر من صفحة API في حساب Capital.com:
  1. مفتاح API
  2. معرّف الدخول (البريد المسجَّل)
  3. كلمة المرور المخصّصة التي أنشأتِها **للمفتاح** — لا كلمة مرور الحساب

INTRO

  if have_keychain; then
    green "الوجهة: macOS Keychain (service=${SERVICE})"
  else
    dim "Keychain غير متاح على هذا النظام. الوجهة: ${SECRETS_FILE} بصلاحية 600."
  fi
  echo

  # كل متغيّر يُهيَّأ فارغاً قبل `read`: تحت `set -u` يكون المتغيّر غير المعيَّن
  # خطأً قاتلاً لو انتهى الإدخال (EOF) قبل أن يكتب فيه `read` شيئاً.
  local key prompt replace value confirm_value
  for key in "${KEYS[@]}"; do
    prompt="$(prompt_for "$key")"
    if secret_exists "$key"; then
      echo "• ${key} — موجود مسبقاً."
      replace=""
      read -r -p "  استبداله؟ اكتبي yes للاستبدال، أو Enter للإبقاء: " replace || true
      if [[ "$replace" != "yes" ]]; then
        dim "  أُبقي على القيمة الحالية."
        continue
      fi
    fi

    while true; do
      value=""
      confirm_value=""
      printf '• %s\n' "$prompt"
      read -r -s -p "  القيمة: " value || true
      echo
      if [[ -z "$value" ]]; then
        red "  القيمة فارغة — أعيدي المحاولة."
        continue
      fi
      read -r -s -p "  أعيدي الإدخال للتأكيد: " confirm_value || true
      echo
      if [[ "$value" != "$confirm_value" ]]; then
        red "  القيمتان غير متطابقتين — أعيدي المحاولة."
        value=""
        confirm_value=""
        continue
      fi
      break
    done

    store_secret "$key" "$value"
    # مسح بالإسناد لا بـ`unset`: يبقى المتغيّر مُعرَّفاً ففارغاً، فلا يسقط `set -u`.
    value=""
    confirm_value=""
    echo
  done

  # الإعداد غير السرّي يبقى في .env العادي، لا هنا.
  green "اكتمل الإعداد."
  echo
  dim "للتحقق بلا كشف أي قيمة:"
  dim "  ./scripts/configure_capital_credentials.sh --check"
  dim "  cd backend && python3 -m app.cli secrets-status"
  echo
  dim "ثم أخبري كلود بجملة واحدة أن الإعداد اكتمل. لا ترسلي أي قيمة."
}

case "${1:-}" in
  --check)  cmd_check ;;
  --remove) cmd_remove ;;
  --help|-h)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
  "") cmd_setup ;;
  *)  red "وسيط غير معروف."; exit 2 ;;
esac
