#!/usr/bin/env bash
# حارسُ ذاكرةِ البناء — **البناء لا يقع على القرص الداخلي، ولا يقع صامتاً.**
#
# ## لماذا وُجد
#
# القرصُ الداخلي بلغ 99% ممتلئاً، وذاكرةُ بناء Xcode وحدها 3.4 غيغا. ونقلُها
# إلى الوعاء الخارجي يحلّ المشكلة **بشرطٍ واحد**: ألّا يُنشئ أحدٌ بديلاً على
# الداخلي حين يكون الوعاء مفصولاً. فمسارٌ غائبٌ يُنشئه Xcode بلا سؤال، فيعود
# القرصُ إلى الامتلاء وأنت تظنّه على الخارجي — وهذا أسوأ من الفشل، لأن الفشل
# يُرى.
#
# فالحارس يفشل بوضوح ولا يخترع بديلاً. لا `mkdir -p` على الداخلي، ولا
# `|| DD=$HOME/...`، ولا صمت.
#
# ## ما يتحقّق منه
#
#   ١ · نقطةُ التركيب موجودة.
#   ٢ · `Volume UUID` يطابق الوعاء المعتمد — لا الاسم وحده: اسمُ «MATHRAH»
#       يمكن أن يحمله أيُّ وعاءٍ يُنشأ بالخطأ، والبصمةُ لا تُقلَّد.
#   ٣ · الوعاء قابلٌ للفصل (Removable) — أي ليس القرصَ الداخلي.
#   ٤ · قابلٌ للكتابة فعلاً — لا بالقراءة من `diskutil` بل بكتابةِ ملفٍّ.
#   ٥ · المسارُ النهائي يقع **على ذلك الوعاء بعينه** — يُقاس بجهاز الملف لا
#       بالنصّ: وصلةٌ رمزية تجعل المسار يبدو خارجياً وهو داخليّ.
#
# يُستدعى: `source scripts/derived_data_guard.sh` ثم `require_external_derived_data`
# ويُصدّر `MATHRAH_DERIVED_DATA` عند النجاح، ويخرج بـ1 عند الفشل.

MATHRAH_VOLUME="${MATHRAH_VOLUME:-/Volumes/MATHRAH}"
MATHRAH_VOLUME_UUID="${MATHRAH_VOLUME_UUID:-1BC3335A-DE1C-4E3B-9F53-3F98B4355EF0}"
MATHRAH_DERIVED_SUBPATH="${MATHRAH_DERIVED_SUBPATH:-DerivedData/MaatherTrader}"

_dd_fail() {
  echo "⛔ ذاكرةُ البناء الخارجية غير متاحة — ولا بديلَ على القرص الداخلي." >&2
  echo "   السبب: $1" >&2
  echo "" >&2
  echo "   الوعاء المعتمد: $MATHRAH_VOLUME" >&2
  echo "   البصمة:        $MATHRAH_VOLUME_UUID" >&2
  echo "" >&2
  echo "   لتشغيل البناء: صِلي قرص TOSHIBA وركّبي MATHRAH، ثم أعيدي الأمر." >&2
  echo "   لن يُنشأ مسارٌ على القرص الداخلي: إنشاؤه يعيد امتلاءه صامتاً." >&2
  return 1
}

require_external_derived_data() {
  # ١ · مركَّب؟
  if [ ! -d "$MATHRAH_VOLUME" ]; then
    _dd_fail "الوعاء غير مركَّب (لا يوجد $MATHRAH_VOLUME) — القرصُ مفصول على الأرجح."
    return 1
  fi

  # ٢ · البصمة — لا الاسم.
  local uuid
  uuid=$(diskutil info "$MATHRAH_VOLUME" 2>/dev/null | awk -F': *' '/Volume UUID/{print $2}' | tr -d ' \r')
  if [ -z "$uuid" ]; then
    _dd_fail "تعذّر قراءة بصمة الوعاء من diskutil."
    return 1
  fi
  if [ "$uuid" != "$MATHRAH_VOLUME_UUID" ]; then
    _dd_fail "بصمةُ الوعاء لا تطابق المعتمد (وجدتُ $uuid) — وعاءٌ آخر يحمل الاسم نفسه."
    return 1
  fi

  # ٣ · خارجيّ — لا الداخليّ متنكّراً.
  local removable
  removable=$(diskutil info "$MATHRAH_VOLUME" 2>/dev/null | awk -F': *' '/Removable Media/{print $2}' | tr -d ' \r')
  if [ "$removable" != "Removable" ]; then
    _dd_fail "الوعاء ليس قابلاً للفصل (Removable Media = ${removable:-غير معروف}) — لن أبني على الداخلي."
    return 1
  fi

  local target="$MATHRAH_VOLUME/$MATHRAH_DERIVED_SUBPATH"

  # ٤ · قابلٌ للكتابة فعلاً — بالكتابة لا بالادّعاء.
  if ! mkdir -p "$target" 2>/dev/null; then
    _dd_fail "تعذّر إنشاء $target — الوعاء للقراءة فقط أو ممتلئ."
    return 1
  fi
  local probe="$target/.write-probe.$$"
  if ! : > "$probe" 2>/dev/null; then
    _dd_fail "الوعاء لا يقبل الكتابة عند $target."
    return 1
  fi
  rm -f "$probe"

  # ٥ · المسارُ على ذلك الوعاء بعينه — يُقاس بجهاز الملف لا بنصّ المسار.
  local dev_target dev_volume
  dev_target=$(df "$target" 2>/dev/null | tail -1 | awk '{print $1}')
  dev_volume=$(df "$MATHRAH_VOLUME" 2>/dev/null | tail -1 | awk '{print $1}')
  if [ -z "$dev_target" ] || [ "$dev_target" != "$dev_volume" ]; then
    _dd_fail "المسار $target ليس على الوعاء ($dev_target ≠ $dev_volume) — وصلةٌ رمزية تخدع النصّ."
    return 1
  fi

  export MATHRAH_DERIVED_DATA="$target"
  echo "ذاكرةُ البناء: $MATHRAH_DERIVED_DATA · الوعاء $uuid · متاح $(df -h "$MATHRAH_VOLUME" | tail -1 | awk '{print $4}')"
  return 0
}
