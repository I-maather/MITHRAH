

/**
 * تُطفأ بيانات المعاينة: بدونها تعرض الشاشة تجهيزة `fixtures` بدل الاستجابة
 * المُقلَّدة، فيمرّ الاختبار على بياناتٍ لم يُرسلها هذا الفحص أصلاً.
 */
jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: false,
}));

import ManagementScreen from '../app/(app)/management';
import { tokenStore } from '@/auth/tokenStore';
import { envelope, fetchReturning, renderWithHarness } from './helpers';

/**
 * إدارةُ المراكز في وضع الظلّ.
 *
 * المحرّك يبني خطّةً كلَّ دورة ولا ينفّذ منها شيئاً: لا سياسةَ ديناميكيةٍ
 * مُسجَّلة، لأنّ الدليل شرطُ التسجيل. وشاشةٌ تعرض «صفر أفعال» وتسكت تقول
 * للمالكة إنّ كلَّ شيءٍ على ما يُرام — وهي لا تعرف أذلك عن رضاً أم عن عطل.
 *
 * فالمقياس هنا ليس أن الشاشة تُصيَّر، بل أنّ **ما لم يُفعَل ولماذا** يظهر
 * بنفس بروز ما فُعل.
 */

const plan = (over: Record<string, unknown> = {}) =>
  envelope('management', {
    sync: {
      ok: true, reason_code: 'OK', error_ar: '',
      last_sync_utc: '2026-09-05T14:30:00Z', age_seconds: 4, stale: false,
    },
    available: true,
    reason_ar: '',
    plan_at_utc: '2026-09-05T14:30:04Z',
    action_count: 0,
    actions: [],
    skipped: [
      {
        deal_id: 'd-1', symbol: 'GBPUSD', code: 'UNATTRIBUTED',
        code_ar: 'بلا نسبة',
        reason_ar: 'مركزٌ بلا نسبةٍ إلى قرار — يبقى على خروجه الثابت ويُراقَب.',
      },
      {
        deal_id: 'd-2', symbol: 'GOLD', code: 'NOT_RECONCILED',
        code_ar: 'غير مطابَق',
        reason_ar: 'المركز في الدفتر ولا يظهر عند الوسيط الآن — لا يُعدَّل.',
      },
    ],
    declared_policies: [],
    dynamic_enabled: false,
    notes_ar: [
      'لا سياسةَ إدارةٍ ديناميكية مفعّلة: الدليل شرطُ التفعيل، والمراكز على خروجها الثابت المعتمد عند الدخول.',
    ],
    ...over,
  });

const render = (payload: unknown) =>
  renderWithHarness(<ManagementScreen />, {
    status: 'UNLOCKED',
    fetchImpl: fetchReturning(payload) as unknown as typeof fetch,
  });

describe('إدارةُ المراكز — وضع الظلّ', () => {
  beforeEach(async () => {
    await tokenStore.save({
      accessToken: 'test-access',
      refreshToken: 'test-refresh',
      deviceId: 'test-device',
      accessExpiresAt: Date.now() + 900_000,
    });
  });

  it('تُصرّح بأن لا قاعدة ديناميكية مفعّلة', async () => {
    const view = render(plan());
    expect(await view.findByTestId('management-fixed-only')).toBeTruthy();
  });

  it('**لا تكتفي بصفر أفعال — تعرض كلَّ متخطٍّ بسببه**', async () => {
    const view = render(plan());
    expect(await view.findByTestId('management-skipped')).toBeTruthy();
    expect(
      await view.findByText(
        'مركزٌ بلا نسبةٍ إلى قرار — يبقى على خروجه الثابت ويُراقَب.',
      ),
    ).toBeTruthy();
    expect(
      await view.findByText(
        'المركز في الدفتر ولا يظهر عند الوسيط الآن — لا يُعدَّل.',
      ),
    ).toBeTruthy();
  });

  it('تقول إنّ الأفعال صفر بلا مواربة', async () => {
    const view = render(plan());
    expect(await view.findByTestId('management-no-actions')).toBeTruthy();
  });

  it('السببُ يُعرَض كما كتبه الخادم، لا مُعاد الصياغة', async () => {
    const view = render(
      plan({
        skipped: [
          {
            deal_id: 'd-9', symbol: 'EURUSD', code: 'NO_STOP',
            code_ar: 'بلا وقف',
            reason_ar: 'نصٌّ فريدٌ لا يعرفه إلا الخادم.',
          },
        ],
      }),
    );
    expect(await view.findByText('نصٌّ فريدٌ لا يعرفه إلا الخادم.')).toBeTruthy();
  });

  it('حين تفشل قراءة المحفظة تُعلن ذلك ولا تعرض خطّةً كأنها حديثة', async () => {
    const view = render(
      plan({
        sync: {
          ok: false, reason_code: 'BROKER_UNREACHABLE',
          error_ar: 'لا اتصال بالوسيط.',
          last_sync_utc: null, age_seconds: null, stale: true,
        },
      }),
    );
    expect(await view.findByTestId('management-sync-failed')).toBeTruthy();
  });

  it('لا سياسةَ معلَنة اليوم — وتقولها الشاشة', async () => {
    const view = render(plan());
    expect(await view.findByTestId('management-no-policies')).toBeTruthy();
  });
});
