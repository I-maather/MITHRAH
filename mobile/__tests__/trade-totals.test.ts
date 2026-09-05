/**
 * المحقَّق مصنَّفاً — وبند التدقيق `E2` بنصّه.
 */
import { anyMissing, money, parseMoney, totalsByKind } from '@/utils/tradeTotals';

describe('قراءة المبلغ من نصّ الخادم', () => {
  it('تقرأ السالب بالشرطة العربية كما تقرأ اللاتيني', () => {
    expect(parseMoney('−0.79')).toBeCloseTo(-0.79);
    expect(parseMoney('-0.79')).toBeCloseTo(-0.79);
  });

  it('تتجاهل الفواصل والمسافات وإشارة الموجب', () => {
    expect(parseMoney('+1,024.50')).toBeCloseTo(1024.5);
  });

  it('وما ليس رقماً يعود `null` لا صفراً', () => {
    expect(parseMoney(null)).toBeNull();
    expect(parseMoney('')).toBeNull();
    expect(parseMoney('غير متاح')).toBeNull();
    expect(parseMoney('−')).toBeNull();
  });
});

describe('ثلاثة أرقامٍ لا رقمٌ واحد', () => {
  const trades = [
    { kind: 'STRATEGY', realised_pnl: '−0.79' },
    { kind: 'ADMINISTRATIVE', realised_pnl: '−0.34' },
    { kind: 'COMMISSIONING', realised_pnl: '−0.01' },
  ];

  it('يفصل كل نسبةٍ عن الأخرى', () => {
    const t = totalsByKind(trades);
    expect(t.STRATEGY.value).toBeCloseTo(-0.79);
    expect(t.ADMINISTRATIVE.value).toBeCloseTo(-0.34);
    expect(t.COMMISSIONING.value).toBeCloseTo(-0.01);
  });

  it('ولا يجمعها — الرقمُ الرابع لا وجود له في هذه الوحدة', () => {
    const t = totalsByKind(trades);
    expect(Object.keys(t).sort()).toEqual(
      ['ADMINISTRATIVE', 'COMMISSIONING', 'STRATEGY', 'UNATTRIBUTED'].sort(),
    );
    expect(t).not.toHaveProperty('total');
  });

  it('وما لا نسبة له يُصنَّف `UNATTRIBUTED` ولا يُلحق باستراتيجية', () => {
    const t = totalsByKind([
      { kind: null, realised_pnl: '−5.00' },
      { kind: 'WHATEVER', realised_pnl: '−1.00' },
    ]);
    expect(t.UNATTRIBUTED.value).toBeCloseTo(-6);
    expect(t.STRATEGY.counted).toBe(0);
  });
});

describe('الجهل يُعَدّ ولا يُجمَع صفراً', () => {
  it('صفقةٌ بلا نتيجة تُعَدّ ناقصةً لا صفراً', () => {
    const t = totalsByKind([
      { kind: 'STRATEGY', realised_pnl: '−1.00' },
      { kind: 'STRATEGY', realised_pnl: null },
    ]);
    expect(t.STRATEGY.value).toBeCloseTo(-1);
    expect(t.STRATEGY.counted).toBe(1);
    expect(t.STRATEGY.missing).toBe(1);
  });

  it('والنقص يُعلَن على مستوى الشاشة', () => {
    const t = totalsByKind([
      { kind: 'STRATEGY', realised_pnl: null },
      { kind: 'ADMINISTRATIVE', realised_pnl: null },
    ]);
    expect(anyMissing(t)).toBe(2);
  });

  it('ولا نقص في سجلٍّ مكتمل', () => {
    expect(anyMissing(totalsByKind([{ kind: 'STRATEGY', realised_pnl: '1.00' }]))).toBe(0);
  });

  it('سجلٌّ فارغ ليس نقصاً', () => {
    const t = totalsByKind([]);
    expect(anyMissing(t)).toBe(0);
    expect(t.STRATEGY.counted).toBe(0);
  });
});

describe('كتابة المبلغ', () => {
  it('الإشارة مع الرقم دائماً، والصفر بلا إشارة', () => {
    expect(money(-0.79)).toBe('−0.79');
    expect(money(1.5)).toBe('+1.50');
    expect(money(0)).toBe('0.00');
  });
});
