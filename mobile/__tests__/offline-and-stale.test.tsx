import { screen } from '@testing-library/react-native';

import { ApiError } from '@/api/client';
import { STALE_AFTER_MS } from '@/api/useEndpoint';
import { ErrorState, OfflineBanner, StaleBanner } from '@/components';
import { formatSince } from '@/i18n';
import { renderWithHarness } from './helpers';

/**
 * الانقطاع والقِدَم.
 *
 * القاعدة: **لا تُمحى البيانات عند الانقطاع، بل تُوسَم**. شاشة فارغة تخفي أن
 * الرقم الذي رأيته قبل دقيقة ما يزال آخر ما وصل؛ شاشة قديمة موسومة تقول ذلك.
 */

describe('شريط الانقطاع', () => {
  it('يقول إن ما يُعرض قد يكون قديماً', () => {
    renderWithHarness(<OfflineBanner />, { status: 'UNLOCKED' });
    const banner = screen.getByTestId('offline-banner');
    expect(String(banner.props.accessibilityLabel)).toContain('لا اتصال بالخادم');
    expect(String(banner.props.accessibilityLabel)).toContain('قديماً');
  });

  it('يُعلَن بوصفه تنبيهاً لا نصّاً عادياً', () => {
    renderWithHarness(<OfflineBanner />, { status: 'UNLOCKED' });
    expect(screen.getByTestId('offline-banner').props.accessibilityRole).toBe('alert');
  });
});

describe('شريط القِدَم', () => {
  it('يذكر منذ متى لم تصل حالة', () => {
    renderWithHarness(<StaleBanner sinceLabel="منذ 5 دقيقة" />, { status: 'UNLOCKED' });
    expect(String(screen.getByTestId('stale-banner').props.accessibilityLabel)).toContain(
      'منذ 5 دقيقة',
    );
  });

  it('عتبة القِدَم قصيرة بما يكفي لرقم مالي', () => {
    expect(STALE_AFTER_MS).toBeLessThanOrEqual(120_000);
  });
});

describe('صياغة العمر', () => {
  const now = new Date('2026-01-15T13:40:00Z').getTime();

  it('«الآن» للثواني القليلة', () => {
    expect(formatSince('2026-01-15T13:39:30Z', now)).toBe('الآن');
  });

  it('بالدقائق ثم بالساعات', () => {
    expect(formatSince('2026-01-15T13:20:00Z', now)).toBe('منذ 20 دقيقة');
    expect(formatSince('2026-01-15T09:40:00Z', now)).toBe('منذ 4 ساعة');
  });

  it('غياب القيمة يُقال شرطةً لا صفراً', () => {
    expect(formatSince(null, now)).toBe('—');
    expect(formatSince('ليس تاريخاً', now)).toBe('—');
  });
});

describe('رسائل الخطأ', () => {
  it('الانقطاع يُصنَّف تنبيهاً لا عطلاً', () => {
    renderWithHarness(<ErrorState error={new ApiError('OFFLINE', 'x')} />, {
      status: 'UNLOCKED',
    });
    expect(screen.getByTestId('error-state')).toBeTruthy();
    expect(screen.getByText(/لا اتصال بالخادم/)).toBeTruthy();
  });

  it('خادم مجهول الهوية يُقال صراحةً ولا يُخلط بالانقطاع', () => {
    renderWithHarness(<ErrorState error={new ApiError('UNTRUSTED_ENDPOINT', 'x')} />, {
      status: 'UNLOCKED',
    });
    expect(screen.getByText(/هوية الخادم غير مؤكدة/)).toBeTruthy();
  });

  it('استجابة مرفوضة تُقال بوصفها مرفوضة لا مفقودة', () => {
    renderWithHarness(<ErrorState error={new ApiError('MALFORMED', 'x')} />, {
      status: 'UNLOCKED',
    });
    expect(screen.getByText(/أُهملت ولم تُعرض/)).toBeTruthy();
  });

  it('زر إعادة المحاولة يحمل تسمية منطوقة', () => {
    renderWithHarness(
      <ErrorState error={new ApiError('OFFLINE', 'x')} onRetry={() => undefined} />,
      { status: 'UNLOCKED' },
    );
    const retry = screen.getByTestId('retry-button');
    expect(String(retry.props.accessibilityLabel).length).toBeGreaterThan(0);
  });
});
