#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
#  حارسُ الوعاء — يُصدَّر قبل أيّ عملٍ يكتب في المستودع.
#
#  المستودع العامل يعيش على وعاء APFS خارجي. والوعاء **يُفصَل حين ينام
#  الماك**. فالخطر ليس أن يتوقّف العمل — الخطر أن يستمرّ: أن تُنشئ أداةٌ
#  مجلداً داخلياً بالاسم نفسه فتصير نسختان تتباعدان بصمت، ولا يُعرف أيُّهما
#  الحقّ إلا بعد ضياع عمل. لذلك هذا الحارس **يفشل بصوتٍ عالٍ ولا يبتكر
#  بديلاً أبداً**.
#
#  الاستعمال:  . scripts/mathrah_mount.sh   أو   bash scripts/mathrah_mount.sh
# ─────────────────────────────────────────────────────────────────────
MATHRAH_VOL="${MATHRAH_VOL:-/Volumes/MATHRAH}"
MATHRAH_IMG="${MATHRAH_IMG:-/Volumes/TOSHIBA/MATHRAH-XL.sparsebundle}"
MATHRAH_REPO="${MATHRAH_REPO:-$HOME/Developer/Maather-Autonomous-Trader}"
MATHRAH_LINKS="$MATHRAH_REPO $HOME/Desktop/Trading/Maather-Autonomous-Trader"

_m_die() { echo "⛔ حارس الوعاء: $*" >&2; return 1; }

mathrah_ensure_mount() {
  # ١ · لا مجلدٌ داخليّ بديل. المسار رابطٌ رمزي أو لا شيء.
  for lnk in $MATHRAH_LINKS; do
    if [ -e "$lnk" ] && [ ! -L "$lnk" ]; then
      _m_die "«$lnk» صار مجلداً حقيقياً على القرص الداخلي.
     نسخةٌ ثانية صامتة أخطرُ من التوقّف. لا أكتب شيئاً.
     افحصيه يدوياً وقرّري أيُّهما الحقّ قبل أيّ عمل." || return 1
    fi
  done

  # ٢ · التركيب عند الحاجة — محاولاتٌ محدودة، بلا التفاف.
  if [ ! -d "$MATHRAH_VOL" ]; then
    [ -e "$MATHRAH_IMG" ] || { _m_die "الوعاء «$MATHRAH_IMG» غير موجود — القرص الخارجي مفصول؟"; return 1; }
    for _i in 1 2 3; do
      hdiutil attach "$MATHRAH_IMG" -nobrowse >/dev/null 2>&1
      [ -d "$MATHRAH_VOL" ] && break
      sleep 3
    done
  fi
  [ -d "$MATHRAH_VOL" ] || { _m_die "تعذّر تركيب «$MATHRAH_VOL». لا عمل."; return 1; }

  # ٣ · أهو الوعاء الصحيح؟ الاسمُ وحده لا يكفي — البصمة تفصل.
  local want have
  want="$(cat "$MATHRAH_REPO/.mathrah-expected-volume" 2>/dev/null)"
  have="$(cat "$MATHRAH_VOL/.mathrah-volume" 2>/dev/null)"
  if [ -n "$want" ] && [ "$want" != "$have" ]; then
    _m_die "وعاءٌ بالاسم نفسه وبصمةٍ مختلفة.
     المتوقَّع: $want
     الموجود : ${have:-—}
     لا أكتب في وعاءٍ لا أعرفه." || return 1
  fi

  # ٤ · أهو خارجيّ فعلاً؟ فالغرض كلّه ألّا يُثقَل الداخلي.
  local dev loc
  dev="$(df "$MATHRAH_VOL" 2>/dev/null | tail -1 | awk '{print $1}')"
  loc="$(diskutil info "$dev" 2>/dev/null | awk -F: '/Device Location/{gsub(/^ +/,"",$2); print $2}')"
  [ "$loc" = "External" ] || { _m_die "«$MATHRAH_VOL» ليس على قرصٍ خارجي (الموقع: ${loc:-مجهول})."; return 1; }

  # ٥ · وهل المستودع نفسه عليه؟
  local real
  real="$(cd "$MATHRAH_REPO" 2>/dev/null && pwd -P)"
  case "$real" in
    "$MATHRAH_VOL"/*) : ;;
    *) _m_die "المستودع يقود إلى «${real:-لا شيء}» لا إلى الوعاء. لا كتابة."; return 1 ;;
  esac
  [ -d "$MATHRAH_REPO/.git" ] || { _m_die "لا «.git» في المستودع."; return 1; }
  return 0
}

mathrah_require() {
  mathrah_ensure_mount || {
    echo "⛔ العمل موقوف: المستودع العامل غير متاح." >&2
    echo "   وصّلي القرص الخارجي، أو ركّبي الوعاء، ثم أعيدي المحاولة." >&2
    return 1
  }
  return 0
}

# التشغيل المباشر يفحص ويُبلّغ
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  if mathrah_require; then
    echo "✅ الوعاء متاح وصحيح: $MATHRAH_VOL"
    echo "   المستودع: $(cd "$MATHRAH_REPO" && pwd -P)"
    echo "   المساحة: $(df -h "$MATHRAH_VOL" | tail -1 | awk '{print $4}') متاحة"
    exit 0
  fi
  exit 1
fi
