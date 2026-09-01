import type { ReactTestInstance } from 'react-test-renderer';
import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';

import EmergencyScreen from '../app/(app)/emergency';
import { RISK_REDUCING_ROUTES } from '@/api/routes';
import { tokenStore } from '@/auth/tokenStore';
import { envelope, renderWithHarness } from './helpers';

// جلسة مخزَّنة: بدونها يفشل العميل مغلقاً قبل الشبكة، وهو سلوك مقصود
// يُختبَر في api-client.test.ts.
beforeEach(async () => {
  await tokenStore.save({
    accessToken: 'test-access',
    refreshToken: 'test-refresh',
    deviceId: 'test-device',
    accessExpiresAt: Date.now() + 900_000,
  });
});

/**
 * الإجراءات الثلاثة.
 *
 * كلها **تقلّل** المخاطرة، وكلها بخطوتين كي لا تُضغط بالخطأ. وليس في الشاشة
 * شيء يفتح: لا إلغاء للقاطع، ولا إعادة تفعيل لمفتاح، ولا رفع لملف المخاطرة.
 */

const makeFetch = (): jest.Mock =>
  jest.fn(async (url: string) => {
    const route = url.split('/api/mobile/v1/')[1] ?? '';
    const data =
      route === 'device/revoke'
        ? { action: 'DEVICE_REVOKED', accepted: true, device_id: 'D', at_utc: 'now' }
        : route === 'killswitch/activate'
          ? {
              action: 'KILL_SWITCH_ACTIVATED',
              accepted: true,
              at_utc: 'now',
              note_ar: 'القاطع مُفعَّل ولا يُلغى من الجوال.',
            }
          : { action: 'PAUSE_REQUESTED', accepted: true, at_utc: 'now', note_ar: 'يقلّل المخاطرة.' };
    return {
      ok: true,
      status: 200,
      json: async () => envelope(route, data),
    } as unknown as Response;
  });

const arm = async (testID: string): Promise<void> => {
  await act(async () => {
    fireEvent.press(screen.getByTestId(testID));
  });
};

describe('تدفّق الإيقاف المؤقت', () => {
  it('لا يُرسَل شيء قبل التأكيد', async () => {
    const fetchImpl = makeFetch();
    renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await arm('pause-action');
    expect(screen.getByTestId('pause-action-panel')).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('التأكيد يصيب pause/request ويُظهر القبول', async () => {
    const fetchImpl = makeFetch();
    renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await arm('pause-action');
    await arm('pause-action-accept');

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/mobile/v1/pause/request');
    expect(init.method).toBe('POST');
    await waitFor(() => {
      expect(screen.getByTestId('emergency-result')).toBeTruthy();
    });
  });

  it('الإلغاء يُغلق لوحة التأكيد بلا إرسال', async () => {
    const fetchImpl = makeFetch();
    renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await arm('pause-action');
    await arm('pause-action-cancel');
    expect(screen.queryByTestId('pause-action-panel')).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe('تدفّق قاطع الطوارئ', () => {
  it('يحتاج خطوتين، ثم يصيب killswitch/activate', async () => {
    const fetchImpl = makeFetch();
    renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await arm('kill-action');
    expect(fetchImpl).not.toHaveBeenCalled();
    await arm('kill-action-accept');
    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });
    expect((fetchImpl.mock.calls[0] as [string])[0]).toContain('/killswitch/activate');
  });

  it('يقول صراحةً إن القاطع لا يُلغى من الجهاز', async () => {
    renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: makeFetch() as unknown as typeof fetch,
    });
    expect(screen.getByTestId('kill-no-undo')).toHaveTextContent(/لا يُلغى/);
  });

  it('لا يوجد زر لإلغاء قاطع الطوارئ في الشاشة', () => {
    /**
     * ⚠️ ضاقت العبارة المرفوضة في 2026-09-01، وهذا **تدقيقٌ لا تخفيف**.
     *
     * كانت تمنع «استئناف» أيضاً، فتخلط شيئين مختلفين تماماً:
     *
     *   إلغاء قاطع الطوارئ  — يرفع **حكماً** بأن شيئاً خطيراً وقع.  ممنوع.
     *   استئناف الإيقاف     — يرفع **قراراً** اتخذته المالكة.        مسموح.
     *
     * والاستئناف لا يمسّ القاطع: الخادم يرفضه ما دام مفعّلاً، ويرفضه من
     * عند المصدر لا من عند الواجهة. فمنعُه هنا كان يمنع الصواب باسم الخطأ.
     */
    const view = renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: makeFetch() as unknown as typeof fetch,
    });
    const buttons = view.UNSAFE_root.findAll(
      (node: ReactTestInstance) => node.props?.accessibilityRole === 'button',
    );
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) {
      const label = String(button.props.accessibilityLabel);
      expect(label).not.toMatch(/إلغاء القاطع|تعطيل القاطع|إيقاف القاطع|رفع القاطع/);
    }
  });

  it('زرّ الاستئناف موجود، ويقول صراحةً إنه لا يفتح شيئاً آخر', () => {
    const view = renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: makeFetch() as unknown as typeof fetch,
    });
    expect(view.getByTestId('resume-action')).toBeTruthy();
    expect(view.getByTestId('resume-card')).toHaveTextContent(/لا يفتح أي قفل آخر/);
    expect(view.getByTestId('resume-card')).toHaveTextContent(/لا يُلغي قاطع الطوارئ/);
  });
});

describe('تدفّق إلغاء الجهاز', () => {
  it('يصيب device/revoke ويمحو الجلسة محلياً', async () => {
    const fetchImpl = makeFetch();
    renderWithHarness(<EmergencyScreen />, {
      status: 'UNLOCKED',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await arm('revoke-action');
    await arm('revoke-action-accept');
    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });
    expect((fetchImpl.mock.calls[0] as [string])[0]).toContain('/device/revoke');

    const memory = (globalThis as unknown as { __secureStoreMemory: Map<string, string> })
      .__secureStoreMemory;
    await waitFor(() => {
      expect(memory.size).toBe(0);
    });
  });
});

describe('سطح الإجراءات مغلق', () => {
  it('ثلاثة مسارات لا رابع لها', () => {
    expect(RISK_REDUCING_ROUTES).toHaveLength(3);
  });

  it('كل مسار منها يقلّل المخاطرة بالاسم', () => {
    for (const route of RISK_REDUCING_ROUTES) {
      expect(route).toMatch(/^(pause|killswitch|device)\//);
    }
  });
});
