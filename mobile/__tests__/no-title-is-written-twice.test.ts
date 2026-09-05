import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';

/**
 * العنوان مرّةً واحدة.
 *
 * كان هيدرُ التنقّل يكتب اسم الشاشة، ثم يكتبه `Screen` تحته بحجم `display`
 * — نصٌّ واحد فوق نفسه، و~٩٠ نقطة تُهدَر في أعلى أربع عشرة شاشة. وعُولج
 * في الرئيسية وحدها وتُرك في البقية، وهو ما يُنتج بالضبط: علاجٌ يُطبَّق
 * على ما يُنظَر إليه.
 */

const MOBILE = join(__dirname, '..');
const LAYOUT = join(MOBILE, 'app', '(app)', '_layout.tsx');
const SCREENS = join(MOBILE, 'app', '(app)');

const layout = (): string => readFileSync(LAYOUT, 'utf8');

describe('لا عنوان يُكتب مرّتين', () => {
  it('الهيدر مُطفأ في خيارات المكدّس', () => {
    const source = layout();
    const options = source.slice(source.indexOf('screenOptions'), source.indexOf('</Stack>'));
    expect(options).toContain('headerShown: false');
  });

  it('لا شاشة تعيد تشغيل الهيدر لنفسها', () => {
    const source = layout();
    const revived = source
      .split('\n')
      .filter((line) => line.includes('Stack.Screen') && line.includes('headerShown: true'));
    expect(revived).toEqual([]);
  });

  it('كل شاشةٍ تحت (app) تستعمل غلاف Screen — فالعنوان والشارة من مكانٍ واحد', () => {
    const files = readdirSync(SCREENS).filter(
      (name) => name.endsWith('.tsx') && name !== '_layout.tsx',
    );
    expect(files.length).toBeGreaterThan(10);
    const missing = files.filter((name) => {
      const source = readFileSync(join(SCREENS, name), 'utf8');
      return !source.includes('<Screen');
    });
    expect(missing).toEqual([]);
  });
});
