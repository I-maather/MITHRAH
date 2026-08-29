/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * تهيئة الاختبارات.
 *
 * كل وحدة أصلية تُقلَّد هنا بأبسط سلوك صحيح، كي تكون الاختبارات عن **منطق
 * التطبيق** لا عن الجسر الأصلي. القاعدة: المُقلِّد لا يكون أكثر تساهلاً من
 * الأصل — سلسلة المفاتيح المُقلَّدة ترفض المفاتيح غير المُعلَنة تماماً كما
 * ترفضها الطبقة الحقيقية.
 */
import '@testing-library/react-native/extend-expect';
// يُستورَد في الأعلى لا داخل الخطّاف: هذه الحزمة تسجّل خطّافات تنظيف عند
// استيرادها، و`jest-circus` يرفض إضافة خطّاف بعد بدء التشغيل.
import { render as renderForWarmup } from '@testing-library/react-native';

// -- expo-constants ---------------------------------------------------------
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: {
    expoConfig: {
      version: '0.1.0',
      ios: { bundleIdentifier: 'com.maather.autonomoustrader' },
      extra: {
        apiBaseUrl: 'http://127.0.0.1:8000',
        bundleIdentifier: 'com.maather.autonomoustrader',
        autoLockMinutes: 2,
        previewData: false,
        authorisesExecution: false,
      },
    },
  },
}));

// -- expo-secure-store ------------------------------------------------------
// خزنة في الذاكرة. تُصدَّر لتفتيشها في اختبار التخزين.
const mockSecureStoreMemory = new Map<string, string>();
(globalThis as any).__secureStoreMemory = mockSecureStoreMemory;

jest.mock('expo-secure-store', () => ({
  __esModule: true,
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY',
  setItemAsync: jest.fn(async (key: string, value: string) => {
    mockSecureStoreMemory.set(key, value);
  }),
  getItemAsync: jest.fn(async (key: string) => mockSecureStoreMemory.get(key) ?? null),
  deleteItemAsync: jest.fn(async (key: string) => {
    mockSecureStoreMemory.delete(key);
  }),
}));

// -- expo-local-authentication ---------------------------------------------
jest.mock('expo-local-authentication', () => ({
  __esModule: true,
  SecurityLevel: { NONE: 0, SECRET: 1, BIOMETRIC_WEAK: 2, BIOMETRIC_STRONG: 3 },
  AuthenticationType: { FINGERPRINT: 1, FACIAL_RECOGNITION: 2, IRIS: 3 },
  hasHardwareAsync: jest.fn(async () => true),
  isEnrolledAsync: jest.fn(async () => true),
  getEnrolledLevelAsync: jest.fn(async () => 3),
  supportedAuthenticationTypesAsync: jest.fn(async () => [2]),
  authenticateAsync: jest.fn(async () => ({ success: true })),
}));

// -- expo-blur --------------------------------------------------------------
jest.mock('expo-blur', () => {
  const { View } = jest.requireActual('react-native');
  return { __esModule: true, BlurView: View };
});

// -- expo-linking -----------------------------------------------------------
jest.mock('expo-linking', () => ({
  __esModule: true,
  getInitialURL: jest.fn(async () => null),
  addEventListener: jest.fn(() => ({ remove: jest.fn() })),
  createURL: jest.fn((path: string) => `maather://${path}`),
}));

// -- expo-router ------------------------------------------------------------
const mockRouter = {
  push: jest.fn(),
  replace: jest.fn(),
  back: jest.fn(),
  navigate: jest.fn(),
};
(globalThis as any).__routerMock = mockRouter;

jest.mock('expo-router', () => {
  const React = jest.requireActual('react');
  const { View } = jest.requireActual('react-native');
  const Stack = ({ children }: { children?: React.ReactNode }) =>
    React.createElement(View, null, children);
  Stack.Screen = () => null;
  return {
    __esModule: true,
    useRouter: () => (globalThis as any).__routerMock,
    usePathname: () => '/',
    useLocalSearchParams: () => ({}),
    Link: ({ children }: { children?: React.ReactNode }) =>
      React.createElement(View, null, children),
    Slot: ({ children }: { children?: React.ReactNode }) =>
      React.createElement(View, null, children),
    Redirect: ({ href }: { href: string }) =>
      React.createElement(View, { testID: `redirect-${href}` }),
    Stack,
  };
});

// -- expo-status-bar --------------------------------------------------------
jest.mock('expo-status-bar', () => ({ __esModule: true, StatusBar: () => null }));

// -- react-native-safe-area-context -----------------------------------------
jest.mock('react-native-safe-area-context', () => {
  const React = jest.requireActual('react');
  const { View } = jest.requireActual('react-native');
  return {
    __esModule: true,
    SafeAreaProvider: ({ children }: { children?: React.ReactNode }) =>
      React.createElement(View, null, children),
    SafeAreaView: View,
    useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  };
});

// ---------------------------------------------------------------------------
// تسخين: أول تصيير يدفع فاتورة ترجمة Babel، فلا يدفعها **تأكيد**
// ---------------------------------------------------------------------------
//
// ## العطب المرصود
//
// على ذاكرة ترجمة باردة — وهي حالة كل تشغيل يلي `npm install` — كان أول
// اختبار يُصيِّر مكوّناً يسقط بمهلة الخمس ثوانٍ، بينما يمرّ كل ما بعده في
// عشرات المللي ثانية. القياس على جهاز المالكة:
//
//     أول تصيير  5666 ms      ← يسقط
//     ما بعده      55–113 ms
//
// السبب ليس بطء الاختبار ولا تعليقاً في منطق التطبيق. `react-native` تُحمِّل
// وحداتها الداخلية **كسولاً** عند أول وصول، لا عند الاستيراد: قياسُ
// `require` وحده يعطي ~940 ms، والباقي يُدفَع داخل `render()` نفسه. فأول
// تصيير في العملية يترجم عشرات الوحدات، ثم تُخدَم البقية من ذاكرة القرص.
//
// ## لماذا ليس رفع المهلة
//
// رفع `testTimeout` يخفي العطب ولا يزيله: يبقى تأكيدٌ واحد رهينةَ حالة
// الذاكرة المؤقتة على جهاز غير معلوم. والصحيح نقل التكلفة إلى حيث تنتمي —
// **التهيئة**. تصييرٌ تافه هنا يمتصّ الفاتورة كاملة:
//
//     التسخين  6046 ms
//     التصيير الحقيقي بعده  124 ms
//
// فتبقى مهلة كل `it` عند الافتراضي (5000 ms) وتظلّ ذات معنى: أي تأكيد
// يتجاوزها بعد اليوم هو بطء حقيقي أو تعليق حقيقي، لا ضجيج ترجمة.
//
// المهلة الممنوحة هنا لخطّاف تهيئة لا لتأكيد، ومهمّته المعلنة دفع كلفة
// تُدفَع مرة واحدة لكل عملية.
beforeAll(() => {
  const React = jest.requireActual('react');
  const { View, Text, Pressable, ScrollView } = jest.requireActual('react-native');
  renderForWarmup(
    React.createElement(
      ScrollView,
      null,
      React.createElement(
        Pressable,
        null,
        React.createElement(View, null, React.createElement(Text, null, 'warmup')),
      ),
    ),
  );
}, 60_000);

beforeEach(() => {
  mockSecureStoreMemory.clear();
  // مُقلِّد الموجّه **مفردة عامة**، فاستدعاءاته تتراكم عبر اختبارات الملف
  // الواحد ما لم تُصفَّر. وهذا يُبطل أي تأكيد من نوع `toHaveBeenCalledTimes(1)`:
  // ينجح صدفةً لأن ما قبله لم يوجّه، ويمرّ كذباً بمجرد إعادة الترتيب.
  // التصفير هنا لا في كل ملف، كي لا يُنسى في ملف جديد.
  mockRouter.push.mockClear();
  mockRouter.replace.mockClear();
  mockRouter.back.mockClear();
  mockRouter.navigate.mockClear();
});
