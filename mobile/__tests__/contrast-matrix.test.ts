import { readFileSync } from 'fs';
import { join } from 'path';

import { darkColors, lightColors, type ColorScheme } from '@/theme/colors';
import { CONTRAST_TEXT, CONTRAST_UI, contrastRatio } from '@/theme/contrast';

/**
 * مصفوفةُ تباينٍ مولَّدة — لا قيمةٌ منقولة بالعين.
 *
 * تعليقُ `tokens.ts` يقول إنّ `glow.600` «مضبوطٌ ليجتاز 4.5:1 على
 * `night.950`» — وهو صحيح. لكنه ضُبط على **الخلفية**، ومعظم النصّ الثالثي
 * يقع **داخل بطاقة**. والفرق بينهما هو الفرق بين تصريحٍ صحيح ونتيجةٍ خاطئة.
 *
 * فتُولَّد هنا كل التركيبات الممكنة (نصّ × سطح × وضع)، وتُفحص عناصر
 * الواجهة غير النصّية على حدة عند 3:1 — وهي العتبة التي سقط عندها العنصر
 * التوقيعيّ للنظام نفسه: مسارُ «الحدّ» عند **1.37 : 1**.
 */

/** الأسطح التي يظهر النصّ فوقها فعلاً. */
const SURFACES: (keyof ColorScheme)[] = ['background', 'surface', 'surfaceSunken'];

/** النصوص التي يجب أن تُقرأ على كل واحدٍ منها. */
const TEXTS: (keyof ColorScheme)[] = ['textPrimary', 'textSecondary', 'textTertiary'];

/** عناصر واجهةٍ غير نصّية: حدود ومسارات ومؤشّرات. */
/**
 * `borderStrong` هو ما تُرسم به **المسارات والمؤشّرات** — عناصرٌ لا يُفهَم
 * المحتوى بدونها (WCAG 1.4.11)، فعتبتها 3:1.
 *
 * أمّا `border` فحدٌّ زخرفيّ يجمع بطاقةً ولا يحمل معلومة، وهو خارج نطاق
 * 1.4.11. ولا يُدَّعى أنه يجتاز: يُقاس ويُعلَن أدناه بقيمته.
 */
const UI_ON_SURFACE: [keyof ColorScheme, keyof ColorScheme][] = [
  ['borderStrong', 'background'],
  ['borderStrong', 'surface'],
  ['borderStrong', 'surfaceSunken'],
];

const MODES: [string, ColorScheme][] = [
  ['فاتح', lightColors],
  ['داكن', darkColors],
];

const ratio = (scheme: ColorScheme, a: keyof ColorScheme, b: keyof ColorScheme): number =>
  contrastRatio(scheme[a] as string, scheme[b] as string);

describe('مصفوفة التباين', () => {
  it.each(MODES)('النصّ يُقرأ على كل سطح — %s', (_mode, scheme) => {
    const failures: string[] = [];
    for (const text of TEXTS) {
      for (const surface of SURFACES) {
        const value = ratio(scheme, text, surface);
        if (value < CONTRAST_TEXT) {
          failures.push(`${String(text)} على ${String(surface)} = ${value.toFixed(2)}:1`);
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it.each(MODES)('عناصر الواجهة تُرى — %s', (_mode, scheme) => {
    const failures: string[] = [];
    for (const [element, surface] of UI_ON_SURFACE) {
      const value = ratio(scheme, element, surface);
      if (value < CONTRAST_UI) {
        failures.push(`${String(element)} على ${String(surface)} = ${value.toFixed(2)}:1`);
      }
    }
    expect(failures).toEqual([]);
  });

  it.each(MODES)('نصّ الشارة يُقرأ على تعبئتها — %s', (_mode, scheme) => {
    const pairs: [keyof ColorScheme, keyof ColorScheme][] = [
      ['accentText', 'accentSoft'],
      ['positive', 'positiveSoft'],
      ['negative', 'negativeSoft'],
      ['caution', 'cautionSoft'],
      ['info', 'infoSoft'],
      ['textOnAccent', 'accent'],
    ];
    const failures: string[] = [];
    for (const [fg, bg] of pairs) {
      const value = ratio(scheme, fg, bg);
      if (value < CONTRAST_TEXT) {
        failures.push(`${String(fg)} على ${String(bg)} = ${value.toFixed(2)}:1`);
      }
    }
    expect(failures).toEqual([]);
  });
});

describe('الحساب نفسه', () => {
  it('الأسود على الأبيض 21:1', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 1);
  });
  it('اللون على نفسه 1:1', () => {
    expect(contrastRatio('#B85A26', '#B85A26')).toBeCloseTo(1, 5);
  });
  it('الشفافية تُقطَع قبل القياس', () => {
    expect(contrastRatio('#000000FF', '#FFFFFF')).toBeCloseTo(21, 1);
  });
});

describe('الحدّ الزخرفي — يُقاس ويُعلَن، ولا يُدَّعى', () => {
  /**
   * حدُّ البطاقة لا يحمل معلومة، فلا تنطبق عليه 1.4.11. لكنّ `tokens.ts`
   * ينصّ: «الفصل يتمّ بالحدّ لا بالظلّ… وحدٌّ لا يُرى ليس حدّاً». فالرقم
   * مثبَّتٌ هنا كي لا يُخفَض بصمت، ومكتوبٌ أنه دون 3:1 عن قصد.
   */
  it.each(MODES)('قيمته معروفة ومثبَّتة — %s', (_mode, scheme) => {
    const onSurface = ratio(scheme, 'border', 'surface');
    expect(onSurface).toBeGreaterThan(1.2);
    expect(onSurface).toBeLessThan(3);
  });

  it('المسارات لا تُرسم بالحدّ الزخرفي', () => {
    const hadd = readFileSync(join(__dirname, '..', 'src', 'components', 'Hadd.tsx'), 'utf8');
    const meter = readFileSync(join(__dirname, '..', 'src', 'components', 'RiskMeter.tsx'), 'utf8');
    expect(hadd).toContain('theme.colors.borderStrong');
    expect(meter).toContain('theme.colors.borderStrong');
    expect(meter).not.toContain('backgroundColor: theme.colors.surfaceSunken,');
  });
});
