import { palette } from './tokens';

/**
 * الألوان الدلالية. كل اسم يصف **الدور** لا الصبغة، فالتبديل بين الوضعين
 * لا يغيّر أي شيء في مواضع الاستعمال.
 */
export interface ColorScheme {
  /** خلفية الشاشة. */
  background: string;
  /** سطح البطاقة. */
  surface: string;
  /** سطح داخل بطاقة (صف، شريحة). */
  surfaceSunken: string;
  /** الحد الفاصل. */
  border: string;
  /** حد أوضح للعناصر المهمة. */
  borderStrong: string;

  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  /** نص فوق سطح ملوّن مصمت. */
  textOnAccent: string;

  accent: string;
  accentSoft: string;

  positive: string;
  positiveSoft: string;
  negative: string;
  negativeSoft: string;
  caution: string;
  cautionSoft: string;
  info: string;
  infoSoft: string;

  /** طبقة إخفاء المحتوى في مبدّل التطبيقات. */
  privacyVeil: string;
  /** حاجب المودالات. */
  scrim: string;
}

const withAlpha = (hex: string, alpha: number): string => {
  const a = Math.round(Math.max(0, Math.min(1, alpha)) * 255)
    .toString(16)
    .padStart(2, '0');
  return `${hex}${a}`;
};

export const lightColors: ColorScheme = {
  background: palette.paper[50],
  surface: palette.paper[0],
  surfaceSunken: palette.paper[100],
  border: palette.paper[200],
  borderStrong: palette.paper[300],

  textPrimary: palette.ink[900],
  textSecondary: palette.ink[500],
  textTertiary: palette.ink[300],
  textOnAccent: palette.paper[0],

  accent: palette.zaafaran.light,
  accentSoft: palette.zaafaran.lightSoft,

  positive: palette.nakhl.light,
  positiveSoft: '#E4F1EA',
  negative: palette.rumman.light,
  negativeSoft: '#F8E7E7',
  caution: palette.kathib.light,
  cautionSoft: '#F7EEDC',
  info: palette.sama.light,
  infoSoft: '#E5EDF6',

  privacyVeil: palette.paper[50],
  scrim: withAlpha(palette.ink[900], 0.4),
};

export const darkColors: ColorScheme = {
  background: palette.night[950],
  surface: palette.night[900],
  surfaceSunken: palette.night[800],
  border: palette.night[700],
  borderStrong: palette.night[600],

  textPrimary: palette.glow[0],
  textSecondary: palette.glow[400],
  textTertiary: palette.glow[600],
  textOnAccent: palette.night[950],

  accent: palette.zaafaran.dark,
  accentSoft: palette.zaafaran.darkSoft,

  positive: palette.nakhl.dark,
  positiveSoft: '#132C22',
  negative: palette.rumman.dark,
  negativeSoft: '#301A1A',
  caution: palette.kathib.dark,
  cautionSoft: '#2C2415',
  info: palette.sama.dark,
  infoSoft: '#152436',

  privacyVeil: palette.night[950],
  scrim: '#000000A6',
};

/** حالات النظام ولونها الدلالي. */
export type ToneName = 'neutral' | 'positive' | 'negative' | 'caution' | 'info' | 'accent';

export interface Tone {
  fg: string;
  bg: string;
}

export const toneOf = (colors: ColorScheme, tone: ToneName): Tone => {
  switch (tone) {
    case 'positive':
      return { fg: colors.positive, bg: colors.positiveSoft };
    case 'negative':
      return { fg: colors.negative, bg: colors.negativeSoft };
    case 'caution':
      return { fg: colors.caution, bg: colors.cautionSoft };
    case 'info':
      return { fg: colors.info, bg: colors.infoSoft };
    case 'accent':
      return { fg: colors.accent, bg: colors.accentSoft };
    case 'neutral':
    default:
      return { fg: colors.textSecondary, bg: colors.surfaceSunken };
  }
};
