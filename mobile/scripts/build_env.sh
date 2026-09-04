#!/usr/bin/env bash
# بيئةُ البناء — **الكوميت يُثبَّت في التطبيق وقت بنائه.**
#
# بلا هذا كان التطبيق لا يحمل كوميتاً، ولا يمكن معرفة أي نسخةٍ على الجهاز
# ولا مقارنتها بالمنشور على الخادم. ورقمُ نسخةٍ بلا كوميت يجيب عن نصف
# السؤال: «أي إصدار» ولا يجيب «أي شيفرة».
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
EXPO_PUBLIC_BUILD_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
EXPO_PUBLIC_BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export EXPO_PUBLIC_BUILD_COMMIT EXPO_PUBLIC_BUILD_TIME
echo "كوميت البناء: $EXPO_PUBLIC_BUILD_COMMIT · $EXPO_PUBLIC_BUILD_TIME"
exec "$@"
