

/**
 * تُطفأ بيانات المعاينة: بدونها تعرض الشاشة تجهيزة `fixtures` بدل الاستجابة
 * المُقلَّدة، فيمرّ الاختبار على بياناتٍ لم يُرسلها هذا الفحص أصلاً.
 */
jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: false,
}));

import ScanScreen from '../app/(app)/scan';
import { tokenStore } from '@/auth/tokenStore';
import { envelope, fetchReturning, renderWithHarness } from './helpers';

/**
 * «ماذا رأيتُ اليوم» — الشاشة التي يخلو منها كل منافس.
 *
 * بحث المنافسين فحص ٦٩ لقطة من ١٨ تطبيقاً ولم يجد **شاشةً واحدة** تقول
 * «لماذا لم أتداول». وهذه هي، فتُفحَص بما يميّزها لا بأنها تُصيَّر.
 */

const scan = (over: Record<string, unknown> = {}) =>
  envelope('scan/latest', {
    instruments: [
      {
        symbol: 'EURUSD', decision: 'NO_TRADE', reason_code: 'NO_APPROVED_STRATEGY',
        reason_ar: 'لا استراتيجية معتمدة.', stage: 'strategy', needs_a_hand: false,
      },
      {
        symbol: 'GOLD', decision: 'NO_TRADE', reason_code: 'INSUFFICIENT_BARS',
        reason_ar: 'وصلت 41 شمعة فقط.', stage: 'runtime', needs_a_hand: true,
      },
    ],
    scanned: 2,
    faults: 1,
    summary_ar: 'نُظِر في 2 أداة، و1 منها لم تُقرأ بياناتها.',
    ...over,
  });

const render = (payload: unknown) =>
  renderWithHarness(<ScanScreen />, {
    status: 'UNLOCKED',
    fetchImpl: fetchReturning(payload) as unknown as typeof fetch,
  });

describe('ماذا رأيتُ اليوم', () => {
  beforeEach(async () => {
    // رموزٌ صالحة: بدونها تعرض الشاشة «انتهت الجلسة» ويمرّ كل فحصٍ على
    // شاشة خطأ بدل الشاشة المقصودة.
    await tokenStore.save({
      accessToken: 'test-access',
      refreshToken: 'test-refresh',
      deviceId: 'test-device',
      accessExpiresAt: Date.now() + 900_000,
    });
  });

  it('يعرض صفّاً لكل أداة نُظِر فيها', async () => {
    const view = render(scan());
    expect(await view.findByTestId('scan-row-EURUSD')).toBeTruthy();
    expect(await view.findByTestId('scan-row-GOLD')).toBeTruthy();
  });

  it('**يعرض سبب كل أداة كما كتبه الخادم**', async () => {
    /**
     * لا يُعاد صوغ السبب في الواجهة: جملةٌ تُكتب هنا لا يعرفها سجلّ التدقيق،
     * فتختلف الشاشة عن السجلّ في وصف الحدث نفسه.
     */
    const view = render(scan());
    expect(await view.findByTestId('scan-row-GOLD')).toHaveTextContent(/41 شمعة/);
  });

  it('يفصل العطل عن «لا فرصة» بشارتين مختلفتين', async () => {
    /**
     * «لم أرَ السوق» يُصلَح، و«رأيتُه ولم أجد» عملُ النظام الطبيعي. وعرضهما
     * بلونٍ واحد يجعل المالكة إمّا تقلق كل يوم أو تتجاهل اليوم الذي يهمّ.
     */
    const view = render(scan());
    expect(await view.findByTestId('scan-pill-GOLD')).toHaveTextContent('يحتاج يداً');
    expect(await view.findByTestId('scan-pill-EURUSD')).toHaveTextContent('لا فرصة');
  });

  it('التمييز يأتي من الخادم لا يُستنتَج في الواجهة', async () => {
    /**
     * تكرار المنطق في الواجهة يجعل شاشتين تختلفان على نفس الحقيقة. فالحقل
     * `needs_a_hand` هو الحكم، ولو خالف الرمزُ ظاهرَه.
     */
    const payload = scan();
    (payload.data.instruments[1] as Record<string, unknown>).needs_a_hand = false;
    const view = render(payload);
    // نفس الرمز (`INSUFFICIENT_BARS`) لكن الخادم قال إنه ليس عطلاً — فالحكم له.
    expect(await view.findByTestId('scan-pill-GOLD')).toHaveTextContent('لا فرصة');
    expect(await view.findByTestId('scan-pill-EURUSD')).toHaveTextContent('لا فرصة');
  });

  it('مسحٌ فارغ يقول إن النبض لا يدور — ولا يُعرض فراغاً صامتاً', async () => {
    const view = render(scan({ instruments: [], scanned: 0, faults: 0, summary_ar: 'لم تبدأ دورة مسحٍ بعد.' }));
    expect(await view.findByTestId('scan-empty')).toBeTruthy();
  });

  it('لا زر تداول في هذه الشاشة', async () => {
    const view = render(scan());
    await view.findByTestId('scan-row-EURUSD');
    for (const forbidden of ['شراء', 'بيع', 'أغلق المركز', 'نفّذ']) {
      expect(view.queryByText(forbidden)).toBeNull();
    }
  });
});
