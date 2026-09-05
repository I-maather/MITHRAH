/**
 * حكمُ اليوم — الجملة التي تعلو كل رقم.
 *
 * النموذج المعتمد يضع فوق شاشة «اليوم» جملةً لا مقياساً، لأنّ سؤال المالكة
 * الفعليّ «هل أتدخّل؟» لا «كم عندي؟». وهذا الملف يشتقّ تلك الجملة من الحالة
 * الحقيقية — ولا يكتبها ثابتةً ولا يخمّنها.
 *
 * ## الترتيب مقصود
 *
 * الأخطرُ أوّلاً: قاطعُ الطوارئ يعلو كلّ شيء، ثم **الجهل** — لأنّ «لا أعرف»
 * أخطرُ من «لا شيء» وأسهلُ خلطاً بها. ثمّ قرارُ المالكة، ثمّ المراكز، ثمّ
 * الصمتُ الطبيعي.
 *
 * ## ولماذا «لا أعرف حالتي» قبل كلّ ما دونها
 *
 * شاشةٌ تقول «لا شيء يحتاجكِ اليوم» بينما الاتصال منقطعٌ منذ ٤٧ دقيقة
 * تكذب — وقد يكون على الحساب خمسة مراكز. والفرق بين الصمت والانقطاع هو
 * الفرق الذي بُني عليه هذا التطبيق.
 */

export interface DayState {
  /** قاطع الطوارئ مفعَّل. */
  killSwitchActive: boolean;
  /** تعذّرت القراءة، أو البيانات قديمة. */
  unknown: boolean;
  /** أوقفت المالكة الدخول الجديد. */
  locallyPaused: boolean;
  /** عدد المراكز المفتوحة — `null` يعني غير معروف. */
  openPositions: number | null;
}

export interface DayVerdict {
  greeting: string;
  verdict: string;
  /** لهجة الشريط الجانبي لبطاقة الوكيل. */
  tone: 'neutral' | 'positive' | 'negative' | 'caution' | 'info' | 'accent';
}

/** تحيّةٌ بالوقت لا بالحالة. الساعة محليّة على الجهاز. */
export const greetingFor = (hour: number): string => {
  if (hour < 5) return 'ليلة هادئة';
  if (hour < 12) return 'صباح الخير';
  if (hour < 17) return 'طاب يومك';
  return 'مساء الخير';
};

export function dayVerdict(state: DayState, at: Date = new Date()): DayVerdict {
  const greeting = greetingFor(at.getHours());

  if (state.killSwitchActive) {
    return { greeting, verdict: 'أوقفتُ نفسي اليوم.', tone: 'negative' };
  }

  // **الجهل قبل الصمت.** شاشةٌ تقول «لا شيء يحتاجكِ» والاتصال منقطع تكذب.
  if (state.unknown) {
    return { greeting, verdict: 'لا أعرف حالتي الآن.', tone: 'caution' };
  }

  if (state.openPositions !== null && state.openPositions > 0) {
    const n = state.openPositions;
    const word =
      n === 1 ? 'مركزٌ واحد مفتوح.' : n === 2 ? 'مركزان مفتوحان.' : `${n} مراكز مفتوحة.`;
    return { greeting, verdict: word, tone: 'accent' };
  }

  if (state.locallyPaused) {
    return { greeting, verdict: 'الدخول موقوفٌ بقرارك.', tone: 'caution' };
  }

  return { greeting, verdict: 'لا شيء يحتاجكِ اليوم.', tone: 'neutral' };
}
