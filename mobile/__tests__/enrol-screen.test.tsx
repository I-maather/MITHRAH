import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';

import EnrolScreen from '../app/enrol';
import { API_BASE_URL } from '@/api/config';
import { renderWithHarness } from './helpers';

/**
 * شاشة المسح — **الانهيار الذي جمّد الجهاز**.
 *
 * الكاميرا تُطلق `onBarcodeScanned` لكل إطار تقرأ فيه رمزاً. وحين كان القفل
 * يُفتَح بعد الفشل «كي تُتاح محاولة أخرى»، كان الرمز الباقي أمام العدسة
 * يُرسَل مئات المرات في الثانية. وهذا ما ظهر في سجل الخادم:
 *
 *     POST /api/mobile/session/enroll → 404   ×  مئات
 *
 * فالاختبارات هنا تحرس قاعدتين: **رمزٌ رُفض لا يُعاد إرساله، ورمزٌ جديد
 * يُعالَج فوراً بلا لمسة.**
 */

/** آخر `onBarcodeScanned` مرّرتها الشاشة — تُستدعى كما تستدعيها الكاميرا. */
let emit: ((event: { data: string }) => void) | null = null;

jest.mock('expo-camera', () => {
  const ReactActual = jest.requireActual('react');
  const { View } = jest.requireActual('react-native');
  return {
    __esModule: true,
    useCameraPermissions: () => [{ granted: true }, jest.fn()],
    CameraView: (props: { onBarcodeScanned?: (e: { data: string }) => void }) => {
      (globalThis as { __emit?: unknown }).__emit = props.onBarcodeScanned;
      return ReactActual.createElement(View, { testID: 'enrol-camera' });
    },
  };
});

const payload = (challenge: string): string =>
  JSON.stringify({
    v: 2,
    b: API_BASE_URL,
    c: challenge,
    e: Math.floor((Date.now() + 90_000) / 1000),
  });

const responding = (status: number): jest.Mock =>
  jest.fn(async () => ({ ok: false, status }) as unknown as Response);

const mount = (status: number): jest.Mock => {
  const fetchImpl = responding(status);
  global.fetch = fetchImpl as unknown as typeof fetch;
  renderWithHarness(<EnrolScreen />, { status: 'NO_SESSION' });
  emit = (globalThis as { __emit?: (e: { data: string }) => void }).__emit ?? null;
  return fetchImpl;
};

describe('شاشة المسح لا تُغرق الخادم', () => {
  it('**رمزٌ رُفض لا يُرسَل إلا مرة واحدة** مهما تكرّر أمام العدسة', async () => {
    const fetchImpl = mount(404);

    const raw = payload('SAME');
    await act(async () => {
      for (let i = 0; i < 40; i += 1) {
        emit?.({ data: raw });
      }
    });

    await waitFor(() => expect(screen.getByTestId('enrol-failure')).toBeTruthy());
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('يقول الحقيقة عند 404: الخادم قديم، لا الرمز منتهٍ', async () => {
    mount(404);
    await act(async () => emit?.({ data: payload('X') }));

    await waitFor(() => expect(screen.getByTestId('enrol-failure')).toBeTruthy());
    expect(screen.getByTestId('enrol-failure')).toHaveTextContent(/أعيدي تشغيله/);
  });

  it('**ورمزٌ جديد يُعالَج فوراً** بلا لمسة من المالكة', async () => {
    const fetchImpl = mount(401);

    await act(async () => emit?.({ data: payload('OLD') }));
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));

    await act(async () => emit?.({ data: payload('NEW') }));
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(2));
  });

  it('زرّ الرجوع يعمل ولو رُفض رمز قبله', async () => {
    mount(404);
    await act(async () => emit?.({ data: payload('ANY') }));
    await waitFor(() => expect(screen.getByTestId('enrol-failure')).toBeTruthy());

    fireEvent.press(screen.getByTestId('enrol-back'));
    const router = (globalThis as { __routerMock?: { replace: jest.Mock } }).__routerMock;
    expect(router?.replace).toHaveBeenCalledWith('/');
  });
});
