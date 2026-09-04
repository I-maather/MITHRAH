import { screen } from '@testing-library/react-native';

import NotificationsScreen from '../app/(app)/notifications';
import { fixtures } from '@/fixtures';
import { renderWithHarness } from './helpers';

/**
 * **وضعُ المعاينة يُطلَب هنا صراحةً.**
 *
 * كان `PREVIEW_DATA_ENABLED` يصير `true` تلقائياً حين `__DEV__` — وهي صحيحة
 * داخل Jest. فكانت هذه الشاشات تُختبَر على بيانات المعاينة بلا أن يُعلن ذلك،
 * وكان وضعُ المعاينة يمنع طلب الشبكة، فبقي مسار الخادم بلا اختبارٍ هنا
 * (يغطّيه `sparse-data.test.tsx` صراحةً).
 *
 * صار الافتراضُ إطفاءً، فيُعلَن الاعتماد بدل أن يُورَث.
 */
jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: true,
}));


/**
 * خصوصية الإشعارات.
 *
 * الحدّ المفروض: **لا رقم حساب على شاشة القفل**. التفصيل داخل التطبيق بعد
 * المصادقة فقط، والنص الظاهر خارجاً ثابت لا يعتمد على محتوى الإشعار.
 */

describe('نصّ الخصوصية معروض', () => {
  it('يشرح ما لا يظهر على شاشة القفل', () => {
    renderWithHarness(<NotificationsScreen />, { status: 'UNLOCKED' });
    const banner = screen.getByTestId('lockscreen-privacy-banner');
    const spoken = String(banner.props.accessibilityLabel);
    for (const forbidden of ['رصيد', 'ربح', 'خسارة', 'حجم مركز', 'سعر', 'اتجاه']) {
      expect(spoken).toContain(forbidden);
    }
    expect(spoken).toContain('بعد المصادقة');
  });

  it('يقول إن الإشعار استشاري وإن الحماية لدى الوسيط', () => {
    renderWithHarness(<NotificationsScreen />, { status: 'UNLOCKED' });
    const banner = screen.getByTestId('advisory-banner');
    expect(String(banner.props.accessibilityLabel)).toContain('الوقف والهدف لدى الوسيط');
  });
});

describe('حمولة الإشعار', () => {
  /**
   * مفاتيح لا يجوز أن تظهر في أي حمولة تصل الجهاز. النسخة نفسها موجودة على
   * الخادم (`FORBIDDEN_PAYLOAD_KEYS`)؛ وجودها على الطرفين يكشف الانحراف مبكراً.
   */
  const FORBIDDEN_PAYLOAD_KEYS = [
    'balance',
    'available',
    'profit_loss',
    'pnl',
    'position_size',
    'quantity',
    'entry_price',
    'stop_price',
    'take_profit',
    'account_id',
    'accountId',
    'direction',
    'side',
    'equity',
  ];

  it('نموذج الإشعار في التطبيق لا يحمل أياً من المفاتيح الممنوعة', () => {
    for (const notification of fixtures.notifications.notifications) {
      const keys = Object.keys(notification);
      for (const forbidden of FORBIDDEN_PAYLOAD_KEYS) {
        expect(keys).not.toContain(forbidden);
      }
    }
  });

  it('حقول الإشعار هي النوع والوقت والتفصيل والرابط والقراءة لا غير', () => {
    for (const notification of fixtures.notifications.notifications) {
      expect(Object.keys(notification).sort()).toEqual(
        ['created_utc', 'deep_link', 'in_app_detail_ar', 'read', 'type'].sort(),
      );
    }
  });

  it('روابط الإشعارات كلها داخلية ولا تحمل معاملات', () => {
    for (const notification of fixtures.notifications.notifications) {
      if (notification.deep_link === null) {
        continue;
      }
      expect(notification.deep_link.startsWith('maather://')).toBe(true);
      expect(notification.deep_link).not.toContain('?');
    }
  });
});

describe('التفصيل خلف المصادقة', () => {
  it('التفصيل يُرسم داخل التطبيق بعد الفتح', () => {
    renderWithHarness(<NotificationsScreen />, { status: 'UNLOCKED' });
    expect(screen.getByTestId('notifications-card')).toBeTruthy();
    expect(
      screen.getByText(fixtures.notifications.notifications[0]!.in_app_detail_ar),
    ).toBeTruthy();
  });

  it('لا طلب شبكة يخرج والتطبيق مقفل', async () => {
    const fetchImpl = jest.fn();
    renderWithHarness(<NotificationsScreen />, {
      status: 'LOCKED',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await Promise.resolve();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
