#!/usr/bin/env python3
"""
بوابة الفحص الأمني — تحكم بالقابلية للوصول لا بالعدد.

## لماذا لا يكفي «صفر ثغرات»

`npm audit` في مشروع Expo يبلّغ عن أدوات البناء كما يبلّغ عن كود التطبيق، ولا
يفرّق. و`--omit=dev` لا يحلّ ذلك: `expo` و`react-native` **تبعيتا إنتاج** في
`package.json`، وتجرّان معهما Metro وCLI وprebuild — وكلها لا تدخل حزمة
الآيفون ولا تُنفَّذ على الهاتف أبداً.

فاشتراط صفر يعني إمّا ترقية كاسرة لكل SDK عند كل تنبيه، أو تجاهل الفحص كلياً.
والاثنان سيّئان.

## القاعدة هنا

    تُرفَض أي ثغرة `critical` أو `high` **ليست** في قائمة أدوات البناء
    الموثَّقة أدناه.

القائمة ليست إعفاءً مفتوحاً: كل اسم فيها أُثبت غيابه من حزمة التطبيق
المُصدَّرة فعلاً — بتصدير الحزمة وقراءة خريطة مصدرها، لا بالافتراض. الطريقة
موثَّقة في `docs/MOBILE_DEPENDENCY_AUDIT.md` وقابلة لإعادة التشغيل.

أي حزمة جديدة تظهر بـcritical/high تُسقط البوابة حتى يُثبَت أنها غير واصلة
وتُضاف هنا **بقرار موثَّق**.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

#: حزم أُثبت — بقراءة خريطة مصدر الحزمة المُصدَّرة — أنها لا تدخل تطبيق iOS.
#: كلها أدوات بناء أو تطوير: مُجمِّع، أو CLI، أو مولّد مشروع أصلي، أو اختبار.
BUILD_ONLY_PROVEN_ABSENT: frozenset[str] = frozenset({
    # سلسلة Metro (المُجمِّع) — تعمل على الماك وقت البناء
    "metro", "metro-config", "metro-transform-worker", "image-size",
    "@react-native/community-cli-plugin",
    # واجهات سطر الأوامر ومولّد المشروع الأصلي
    "@react-native-community/cli", "@react-native-community/cli-doctor",
    "@react-native-community/cli-hermes",
    "@react-native-community/cli-platform-android",
    "@react-native-community/cli-platform-apple",
    "@react-native-community/cli-platform-ios",
    "@expo/cli", "@expo/config", "@expo/config-plugins", "@expo/metro-config",
    "@expo/plist", "@expo/prebuild-config", "@expo/bunyan",
    "@expo/rudder-sdk-node", "xcode", "cacache", "tar", "send",
    # أدوات اختبار وترجمة
    "jest-expo", "@babel/core",
    # مسار الخادم في expo-router — غير مستعمل في تطبيق أصلي
    "turbo-stream", "@remix-run/node", "@remix-run/server-runtime",
    # صيغ ملفات تُقرأ وقت البناء وحده
    "@xmldom/xmldom", "fast-xml-parser", "postcss", "uuid",
})

#: الحزم الجذرية التي يرفع npm إليها خطورة تبعياتها. وجودها في التقرير
#: **انعكاس** لأداة بناء تحتها، لا ثغرة في كودها هي.
UMBRELLA_PACKAGES: frozenset[str] = frozenset({
    "react-native", "expo", "expo-router", "expo-constants", "expo-linking",
    "expo-notifications", "expo-splash-screen", "expo-asset",
})

BLOCKING = {"critical", "high"}


def main(path: str) -> int:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⛔ تعذّرت قراءة تقرير الفحص: {type(exc).__name__}", file=sys.stderr)
        return 1

    vulnerabilities = report.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        print("⛔ شكل تقرير الفحص غير متوقَّع.", file=sys.stderr)
        return 1

    allowed = BUILD_ONLY_PROVEN_ABSENT | UMBRELLA_PACKAGES
    unexpected: list[tuple[str, str]] = []
    for name, entry in vulnerabilities.items():
        severity = str(entry.get("severity", "unknown"))
        if severity not in BLOCKING:
            continue
        if name in allowed:
            continue
        unexpected.append((severity, name))

    if unexpected:
        print("⛔ ثغرات critical/high **غير موثَّقة** كأدوات بناء:", file=sys.stderr)
        for severity, name in sorted(unexpected):
            print(f"     {severity:9} {name}", file=sys.stderr)
        print(
            "\n   لكل واحدة: إمّا ترقيتها، أو إثبات غيابها من حزمة التطبيق\n"
            "   (npx expo export --no-bytecode --source-maps ثم فحص خريطة المصدر)\n"
            "   ثم إضافتها هنا بقرار موثَّق. **لا تُضاف بلا إثبات.**",
            file=sys.stderr,
        )
        return 1

    blocking_count = sum(
        1 for e in vulnerabilities.values() if str(e.get("severity")) in BLOCKING
    )
    print(f"   ({blocking_count} تنبيهاً critical/high، كلها أدوات بناء موثَّقة)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "audit.json"))
