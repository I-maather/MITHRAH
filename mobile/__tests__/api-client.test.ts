import { ApiError, MobileApiClient, type RefreshOutcome, type TokenSource } from '@/api/client';
import { verifyBaseUrl } from '@/api/config';
import { envelope } from './helpers';

/**
 * عميل الشبكة: يفشل **مغلقاً** في كل حالة شك.
 */

const makeTokens = (overrides: Partial<TokenSource> = {}): TokenSource => ({
  getAccessToken: jest.fn(async () => 'access-token'),
  refresh: jest.fn(async (): Promise<RefreshOutcome> => ({ status: 'rejected' })),
  onSessionLost: jest.fn(async () => undefined),
  ...overrides,
});

const okResponse = (body: unknown, status = 200): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response;

describe('التحقق من هوية الخادم', () => {
  it('https مقبول', () => {
    expect(verifyBaseUrl('https://example.invalid').ok).toBe(true);
  });

  it('http على حلقة محلية مقبول', () => {
    expect(verifyBaseUrl('http://127.0.0.1:8000').ok).toBe(true);
    expect(verifyBaseUrl('http://192.168.1.20:8000').ok).toBe(true);
  });

  it('http على مضيف عام مرفوض', () => {
    const verdict = verifyBaseUrl('http://example.invalid');
    expect(verdict.ok).toBe(false);
    expect(verdict.reasonAr).toContain('مجهول الهوية');
  });

  it('عنوان غير صالح مرفوض', () => {
    expect(verifyBaseUrl('not a url').ok).toBe(false);
  });
});

describe('الفشل المغلق', () => {
  it('لا يُرسَل أي طلب إلى خادم غير موثوق', async () => {
    const fetchImpl = jest.fn();
    const client = new MobileApiClient({
      baseUrl: 'http://public.invalid',
      tokens: makeTokens(),
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await expect(client.getStatus()).rejects.toMatchObject({ kind: 'UNTRUSTED_ENDPOINT' });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('لا طلب بلا رمز', async () => {
    const fetchImpl = jest.fn();
    const client = new MobileApiClient({
      tokens: makeTokens({ getAccessToken: jest.fn(async () => null) }),
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await expect(client.getStatus()).rejects.toMatchObject({ kind: 'UNAUTHORISED' });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('انقطاع الشبكة يعطي خطأ OFFLINE بلا تسريب تفاصيل', async () => {
    const client = new MobileApiClient({
      tokens: makeTokens(),
      fetchImpl: (async () => {
        throw new Error('getaddrinfo ENOTFOUND secret-host');
      }) as unknown as typeof fetch,
    });
    await expect(client.getStatus()).rejects.toMatchObject({ kind: 'OFFLINE' });
    await client.getStatus().catch((error: unknown) => {
      expect((error as ApiError).messageAr).not.toContain('secret-host');
    });
  });
});

describe('حارس الغلاف', () => {
  it('يقبل الاستجابة الصحيحة ويعيد data', async () => {
    const body = envelope('status', { system_state: 'PAUSED' });
    const client = new MobileApiClient({
      tokens: makeTokens(),
      fetchImpl: (async () => okResponse(body)) as unknown as typeof fetch,
    });
    const result = await client.getStatus();
    expect(result.authorises_execution).toBe(false);
    expect(result.data).toEqual({ system_state: 'PAUSED' });
  });

  it('يرفض استجابة تدّعي الإذن بالتنفيذ', async () => {
    const body = envelope('status', {}, { authorises_execution: true });
    const client = new MobileApiClient({
      tokens: makeTokens(),
      fetchImpl: (async () => okResponse(body)) as unknown as typeof fetch,
    });
    await expect(client.getStatus()).rejects.toMatchObject({ kind: 'MALFORMED' });
  });

  it('يرفض استجابة بلا غلاف', async () => {
    const client = new MobileApiClient({
      tokens: makeTokens(),
      fetchImpl: (async () => okResponse({ anything: 1 })) as unknown as typeof fetch,
    });
    await expect(client.getStatus()).rejects.toMatchObject({ kind: 'MALFORMED' });
  });
});

describe('التجديد عند 401', () => {
  it('يجدّد مرة واحدة ثم يعيد المحاولة', async () => {
    let call = 0;
    const refresh = jest.fn(async (): Promise<RefreshOutcome> => ({
      status: 'renewed',
      accessToken: 'fresh-token',
    }));
    const client = new MobileApiClient({
      tokens: makeTokens({ refresh }),
      fetchImpl: (async () => {
        call += 1;
        return call === 1 ? okResponse({}, 401) : okResponse(envelope('risk', { profile: 'X' }));
      }) as unknown as typeof fetch,
    });
    const result = await client.getRisk();
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(result.data).toEqual({ profile: 'X' });
  });

  it('يُسقط الجلسة حين **يرفض الخادم** الرمز', async () => {
    const onSessionLost = jest.fn(async () => undefined);
    const client = new MobileApiClient({
      tokens: makeTokens({
        refresh: jest.fn(async (): Promise<RefreshOutcome> => ({ status: 'rejected' })),
        onSessionLost,
      }),
      fetchImpl: (async () => okResponse({}, 401)) as unknown as typeof fetch,
    });
    await expect(client.getRisk()).rejects.toMatchObject({ kind: 'UNAUTHORISED', status: 401 });
    expect(onSessionLost).toHaveBeenCalledTimes(1);
  });

  it('لا يُسقط الجلسة حين يتعذّر التجديد — شبكة أو خادم يُعيد التشغيل', async () => {
    /**
     * **العطل الذي كان يفرض مسح رمز اقتران بعد كل نشر.**
     *
     * كان كل إخفاق في التجديد يُقرأ «أُلغي الجهاز» فتُمسح سلسلة المفاتيح.
     * والنشر يعيد تشغيل الخدمة، فيصادف تجديدٌ جارٍ خادماً لا يردّ —
     * فتُمحى جلسةٌ سليمة تماماً، والخادم لم يقل عنها شيئاً.
     *
     * المحو الآن لا يقع إلا على رفضٍ صريح.
     */
    const onSessionLost = jest.fn(async () => undefined);
    const client = new MobileApiClient({
      tokens: makeTokens({
        refresh: jest.fn(async (): Promise<RefreshOutcome> => ({ status: 'unavailable' })),
        onSessionLost,
      }),
      fetchImpl: (async () => okResponse({}, 401)) as unknown as typeof fetch,
    });
    await expect(client.getRisk()).rejects.toMatchObject({ kind: 'OFFLINE' });
    expect(onSessionLost).not.toHaveBeenCalled();
  });

  it('استثناءٌ داخل التجديد لا يُسقط الجلسة', async () => {
    const onSessionLost = jest.fn(async () => undefined);
    const client = new MobileApiClient({
      tokens: makeTokens({
        refresh: jest.fn(async () => {
          throw new Error('boom');
        }),
        onSessionLost,
      }),
      fetchImpl: (async () => okResponse({}, 401)) as unknown as typeof fetch,
    });
    await expect(client.getRisk()).rejects.toMatchObject({ kind: 'OFFLINE' });
    expect(onSessionLost).not.toHaveBeenCalled();
  });

  it('403 لا يُعامَل كجلسة منتهية', async () => {
    const onSessionLost = jest.fn(async () => undefined);
    const client = new MobileApiClient({
      tokens: makeTokens({ onSessionLost }),
      fetchImpl: (async () => okResponse({}, 403)) as unknown as typeof fetch,
    });
    await expect(client.getRisk()).rejects.toMatchObject({ kind: 'FORBIDDEN' });
    expect(onSessionLost).not.toHaveBeenCalled();
  });
});

describe('المسارات المطلوبة', () => {
  it('كل دالة قراءة تصيب مسارها المُعلَن تحت البادئة الصحيحة', async () => {
    const seen: string[] = [];
    const client = new MobileApiClient({
      tokens: makeTokens(),
      fetchImpl: (async (url: string) => {
        seen.push(url);
        return okResponse(envelope('x', {}));
      }) as unknown as typeof fetch,
    });

    await client.getStatus();
    await client.getIntelligence();
    await client.getDecision();
    await client.getRisk();
    await client.getProfiles();
    await client.getCurrentPosition();
    await client.getTrades();
    await client.getPerformance();
    await client.getProviderHealth();
    await client.getNotifications();
    await client.getAudit();

    expect(seen).toEqual([
      'http://127.0.0.1:8000/api/mobile/v1/status',
      'http://127.0.0.1:8000/api/mobile/v1/intelligence/latest',
      'http://127.0.0.1:8000/api/mobile/v1/decision/latest',
      'http://127.0.0.1:8000/api/mobile/v1/risk',
      'http://127.0.0.1:8000/api/mobile/v1/profiles',
      'http://127.0.0.1:8000/api/mobile/v1/positions/current',
      'http://127.0.0.1:8000/api/mobile/v1/trades',
      'http://127.0.0.1:8000/api/mobile/v1/performance',
      'http://127.0.0.1:8000/api/mobile/v1/providers/health',
      'http://127.0.0.1:8000/api/mobile/v1/notifications',
      'http://127.0.0.1:8000/api/mobile/v1/audit/recent',
    ]);
  });

  it('الإجراءات الثلاثة تُرسَل POST إلى مساراتها', async () => {
    const seen: Array<{ url: string; method: string }> = [];
    const client = new MobileApiClient({
      tokens: makeTokens(),
      fetchImpl: (async (url: string, init: RequestInit) => {
        seen.push({ url, method: String(init.method) });
        return okResponse(envelope('x', { accepted: true }));
      }) as unknown as typeof fetch,
    });

    await client.requestPause();
    await client.activateKillSwitch();
    await client.revokeDevice();

    expect(seen).toEqual([
      { url: 'http://127.0.0.1:8000/api/mobile/v1/pause/request', method: 'POST' },
      { url: 'http://127.0.0.1:8000/api/mobile/v1/killswitch/activate', method: 'POST' },
      { url: 'http://127.0.0.1:8000/api/mobile/v1/device/revoke', method: 'POST' },
    ]);
  });

  it('كل طلب يحمل رمزاً بصيغة Bearer ولا يحمل اعتماد وسيط', async () => {
    let headers: Record<string, string> = {};
    const client = new MobileApiClient({
      tokens: makeTokens(),
      fetchImpl: (async (_url: string, init: RequestInit) => {
        headers = init.headers as Record<string, string>;
        return okResponse(envelope('status', {}));
      }) as unknown as typeof fetch,
    });
    await client.getStatus();
    expect(headers.authorization).toBe('Bearer access-token');
    // مجموعة الترويسات مغلقة: لا مجال لترويسة وسيط أن تتسلّل.
    expect(Object.keys(headers).sort()).toEqual(['accept', 'authorization']);
  });
});
