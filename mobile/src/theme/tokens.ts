/**
 * نسق مآثر — رموز التصميم.
 *
 * An original token set for this app. It is deliberately quiet: one accent, a
 * narrow neutral ramp, and three semantic risk colours. Nothing here imitates
 * any broker's branding.
 *
 * القاعدة: اللون يحمل معنى واحداً فقط.
 *   accent   = ما هو تفاعلي
 *   positive = ربح محقق أو حالة سليمة
 *   negative = خسارة أو عطل
 *   caution  = نقص بيانات أو انتظار
 * A number is never coloured for decoration.
 */

export const palette = {
  /** حبر — النص الأساسي في الوضع الفاتح. */
  ink: {
    900: '#111417',
    700: '#3A4046',
    500: '#5C6369',
    300: '#8B9298',
  },
  /** ورق — الأسطح في الوضع الفاتح. */
  paper: {
    0: '#FFFFFF',
    50: '#FAFAF8',
    100: '#F4F4F1',
    200: '#E8E8E3',
    300: '#DBDBD4',
  },
  /** ليل — الأسطح في الوضع الداكن. */
  night: {
    950: '#0C0E10',
    900: '#131619',
    800: '#1A1E22',
    700: '#242A2F',
    600: '#333A41',
  },
  /** ضوء — النص في الوضع الداكن. */
  glow: {
    0: '#F5F7F8',
    200: '#C3CACF',
    400: '#98A1A8',
    600: '#6E767D',
  },
  /** أثل — اللون المميّز. أخضر مزرقّ هادئ، لا أزرق مؤسسي. */
  athl: {
    light: '#1C5F5A',
    lightSoft: '#E3EFEE',
    dark: '#5CC9BE',
    darkSoft: '#12302E',
  },
  /** نخل — إيجابي. */
  nakhl: { light: '#146C48', dark: '#4CBE89' },
  /** رمّان — سلبي. */
  rumman: { light: '#A32828', dark: '#F0736F' },
  /** كثيب — تنبيه / نقص. */
  kathib: { light: '#845D14', dark: '#DEAE52' },
  /** سماء — معلومة محايدة. */
  sama: { light: '#215288', dark: '#7CB0EE' },
} as const;

/** المسافات — سلّم 4pt. */
export const spacing = {
  none: 0,
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
  huge: 40,
} as const;

/** أنصاف الأقطار. */
export const radii = {
  none: 0,
  sm: 6,
  md: 10,
  lg: 14,
  xl: 20,
  pill: 999,
} as const;

/**
 * الطباعة — مقاسات نقطية أساسية.
 * `allowFontScaling` يبقى مفعّلاً (افتراض React Native) فتُحترم Dynamic Type.
 * The point sizes below are the *base*; iOS scales them per the user's setting.
 * Only the display size is capped, to keep very large headings from pushing the
 * numbers they label off-screen.
 */
export const typography = {
  display: { size: 30, lineHeight: 38, weight: '700' as const, maxScale: 1.6 },
  title: { size: 22, lineHeight: 30, weight: '700' as const, maxScale: 1.8 },
  heading: { size: 18, lineHeight: 26, weight: '600' as const, maxScale: 2 },
  body: { size: 16, lineHeight: 24, weight: '400' as const, maxScale: 2.4 },
  bodyStrong: { size: 16, lineHeight: 24, weight: '600' as const, maxScale: 2.4 },
  caption: { size: 13, lineHeight: 19, weight: '400' as const, maxScale: 2.6 },
  captionStrong: { size: 13, lineHeight: 19, weight: '600' as const, maxScale: 2.6 },
  micro: { size: 11, lineHeight: 16, weight: '600' as const, maxScale: 2.8 },
  /** للأرقام: عرض ثابت كي لا ترقص القيم عند التحديث. */
  numeric: { size: 20, lineHeight: 28, weight: '600' as const, maxScale: 1.8 },
  numericLarge: { size: 34, lineHeight: 42, weight: '700' as const, maxScale: 1.5 },
} as const;

export type TypographyKey = keyof typeof typography;

/** الحركة — قصيرة، ولا شيء يعتمد عليها. */
export const motion = {
  instant: 0,
  fast: 140,
  base: 220,
  slow: 340,
  /** القيمة المستعملة عند تفعيل «تقليل الحركة». */
  reduced: 0,
} as const;

/** الظلال — خفيفة جداً؛ الفصل يتم بالحدود لا بالظل. */
export const elevation = {
  none: {
    shadowColor: 'transparent',
    shadowOpacity: 0,
    shadowRadius: 0,
    shadowOffset: { width: 0, height: 0 },
    elevation: 0,
  },
  card: {
    shadowColor: '#000000',
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
} as const;

/** أقل مساحة لمس مقبولة (إرشادات Apple). */
export const MIN_TOUCH_TARGET = 44;
