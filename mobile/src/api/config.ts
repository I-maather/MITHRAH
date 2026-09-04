import Constants from 'expo-constants';

/**
 * قراءة الإعداد من `app.config.ts` عبر expo-constants — **مصدر واحد**.
 * Nothing in this file is a secret; it is a URL, a bundle id and two flags.
 */

interface Extra {
  apiBaseUrl?: unknown;
  appVersion?: unknown;
  buildNumber?: unknown;
  buildCommit?: unknown;
  buildTime?: unknown;
  tradingEnvironment?: unknown;
  bundleIdentifier?: unknown;
  autoLockMinutes?: unknown;
  previewData?: unknown;
  authorisesExecution?: unknown;
}

const extra: Extra = (Constants.expoConfig?.extra ?? {}) as Extra;

const asString = (value: unknown, fallback: string): string =>
  typeof value === 'string' && value.length > 0 ? value : fallback;

const asNumber = (value: unknown, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

/** عنوان الخادم. الافتراضي حلقة محلية — لا مضيف عام في المصدر إطلاقاً. */
export const API_BASE_URL: string = asString(extra.apiBaseUrl, 'http://127.0.0.1:8000');

/** معرّف الحزمة — يُقرأ ولا يُكرَّر. */
export const BUNDLE_IDENTIFIER: string = asString(
  extra.bundleIdentifier ?? Constants.expoConfig?.ios?.bundleIdentifier,
  'com.maather.autonomoustrader',
);

/** نسخةُ التطبيق — من `package.json`، مصدرٌ واحد. */
export const APP_VERSION: string = asString(extra.appVersion, 'unknown');

/** رقمُ البناء. */
export const BUILD_NUMBER: string = asString(extra.buildNumber, 'unknown');

/** كوميتُ البناء — يُثبَّت وقت البناء ويُعرض، فتُعرف النسخة التي في اليد. */
export const BUILD_COMMIT: string = asString(extra.buildCommit, 'unknown');

/**
 * بيئةُ التداول المعلَنة في البناء — `DEMO` أو `REAL`.
 *
 * تُعرَض شارةً ظاهرة. وشاشةٌ لا تقول أيَّهما ليست ملتبسة، هي خطرة: القرار
 * الذي يُتَّخذ على أنه تجريبيٌّ وهو حقيقي لا يُستدرَك.
 */
export const TRADING_ENVIRONMENT: string = asString(extra.tradingEnvironment, 'UNSET');

/** زمنُ البناء. */
export const BUILD_TIME: string = asString(extra.buildTime, 'unknown');

/** دقائق الخمول قبل القفل التلقائي. */
export const AUTO_LOCK_MINUTES: number = asNumber(extra.autoLockMinutes, 2);

/**
 * بيانات المعاينة. تعمل فقط في التطوير أو عند رفع العلم صراحةً،
 * وكل شاشة تعرضها تحمل وسم «معاينة / Preview».
 */
export const PREVIEW_DATA_ENABLED: boolean =
  extra.previewData === true || (typeof __DEV__ !== 'undefined' && __DEV__ === true);

/** بادئة مجال الجوال. */
export const API_PREFIX = '/api/mobile/v1';

/**
 * مسار تجديد الجلسة. **خارج مجال البيانات** عمداً: مجال `v1` يرفض أي POST
 * غير الثلاثة المُقلِّلة للمخاطرة، فالتجديد يقع في وحدة التسجيل المستقلة.
 * If the backend has not exposed it yet, the client fails closed and asks for
 * re-enrolment rather than silently continuing with an expired token.
 */
export const SESSION_REFRESH_PATH = '/api/mobile/session/refresh';

/**
 * مسار التسجيل. **خارج مجال البيانات** للسبب نفسه: مجال `v1` يرفض أي POST
 * غير الثلاثة المُقلِّلة للمخاطرة، ولا يجوز أن يصير التسجيل استثناءً داخله.
 */
export const SESSION_ENROLL_PATH = '/api/mobile/session/enroll';

/** عناوين محلية/خاصة يُسمح فيها بـhttp أثناء التطوير. */
const PRIVATE_HOST_PATTERNS: RegExp[] = [
  /^localhost$/i,
  /^127\.\d+\.\d+\.\d+$/,
  /^\[?::1\]?$/,
  /^10\.\d+\.\d+\.\d+$/,
  /^192\.168\.\d+\.\d+$/,
  /^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$/,
  /\.local$/i,
];

export const isPrivateHost = (host: string): boolean =>
  PRIVATE_HOST_PATTERNS.some((pattern) => pattern.test(host));

export interface BaseUrlVerdict {
  ok: boolean;
  reasonAr: string;
}

/**
 * يفشل مغلقاً عند الشك في هوية الخادم.
 *
 * القاعدة:
 *   https  ⇒ مقبول دائماً (TLS يتحقّق منه النظام، ولا نعطّله أبداً).
 *   http   ⇒ مقبول **فقط** لعنوان محلي/خاص.
 *   غير ذلك ⇒ مرفوض، ولا يُرسَل أي رمز.
 */
export function verifyBaseUrl(raw: string): BaseUrlVerdict {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { ok: false, reasonAr: 'عنوان الخادم غير صالح. لن يُرسَل أي طلب.' };
  }
  if (url.protocol === 'https:') {
    return { ok: true, reasonAr: 'اتصال مُعمّى ومُتحقَّق منه.' };
  }
  if (url.protocol === 'http:' && isPrivateHost(url.hostname)) {
    return {
      ok: true,
      reasonAr: 'اتصال محلي غير مُعمّى — مسموح للتطوير على الشبكة الخاصة فقط.',
    };
  }
  return {
    ok: false,
    reasonAr:
      'الخادم غير مُعمّى وليس على شبكة خاصة. أُوقف الاتصال — لا يُرسَل رمز إلى خادم مجهول الهوية.',
  };
}
