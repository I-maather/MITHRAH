import { duplicateInstruments, sumOf } from '@/api/positionTotals';
import type { OpenPositionView } from '@/api/types';

/**
 * مجموعٌ يُخفي ما سقط منه أسوأ من لا مجموع.
 *
 * يوم 2026-09-04 كان على GBPUSD مركزان في اليوم نفسه — ضِعفُ المخاطرة
 * المعتمدة على أداة واحدة — والشاشة تملك المصفوفة ولا تقول شيئاً.
 */

const position = (over: Partial<OpenPositionView>): OpenPositionView =>
  ({
    id: 'x', instrument: 'EURUSD', instrument_ar: null, direction_ar: 'شراء',
    opened_utc: null, entry_price: null, current_price: null, stop_price: null,
    take_profit_price: null, size_display: null, notional_display: null,
    unrealised_pnl: null, unrealised_pnl_sign: null, risk_at_stop: null,
    protection_held_by_broker: true, strategy_ar: null, kind: 'STRATEGY',
    reconciliation: 'CONFIRMED', last_confirmed_utc: null,
    ...over,
  }) as OpenPositionView;

describe('المجاميع', () => {
  it('تجمع ما أمكن وتعدّ ما سقط', () => {
    const total = sumOf(
      [
        position({ risk_at_stop: '0.75' }),
        position({ risk_at_stop: '1,250.50' }),
        position({ risk_at_stop: null }),
      ],
      'risk_at_stop',
    );
    expect(total.value).toBeCloseTo(1251.25, 2);
    expect(total.counted).toBe(2);
    expect(total.missing).toBe(1);
  });

  it('لا مجموعَ حين لا يُقرأ شيء — لا صفر', () => {
    const total = sumOf([position({}), position({})], 'risk_at_stop');
    expect(total.value).toBeNull();
    expect(total.missing).toBe(2);
  });

  it('قيمةٌ غير رقمية تُعَدّ ساقطة لا صفراً', () => {
    const total = sumOf([position({ notional_display: 'غير متاح' })], 'notional_display');
    expect(total.value).toBeNull();
    expect(total.missing).toBe(1);
  });

  it('القائمة الفارغة لا مجموع لها', () => {
    expect(sumOf([], 'risk_at_stop')).toEqual({ value: null, counted: 0, missing: 0 });
  });
});

describe('تكرار الأداة', () => {
  it('**يكشف مركزين على الأداة نفسها**', () => {
    const found = duplicateInstruments([
      position({ instrument: 'GBPUSD' }),
      position({ instrument: 'GBPUSD' }),
      position({ instrument: 'EURUSD' }),
    ]);
    expect(found).toEqual([{ instrument: 'GBPUSD', count: 2 }]);
  });

  it('الاتجاه لا يُلغي التكرار — مركزان متعاكسان تعرّضان ورسمان', () => {
    const found = duplicateInstruments([
      position({ instrument: 'GBPUSD', direction_ar: 'شراء' }),
      position({ instrument: 'GBPUSD', direction_ar: 'بيع' }),
    ]);
    expect(found).toEqual([{ instrument: 'GBPUSD', count: 2 }]);
  });

  it('حالةُ الأحرف لا تُنشئ أداةً ثانية', () => {
    const found = duplicateInstruments([
      position({ instrument: 'gbpusd' }),
      position({ instrument: 'GBPUSD' }),
    ]);
    expect(found).toEqual([{ instrument: 'GBPUSD', count: 2 }]);
  });

  it('لا تكرار ⇒ قائمة فارغة', () => {
    expect(duplicateInstruments([position({ instrument: 'EURUSD' })])).toEqual([]);
  });
});
