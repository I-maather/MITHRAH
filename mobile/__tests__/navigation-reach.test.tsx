import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';

import { TABS } from '@/components';
import { ALLOWED_DEEP_LINK_TARGETS } from '@/utils/deepLinks';

/**
 * **كل شاشة يجب أن تُفتَح من داخل التطبيق.**
 *
 * ## العطل الذي فرض هذا الملف
 *
 * كانت عشرٌ من أربع عشرة شاشة مبنيّةً ومسجَّلةً في `_layout` ومُختبَرة —
 * **ولا صفَّ انتقالٍ واحد يفتحها**. التبويبات الأربعة تصل إلى أربع، وثلاثة
 * صفوف في «الرئيسية» تصل إلى ثلاث، والباقي — «ماذا رأيتُ اليوم» و«خط
 * التدقيق» و«الطوارئ» وغيرها — لا يُفتَح إلا برابطٍ عميق من إشعار. و«ماذا
 * رأيتُ اليوم» لم يكن حتى في قائمة الروابط العميقة: لا طريق إليها بحال.
 *
 * وهو العطل الحاكم في هذا المشروع بصورةٍ جديدة: شيءٌ بُني ولم يُنفَّذ قط.
 * وكل اختبارات تلك الشاشات كانت تمرّ، لأنها تُصيّر المكوّن مباشرةً ولا يسأل
 * أحدها: **هل يصل إليه أحد؟**
 *
 * ## كيف يُفحَص
 *
 * فحصٌ نصّي على المصدر — لا تصيير. يبدأ من جذور التبويبات، ويتبع كل
 * `href="/(app)/…"` في ملفات الشاشات، ويطالب بأن تُبلَغ كل شاشة.
 */

const SCREENS_DIR = join(__dirname, '..', 'app', '(app)');

const screenNames = readdirSync(SCREENS_DIR)
  .filter((f) => f.endsWith('.tsx') && f !== '_layout.tsx')
  .map((f) => f.replace(/\.tsx$/, ''))
  .sort();

const sourceOf = (name: string): string =>
  readFileSync(join(SCREENS_DIR, `${name}.tsx`), 'utf8');

/** كل وجهة داخلية يفتحها هذا الملف. */
const linksFrom = (name: string): string[] => {
  const out = new Set<string>();
  for (const match of sourceOf(name).matchAll(/href="\/\(app\)\/([a-z-]+)"/g)) {
    out.add(match[1] as string);
  }
  return [...out];
};

const tabRoots = TABS.map((tab) => tab.path.replace(/^\//, ''));

/** البحث بالعرض من جذور التبويبات. */
const reachable = ((): Set<string> => {
  const seen = new Set<string>(tabRoots);
  const queue = [...tabRoots];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    if (!screenNames.includes(current)) continue;
    for (const next of linksFrom(current)) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return seen;
})();

describe('لا شاشة بلا طريق', () => {
  it('كل ملف شاشة مسجَّل في `_layout`', () => {
    // شاشةٌ غير مسجَّلة تفتح بعنوانٍ فارغ وبلا زرّ رجوع.
    const layout = readFileSync(join(SCREENS_DIR, '_layout.tsx'), 'utf8');
    const missing = screenNames.filter((n) => !layout.includes(`name="${n}"`));
    expect(missing).toEqual([]);
  });

  it('**كل شاشة يُبلَغ إليها من تبويب أو من صفٍّ في شاشة تبويب**', () => {
    const orphans = screenNames.filter((n) => !reachable.has(n));
    expect(orphans).toEqual([]);
  });

  it('كل تبويب يملك شاشةً موجودة', () => {
    const broken = tabRoots.filter((n) => !screenNames.includes(n));
    expect(broken).toEqual([]);
  });

  it('كل شاشة تنتمي إلى تبويب — فلا يفقد الشريط موضعه فيها', () => {
    /**
     * شاشةٌ خارج `owns` تُفتَح ولا تبويب مضاء: يفقد المستخدم موضعه في
     * التطبيق ولا يعرف من أين جاء.
     */
    const owned = new Set(TABS.flatMap((tab) => tab.owns.map((p) => p.replace(/^\//, ''))));
    const homeless = screenNames.filter((n) => !owned.has(n));
    expect(homeless).toEqual([]);
  });

  it('كل وجهة رابطٍ عميق شاشةٌ موجودة', () => {
    const broken = ALLOWED_DEEP_LINK_TARGETS.filter((n) => !screenNames.includes(n));
    expect(broken).toEqual([]);
  });
});
