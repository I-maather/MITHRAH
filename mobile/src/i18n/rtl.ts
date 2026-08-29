import { I18nManager } from 'react-native';

/**
 * فرض الاتجاه من اليمين إلى اليسار.
 *
 * التطبيق **عربي أولاً**: لا يعتمد على لغة النظام ولا ينقلب إذا كان الهاتف
 * بالإنجليزية. الواجهة تُقرأ من اليمين دائماً.
 *
 * HOW THIS WORKS IN A NATIVE BUILD
 * `I18nManager.forceRTL(true)` writes a native flag that only takes effect on
 * the **next** launch of the process. On a fresh install the very first launch
 * therefore renders LTR unless we detect and report it. We do not silently ship
 * a mirrored-wrong layout: `rtlState()` tells the UI whether a restart is still
 * pending, and `app/_layout.tsx` shows a one-line notice asking the owner to
 * relaunch. From the second launch onward it is permanent.
 *
 * We deliberately do NOT call a reload API here. Forcing a restart from inside
 * the app fights the OS and hides the state; a single honest notice is better.
 */

let forcedThisLaunch = false;

export function applyRtl(): void {
  if (forcedThisLaunch) {
    return;
  }
  forcedThisLaunch = true;
  I18nManager.allowRTL(true);
  if (!I18nManager.isRTL) {
    I18nManager.forceRTL(true);
  }
}

export interface RtlState {
  /** الاتجاه الفعّال في هذه الجلسة. */
  isRTL: boolean;
  /** true إذا لزم إعادة تشغيل كي يسري الاتجاه. */
  restartRequired: boolean;
  noticeAr: string | null;
}

export function rtlState(): RtlState {
  const isRTL = I18nManager.isRTL;
  return {
    isRTL,
    restartRequired: !isRTL,
    noticeAr: isRTL
      ? null
      : 'اتجاه الواجهة سيُضبط من اليمين إلى اليسار بعد إغلاق التطبيق وفتحه مرة واحدة.',
  };
}

/**
 * محاذاة النص. نستعمل `'right'` صراحةً بدل `'left'` المنعكسة، لأن الأرقام
 * والنصوص المختلطة تُقرأ أوضح حين تكون المحاذاة مصرَّحاً بها.
 */
export const textStart = (): 'right' | 'left' => (I18nManager.isRTL ? 'right' : 'left');
export const textEnd = (): 'right' | 'left' => (I18nManager.isRTL ? 'left' : 'right');

/**
 * الأرقام تُعرض بالأرقام العربية الشرقية أو الغربية؟ — الغربية.
 * القيم المالية تأتي من الخادم كنصوص جاهزة، ونعرضها كما هي بلا إعادة تنسيق،
 * كي لا يختلف رقم على الشاشة عن رقم في السجل.
 */
export const LOCALE = 'ar';
