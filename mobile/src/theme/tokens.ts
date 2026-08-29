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
  /**
   * حبر — النص الأساسي في الوضع الفاتح.
   *
   * حبر **دافئ** لا رمادي بارد: الرمادي المحايد يجعل الواجهة تبدو نموذجاً
   * أوّلياً، والميل البسيط نحو البنفسجي يجعلها تبدو مقصودة.
   */
  ink: {
    900: '#1B1733',
    700: '#3D3663',
    500: '#635B87',
    300: '#938BB0',
  },
  /** ورق — الأسطح في الوضع الفاتح. دافئ قليلاً، لا أبيض مستشفى. */
  paper: {
    0: '#FFFFFF',
    50: '#FCFAF6',
    100: '#F6F2EA',
    200: '#EBE4D8',
    300: '#DCD2C1',
  },
  /**
   * ليل — الأسطح في الوضع الداكن.
   *
   * **نيلي عميق لا أسود.** الأسود شبه المطلق كان يجعل التطبيق يبدو جنائزياً،
   * والنيلي يحتفظ بالعمق ويكتسب حياة. وهو لون خلفية الأيقونة نفسها، فالهوية
   * واحدة من الشاشة الرئيسية إلى داخل التطبيق.
   */
  night: {
    950: '#1A0754',
    900: '#240B6E',
    800: '#301091',
    700: '#3F1CB0',
    600: '#5433C4',
  },
  /** ضوء — النص في الوضع الداكن. */
  glow: {
    0: '#FBF7F0',
    200: '#D5CDE8',
    400: '#A79DC4',
    600: '#7A719B',
  },
  /**
   * زعفران — اللون المميّز.
   *
   * ذهبٌ حارّ مشبع. **ليس أخضر الأرباح** ولا أزرق الشركات: لا يَعِد بشيء،
   * لكنه يبعث الدفء والثقة. وهو لون حلقة الإسطرلاب في الأيقونة.
   */
  zaafaran: {
    light: '#4A1FB8',
    lightSoft: '#EDE7FF',
    dark: '#4CC9F0',
    darkSoft: '#152B47',
  },
  /** مرجان — لهجة ثانية حارّة، للمؤشّرات والتمييز. */
  murjan: { light: '#C2185B', lightSoft: '#FFE3EE', dark: '#F72585', darkSoft: '#4A0E29' },
  /** نخل — إيجابي. مشبع لا باهت. */
  nakhl: { light: '#0E7A4F', dark: '#3DD68C' },
  /** رمّان — سلبي. */
  rumman: { light: '#C01B3C', dark: '#FF6B84' },
  /** كثيب — تنبيه / نقص. */
  kathib: { light: '#9A6B00', dark: '#FFC94A' },
  /** سماء — معلومة محايدة. */
  sama: { light: '#1C6FB0', dark: '#5CC2F5' },
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
