/**
 * محورا الرسم، ومَن يملك اللمسة.
 *
 * قالت المالكة ثلاثاً في جملة: «أقدر أكبّر بس ما أحرّك، والأوقات والتواريخ
 * مو موجودة، وخط السعر». وهذه الفحوص على العلل الثلاث نفسها — لا على أن
 * المكوّن يُصيَّر.
 */

jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: false,
}));

import { PanResponder } from 'react-native';
import { fireEvent } from '@testing-library/react-native';

import ChartScreen from '../app/(app)/chart';
import { barLabel, parseCandles, spanLabel, stepOf } from '@/components';
import { tokenStore } from '@/auth/tokenStore';
import { envelope, fetchReturning, renderWithHarness } from './helpers';

const DAY_MS = 24 * 3600 * 1000;

const bar = (o: string, h: string, l: string, c: string, t: string) => ({
  t,
  o,
  h,
  l,
  c,
});

const payload = () =>
  envelope('market/candles', {
    instruments: {
      EURUSD: {
        DAY: [
          bar('1.10000', '1.10200', '1.09900', '1.10150', '2026-01-12T00:00:00+00:00'),
          bar('1.10150', '1.10400', '1.10100', '1.10300', '2026-01-13T00:00:00+00:00'),
          bar('1.10300', '1.10350', '1.10050', '1.10100', '2026-01-14T00:00:00+00:00'),
        ],
        MINUTE_15: [
          bar('1.10300', '1.10320', '1.10280', '1.10290', '2026-01-14T09:00:00+00:00'),
          bar('1.10290', '1.10330', '1.10270', '1.10310', '2026-01-14T09:15:00+00:00'),
        ],
      },
      // الذهب بمنزلتين عشريتين — لا خمس. والدقّة تُقرأ من النصّ الوارد.
      GOLD: {
        DAY: [bar('2400.00', '2410.00', '2395.00', '2405.00', '2026-01-14T00:00:00+00:00')],
      },
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
  });

const render = () =>
  renderWithHarness(<ChartScreen />, {
    status: 'UNLOCKED',
    fetchImpl: fetchReturning(payload()) as unknown as typeof fetch,
  });

describe('الإطار يُقرأ من الشموع لا من اسمه', () => {
  const rows = (isoList: string[]) =>
    parseCandles(isoList.map((t) => bar('1.1', '1.2', '1.0', '1.15', t))).bars;

  it('**الفارق وسيطٌ لا متوسّط** — عطلةُ نهاية الأسبوع فجوةٌ واحدة تفسد المتوسّط', () => {
    const bars = rows([
      '2026-01-08T00:00:00+00:00',
      '2026-01-09T00:00:00+00:00',
      // قفزةُ عطلة: ثلاثة أيام.
      '2026-01-12T00:00:00+00:00',
      '2026-01-13T00:00:00+00:00',
    ]);
    expect(stepOf(bars)).toBe(DAY_MS);
  });

  it('اليومي يُوسَم بالتاريخ، وما دونه بالساعة', () => {
    const daily = rows(['2026-01-12T00:00:00+00:00', '2026-01-13T00:00:00+00:00']);
    const quarter = rows(['2026-01-14T09:00:00+00:00', '2026-01-14T09:15:00+00:00']);
    expect(barLabel(daily[1]!, stepOf(daily))).toMatch(/^\d{2}\/\d{2}$/);
    expect(barLabel(quarter[1]!, stepOf(quarter))).toMatch(/^\d{2}:\d{2}$/);
  });

  it('**وقتٌ لا يُقرأ لا يُوسَم بتخمين** — والسعر يبقى مرسوماً', () => {
    const parsed = parseCandles([bar('1.1', '1.2', '1.0', '1.15', 'ليس تاريخاً')]);
    expect(parsed.bars).toHaveLength(1);
    expect(parsed.dropped).toBe(0);
    expect(barLabel(parsed.bars[0]!, DAY_MS)).toBe('');
    expect(spanLabel(parsed.bars)).toBe('');
  });

  it('مدى التواريخ يُكتب كاملاً — «14:30» بلا يومٍ نصفُ وسم', () => {
    const bars = rows(['2026-01-12T00:00:00+00:00', '2026-01-14T00:00:00+00:00']);
    expect(spanLabel(bars)).toMatch(/^\d{2}\/\d{2}\/\d{4} — \d{2}\/\d{2}\/\d{4}$/);
  });
});

describe('محورا الرسم', () => {
  beforeEach(async () => {
    await tokenStore.save({
      accessToken: 'test-access',
      refreshToken: 'test-refresh',
      deviceId: 'test-device',
      accessExpiresAt: Date.now() + 900_000,
    });
  });

  it('**خطّ السعر موجود، ومعه رقمه** — خطٌّ بلا رقمٍ يقول «هنا» ولا يقول «كم»', async () => {
    const view = render();
    expect(await view.findByTestId('chart-last-line')).toBeTruthy();
    expect(view.getByTestId('chart-last-price')).toHaveTextContent('1.10100');
  });

  it('**الدقّة تُقرأ من الخادم لا تُفترَض من الأداة**', async () => {
    /**
     * `toFixed(5)` كان يكتب الذهب «2405.00000» — ثلاثة أصفارٍ لا يملكها
     * المصدر، في شاشةٍ قاعدتُها ألّا تُعرض قيمة لم تُقرأ.
     */
    const view = render();
    await view.findByTestId('candle-0');
    fireEvent.press(view.getByTestId('chart-pick-GOLD'));
    expect(view.getByTestId('chart-last-price')).toHaveTextContent('2405.00');
    expect(view.queryByText('2405.00000')).toBeNull();
  });

  it('محور الوقت يحمل تواريخ في اليومي وساعاتٍ في الربع ساعة', async () => {
    const view = render();
    const axis = await view.findByTestId('chart-time-axis');
    expect(axis).toHaveTextContent(/\d{2}\/\d{2}/);
    fireEvent.press(view.getByTestId('chart-frame-MINUTE_15'));
    expect(view.getByTestId('chart-time-axis')).toHaveTextContent(/\d{2}:\d{2}/);
  });

  it('**كل مستوى يحمل اسمه** — ثلاثة خطوطٍ ملوّنة بلا أسماء تُحفَظ ولا تُقرأ', async () => {
    const view = render();
    expect(await view.findByTestId('chart-level-tag-stop')).toHaveTextContent('الوقف');
    expect(view.getByTestId('chart-level-tag-target')).toHaveTextContent('الهدف');
  });

  it('عمود السعر يحمل حدّي المقياس', async () => {
    const view = render();
    const axis = await view.findByTestId('chart-price-axis');
    expect(axis).toHaveTextContent(/1\.\d{5}/);
  });
});

describe('مَن يملك اللمسة', () => {
  beforeEach(async () => {
    await tokenStore.save({
      accessToken: 'test-access',
      refreshToken: 'test-refresh',
      deviceId: 'test-device',
      accessExpiresAt: Date.now() + 900_000,
    });
  });

  it('**يُبنى المُستجيب مرّةً واحدة** — نسخةٌ جديدة في منتصف السحب تبدأ من صفر', async () => {
    /**
     * `PanResponder` يحفظ حالة الإيماءة (`dx`) داخل النسخة نفسها. وكان
     * يُبنى في `useMemo` بتبعيّتين تتغيّران عند أول حركة، فتُستبدل النسخة
     * والإصبع لم يُرفَع بعد — فتقرأ `dx = 0` أبداً. والمالكة رأت ذلك:
     * «أقدر أكبّر بس ما أحرّك». والتقريب كان يعمل لأنه يُحسب من مسافة
     * الإصبعين لا من `dx`.
     */
    const spy = jest.spyOn(PanResponder, 'create');
    const view = render();
    await view.findByTestId('candle-0');
    // إعادة تصيير حقيقية: تبديل الأداة ثم العودة، وتبديل الإطار.
    fireEvent.press(view.getByTestId('chart-frame-MINUTE_15'));
    fireEvent.press(view.getByTestId('chart-frame-DAY'));
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it('**لا تُسلَّم اللمسة إلى الصفحة** — و«ScrollView» تطلبها', async () => {
    const spy = jest.spyOn(PanResponder, 'create');
    const view = render();
    await view.findByTestId('candle-0');
    const config = spy.mock.calls[0]?.[0];
    expect(config).toBeDefined();
    // الجواب لا: الإيماءة الأفقية بدأت في الرسم فتنتهي فيه.
    expect(config?.onPanResponderTerminationRequest?.({} as never, {} as never)).toBe(false);
    // ولا تُؤخذ عند النزول: الأخذ عند النزول يجعل الرسم جداراً لا تُمرَّر
    // الصفحة من فوقه.
    expect(config?.onStartShouldSetPanResponder?.({} as never, {} as never)).toBe(false);
    spy.mockRestore();
  });

  it('السحب الرأسي للصفحة، والأفقي للرسم', async () => {
    const spy = jest.spyOn(PanResponder, 'create');
    const view = render();
    await view.findByTestId('candle-0');
    const should = spy.mock.calls[0]?.[0]?.onMoveShouldSetPanResponder;
    const event = { nativeEvent: { touches: [{}] } } as never;
    expect(should?.(event, { dx: 40, dy: 4 } as never)).toBe(true);
    expect(should?.(event, { dx: 4, dy: 40 } as never)).toBe(false);
    // إصبعان: تقريبٌ مهما كان الاتجاه.
    expect(
      should?.({ nativeEvent: { touches: [{}, {}] } } as never, { dx: 0, dy: 0 } as never),
    ).toBe(true);
    spy.mockRestore();
  });
});
