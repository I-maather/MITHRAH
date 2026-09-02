
/**
 * تُطفأ بيانات المعاينة: بدونها تعرض الشاشة تجهيزة `fixtures` بدل الاستجابة
 * المُقلَّدة، فيمرّ الاختبار على بياناتٍ لم يُرسلها هذا الفحص أصلاً.
 */
jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: false,
}));

import { fireEvent } from '@testing-library/react-native';

import ChartScreen from '../app/(app)/chart';
import { buildScale, parseCandles, type ChartLevel } from '@/components';
import { tokenStore } from '@/auth/tokenStore';
import { envelope, fetchReturning, renderWithHarness } from './helpers';

/**
 * شاشة الشموع.
 *
 * الفحوص هنا على ما يمكن أن **يكذب**: المقياس، والمستويات التي تخصّ أداةً
 * أخرى، والأسعار التي لا تُقرأ أرقاماً — لا على أن الشاشة تُصيَّر.
 */

const bar = (o: string, h: string, l: string, c: string, hour: number) => ({
  t: `2026-01-14T${String(hour).padStart(2, '0')}:00:00+00:00`,
  o,
  h,
  l,
  c,
});

const candles = (over: Record<string, unknown> = {}) =>
  envelope('market/candles', {
    instruments: {
      EURUSD: {
        DAY: [
          bar('1.10000', '1.10200', '1.09900', '1.10150', 0),
          bar('1.10150', '1.10400', '1.10100', '1.10300', 1),
          bar('1.10300', '1.10350', '1.10050', '1.10100', 2),
        ],
        MINUTE_15: [bar('1.10300', '1.10320', '1.10280', '1.10290', 3)],
      },
      GOLD: { DAY: [bar('2400.00', '2410.00', '2395.00', '2405.00', 0)] },
    },
    symbols: ['EURUSD', 'GOLD'],
    resolutions: ['DAY', 'MINUTE_15'],
    decision_resolution: 'DAY',
    levels: {
      symbol: 'EURUSD',
      entry: '1.10150',
      stop: '1.09950',
      target: '1.10450',
    },
    note_ar: 'الشموع كما رآها النظام في آخر دورة مسح، لا أحدث منها.',
    ...over,
  });

const render = (payload: unknown) =>
  renderWithHarness(<ChartScreen />, {
    status: 'UNLOCKED',
    fetchImpl: fetchReturning(payload) as unknown as typeof fetch,
  });

describe('حساب المقياس', () => {
  const level = (key: ChartLevel['key'], value: number): ChartLevel => ({
    key,
    label: key,
    value,
    color: '#000000',
  });

  it('**الشمعة التي لا تُقرأ أرقاماً تُسقَط ولا تُرسَم على تخمين**', () => {
    const { bars, dropped } = parseCandles([
      bar('1.1', '1.2', '1.0', '1.15', 0),
      bar('لا شيء', '1.2', '1.0', '1.15', 1),
      // قاعٌ فوق القمّة: بياناتٌ متناقضة، لا شمعة.
      bar('1.1', '1.0', '1.2', '1.15', 2),
    ]);
    expect(bars).toHaveLength(1);
    expect(dropped).toBe(2);
  });

  it('يوسّع المقياس لمستوى قريب', () => {
    const { bars } = parseCandles([bar('1.10', '1.12', '1.08', '1.11', 0)]);
    const scale = buildScale(bars, [level('stop', 1.07)]);
    expect(scale.drawn.map((l) => l.key)).toEqual(['stop']);
    expect(scale.offChart).toEqual([]);
    expect(scale.lo).toBeLessThanOrEqual(1.07);
  });

  it('**ولا يوسّعه لمستوى بعيد** — مدُّه يضغط الشموع في خيط', () => {
    /**
     * لو وُسّع المقياس ليبلغ 0.5 على شموعٍ بين 1.08 و1.12، صار مدى الرسم
     * ستين ضعف مدى السعر: الشموع كلها خطٌّ واحد لأجل خطٍّ واحد. والصواب أن
     * يُقال إنه خارج المدى.
     */
    const { bars } = parseCandles([bar('1.10', '1.12', '1.08', '1.11', 0)]);
    const scale = buildScale(bars, [level('stop', 0.5)]);
    expect(scale.drawn).toEqual([]);
    expect(scale.offChart.map((l) => l.key)).toEqual(['stop']);
    // المقياس بقي على السعر وحده (زائد هامشاً صغيراً).
    expect(scale.hi - scale.lo).toBeLessThan(0.06);
  });
});

describe('شاشة الشموع', () => {
  beforeEach(async () => {
    await tokenStore.save({
      accessToken: 'test-access',
      refreshToken: 'test-refresh',
      deviceId: 'test-device',
      accessExpiresAt: Date.now() + 900_000,
    });
  });

  it('ترسم شمعةً لكل صفٍّ وصل', async () => {
    const view = render(candles());
    expect(await view.findByTestId('candle-0')).toBeTruthy();
    expect(view.getByTestId('candle-2')).toBeTruthy();
    expect(view.queryByTestId('candle-3')).toBeNull();
  });

  it('**الاتجاه بالشكل لا باللون** — الصاعدة مجوّفة والهابطة مصمتة', async () => {
    /**
     * معنى يُحمَل باللون وحده يسقط عند عمى الألوان. والشمعة الثالثة هنا
     * هابطة (1.10300 ⇐ 1.10100) والأولى صاعدة.
     */
    const view = render(candles());
    const rising = await view.findByTestId('candle-body-0');
    const falling = view.getByTestId('candle-body-2');
    const bg = (node: { props: Record<string, unknown> }): unknown =>
      (node.props.style as { backgroundColor?: unknown }).backgroundColor;
    expect(bg(rising)).toBe('transparent');
    expect(bg(falling)).not.toBe('transparent');
  });

  it('**لا تُرسَم مستويات مركزٍ على أداةٍ أخرى**', async () => {
    /**
     * وقفٌ عند 1.0995 مرسومٌ على ذهبٍ عند 2400 ليس خطأً في المقياس بل كذبةٌ
     * في المعنى: يقرأ الناظر أن له وقفاً على الذهب وليس له.
     */
    const view = render(candles());
    expect(await view.findByTestId('chart-level-stop')).toBeTruthy();
    fireEvent.press(view.getByTestId('chart-pick-GOLD'));
    expect(view.queryByTestId('chart-level-stop')).toBeNull();
    expect(view.getByTestId('chart-no-levels')).toBeTruthy();
  });

  it('بلا مركز: لا خطوط، ويُقال ذلك بنصّه', async () => {
    const view = render(
      candles({ levels: { symbol: null, entry: null, stop: null, target: null } }),
    );
    expect(await view.findByTestId('chart-no-levels')).toBeTruthy();
    expect(view.queryByTestId('chart-level-entry')).toBeNull();
  });

  it('لا شموع بعد: تُقال العلّة ولا يُعرض فراغٌ صامت', async () => {
    const view = render(
      candles({
        instruments: {},
        symbols: [],
        resolutions: [],
        levels: { symbol: null, entry: null, stop: null, target: null },
        note_ar: 'لم تُقرأ شموعٌ بعد — دورة المسح لم تكتمل.',
      }),
    );
    expect(await view.findByTestId('chart-empty')).toBeTruthy();
  });

  it('**لا تدّعي «مباشر»** — النصّ من الخادم كما هو', async () => {
    const view = render(candles());
    await view.findByTestId('candle-0');
    expect(view.getByTestId('chart-note')).toHaveTextContent(/آخر دورة مسح/);
    expect(view.queryByText(/مباشر/)).toBeNull();
  });

  it('لا زر تداول في هذه الشاشة', async () => {
    const view = render(candles());
    await view.findByTestId('candle-0');
    for (const forbidden of ['شراء', 'بيع', 'أغلق المركز', 'نفّذ']) {
      expect(view.queryByText(forbidden)).toBeNull();
    }
  });
});

describe('أطر الشموع', () => {
  beforeEach(async () => {
    await tokenStore.save({
      accessToken: 'test-access',
      refreshToken: 'test-refresh',
      deviceId: 'test-device',
      accessExpiresAt: Date.now() + 900_000,
    });
  });

  it('تبدأ على إطار القرار لا على أقصر إطار', async () => {
    /**
     * عرضُ الربع ساعة ابتداءً يوحي بأن النظام يقرّر عليه — وهو لا يقرّر،
     * وقيدُ الوسيط يمنعه أصلاً.
     */
    const view = render(candles());
    expect(await view.findByTestId('candle-0')).toBeTruthy();
    expect(view.getByTestId('candle-2')).toBeTruthy();
    expect(view.queryByTestId('chart-view-only')).toBeNull();
  });

  it('**تقول صراحةً أن الإطار الآخر للعرض وحده**', async () => {
    const view = render(candles());
    await view.findByTestId('candle-0');
    fireEvent.press(view.getByTestId('chart-frame-MINUTE_15'));
    expect(view.getByTestId('chart-view-only')).toBeTruthy();
    // شمعةٌ واحدة في هذا الإطار — أي أن المعروض تغيّر فعلاً لا الوسم وحده.
    expect(view.queryByTestId('candle-1')).toBeNull();
  });

  it('أداةٌ بإطارٍ واحد لا تعرض منتقي أطر', async () => {
    const view = render(candles());
    await view.findByTestId('candle-0');
    fireEvent.press(view.getByTestId('chart-pick-GOLD'));
    expect(view.queryByTestId('chart-frame-MINUTE_15')).toBeNull();
  });
});
