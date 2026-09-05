/**
 * الإقلاع لا يعلَق — والجهل يُقال.
 *
 * ## ما وُجد يوم ٦ سبتمبر ٢٠٢٦
 *
 * أوّلُ تثبيتٍ على محاكٍ نظيف: التطبيق يقف على «جارٍ التحميل…» إلى الأبد،
 * وفي الطرفية سطرٌ واحد — `Possible unhandled promise rejection`.
 *
 * السبب: أثرُ الإقلاع في `SessionProvider` كان
 *
 *     void (async () => {
 *       const [hasSession, deviceId] = await Promise.all([...]);
 *       setStatus(hasSession ? 'LOCKED' : 'NO_SESSION');
 *     })();
 *
 * بلا `catch`. فإن رفضت سلسلةُ المفاتيح — وهي تُفتح بـ
 * `WHEN_UNLOCKED_THIS_DEVICE_ONLY`، أي **تفشل والجهازُ مقفل** — لم تُستدعَ
 * `setStatus`، فبقيت `BOOTING`، ورسم الحارس شاشةَ تحميلٍ بلا نهاية.
 *
 * وهذا أخطر من الشاشة السوداء التي مُنعت بالاسم في `FontGate`: الشاشةُ
 * السوداء تُقرأ عطلاً، وشاشةُ التحميل تُقرأ انتظاراً — فتُنتظَر.
 */
import React from 'react';
import { Text } from 'react-native';
import { render, screen, waitFor } from '@testing-library/react-native';

jest.mock('@/auth/tokenStore', () => ({
  tokenStore: {
    hasSession: jest.fn(),
    loadDeviceId: jest.fn(),
    clear: jest.fn(async () => undefined),
    save: jest.fn(async () => undefined),
    rotate: jest.fn(async () => undefined),
    loadAccessToken: jest.fn(async () => null),
    loadRefreshToken: jest.fn(async () => null),
    loadPublicIdentity: jest.fn(async () => null),
    savePublicIdentity: jest.fn(async () => undefined),
  },
  ACCESS_TOKEN_TTL_MS: 900000,
  REFRESH_MARGIN_MS: 60000,
  maskToken: (v: string | null) => (v === null ? '—' : '••••'),
}));

import { tokenStore } from '@/auth/tokenStore';
import { SessionProvider, useSession } from '@/auth/SessionProvider';

const store = tokenStore as unknown as {
  hasSession: jest.Mock;
  loadDeviceId: jest.Mock;
};

function Probe(): React.JSX.Element {
  const { status } = useSession();
  return <Text testID="status">{status}</Text>;
}

const mount = (): void => {
  render(
    <SessionProvider>
      <Probe />
    </SessionProvider>,
  );
};

describe('الإقلاع يحسم حالته دائماً', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('سلسلةُ مفاتيح ترفض ⇒ حالةٌ مُعلَنة، لا BOOTING إلى الأبد', async () => {
    store.hasSession.mockRejectedValue(new Error('keychain unavailable'));
    store.loadDeviceId.mockResolvedValue(null);

    mount();

    await waitFor(() => {
      expect(screen.getByTestId('status').props.children).not.toBe('BOOTING');
    });
    expect(screen.getByTestId('status').props.children).toBe('UNREADABLE');
  });

  it('الجهلُ لا يُكتَب غياباً — ولا يُقال «لا جهاز مسجَّل»', async () => {
    // `NO_SESSION` دعوى معرفة: «قرأتُ فلم أجد». وهنا لم نقرأ أصلاً.
    store.hasSession.mockRejectedValue(new Error('keychain unavailable'));
    store.loadDeviceId.mockResolvedValue(null);

    mount();

    await waitFor(() => {
      expect(screen.getByTestId('status').props.children).toBe('UNREADABLE');
    });
    expect(screen.getByTestId('status').props.children).not.toBe('NO_SESSION');
  });

  it('فشلُ معرّف الجهاز وحده يُمسَك كذلك', async () => {
    store.hasSession.mockResolvedValue(true);
    store.loadDeviceId.mockRejectedValue(new Error('keychain unavailable'));

    mount();

    await waitFor(() => {
      expect(screen.getByTestId('status').props.children).toBe('UNREADABLE');
    });
  });

  it('القراءةُ الناجحة بلا جلسة ⇒ NO_SESSION', async () => {
    store.hasSession.mockResolvedValue(false);
    store.loadDeviceId.mockResolvedValue(null);

    mount();

    await waitFor(() => {
      expect(screen.getByTestId('status').props.children).toBe('NO_SESSION');
    });
  });

  it('القراءةُ الناجحة بجلسة ⇒ LOCKED', async () => {
    store.hasSession.mockResolvedValue(true);
    store.loadDeviceId.mockResolvedValue('dev-1');

    mount();

    await waitFor(() => {
      expect(screen.getByTestId('status').props.children).toBe('LOCKED');
    });
  });
});
