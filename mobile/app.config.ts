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

/**
 * تفعيل بيانات المعاينة — **صراحةً وحدها**. لا يُفعّلها كون البناء تطويرياً:
 * وضعُ المعاينة يمنع طلب الشبكة، فبناءُ التطوير كان لا يصل إلى الخادم أبداً.
 */
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

/**
 * نسخةُ التطبيق وكوميتُه — **يُثبَّتان وقت البناء ويُعرضان في شاشة النظام.**
 *
 * كان `app.config.ts` يقول `0.4.0` و`package.json` يقول `0.6.1`، ولا كوميت
 * في التطبيق إطلاقاً. فلم يكن ممكناً أن تُعرف أي نسخةٍ على الجهاز، ولا أن
 * يُقارَن ما في اليد بما نُشر. ورقمان متناقضان أسوأ من رقمٍ واحد خاطئ:
 * كلاهما يُقرأ على أنه الحقيقة.
 *
 * المصدر الآن `package.json` وحده، والكوميت يأتي من البيئة وقت البناء.
 */
// eslint-disable-next-line @typescript-eslint/no-var-requires
const appVersion: string = require('./package.json').version;
const buildNumber: string = process.env.EXPO_PUBLIC_BUILD_NUMBER ?? '2';
const buildCommit: string = process.env.EXPO_PUBLIC_BUILD_COMMIT ?? 'unknown';
const buildTime: string = process.env.EXPO_PUBLIC_BUILD_TIME ?? 'unknown';
/** بيئةُ التداول — تُثبَّت وقت البناء وتُعرض. لا يُبنى إصدارٌ بلا إعلانها. */
const tradingEnvironment: string =
  process.env.EXPO_PUBLIC_TRADING_ENVIRONMENT ?? 'UNSET';

/**
 * **حارسٌ على العنوان.** الافتراضي `http://127.0.0.1:8000` يعني على الجوال
 * الجوالَ نفسه — أي تطبيقٌ يُبنى فلا يصل إلى شيء، ويُقرأ صمتُه على أنه
 * «لا بيانات». يُمنع البناء به إلا في التطوير.
 */
/**
 * **حرّاسُ البناء.** إصدارٌ قابلٌ للتثبيت لا يُبنى ناقصاً.
 *
 * كل واحدٍ منها أُضيف عن سببٍ لا عن احتياط:
 *  · `127.0.0.1` على الجوال تعني الجوالَ نفسه — تطبيقٌ لا يصل إلى شيء،
 *    ويُقرأ صمتُه على أنه «لا بيانات».
 *  · عنوانٌ غائب: الشيء نفسه بصورةٍ أوضح.
 *  · بيئةُ تداولٍ غير معلَنة: شاشةٌ لا تقول DEMO أو REAL خطرٌ لا التباس.
 *  · كوميتٌ مجهول: نسخةٌ على الجهاز لا تُقارَن بما نُشر على الخادم — وهو
 *    ما وقع فعلاً: `app.config` يقول 0.4.0 و`package.json` يقول 0.6.1
 *    ولا كوميت في التطبيق إطلاقاً.
 *
 * وتُرفَع في بناء الإصدار وحده؛ التطويرُ يمرّ.
 */
const isReleaseBuild =
  process.env.NODE_ENV === 'production' || process.env.EXPO_PUBLIC_RELEASE === '1';

if (isReleaseBuild) {
  const faults: string[] = [];
  if (!process.env.EXPO_PUBLIC_API_BASE_URL) {
    faults.push('EXPO_PUBLIC_API_BASE_URL غير مضبوط.');
  }
  if (apiBaseUrl.includes('127.0.0.1') || apiBaseUrl.includes('localhost')) {
    faults.push('عنوان الخادم حلقةٌ محلية — لا يصل إليه الجوال.');
  }
  if (tradingEnvironment !== 'DEMO' && tradingEnvironment !== 'REAL') {
    faults.push('EXPO_PUBLIC_TRADING_ENVIRONMENT يجب أن تكون DEMO أو REAL.');
  }
  if (buildCommit === 'unknown') {
    faults.push('كوميت البناء مجهول — شغّلي البناء عبر scripts/build_env.sh.');
  }
  if (faults.length > 0) {
    throw new Error('بناءٌ ناقص:\n  - ' + faults.join('\n  - '));
  }
}

const config: ExpoConfig = {
  name: 'Maather Trader',
  slug: 'maather-trader',
  version: appVersion,
  /**
   * **التحديثُ عبر الهواء — وهو ما أنهى الارتباطَ بالماك.**
   *
   * لم يكن `expo-updates` في المشروع قطّ، فكان كلُّ إصلاحٍ — ولو كلمةً
   * في رسالة — يحتاج بناءً كاملاً على ماك المالكة بXcode وقرصٍ خارجي.
   * وذلك لم يكن قدراً بل نقصَ إعداد.
   *
   * و`runtimeVersion` حارسٌ لا زينة: يمنعُ وصولَ تحديثٍ لا يوافق
   * الشِفرةَ الأصليةَ في الحزمة. وبدونه قد يطيرُ تحديثٌ يعتمدُ وحدةً
   * أصليةً غائبةً فينهار التطبيقُ عند الفتح — وهو بالضبط ما وقع في
   * ١٦ سبتمبر ٢٠٢٦ حين بُنيت الحزمةُ بلا `pod install`.
   *
   * و`fallbackToCacheTimeout: 0` كي لا ينتظرَ الفتحُ الشبكةَ.
   */
  updates: {
    url: 'https://u.expo.dev/9e7251fa-2602-4946-8902-46bad895b3f9',
    fallbackToCacheTimeout: 0,
  },
  runtimeVersion: { policy: 'appVersion' },
  orientation: 'portrait',
  scheme: 'maather',
  userInterfaceStyle: 'automatic',
  icon: './assets/icon.png',
  splash: {
    image: './assets/splash.png',
    resizeMode: 'contain',
    backgroundColor: '#0B0A0A',
  },
  assetBundlePatterns: ['**/*'],
  platforms: ['ios'],
  ios: {
    bundleIdentifier,
    buildNumber,
    supportsTablet: false,
    // الوصول للشبكة يمرّ بـTLS. لا استثناء عام.
    infoPlist: {
      NSFaceIDUsageDescription:
        'يُستعمل Face ID لفتح تطبيق مآثر على هذا الجهاز. هو بوابة وصول محلية ولا يأذن بأي تنفيذ.',
      // الكاميرا لقراءة رمز الاقتران وحده. لا تُلتقط صور ولا تُرفع.
      NSCameraUsageDescription:
        'تُستعمل الكاميرا لقراءة رمز اقتران الجهاز مرة واحدة. لا تُلتقط صور ولا يُرسَل شيء منها.',
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
    // الخطوط تُحمَّل وقت التشغيل عبر `useFonts`؛ وهذا الملحق يُضمّنها أصلياً
    // عند `prebuild` فتُرسَم من أول إطار بلا تحميل. الاثنان يعملان معاً.
    'expo-font',
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
              color: '#0B0A0A',
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
        backgroundColor: '#0B0A0A',
        dark: { backgroundColor: '#0B0A0A' },
        imageWidth: 180,
      },
    ],
  ],
  experiments: {
    typedRoutes: true,
  },
  extra: {
    /** يربطُ الحزمةَ بمشروع Expo — يُكتَب يداً لأنّ الإعدادَ TypeScript. */
    eas: { projectId: '9e7251fa-2602-4946-8902-46bad895b3f9' },
    apiBaseUrl,
    bundleIdentifier,
    appVersion,
    buildNumber,
    buildCommit,
    buildTime,
    tradingEnvironment,
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
