/**
 * المسارات المُعلَنة — نسخة طبق الأصل من `backend/app/mobile/api.py`.
 *
 * THIS LIST IS THE WHOLE SURFACE.
 * There is no order route, no position route beyond *reading* the current one,
 * no leverage route, no key-reactivation route. `__tests__/security-boundary.test.ts`
 * asserts that these two tuples are exactly what the API client can reach.
 */

/** مسارات القراءة، بالترتيب نفسه في الخادم. */
export const READ_ROUTES = [
  'status',
  'intelligence/latest',
  'decision/latest',
  'risk',
  'profiles',
  'positions/current',
  'trades',
  'performance',
  'providers/health',
  'notifications',
  'audit/recent',
  'scan/latest',
] as const;

export type ReadRoute = (typeof READ_ROUTES)[number];

/**
 * مسارات التعديل. ثلاثة، **كلها تقلّل المخاطرة**.
 * None of them opens anything. The worst an attacker with a stolen device can
 * do through this app is stop the system from trading.
 */
export const RISK_REDUCING_ROUTES = [
  'pause/request',
  'killswitch/activate',
  'device/revoke',
] as const;

export type RiskReducingRoute = (typeof RISK_REDUCING_ROUTES)[number];

/**
 * **المسار الوحيد الذي يزيد المخاطرة** — في فئةٍ خاصة به، مطابقةً للخادم.
 *
 * ولو أُضيف إلى `RISK_REDUCING_ROUTES` لبقي اسمها وصار كاذباً — وذلك أخطر من
 * مسارٍ مفتوح، لأن القارئ يثق بالاسم لا بالمحتوى.
 *
 * ولا يفتح إلا الإيقاف المحلي: أسوأ ما يفعله جهازٌ مسروق أن يعيد النظام من
 * «موقوف» إلى «يقيّم» — ولا يستطيع بعدها إرسال أمرٍ واحد.
 */
export const RISK_INCREASING_ROUTES = ['pause/resume'] as const;

export type RiskIncreasingRoute = (typeof RISK_INCREASING_ROUTES)[number];

export type MutatingRoute = RiskReducingRoute | RiskIncreasingRoute;

/**
 * عبارة التأكيد كما يطلبها الخادم حرفاً بحرف.
 * تُكتب هنا مرّة واحدة كي لا تتفرّق نسخُها في الشاشات فتنحرف إحداها.
 */
export const RESUME_PHRASE = 'أستأنف التداول';

/**
 * كلمات لا يجوز أن تظهر في أي مسار. نسخة من قائمة الخادم كي يُكتشف الانحراف
 * على الجانبين معاً لا على جانب واحد.
 */
export const FORBIDDEN_ROUTE_TOKENS = [
  'order',
  'trade/submit',
  'position/open',
  'position/close',
  'leverage',
  'preferences',
  'deposit',
  'withdraw',
  'quantity',
  'stop',
  'takeprofit',
  'activate-key',
  'commissioning',
] as const;

/**
 * أصناف الأسرار التي **لا يجوز أن توجد على الجهاز**.
 *
 * الوصف بالصنف لا بالاسم الحرفي عن قصد: كتابة اسم متغيّر سرّي في مصدر التطبيق
 * — ولو في قائمة منع — تجعل البحث عن تسريب أصعب لا أسهل، وتترك في الحزمة نصاً
 * يشبه المفتاح وليس مفتاحاً.
 *
 * The app's keychain holds exactly three things: its own access token, its own
 * refresh token, and the device id the server issued. Nothing else. Every
 * category below lives on the FastAPI backend and has no path to this bundle.
 * `__tests__/security-boundary.test.ts` greps the whole tree for the *shapes*
 * of these secrets rather than their names.
 */
export const NEVER_ON_DEVICE = [
  'اعتماد الوسيط (معرّف، كلمة مرور، مفتاح واجهة)',
  'رموز جلسة الوسيط',
  'مفاتيح مزوّدي بيانات السوق والأخبار والبيانات الكلية',
  'مفتاح توقيع الإشعارات لدى Apple',
  'سرّ توقيع الأوامر',
  'رابط قاعدة البيانات',
] as const;

const assertNoForbiddenToken = (): void => {
  for (const route of [...READ_ROUTES, ...RISK_REDUCING_ROUTES, ...RISK_INCREASING_ROUTES]) {
    for (const token of FORBIDDEN_ROUTE_TOKENS) {
      if (route.includes(token)) {
        throw new Error(`مسار محظور تسلّل إلى العميل: ${route}`);
      }
    }
  }
};

assertNoForbiddenToken();
