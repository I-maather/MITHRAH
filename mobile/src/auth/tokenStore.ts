import * as SecureStore from 'expo-secure-store';

/**
 * تخزين **رموز جلسة التطبيق فقط** في سلسلة مفاتيح iOS.
 *
 * WHAT LIVES HERE
 *   access token   — 15 دقيقة، يصدره خادم مثراة لهذا الجهاز.
 *   refresh token  — 30 يوماً، يُدوَّر عند كل استعمال.
 *   device id      — معرّف عام يصدره الخادم.
 *
 * WHAT NEVER LIVES HERE
 *   لا مفتاح وسيط، ولا اعتماد مزوّد بيانات، ولا مفتاح APNs، ولا سرّ توقيع
 *   أوامر، ولا رابط قاعدة بيانات. لا يوجد أي منها في التطبيق أصلاً، فلا يوجد
 *   ما يُخزَّن. `__tests__/token-storage.test.ts` يثبت أن المفاتيح المكتوبة
 *   هي هذه الثلاثة لا غير.
 *
 * `WHEN_UNLOCKED_THIS_DEVICE_ONLY`: الرموز لا تُنسَخ احتياطياً ولا تُزامَن إلى
 * جهاز آخر ولا تُقرأ والجهاز مقفل.
 */

const ACCESS_TOKEN_KEY = 'maather.session.access';
const REFRESH_TOKEN_KEY = 'maather.session.refresh';
const DEVICE_ID_KEY = 'maather.session.device_id';
/** هوية الجهاز المُعلَنة عند التسجيل. ليست سرّاً — انظر `identity.ts`. */
const PUBLIC_IDENTITY_KEY = 'maather.device.public_identity';

/** المفاتيح المسموح بها. أي مفتاح خارجها خطأ برمجي. */
export const ALLOWED_KEYCHAIN_KEYS: readonly string[] = [
  ACCESS_TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  DEVICE_ID_KEY,
  PUBLIC_IDENTITY_KEY,
];

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export interface StoredSession {
  accessToken: string;
  refreshToken: string;
  deviceId: string;
  /** لحظة انتهاء رمز الوصول بالمللي ثانية منذ Epoch. */
  accessExpiresAt: number;
}

const assertAllowedKey = (key: string): void => {
  if (!ALLOWED_KEYCHAIN_KEYS.includes(key)) {
    throw new Error('محاولة كتابة مفتاح غير مُعلَن في سلسلة المفاتيح.');
  }
};

const setItem = async (key: string, value: string): Promise<void> => {
  assertAllowedKey(key);
  await SecureStore.setItemAsync(key, value, OPTIONS);
};

const getItem = async (key: string): Promise<string | null> => {
  assertAllowedKey(key);
  return SecureStore.getItemAsync(key, OPTIONS);
};

const deleteItem = async (key: string): Promise<void> => {
  assertAllowedKey(key);
  await SecureStore.deleteItemAsync(key, OPTIONS);
};

/** عمر رمز الوصول كما يعلنه الخادم — 15 دقيقة. */
export const ACCESS_TOKEN_TTL_MS = 15 * 60 * 1000;
/** هامش أمان: نجدّد قبل الانتهاء بدقيقة. */
export const REFRESH_MARGIN_MS = 60 * 1000;

export const tokenStore = {
  async save(session: StoredSession): Promise<void> {
    await setItem(ACCESS_TOKEN_KEY, session.accessToken);
    await setItem(REFRESH_TOKEN_KEY, session.refreshToken);
    await setItem(DEVICE_ID_KEY, session.deviceId);
  },

  async loadAccessToken(): Promise<string | null> {
    return getItem(ACCESS_TOKEN_KEY);
  },

  async loadRefreshToken(): Promise<string | null> {
    return getItem(REFRESH_TOKEN_KEY);
  },

  async loadDeviceId(): Promise<string | null> {
    return getItem(DEVICE_ID_KEY);
  },

  /** استبدال الرمزين بعد التدوير. القديم يُكتب فوقه، لا يُترك. */
  async rotate(accessToken: string, refreshToken: string): Promise<void> {
    await setItem(ACCESS_TOKEN_KEY, accessToken);
    await setItem(REFRESH_TOKEN_KEY, refreshToken);
  },

  /** محو كامل — عند الإلغاء أو انتهاء الجلسة أو إلغاء الجهاز. */
  async clear(): Promise<void> {
    await deleteItem(ACCESS_TOKEN_KEY);
    await deleteItem(REFRESH_TOKEN_KEY);
    await deleteItem(DEVICE_ID_KEY);
  },

  async loadPublicIdentity(): Promise<string | null> {
    return getItem(PUBLIC_IDENTITY_KEY);
  },

  /**
   * الهوية **لا تُمحى مع `clear()`** عمداً: إلغاء الجلسة لا يجعل الجهاز
   * جهازاً آخر. إبقاؤها يجعل إعادة التسجيل تُقرأ في التدقيق «الجهاز نفسه
   * عاد» لا «جهاز جديد ظهر».
   */
  async savePublicIdentity(value: string): Promise<void> {
    await setItem(PUBLIC_IDENTITY_KEY, value);
  },

  async hasSession(): Promise<boolean> {
    const refresh = await getItem(REFRESH_TOKEN_KEY);
    return refresh !== null && refresh.length > 0;
  },
};

/**
 * تقنيع رمز للعرض. يُستعمل في شاشة النظام فقط، ولا يُطبع في أي سجل.
 * Shows four characters and nothing more.
 */
export const maskToken = (token: string | null): string => {
  if (token === null || token.length === 0) {
    return '—';
  }
  return `${token.slice(0, 4)}${'•'.repeat(6)}`;
};
