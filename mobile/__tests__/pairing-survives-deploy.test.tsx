import { screen, waitFor } from '@testing-library/react-native';

import { ApiError } from '@/api/client';
import { useSession } from '@/auth/SessionProvider';
import { tokenStore } from '@/auth/tokenStore';
import { Text } from 'react-native';
import { renderWithHarness, SessionProbe } from './helpers';

/**
 * الاقتران يبقى عبر النشر.
 *
 * ## الشكوى التي أنتجت هذا الملف
 *
 * «ليش لين دحين فيه مسح QR Code؟ ابغا خلاص على طول افتح بالفيس اي دي حتى لو
 * عدلنا وحدثنا — كل مرة بيطلع ونمسح؟!»
 *
 * والسبب كان في مكانين، وكلاهما يُشغَّل بالنشر نفسه:
 *
 * 1. **الخادم** — كان كل نشر ينسخ ملف حالة الجوال من الماك فوق ملف الخادم.
 *    ورمز التجديد يُدوَّر عند كل استعمال، فالنسخة القديمة تُفقد الخادمَ
 *    الرمزَ الحيّ. (حُرس في `deploy/server_bootstrap.sh`.)
 *
 * 2. **التطبيق** — وهو ما يحرسه هذا الملف: كان `refresh` يعيد `null` لكل
 *    إخفاق، والعميل يقرأ `null` «أُلغي الجهاز» فيمسح سلسلة المفاتيح.
 *    والنشر يعيد تشغيل الخدمة، فيصادف تجديدٌ جارٍ خادماً لا يردّ — فتُمحى
 *    جلسةٌ سليمة تماماً، والخادم لم يقل عنها شيئاً.
 *
 * القاعدة الآن: **لا تُمحى جلسة إلا برفضٍ صريح من الخادم.**
 */

jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: false,
}));

/** يستدعي نداءً واحداً ويُصيّر نوع الإخفاق. */
function CallProbe(): React.JSX.Element {
  const { client } = useSession();
  const [kind, setKind] = React.useState('PENDING');
  React.useEffect(() => {
    void (async () => {
      try {
        await client.getRisk();
        setKind('OK');
      } catch (error) {
        setKind(error instanceof ApiError ? error.kind : 'THROWN');
      }
    })();
  }, [client]);
  return <Text testID="call-kind">{kind}</Text>;
}

import React from 'react';

/** يردّ 401 على نداءات `v1`، وما يُمرَّر على مسار التجديد. */
function fetchWithRefreshStatus(refreshStatus: number | 'network'): jest.Mock {
  return jest.fn(async (url: unknown) => {
    if (String(url).includes('/session/refresh')) {
      if (refreshStatus === 'network') {
        throw new TypeError('Network request failed');
      }
      return {
        ok: refreshStatus >= 200 && refreshStatus < 300,
        status: refreshStatus,
        json: async () => ({}),
      } as unknown as Response;
    }
    return { ok: false, status: 401, json: async () => ({}) } as unknown as Response;
  });
}

beforeEach(async () => {
  await tokenStore.save({
    accessToken: 'access',
    refreshToken: 'refresh',
    deviceId: 'device-1',
    accessExpiresAt: Date.now() + 60_000,
  });
  jest.spyOn(tokenStore, 'clear');
});

afterEach(async () => {
  jest.restoreAllMocks();
  await tokenStore.clear();
});

describe('الجلسة لا تُمحى على ظنّ', () => {
  it.each([
    ['انقطاع شبكة', 'network' as const],
    ['الخادم يُعيد التشغيل (503)', 503],
    ['بوابة عاطلة (502)', 502],
    ['خطأ داخلي (500)', 500],
  ])('%s ⇒ الجلسة محفوظة', async (_label, status) => {
    renderWithHarness(<CallProbe />, {
      status: 'UNLOCKED',
      fetchImpl: fetchWithRefreshStatus(status) as unknown as typeof fetch,
    });

    await waitFor(() => expect(screen.getByTestId('call-kind').props.children).toBe('OFFLINE'));
    expect(tokenStore.clear).not.toHaveBeenCalled();
    expect(await tokenStore.hasSession()).toBe(true);
  });

  it.each([
    ['الجهاز أُلغي (401)', 401],
    ['ممنوع (403)', 403],
  ])('%s ⇒ الجلسة تُمحى — وهذا صحيح', async (_label, status) => {
    /**
     * الاتجاه الآخر يجب أن يبقى عاملاً: جهازٌ أُلغي فعلاً لا يُترك بجلسة
     * حيّة. الحارس هنا ذو حدّين، وهذه حدّه الثاني.
     */
    renderWithHarness(<CallProbe />, {
      status: 'UNLOCKED',
      fetchImpl: fetchWithRefreshStatus(status) as unknown as typeof fetch,
    });

    await waitFor(() =>
      expect(screen.getByTestId('call-kind').props.children).toBe('UNAUTHORISED'),
    );
    expect(await tokenStore.hasSession()).toBe(false);
  });
});

describe('الإقلاع بعد نشر', () => {
  it('جلسةٌ محفوظة تعني القفل لا الاقتران', async () => {
    /**
     * `LOCKED` تعني «افتحي بالوجه»، و`NO_SESSION` تعني «امسحي رمزاً».
     * والفرق بينهما هو كل ما تسأل عنه المالكة.
     */
    renderWithHarness(<SessionProbe />);
    await waitFor(() => expect(screen.getByTestId('probe-status').props.children).toBe('LOCKED'));
  });

  it('بلا جلسة محفوظة يُطلب الاقتران', async () => {
    await tokenStore.clear();
    renderWithHarness(<SessionProbe />);
    await waitFor(() =>
      expect(screen.getByTestId('probe-status').props.children).toBe('NO_SESSION'),
    );
  });
});
