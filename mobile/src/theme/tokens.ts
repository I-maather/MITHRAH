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
   * حبر — النص في الوضع الفاتح.
   *
   * رمادي **محايد بميل دافئ خفيف**: محايدٌ تماماً يبدو نموذجاً أوّلياً، والميل
   * الدافئ يجعله مقصوداً بلا أن يصير صبغة. والتدرّج مضبوط على التباين لا على
   * الذوق: `300` هو أفتح ما يجوز لنصّ يحمل رسالة حقيقية (≥ 4.5:1 على `paper.50`).
   */
  ink: {
    900: '#16161A',
    700: '#33322F',
    500: '#4F4D48',
    300: '#6B6963',
  },
  /** ورق — الأسطح في الوضع الفاتح. رمادي فاتح، لا أبيض مستشفى. */
  paper: {
    0: '#FFFFFF',
    50: '#F3F2F0',
    100: '#EAE8E5',
    200: '#DEDCD8',
    300: '#CBC8C3',
  },
  /**
   * ليل — الأسطح في الوضع الداكن.
   *
   * شبه أسود بميل دافئ. `700` و`600` مرفوعان عمداً: الفصل يتمّ بالحدّ لا
   * بالظلّ (انظر `elevation`)، وحدٌّ لا يُرى ليس حدّاً.
   */
  night: {
    950: '#100F0E',
    900: '#181716',
    800: '#201F1D',
    700: '#3A3734',
    600: '#57534E',
  },
  /** ضوء — النص في الوضع الداكن. `600` مضبوط ليجتاز 4.5:1 على `night.950`. */
  glow: {
    0: '#F4F2EE',
    200: '#D6D3CD',
    400: '#A5A19A',
    600: '#807C74',
  },
  /**
   * جَمْر — اللون المميّز الوحيد.
   *
   * القوس الدافئ 300°–40° كان **خالياً** في قياس 69 لقطة من 18 تطبيقاً؛ وكل
   * المنافسين متكدّسون بين 90° و263°. والجمري هنا عند ~22°.
   *
   * **قاعدة صارمة: لا يُلوَّن به رقم أبداً.** موضعه ما هو *حيّ* فقط — التبويب
   * النشط، والأيقونة النشطة، ونقطة الاتصال. فإن حمل قيمةً اشتبه بلون الخسارة
   * عند 353°، والفجوة بينهما 29° لا تكفي.
   */
  jamr: {
    light: '#B85A26',
    lightSoft: '#F7EBE1',
    dark: '#D97B3C',
    darkSoft: '#2A1C13',
  },
  /** مرجان — لهجة ثانية، للتمييز غير الحامل لمعنى. */
  murjan: { light: '#9C4221', lightSoft: '#F6E8E0', dark: '#E09A6B', darkSoft: '#2B1D14' },
  /** نخل — ربح. يظهر **مع الإشارة `+` دائماً**، فلا يحمل المعنى وحده. */
  nakhl: { light: '#1B7A4B', dark: '#4BD08D' },
  /** رمّان — خسارة. ومعه الإشارة `−` دائماً. */
  rumman: { light: '#B32B31', dark: '#F0736F' },
  /** كثيب — تنبيه أو نقص بيانات. */
  kathib: { light: '#8A6516', dark: '#DBA94E' },
  /** سماء — معلومة محايدة. */
  sama: { light: '#2A6491', dark: '#7FB6E0' },
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

/**
 * الخطوط.
 *
 * **العربية خطٌّ أصلي لا خط نظام.** خط النظام (SF Arabic) ممتاز — ولهذا
 * تحديداً يجعل التطبيق يشبه كل تطبيق آخر على الجهاز. وبحث المنافسين رصد
 * الفراغ: لا تطبيق في الـ69 يعامل شكل الحرف العربي كعنصر هوية.
 *
 * **والأرقام خطٌّ مستقلّ عن نصّ الواجهة.** قرارٌ لا تفصيلة: التطبيق تسعون
 * بالمئة منه أرقام، ولا أحد من الثمانية عشر عاملها كقرار تصميمي.
 *
 * ## لماذا عائلة لكل وزن
 *
 * على iOS، تحديد `fontFamily` مخصّصة يجعل `fontWeight` **غير موثوق**: النظام
 * إمّا يتجاهله أو يصطنع وزناً ثقيلاً مشوّهاً. فالوزن يُختار بالملفّ لا بالخاصية،
 * و`Text` تُسقط `fontWeight` حين تستعمل عائلة مخصّصة.
 */
export const fontFamilies = {
  arabic: {
    '300': 'IBMPlexSansArabic-Regular',
    '400': 'IBMPlexSansArabic-Regular',
    '500': 'IBMPlexSansArabic-Medium',
    '600': 'IBMPlexSansArabic-SemiBold',
    '700': 'IBMPlexSansArabic-Bold',
  } as Record<string, string>,
  /** الأرقام — سيريفي. أوضح في الفصل بين 0 و8 و6 و9 على الشاشة الصغيرة. */
  numeric: 'Newsreader',
  /** العلامة وشاشة البداية فقط. لا يُستعمل في نصّ الواجهة. */
  display: 'ReemKufi',
} as const;

export const fonts = {
  arabic: fontFamilies.arabic['400'],
  numeric: fontFamilies.numeric,
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
