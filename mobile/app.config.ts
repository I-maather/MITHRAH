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
    backgroundColor: '#0D0F11',
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
      UIBackgroundModes: ['remote-notification'],
    },
    // قالب الاستحقاقات. **لم يُنشَأ أي App ID ولا مفتاح APNs بعد** —
    // القيمة `development` صالحة للبناء المحلي، وتتحوّل إلى `production`
    // عند أول رفع إلى TestFlight.
    entitlements: {
      'aps-environment': 'development',
    },
  },
  plugins: [
    'expo-router',
    // للحصول على **رمز الجهاز الأصلي** فقط. التسليم يتم من الخادم مباشرةً
    // إلى APNs، لا عبر خدمة ترحيل Expo.
    [
      'expo-notifications',
      {
        icon: './assets/icon.png',
        color: '#0D0F11',
      },
    ],
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
        backgroundColor: '#0D0F11',
        dark: { backgroundColor: '#0D0F11' },
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
