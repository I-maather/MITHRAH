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

beforeEach(() => {
  mockSecureStoreMemory.clear();
  mockRouter.push.mockClear();
  mockRouter.replace.mockClear();
});
