#!/usr/bin/env bash
# بيئةُ البناء — **الكوميت يُثبَّت في التطبيق وقت بنائه.**
#
# بلا هذا كان التطبيق لا يحمل كوميتاً، ولا يمكن معرفة أي نسخةٍ على الجهاز
# ولا مقارنتها بالمنشور على الخادم. ورقمُ نسخةٍ بلا كوميت يجيب عن نصف
# السؤال: «أي إصدار» ولا يجيب «أي شيفرة».
#
# ومعه منذ 2026-09-05: **ذاكرةُ البناء على الوعاء الخارجي وحده.**
# القرصُ الداخلي بلغ 99%، وذاكرةُ Xcode وحدها 3.4 غيغا. والحارس يفشل بوضوح
# إن كان الوعاء مفصولاً، ولا يُنشئ بديلاً على الداخلي — لأنّ البديل الصامت
# يعيد الامتلاء وأنتِ تظنّينه على الخارجي.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

EXPO_PUBLIC_BUILD_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
EXPO_PUBLIC_BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export EXPO_PUBLIC_BUILD_COMMIT EXPO_PUBLIC_BUILD_TIME
echo "كوميت البناء: $EXPO_PUBLIC_BUILD_COMMIT · $EXPO_PUBLIC_BUILD_TIME"

# shellcheck source=scripts/derived_data_guard.sh
source "$(dirname "${BASH_SOURCE[0]}")/derived_data_guard.sh"
require_external_derived_data || exit 1

exec "$@"
