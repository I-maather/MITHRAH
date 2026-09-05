/**
 * تباينُ WCAG — **محسوبٌ لا مُقدَّر بالعين**.
 *
 * نظام التصميم ينصّ: «الفصل يتمّ بالحدّ لا بالظلّ… وحدٌّ لا يُرى ليس حدّاً».
 * والنصّ وحده لا يحرس نفسه: القياس قال إنّ حدّ البطاقة على الخلفية يبلغ
 * **1.22 : 1** في الوضع الفاتح — أي أنّ المبدأ يناقض نفسه بصمت.
 *
 * فتُحسب النسبة هنا، وتُفحص في اختبارٍ يفشل تحت العتبة، فلا يعود التصريح
 * كافياً.
 */

const clampChannel = (value: number): number =>
  value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;

/** يقبل `#RGB` و`#RRGGBB` و`#RRGGBBAA` (تُتجاهل الشفافية — تُدمج قبل القياس). */
export function toRgb(hex: string): [number, number, number] {
  let value = hex.trim().replace('#', '');
  if (value.length === 3) {
    value = value
      .split('')
      .map((c) => c + c)
      .join('');
  }
  if (value.length === 8) {
    value = value.slice(0, 6);
  }
  if (value.length !== 6 || /[^0-9a-fA-F]/.test(value)) {
    throw new Error(`لونٌ غير صالح: ${hex}`);
  }
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ];
}

export function relativeLuminance(hex: string): number {
  const [r, g, b] = toRgb(hex).map((channel) => clampChannel(channel / 255)) as [
    number,
    number,
    number,
  ];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a: string, b: string): number {
  const first = relativeLuminance(a);
  const second = relativeLuminance(b);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

/** عتبات WCAG 2.2 المستعملة في هذا المشروع. */
export const CONTRAST_TEXT = 4.5;
export const CONTRAST_LARGE_TEXT = 3;
/** §1.4.11 — عناصر الواجهة غير النصّية: مسارات، حدود، مؤشّرات. */
export const CONTRAST_UI = 3;
