#!/usr/bin/env bash
#
# يبني أرشيف تسليم/تصحيح **خالياً من أي ملف خاص**.
#
#   ./scripts/make_delivery_archive.sh [اسم-الأرشيف.tar.gz]
#
# لماذا سكربت بدل أمر tar يدوي:
#   نسيان استثناء واحد يكفي لتسريب رصيد الحساب في أرشيف يُرسَل أو يُرفع.
#   الاستثناءات هنا مكتوبة مرة واحدة، والسكربت **يتحقق بعد البناء** أن الأرشيف
#   لا يحتوي أي مسار خاص، ويحذفه ويفشل إن احتوى.
#
# التوافق: bash 3.2 فأحدث (إصدار macOS الافتراضي).

set -euo pipefail
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-maather-delivery.tar.gz}"

# مسارات لا تدخل أي أرشيف — بأي حال.
EXCLUDES=(
  --exclude=data
  --exclude=data/private
  --exclude=secrets
  --exclude=.env
  --exclude='*.pem'
  --exclude='*.key'
  --exclude='*.db'
  --exclude='*.sqlite3'
  --exclude=node_modules
  --exclude=.venv
  --exclude=venv
  --exclude=__pycache__
  --exclude='*.pyc'
  --exclude=.next
  --exclude=.pytest_cache
  --exclude=backups
)

cd "$(dirname "$REPO_ROOT")"
PROJECT="$(basename "$REPO_ROOT")"

tar "${EXCLUDES[@]}" -czf "$OUTPUT" "$PROJECT"

# التحقق بعد البناء: لا مسار خاص داخل الأرشيف.
LEAKED="$(tar -tzf "$OUTPUT" | grep -E '(^|/)(data/private|secrets)/|\.env$|\.pem$|\.key$' || true)"
if [ -n "$LEAKED" ]; then
  rm -f "$OUTPUT"
  echo "⛔ الأرشيف احتوى مسارات خاصة — حُذف ولم يُسلَّم:" >&2
  echo "$LEAKED" >&2
  exit 1
fi

echo "✅ الأرشيف جاهز وخالٍ من أي مسار خاص: $OUTPUT"
