#!/usr/bin/env python3
"""
بوابة الفحص الأمني — تحكم بالقابلية للوصول لا بالعدد.

## لماذا لا يكفي «صفر ثغرات»

`npm audit` في مشروع Expo يبلّغ عن أدوات البناء كما يبلّغ عن كود التطبيق، ولا
يفرّق. و`--omit=dev` لا يحلّ ذلك: `expo` و`react-native` **تبعيتا إنتاج** في
`package.json`، وتجرّان معهما Metro وCLI وprebuild — وكلها لا تدخل حزمة
الآيفون ولا تُنفَّذ على الهاتف أبداً.

## ولماذا لا تُطارَد الأرقام بـoverrides

جُرّب ذلك وفشل فشلاً مكلفاً. سبعة `overrides` خفضت العدد من 40 إلى 6، وكلها
السبعة رفعت حزمة **خارج النطاق الذي يعلنه مستهلكها**، وإحداها كسرت
`expo prebuild` تماماً: `@expo/cli` يعلن `tar: ^6.0.5`، وtar 7 لا يصدّر
`default`، فصار `_tar().default.extract` قراءةً من `undefined`.

الدرس: على حزمة **لا تُشحَن أصلاً**، الترقية القسرية لا تشتري أماناً — تشتري
رقماً، وتدفع ثمنه بناءً مكسوراً. فالمعيار هنا ليس الرقم:

    تُرفَض أي ثغرة `critical` أو `high` لم يُثبَت غيابها من حزمة التطبيق.

الإثبات شرط لا ادّعاء: كل اسم أدناه أُثبت غيابه بتصدير الحزمة وقراءة خريطة
مصدرها. الطريقة موثَّقة في `docs/MOBILE_DEPENDENCY_AUDIT.md` وقابلة لإعادة
التشغيل.

## الحرج يُعامَل وحده

الحرج **لا يمرّ عبر قائمة عامة**. لكل ثغرة حرجة مقبولة سطرٌ باسمها وسببها
هنا، كي يستحيل أن تنزلق واحدة جديدة داخل تصنيف واسع.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

#: ثغرات **حرجة** مقبولة، كلٌّ بسببها. القبول فردي لا بالفئة.
CRITICAL_ACCEPTED: dict[str, str] = {
    "tar": (
        "أداة بناء. تستعملها @expo/cli مرة واحدة لفكّ قالب Expo الرسمي "
        "المنزَّل من registry.npmjs.org عبر HTTPS وبمجموع تحقّق — لا أرشيف "
        "من مصدر خارجي. التصحيح لا يوجد إلا في tar 7، و@expo/cli تعلن "
        "^6.0.5 وتستدعي واجهة CommonJS التي حذفتها 7 (أُثبت: كسرت prebuild). "
        "غائبة عن حزمة iOS بالقياس."
    ),
}

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
    "@expo/rudder-sdk-node", "xcode", "cacache", "send",
    # أدوات اختبار وترجمة
    "jest-expo", "@babel/core",
    # مسار الخادم في expo-router — غير مستعمل في تطبيق أصلي
    "turbo-stream", "@remix-run/node", "@remix-run/server-runtime",
    # صيغ ملفات تُقرأ وقت البناء وحده
    "@xmldom/xmldom", "fast-xml-parser", "postcss", "uuid", "plist",
})

#: الحزم الجذرية التي يرفع npm إليها خطورة تبعياتها. وجودها في التقرير
#: **انعكاس** لأداة بناء تحتها، لا ثغرة في كودها هي. ويُتحقَّق من ذلك بنيوياً
#: أدناه: حقل `via` لا يحوي كائن تحذير، بل أسماء حزم فقط.
UMBRELLA_PACKAGES: frozenset[str] = frozenset({
    "react-native", "expo", "expo-router", "expo-constants", "expo-linking",
    "expo-notifications", "expo-splash-screen", "expo-asset",
})

BLOCKING = {"critical", "high"}


def _carries_own_advisory(entry: dict) -> bool:
    """
    الحزمة تحمل تحذيراً خاصاً بها متى احتوى `via` **كائن تحذير**. أما إن
    احتوى أسماء حزم فقط فهي «مظلّة»: مُعلَّمة بسبب ما تحتها لا بسبب كودها.
    """
    return any(isinstance(item, dict) for item in entry.get("via", []))


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

    blocked_critical: list[str] = []
    blocked_high: list[str] = []
    #: مظلّة ادّعت أنها مظلّة ثم ظهر لها تحذير خاص — لا تُقبل بصفتها القديمة.
    umbrella_now_vulnerable: list[str] = []

    for name, entry in vulnerabilities.items():
        severity = str(entry.get("severity", "unknown"))
        if severity not in BLOCKING:
            continue

        if name in UMBRELLA_PACKAGES:
            if _carries_own_advisory(entry):
                umbrella_now_vulnerable.append(f"{severity:9} {name}")
            continue

        if severity == "critical":
            if name not in CRITICAL_ACCEPTED:
                blocked_critical.append(name)
            continue

        if name not in BUILD_ONLY_PROVEN_ABSENT:
            blocked_high.append(name)

    if blocked_critical or blocked_high or umbrella_now_vulnerable:
        print("⛔ الفحص الأمني أسقط البناء:", file=sys.stderr)
        for name in sorted(blocked_critical):
            print(f"     critical  {name}  ← لا سطر قبول باسمها", file=sys.stderr)
        for name in sorted(blocked_high):
            print(f"     high      {name}  ← غير موثَّقة كأداة بناء", file=sys.stderr)
        for line in sorted(umbrella_now_vulnerable):
            print(f"     {line}  ← «مظلّة» صار لها تحذير خاص بها", file=sys.stderr)
        print(
            "\n   لكل واحدة: إمّا ترقيتها **داخل النطاق الذي يعلنه مستهلكها**،\n"
            "   أو إثبات غيابها من حزمة التطبيق:\n"
            "     npx expo export --platform ios --no-bytecode --source-maps\n"
            "   ثم فحص `sources[]` في خريطة المصدر، ثم إضافتها هنا بقرار\n"
            "   موثَّق. **لا تُضاف بلا إثبات، ولا تُرفَع بـoverride كاسر.**",
            file=sys.stderr,
        )
        return 1

    critical_count = sum(
        1 for e in vulnerabilities.values() if str(e.get("severity")) == "critical"
    )
    high_count = sum(
        1 for e in vulnerabilities.values() if str(e.get("severity")) == "high"
    )
    print(
        f"   ({critical_count} حرجة و{high_count} عالية — كلها موثَّقة "
        "كأدوات بناء غائبة عن حزمة التطبيق)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "audit.json"))
