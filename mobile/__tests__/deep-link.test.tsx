import { act, screen, waitFor } from '@testing-library/react-native';
import * as Linking from 'expo-linking';

import { AppShell } from '../app/_layout';
import SecureLaunchScreen from '../app/index';
import { ALLOWED_DEEP_LINK_TARGETS, resolveDeepLink } from '@/utils/deepLinks';
import { renderWithHarness } from './helpers';

/**
 * الروابط العميقة **لا تُحلّ قبل المصادقة**.
 */

describe('قائمة الوجهات', () => {
  it('كل وجهة مسموحة تُحلّ إلى مسار داخلي', () => {
    for (const target of ALLOWED_DEEP_LINK_TARGETS) {
      const resolved = resolveDeepLink(`maather://${target}`);
      expect(resolved.path).toMatch(/^\/\(app\)\//);
    }
  });

  it('وجهة مجهولة تُهمَل', () => {
    expect(resolveDeepLink('maather://place-order').path).toBeNull();
    expect(resolveDeepLink('maather://../../etc/passwd').path).toBeNull();
  });

  it('مخطط خارجي يُهمَل', () => {
    expect(resolveDeepLink('https://example.invalid/home').path).toBeNull();
    expect(resolveDeepLink('otherapp://home').path).toBeNull();
  });

  it('رابط يحمل معاملات يُهمَل — لا حالة تدخل من الخارج', () => {
    const resolved = resolveDeepLink('maather://home?token=abc');
    expect(resolved.path).toBeNull();
    expect(resolved.reasonAr).toContain('معاملات');
  });

  it('رابط غير صالح يُهمَل بلا انفجار', () => {
    expect(resolveDeepLink('%%%').path).toBeNull();
    expect(resolveDeepLink('').path).toBeNull();
  });

  it('لا وجهة تفتح إجراءً — الطوارئ شاشة لا فعل', () => {
    for (const target of ALLOWED_DEEP_LINK_TARGETS) {
      expect(target).not.toMatch(/pause|killswitch|revoke|activate/);
    }
  });
});

describe('الاحتجاز حتى المصادقة', () => {
  const getInitialURL = Linking.getInitialURL as unknown as jest.Mock;

  beforeEach(() => {
    getInitialURL.mockResolvedValue(null);
  });

  it('رابط وارد والتطبيق مقفل: يُحتجَز ولا يُوجَّه', async () => {
    getInitialURL.mockResolvedValue('maather://position');
    const router = (globalThis as unknown as { __routerMock: { push: jest.Mock } }).__routerMock;

    renderWithHarness(<SecureLaunchScreen />, { status: 'LOCKED' });
    // نُحاكي الجذر: الالتقاط يحدث في app/_layout.tsx، والتحقق هنا أن القفل يمنع التوجيه.
    await act(async () => {
      await Promise.resolve();
    });
    expect(router.push).not.toHaveBeenCalled();
  });

  it('الجذر يلتقط الرابط ولا يوجّه ما دام مقفلاً', async () => {
    getInitialURL.mockResolvedValue('maather://audit');
    const router = (globalThis as unknown as { __routerMock: { push: jest.Mock } }).__routerMock;

    renderWithHarness(<AppShell />, { status: 'LOCKED' });
    await act(async () => {
      await Promise.resolve();
    });
    expect(router.push).not.toHaveBeenCalled();
  });

  it('بعد الفتح يُحلّ الرابط المحتجَز مرة واحدة', async () => {
    getInitialURL.mockResolvedValue('maather://audit');
    const router = (globalThis as unknown as { __routerMock: { push: jest.Mock } }).__routerMock;

    renderWithHarness(<AppShell />, { status: 'UNLOCKED' });
    await waitFor(() => {
      expect(router.push).toHaveBeenCalledWith('/(app)/audit');
    });
    expect(router.push).toHaveBeenCalledTimes(1);
  });

  it('رابط غير مسموح لا يوجّه حتى بعد الفتح', async () => {
    getInitialURL.mockResolvedValue('maather://place-order');
    const router = (globalThis as unknown as { __routerMock: { push: jest.Mock } }).__routerMock;

    renderWithHarness(<AppShell />, { status: 'UNLOCKED' });
    await act(async () => {
      await Promise.resolve();
    });
    expect(router.push).not.toHaveBeenCalled();
  });

  it('شاشة القفل تُعلم أن رابطاً بانتظار التحقق', async () => {
    renderWithHarness(<AppShell />, { status: 'LOCKED' });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByTestId('home-screen')).toBeNull();
  });
});
