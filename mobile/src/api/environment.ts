import { useSyncExternalStore } from 'react';

/**
 * بيئةُ التداول **كما يقولها الخادم الآن** — مقابل ما بُني عليه التطبيق.
 *
 * ## لماذا مصدران لا واحد
 *
 * `TRADING_ENVIRONMENT` يُثبَّت لحظةَ البناء: إجابةُ «على أيّ بيئةٍ صُنعت هذه
 * النسخة». و`broker.is_demo` يقولها الخادم كلَّ طلب: إجابةُ «أين يتداول
 * النظام الآن». وهما يفترقان فعلاً — التطبيق يحمل زرَّ تبديلٍ بين الحسابين،
 * فالحالة تتغيّر أثناء الاستعمال.
 *
 * **واختلافُهما بذاته إنذار**، لا تفصيلٌ يُطوى: نسخةٌ بُنيت للتجريب وهي
 * موصولةٌ بحسابٍ حقيقي هي أخطر تركيبةٍ ممكنة، لأنّ القرار يُتَّخذ على أنه
 * تجريبيّ ولا يُستدرَك.
 *
 * المخزنُ هنا يُملأ من أيّ استجابةٍ تحمل `broker.is_demo` — فأيُّ شاشةٍ
 * تُجلَب تُحدِّث الشارة في كل الشاشات. وقبل أوّل استجابة تبقى `UNKNOWN`،
 * وتقول الشارة ذلك صراحةً بدل أن تفترض.
 */

export type ServerEnvironment = 'DEMO' | 'REAL' | 'UNKNOWN';

let current: ServerEnvironment = 'UNKNOWN';
const listeners = new Set<() => void>();

const emit = (): void => {
  listeners.forEach((listener) => {
    listener();
  });
};

/** يُستعمل في الاختبارات وعند تسجيل الخروج. */
export function resetServerEnvironment(): void {
  if (current !== 'UNKNOWN') {
    current = 'UNKNOWN';
    emit();
  }
}

export function setServerEnvironment(next: ServerEnvironment): void {
  if (next !== current) {
    current = next;
    emit();
  }
}

/**
 * يلتقط `broker.is_demo` من أيّ حمولة، ويتجاهل ما سواها بصمت.
 *
 * لا يُخمَّن من غياب الحقل: حمولةٌ بلا `broker` لا تُغيّر شيئاً. فالغياب
 * ليس خبراً، والافتراض عند الغياب هو ما يُنتج شارةً تقول «تجريبي» بلا أن
 * يقولها أحد.
 */
export function observeEnvironment(payload: unknown): void {
  if (payload === null || typeof payload !== 'object') {
    return;
  }
  const broker = (payload as { broker?: unknown }).broker;
  if (broker === null || typeof broker !== 'object') {
    return;
  }
  const isDemo = (broker as { is_demo?: unknown }).is_demo;
  if (typeof isDemo !== 'boolean') {
    return;
  }
  setServerEnvironment(isDemo ? 'DEMO' : 'REAL');
}

export function useServerEnvironment(): ServerEnvironment {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => current,
    () => current,
  );
}
