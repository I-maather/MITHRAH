import { fireEvent, screen, waitFor } from '@testing-library/react-native';

import EnrolScreen from '../app/enrol';
import { API_BASE_URL } from '@/api/config';
import { renderWithHarness } from './helpers';

/**
 * الاقتران على المحاكي — مدخلٌ للحمولة حين لا عدسة.
 *
 * ## لماذا وُجد أصلاً
 *
 * المحاكي بلا كاميرا. فبلا مدخلٍ آخر لا سبيل **إطلاقاً** إلى إثبات أن
 * التطبيق يعرض أرقام الخادم الحقيقية قبل تسليم بناءٍ إلى الجهاز: يبقى كلُّ
 * دليلٍ بصريّ مؤجَّلاً إلى ما بعد التسليم، وهو عكس الترتيب الصحيح تماماً.
 *
 * ## وما يحرسه هذا الملف
 *
 * أنّه **ليس مساراً موازياً**. الحمولة نفسها، و`enrolDevice` نفسها، والقفلان
 * نفسهما: حمولةٌ رُفضت لا تُعاد، وحمولةٌ واحدة لا تُرسَل مرتين. والأهمّ: أنه
 * لا يصل إلى حزمةٍ قابلة للتثبيت — الفرع كلّه تحت `__DEV__`.
 */

jest.mock('expo-camera', () => {
  const ReactActual = jest.requireActual('react');
  const { View } = jest.requireActual('react-native');
  return {
    __esModule: true,
    useCameraPermissions: () => [{ granted: true }, jest.fn()],
    CameraView: () => ReactActual.createElement(View, { testID: 'enrol-camera' }),
  };
});

const payload = (challenge: string): string =>
  JSON.stringify({
    v: 2,
    b: API_BASE_URL,
    c: challenge,
    e: Math.floor((Date.now() + 90_000) / 1000),
  });

const paste = (text: string): void => {
  fireEvent.changeText(screen.getByTestId('enrol-dev-paste-input'), text);
  fireEvent.press(screen.getByTestId('enrol-dev-paste-button'));
};

describe('اللصق يسلك مسار المسح نفسه', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('يظهر الحقل في التطوير', () => {
    renderWithHarness(<EnrolScreen />);
    expect(screen.getByTestId('enrol-dev-paste')).toBeTruthy();
  });

  it('لا يظهر الحقل خارج التطوير', () => {
    const globals = globalThis as unknown as { __DEV__: boolean };
    const was = globals.__DEV__;
    globals.__DEV__ = false;
    try {
      renderWithHarness(<EnrolScreen />);
      expect(screen.queryByTestId('enrol-dev-paste')).toBeNull();
    } finally {
      globals.__DEV__ = was;
    }
  });

  it('الحقل الفارغ لا يُرسل طلباً', () => {
    const fetchMock = jest.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderWithHarness(<EnrolScreen />);
    fireEvent.press(screen.getByTestId('enrol-dev-paste-button'));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('الحمولة الملصوقة تُرسَل إلى مسار التسجيل نفسه', async () => {
    // نوعُ الوسيط معلَن كي يعرف TypeScript أنّ للنداء وسيطاً أوّل.
    const fetchMock = jest.fn(
      async (_url: string) => ({ ok: false, status: 401 }) as unknown as Response,
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderWithHarness(<EnrolScreen />);
    paste(payload('c-1'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain('/api/mobile/session/enroll');
  });

  it('حمولةٌ رُفضت لا تُعاد ولو ضُغط الزرّ ثانيةً', async () => {
    const fetchMock = jest.fn(
      async () => ({ ok: false, status: 401 }) as unknown as Response,
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderWithHarness(<EnrolScreen />);
    paste(payload('c-2'));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    fireEvent.press(screen.getByTestId('enrol-dev-paste-button'));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });

  it('حمولةٌ جديدة تُعالَج بعد رفض السابقة', async () => {
    const fetchMock = jest.fn(
      async () => ({ ok: false, status: 401 }) as unknown as Response,
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderWithHarness(<EnrolScreen />);
    paste(payload('c-3'));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    paste(payload('c-4'));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
  });
});
