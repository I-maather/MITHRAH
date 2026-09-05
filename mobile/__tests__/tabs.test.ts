/**
 * شريط التبويبات يطابق النموذج المعتمد — بالاسم والترتيب.
 *
 * النموذج المجمَّد في `docs/design/approved/qareeb-2026-09-04.html` يعرض أربعة:
 * اليوم · المحفظة · السجل · النظام. وتسميةٌ تخالفه تجعل المقارنة البصرية
 * تكذب: الشاشة تبدو مطابقةً وطريقُ الوصول إليها مختلف.
 */
import { TABS } from '@/components';

describe('التبويبات كما في النموذج المعتمد', () => {
  it('أربعةٌ بأسمائها وترتيبها', () => {
    expect(TABS.map((t) => t.label)).toEqual(['اليوم', 'المحفظة', 'السجل', 'النظام']);
  });

  it('ولكلٍّ جذرُه', () => {
    expect(TABS.map((t) => t.path)).toEqual(['/home', '/position', '/history', '/system']);
  });

  it('«السجل» تبويبٌ قائمٌ بذاته لا شاشةٌ داخل المحفظة', () => {
    const portfolio = TABS.find((t) => t.path === '/position');
    expect(portfolio?.owns).not.toContain('/history');
    const log = TABS.find((t) => t.path === '/history');
    expect(log).toBeDefined();
    expect(log?.owns).toContain('/history');
  });

  it('و«القرار» جزءٌ من اليوم لا وجهةٌ تُقصَد', () => {
    const today = TABS.find((t) => t.path === '/home');
    expect(today?.owns).toContain('/decision');
    expect(TABS.map((t) => t.path)).not.toContain('/decision');
  });

  it('لا شاشةَ مملوكةٌ لتبويبين', () => {
    const seen = new Set<string>();
    const twice: string[] = [];
    for (const tab of TABS) {
      for (const screen of tab.owns) {
        if (seen.has(screen)) twice.push(screen);
        seen.add(screen);
      }
    }
    expect(twice).toEqual([]);
  });
});
