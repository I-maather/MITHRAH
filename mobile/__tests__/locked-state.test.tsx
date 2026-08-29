import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';

import AuthenticatedLayout from '../app/(app)/_layout';
import SecureLaunchScreen from '../app/index';
import { t } from '@/i18n';
import { renderWithHarness } from './helpers';

/**
 * الحالة المقفلة.
 *
 * لا شاشة بيانات واحدة تُرسَم قبل فتح البوابة، ولا يظهر رقم على شاشة القفل.
 */

describe('شاشة الإقلاع الآمن', () => {
  it('تعرض التطبيق مقفلاً ولا تعرض أي بيانات نظام', () => {
    renderWithHarness(<SecureLaunchScreen />, { status: 'LOCKED' });
    expect(screen.getByTestId('gate-locked-label')).toBeTruthy();
    expect(screen.queryByTestId('home-screen')).toBeNull();
    expect(screen.queryByText(/المخاطرة المستهلكة/)).toBeNull();
  });

  it('تقول صراحةً إن Face ID بوابة محلية لا مصادقة خادم', () => {
    renderWithHarness(<SecureLaunchScreen />, { status: 'LOCKED' });
    const note = screen.getByTestId('faceid-note');
    expect(note).toHaveTextContent(/بوابة وصول/);
    expect(note).toHaveTextContent(/المصادقة الفعلية/);
  });

  it('زر الفتح يحمل تسمية وتلميحاً لـVoiceOver', () => {
    renderWithHarness(<SecureLaunchScreen />, { status: 'LOCKED' });
    const button = screen.getByTestId('unlock-button');
    expect(button.props.accessibilityLabel).toBe(t.gate.unlock);
    expect(String(button.props.accessibilityHint)).toContain('بوابة وصول');
  });

  it('الفتح الناجح ينقل إلى الرئيسية', async () => {
    const router = (globalThis as unknown as { __routerMock: { replace: jest.Mock } })
      .__routerMock;
    renderWithHarness(<SecureLaunchScreen />, {
      status: 'LOCKED',
      unlockImpl: async () => ({ ok: true, method: 'BIOMETRIC' }),
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('unlock-button'));
    });
    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith('/(app)/home');
    });
  });

  it('الفتح المرفوض يُظهر السبب ويبقي القفل', async () => {
    renderWithHarness(<SecureLaunchScreen />, {
      status: 'LOCKED',
      unlockImpl: async () => ({
        ok: false,
        reason: 'CANCELLED',
        messageAr: 'أُلغي الفتح. التطبيق ما يزال مقفلاً.',
      }),
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('unlock-button'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('gate-message')).toBeTruthy();
    });
    expect(screen.queryByTestId('home-screen')).toBeNull();
  });

  it('الجهاز المُلغى: زر الفتح معطّل ورسالة صريحة', () => {
    renderWithHarness(<SecureLaunchScreen />, { status: 'REVOKED' });
    expect(screen.getByTestId('revoked-banner')).toBeTruthy();
    expect(screen.getByTestId('unlock-button').props.accessibilityState.disabled).toBe(true);
  });

  it('بلا جهاز مسجَّل: يشرح أن التسجيل من الخادم برمز لمرة واحدة', () => {
    renderWithHarness(<SecureLaunchScreen />, { status: 'NO_SESSION' });
    expect(screen.getByTestId('no-session-banner')).toBeTruthy();
    expect(screen.getByTestId('unlock-button').props.accessibilityState.disabled).toBe(true);
  });
});

describe('حارس الشاشات المصادَق عليها', () => {
  it('يوجّه إلى شاشة القفل ما لم تُفتح البوابة', () => {
    renderWithHarness(<AuthenticatedLayout />, { status: 'LOCKED' });
    expect(screen.getByTestId('redirect-/')).toBeTruthy();
  });

  it('الجهاز المُلغى لا يمرّ من الحارس', () => {
    renderWithHarness(<AuthenticatedLayout />, { status: 'REVOKED' });
    expect(screen.getByTestId('redirect-/')).toBeTruthy();
  });

  it('يمرّر الشاشات بعد الفتح', () => {
    renderWithHarness(<AuthenticatedLayout />, { status: 'UNLOCKED' });
    expect(screen.queryByTestId('redirect-/')).toBeNull();
  });
});
