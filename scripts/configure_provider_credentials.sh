#!/usr/bin/env bash
#
# إعداد مفاتيح مزوّدي البيانات في سلسلة مفاتيح macOS.
#
#   ./scripts/configure_provider_credentials.sh
#   ./scripts/configure_provider_credentials.sh --check
#   ./scripts/configure_provider_credentials.sh FRED_API_KEY
#
# ما **لا** يفعله هذا السكربت — عمداً:
#   * لا يقرأ قيمة موجودة ولا يعرضها ولا يطبعها في أي حال
#   * لا يكتب أي مفتاح في ملف داخل المستودع
#   * لا يُصدِّر مفتاحاً إلى بيئة عملية أخرى
#   * لا يُرسل شيئاً إلى أي شبكة
#
# الإدخال صامت (`read -s`) ومؤكَّد مرتين. القيمة تذهب إلى Keychain مباشرةً.
#
# التوافق: bash 3.2 فأحدث — وهو إصدار macOS الافتراضي (/bin/bash).

set -euo pipefail
umask 077

SERVICE_PREFIX="maather-trader"

# التوافق: bash 3.2 لا يملك المصفوفات الترابطية، فالوصف عبر دالة `case`.
prompt_for() {
  case "$1" in
    FMP_API_KEY)
      printf '%s' "مفتاح Financial Modeling Prep (التقويم الاقتصادي)" ;;
    FINNHUB_API_KEY)
      printf '%s' "مفتاح Finnhub (أخبار الفوركس)" ;;
    FRED_API_KEY)
      printf '%s' "مفتاح FRED (بيانات الاحتياطي الفيدرالي الكلية)" ;;
    *) printf '%s' "$1" ;;
  esac
}

signup_for() {
  case "$1" in
    FMP_API_KEY)      printf '%s' "https://site.financialmodelingprep.com/developer/docs" ;;
    FINNHUB_API_KEY)  printf '%s' "https://finnhub.io/register" ;;
    FRED_API_KEY)     printf '%s' "https://fredaccount.stlouisfed.org/apikeys" ;;
    *) printf '%s' "—" ;;
  esac
}

ALL_KEYS="FMP_API_KEY FINNHUB_API_KEY FRED_API_KEY"

have_keychain() {
  command -v security >/dev/null 2>&1
}

keychain_service() {
  printf '%s-%s' "$SERVICE_PREFIX" "$(printf '%s' "$1" | tr '[:upper:]_' '[:lower:]-')"
}

# **يفحص الوجود فقط.** لا يطبع القيمة ولا يمرّرها ولا يحتفظ بها.
keychain_has() {
  security find-generic-password -s "$(keychain_service "$1")" -a "$USER" \
    >/dev/null 2>&1
}

keychain_store() {
  # `-U` يحدّث الموجود بدل أن يُنشئ نسخة ثانية صامتة.
  security add-generic-password \
    -s "$(keychain_service "$1")" -a "$USER" -w "$2" -U >/dev/null 2>&1
}

check_only() {
  printf 'حالة مفاتيح المزوّدين — لا تُعرض أي قيمة:\n\n'
  local missing=0
  for key in $ALL_KEYS; do
    if ! have_keychain; then
      printf '  ⚠️   %-18s Keychain غير متاح على هذا النظام\n' "$key"
      missing=1
    elif keychain_has "$key"; then
      printf '  ✅  %-18s موجود\n' "$key"
    else
      printf '  ❌  %-18s غير مُعدّ\n' "$key"
      missing=1
    fi
  done
  printf '\n  ✅  ECB Data Portal    لا يحتاج مفتاحاً (وصول مفتوح)\n\n'
  if [ "$missing" -eq 0 ]; then
    printf 'كل المفاتيح موجودة. لم تُقرأ ولم تُعرض أي قيمة.\n'
    return 0
  fi
  printf 'بعض المفاتيح ناقصة. شغّلي السكربت بلا --check لضبطها.\n'
  return 1
}

configure_one() {
  local key="$1"
  local label
  label="$(prompt_for "$key")"

  printf '\n──────────────────────────────────────────────\n'
  printf '%s\n' "$key"
  printf '  %s\n' "$label"
  printf '  التسجيل: %s\n' "$(signup_for "$key")"

  if have_keychain && keychain_has "$key"; then
    printf '  الحالة: موجود بالفعل.\n'
    local answer=""
    printf '  استبداله؟ (y/N): '
    read -r answer || true
    case "$answer" in
      y|Y) ;;
      *) printf '  تُرك كما هو.\n'; return 0 ;;
    esac
  fi

  local value=""
  local confirm_value=""
  printf '  القيمة (لن تظهر على الشاشة): '
  read -rs value || true
  printf '\n'
  if [ -z "$value" ]; then
    printf '  ⚠️  قيمة فارغة — تُخطّى.\n'
    return 0
  fi
  printf '  أعيدي الإدخال للتأكيد: '
  read -rs confirm_value || true
  printf '\n'
  if [ "$value" != "$confirm_value" ]; then
    printf '  ⛔ القيمتان غير متطابقتين — لم يُحفظ شيء.\n' >&2
    return 1
  fi

  if ! have_keychain; then
    printf '  ⛔ Keychain غير متاح. لا يُكتب مفتاح في ملف داخل المستودع.\n' >&2
    return 1
  fi
  if keychain_store "$key" "$value"; then
    printf '  ✅ حُفظ في Keychain. لم تُطبع القيمة ولن تُقرأ ثانيةً من هنا.\n'
  else
    printf '  ⛔ تعذّر الحفظ في Keychain.\n' >&2
    return 1
  fi
  # لا تبقى القيمة في متغيّر بعد الحفظ.
  value=""
  confirm_value=""
  return 0
}

main() {
  if [ $# -gt 0 ] && [ "$1" = "--check" ]; then
    check_only
    return $?
  fi

  printf '\n'
  printf 'إعداد مفاتيح مزوّدي البيانات\n'
  printf '════════════════════════════\n'
  printf 'المفاتيح تُحفظ في Keychain وحدها.\n'
  printf '**لا تُلصَق أي قيمة في محادثة، ولا تدخل تطبيق الجوال، ولا تُودَع في git.**\n'
  printf 'ECB لا يحتاج مفتاحاً.\n'

  local targets="$ALL_KEYS"
  if [ $# -gt 0 ]; then
    targets=""
    for arg in "$@"; do
      case " $ALL_KEYS " in
        *" $arg "*) targets="$targets $arg" ;;
        *) printf '⛔ مفتاح غير معروف: %s\n' "$arg" >&2; return 2 ;;
      esac
    done
  fi

  local failed=0
  for key in $targets; do
    if ! configure_one "$key"; then
      failed=1
    fi
  done

  printf '\n──────────────────────────────────────────────\n'
  if [ "$failed" -eq 0 ]; then
    printf '✅ انتهى. تحقّقي بـ: python3 -m app.cli provider-status\n'
  else
    printf '⚠️  انتهى مع أخطاء. راجعي ما سبق.\n' >&2
  fi
  return "$failed"
}

main "$@"
