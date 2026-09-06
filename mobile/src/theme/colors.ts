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
  /**
   * الجمر **نصّاً**. الصبغة نفسها بإضاءةٍ أخفض.
   *
   * لون العلامة يُملأ به ولا يُكتَب به دائماً: `#B85A26` على تعبئته الفاتحة
   * يبلغ 3.96:1، ونصُّ الشارة ليس نصّاً كبيراً. والهوية معتمدة فلا تُغيَّر
   * صبغتها — يُغيَّر الدور: تعبئةٌ بلون، وكتابةٌ بلونٍ يُقرأ.
   */
  accentText: string;

  positive: string;
  positiveSoft: string;
  negative: string;
  negativeSoft: string;
  caution: string;
  cautionSoft: string;
  info: string;
  infoSoft: string;

  /*
    **الزجاج** — منقولٌ من `.glass` في النموذج المعتمد بقيمه:

        background: linear-gradient(135deg, rgba(255,255,255,.10),
                                            rgba(255,255,255,.035));
        border: 1px solid rgba(255,255,255,.15);
        box-shadow: inset 0 1px rgba(255,255,255,.09);
        :before  background: rgba(16,15,14,.55)   ← تحت الزجاج

    والطبقةُ السفلى ليست زينة: هي التي تُثبّت التباين مهما كان خلف البطاقة.
  */
  /** أعلى التدرّج القُطري. */
  glassTop: string;
  /** أسفله. */
  glassBottom: string;
  /** حدُّ الزجاج. */
  glassBorder: string;
  /** الطبقة المعتمة تحت الزجاج — بها يثبت التباين. */
  glassBacking: string;
  /** اللمعةُ الداخلية عند الحافة العليا. */
  glassHighlight: string;

  /** قمّةُ تدرّج الخلفية — `linear-gradient(160deg, …)` في النموذج. */
  backdropWarm: string;
  /** الطرفُ الفاتح في تدرّجات الشعار والحرارة — المرجان. */
  accentGlow: string;

  /** `.nav` — سطح شريط التبويبات العائم. */
  navSurface: string;
  navBorder: string;

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
  /*
    الوضعُ الفاتح **ليس في النموذج المعتمد**: النموذج داكنٌ وحده
    (`#0C0B0A`). فهذه القيم اجتهادٌ متّسق مع منطق الزجاج نفسه — طبقةٌ
    فاتحةٌ شبه معتمة يعلوها تدرّجٌ أبيض — ولا تُقدَّم على أنها معتمدة.
  */
  backdropWarm: palette.paper[0],
  accentGlow: palette.jamr.light,
  navSurface: 'rgba(255,255,255,0.92)',
  navBorder: 'rgba(20,20,19,0.10)',
  glassTop: 'rgba(255,255,255,0.86)',
  glassBottom: 'rgba(255,255,255,0.46)',
  glassBorder: 'rgba(20,20,19,0.10)',
  glassBacking: 'rgba(255,255,255,0.72)',
  glassHighlight: 'rgba(255,255,255,0.90)',
  background: palette.paper[50],
  surface: palette.paper[0],
  surfaceSunken: palette.paper[100],
  border: palette.paper[200],
  borderStrong: palette.paper[300],

  textPrimary: palette.ink[900],
  textSecondary: palette.ink[500],
  textTertiary: palette.ink[300],
  textOnAccent: palette.paper[0],

  accent: palette.jamr.light,
  accentSoft: palette.jamr.lightSoft,
  accentText: palette.jamr.lightText,

  positive: palette.nakhl.light,
  positiveSoft: '#E3EFE8',
  negative: palette.rumman.light,
  negativeSoft: '#F7E6E5',
  caution: palette.kathib.light,
  cautionSoft: '#F5EEDF',
  info: palette.sama.light,
  infoSoft: '#E6EDF4',

  privacyVeil: palette.paper[50],
  scrim: withAlpha(palette.ink[900], 0.4),
};

export const darkColors: ColorScheme = {
  /** `#1A1512` — قمّةُ التدرّج القُطريّ في `.screen`. */
  backdropWarm: '#1A1512',
  /** المرجان `#E09A6B` — طرفُ التدرّج الفاتح. */
  accentGlow: '#E09A6B',
  /** `.nav` في النموذج: `rgba(26,21,18,.9)` وحدٌّ `#4A3B2E`. */
  navSurface: 'rgba(26,21,18,0.9)',
  navBorder: '#4A3B2E',
  /** بقيم `.glass` في النموذج المعتمد حرفاً بحرف. */
  glassTop: 'rgba(255,255,255,0.10)',
  glassBottom: 'rgba(255,255,255,0.035)',
  glassBorder: 'rgba(255,255,255,0.15)',
  glassBacking: 'rgba(16,15,14,0.55)',
  glassHighlight: 'rgba(255,255,255,0.09)',
  background: palette.night[950],
  surface: palette.night[900],
  surfaceSunken: palette.night[800],
  border: palette.night[700],
  borderStrong: palette.night[600],

  textPrimary: palette.glow[0],
  textSecondary: palette.glow[400],
  textTertiary: palette.glow[600],
  textOnAccent: palette.night[950],

  accent: palette.jamr.dark,
  accentSoft: palette.jamr.darkSoft,
  // في الداكن يبلغ الجمر 5.38:1 على تعبئته، فلا حاجة إلى نسخةٍ ثانية.
  accentText: palette.jamr.dark,

  positive: palette.nakhl.dark,
  positiveSoft: '#122419',
  negative: palette.rumman.dark,
  negativeSoft: '#2B1614',
  caution: palette.kathib.dark,
  cautionSoft: '#271F12',
  info: palette.sama.dark,
  infoSoft: '#141F2B',

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
      return { fg: colors.accentText, bg: colors.accentSoft };
    case 'neutral':
    default:
      return { fg: colors.textSecondary, bg: colors.surfaceSunken };
  }
};
