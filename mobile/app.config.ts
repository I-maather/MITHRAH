import type { ExpoConfig } from 'expo/config';

/**
 * إعداد التطبيق — المصدر الوحيد لمعرّف الحزمة وعنوان الخادم.
 *
 * SINGLE SOURCE OF TRUTH.
 * The bundle identifier and the backend URL are declared here once and read at
 * runtime through `expo-constants` (`src/api/config.ts`). They are never
 * repeated anywhere else in the source tree.
 *
 * NOTHING IN THIS FILE IS A SECRET.
 * The app holds no broker credentials, no provider API keys, no push signing
 * key and no database URL. Every one of those lives on the FastAPI backend and
 * never reaches the device. See README.md § "ما لا يملكه التطبيق".
 */

/** معرّف الحزمة المبدئي — لم يُسجَّل لدى Apple بعد. */
const PROVISIONAL_BUNDLE_ID = 'com.maather.autonomoustrader';

/**
 * العنوان الافتراضي للخادم: حلقة محلية فقط.
 * A private/loopback placeholder on purpose. The owner points this at their own
 * backend at build time via `EXPO_PUBLIC_API_BASE_URL`. No public host is ever
 * baked into the source.
 */
const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';

const bundleIdentifier =
  process.env.EXPO_PUBLIC_IOS_BUNDLE_ID ?? PROVISIONAL_BUNDLE_ID;

const apiBaseUrl = process.env.EXPO_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;

/** دقائق الخمول قبل القفل التلقائي. */
const autoLockMinutes = Number(process.env.EXPO_PUBLIC_AUTO_LOCK_MINUTES ?? '2');

/** تفعيل بيانات المعاينة صراحةً (وسوم «معاينة» تظهر في الواجهة). */
const previewData = process.env.EXPO_PUBLIC_PREVIEW_DATA === '1';

/**
 * الإشعارات الفورية — **معطّلة افتراضاً**، وتُفعَّل بـ`EXPO_PUBLIC_ENABLE_PUSH=1`.
 *
 * ## لماذا العكس هو الخطأ
 *
 * كانت مُعلَنة دائماً. فسقط التوقيع على جهاز المالكة برسالة صريحة:
 *
 *     Personal development teams do not support the Push Notifications
 *     capability.
 *
 * الحساب المجاني (Personal Team) لا يصدر ملف تزويد يحمل استحقاق APNs. فكانت
 * النتيجة أن التطبيق **لا يعمل على الجهاز أصلاً** بسبب ميزة لا تعمل هي
 * الأخرى ولن تعمل قبل عضوية مدفوعة.
 *
 * والحذف اليدوي من Xcode لا يكفي: `expo prebuild --clean` يعيد توليد
 * `ios/` من هذا الملف، فيعود العائق عند أول إعادة بناء. مكان الإصلاح هنا.
 *
 * وحين تُشترى العضوية ويُنشأ مفتاح APNs، يُصدَّر المتغيّر ويعود كل شيء بلا
 * تغيير في الكود:
 *
 *     EXPO_PUBLIC_ENABLE_PUSH=1 ./scripts/ios_build_prep.sh
 */
const enablePush = process.env.EXPO_PUBLIC_ENABLE_PUSH === '1';

const config: ExpoConfig = {
  name: 'Maather Trader',
  slug: 'maather-trader',
  version: '0.4.0',
  orientation: 'portrait',
  scheme: 'maather',
  userInterfaceStyle: 'automatic',
  icon: './assets/icon.png',
  splash: {
    image: './assets/splash.png',
    resizeMode: 'contain',
    backgroundColor: '#3A0CA3',
  },
  assetBundlePatterns: ['**/*'],
  platforms: ['ios'],
  ios: {
    bundleIdentifier,
    buildNumber: '1',
    supportsTablet: false,
    // الوصول للشبكة يمرّ بـTLS. لا استثناء عام.
    infoPlist: {
      NSFaceIDUsageDescription:
        'يُستعمل Face ID لفتح تطبيق مآثر على هذا الجهاز. هو بوابة وصول محلية ولا يأذن بأي تنفيذ.',
      ITSAppUsesNonExemptEncryption: false,
      NSAppTransportSecurity: {
        // TLS مفروض. الاستثناء الوحيد هو الشبكة المحلية أثناء التطوير،
        // وهو ما تسمح به Apple دون فتح الإنترنت العام.
        NSAllowsArbitraryLoads: false,
        NSAllowsLocalNetworking: true,
      },
      // إشعارات صامتة غير مطلوبة: الإشعار **استشاري** ولا يُشغّل عملاً في
      // الخلفية. `remote-notification` وحدها، وبلا `fetch` ولا `processing`.
      // ولا تُعلَن إن كانت الإشعارات معطّلة — وضعُ مفتاح خلفية بلا استحقاق
      // يقابله يجعل الإعلان كذبةً على النظام.
      ...(enablePush ? { UIBackgroundModes: ['remote-notification'] } : {}),
    },
    // قالب الاستحقاقات. **لم يُنشَأ أي App ID ولا مفتاح APNs بعد** —
    // القيمة `development` صالحة للبناء المحلي، وتتحوّل إلى `production`
    // عند أول رفع إلى TestFlight.
    ...(enablePush ? { entitlements: { 'aps-environment': 'development' } } : {}),
  },
  plugins: [
    'expo-router',
    // للحصول على **رمز الجهاز الأصلي** فقط. التسليم يتم من الخادم مباشرةً
    // إلى APNs، لا عبر خدمة ترحيل Expo.
    //
    // مشروط أيضاً: هذا الملحق **يحقن `aps-environment` بنفسه** في
    // الاستحقاقات. فحذف الاستحقاق من كتلة `ios` وحده لا يكفي — قياسٌ
    // بـ`expo config --type introspect` أظهر أنه يعود من هنا.
    ...(enablePush
      ? ([
          [
            'expo-notifications',
            {
              icon: './assets/icon.png',
              color: '#3A0CA3',
            },
          ],
        ] as NonNullable<ExpoConfig['plugins']>)
      : // يعمل **بعد** الجميع فيحذف ما حقنه الربط التلقائي. انظر الملف نفسه.
        (['./plugins/with-push-disabled'] as NonNullable<ExpoConfig['plugins']>)),
    [
      'expo-local-authentication',
      {
        faceIDPermission:
          'يُستعمل Face ID لفتح تطبيق مآثر على هذا الجهاز. هو بوابة وصول محلية ولا يأذن بأي تنفيذ.',
      },
    ],
    [
      'expo-splash-screen',
      {
        image: './assets/splash.png',
        backgroundColor: '#3A0CA3',
        dark: { backgroundColor: '#3A0CA3' },
        imageWidth: 180,
      },
    ],
  ],
  experiments: {
    typedRoutes: true,
  },
  extra: {
    apiBaseUrl,
    bundleIdentifier,
    autoLockMinutes: Number.isFinite(autoLockMinutes) ? autoLockMinutes : 2,
    previewData,
    /**
     * ثابت صريح يُختبَر: التطبيق **لا يأذن بتنفيذ**.
     * The server repeats this in every response body; the client refuses any
     * payload where it is not `false`.
     */
    authorisesExecution: false,
  },
};

export default config;
