import { API_BASE_URL } from '@/api/config';
import { enrolDevice, parseEnrolmentPayload } from '@/auth/enrolment';

/**
 * رمز QR **مُدخَل من العالم الخارجي يصل قبل أي مصادقة**.
 *
 * الخطر ليس سرقة شيء — التطبيق لا يملك ما يُسرَق قبل التسجيل. الخطر أن
 * يُسجَّل الجهاز لدى خادم مهاجم فتصير الشاشة تكذب: «قاطع الطوارئ مطفأ»،
 * «لا خسائر»، «كل شيء بخير».
 *
 * فأغلب هذه الاختبارات على `parseEnrolmentPayload` — ما يُوقَف **قبل** أي
 * طلب شبكة.
 */

const future = (): string => new Date(Date.now() + 90_000).toISOString();

const valid = (over: Record<string, unknown> = {}): string =>
  JSON.stringify({
    v: 1,
    backend: API_BASE_URL,
    challenge_id: 'CHALLENGE',
    nonce: 'NONCE-VALUE',
    expires_utc: future(),
    contains_secret: false,
    ...over,
  });

describe('فحص حمولة الاقتران قبل أي طلب', () => {
  it('يقبل حمولة سليمة تشير إلى الخادم المُجمَّع', () => {
    const result = parseEnrolmentPayload(valid());
    expect(result.ok).toBe(true);
  });

  it('**يرفض رمزاً يشير إلى خادم آخر**', () => {
    const result = parseEnrolmentPayload(valid({ backend: 'https://evil.example' }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.result.failure).toBe('BACKEND_MISMATCH');
    }
  });

  it('يرفض عنواناً غير مُعمّى خارج الشبكات الخاصة', () => {
    const result = parseEnrolmentPayload(valid({ backend: 'http://evil.example' }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.result.failure).toBe('UNTRUSTED_BACKEND');
    }
  });

  it('يرفض رمزاً يقرّ بحمل سرّ', () => {
    const result = parseEnrolmentPayload(valid({ contains_secret: true }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.result.failure).toBe('CLAIMS_SECRET');
    }
  });

  it('يرفض إصداراً غير معروف بدل أن يخمّن', () => {
    const result = parseEnrolmentPayload(valid({ v: 2 }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.result.failure).toBe('UNSUPPORTED_VERSION');
    }
  });

  it('يرفض رمزاً منتهياً', () => {
    const stale = valid({ expires_utc: new Date(Date.now() - 1000).toISOString() });
    const result = parseEnrolmentPayload(stale);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.result.failure).toBe('EXPIRED');
    }
  });

  it.each([
    ['نص ليس JSON', 'مجرّد نص'],
    ['JSON ليس كائناً', '[1,2,3]'],
    ['بلا معرّف تحدٍّ', JSON.stringify({ v: 1, backend: API_BASE_URL, nonce: 'N' })],
    ['معرّف تحدٍّ فارغ', valid({ challenge_id: '' })],
    ['وقت انتهاء غير مفهوم', valid({ expires_utc: 'ليس تاريخاً' })],
  ])('يرفض %s', (_label, raw) => {
    expect(parseEnrolmentPayload(raw).ok).toBe(false);
  });

  it('لا يتعثّر على شرطة مائلة زائدة في العنوان', () => {
    expect(parseEnrolmentPayload(valid({ backend: `${API_BASE_URL}/` })).ok).toBe(true);
  });
});

describe('إتمام التسجيل', () => {
  it('لا يُرسل أي طلب إن سقط الفحص', async () => {
    const fetchImpl = jest.fn();
    const result = await enrolDevice(
      valid({ backend: 'https://evil.example' }), 'identity', 'Mesa',
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(result.ok).toBe(false);
    // الفحص قبل الشبكة: لم يُلمس الخادم أصلاً.
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('يرسل معرّف التحدّي والهوية والاسم إلى مسار الجلسة', async () => {
    const fetchImpl = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        device: { device_id: 'DEV' },
        access_token: 'A',
        refresh_token: 'R',
        access_expires_utc: new Date(Date.now() + 900_000).toISOString(),
        authorises_execution: false,
      }),
    }));
    const result = await enrolDevice(valid(), 'identity-value', 'Mesa', {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result.ok).toBe(true);
    expect(result.session?.deviceId).toBe('DEV');

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/api/mobile/session/enroll`);
    expect(JSON.parse(String(init.body))).toEqual({
      challenge_id: 'CHALLENGE',
      public_identity: 'identity-value',
      device_name: 'Mesa',
    });
  });

  it('**يرفض جلسة من خادم لا يُعلن أنه لا يأذن بتنفيذ**', async () => {
    const fetchImpl = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        device: { device_id: 'DEV' },
        access_token: 'A',
        refresh_token: 'R',
        authorises_execution: true,
      }),
    }));
    const result = await enrolDevice(valid(), 'identity', 'Mesa', {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result.ok).toBe(false);
    expect(result.failure).toBe('REJECTED');
  });

  it('يرفض ردّاً ناقص الرموز ولا يحفظ شيئاً', async () => {
    const fetchImpl = jest.fn(async () => ({
      ok: true,
      json: async () => ({ device: { device_id: 'DEV' }, access_token: 'A' }),
    }));
    const result = await enrolDevice(valid(), 'identity', 'Mesa', {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result.ok).toBe(false);
    expect(result.session).toBeUndefined();
  });

  it('يترجم رفض الخادم إلى رسالة عربية بلا تفاصيل تقنية', async () => {
    const fetchImpl = jest.fn(async () => ({ ok: false, status: 401 }));
    const result = await enrolDevice(valid(), 'identity', 'Mesa', {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result.ok).toBe(false);
    expect(result.reasonAr).toContain('رمزاً جديداً');
    expect(result.reasonAr).not.toMatch(/401|http|fetch/i);
  });

  it('عطل الشبكة لا يُظهر عنواناً ولا نصّ استثناء', async () => {
    const fetchImpl = jest.fn(async () => {
      throw new Error('connect ECONNREFUSED 100.106.54.103:8000');
    });
    const result = await enrolDevice(valid(), 'identity', 'Mesa', {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result.failure).toBe('NETWORK');
    expect(result.reasonAr).not.toMatch(/ECONNREFUSED|\d+\.\d+\.\d+\.\d+/);
  });
});
