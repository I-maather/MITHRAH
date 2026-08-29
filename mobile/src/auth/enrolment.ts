/**
 * تسجيل الجهاز من رمز QR.
 *
 * ## الخطر الذي يعالجه هذا الملف
 *
 * رمز QR مُدخَل **من العالم الخارجي** يصل إلى التطبيق قبل أي مصادقة. ولو
 * قُبل كما هو، لأمكن أن يُمسَح رمزٌ يشير إلى خادم مهاجم:
 *
 *     التطبيق يسجّل لدى خادم المهاجم  ⇒  يقبل رموزه
 *     ⇒  يعرض ما يشاء المهاجم: «قاطع الطوارئ مطفأ»، «لا خسائر»، «كل شيء بخير»
 *
 * ولا يحتاج المهاجم إلى سرقة شيء — يكفي أن يجعل الشاشة تكذب.
 *
 * ## الحارس
 *
 * عنوان الخادم في الرمز يجب أن يطابق **العنوان المُجمَّع في التطبيق**
 * (`EXPO_PUBLIC_API_BASE_URL`) مطابقةً تامة. وهذا ليس تشدّداً زائداً: عنوان
 * الخادم يُثبَّت وقت البناء، فرمزٌ يشير إلى غيره **غير شرعي بالتعريف**.
 *
 * وأربعة فحوص أخرى قبل أي طلب شبكة:
 *
 *   * الشكل صحيح والإصدار معروف
 *   * `contains_secret` يساوي `false` صراحةً — رمزٌ يعترف بحمل سرّ يُرفَض
 *   * لم ينتهِ وقته (يُفحَص محلياً كي تُقال الرسالة فوراً، والخادم يفحص أيضاً)
 *   * العنوان يجتاز `verifyBaseUrl`
 *
 * **كل فحص يفشل مغلقاً** برسالة عربية تُعرض كما هي.
 */
import { API_BASE_URL, SESSION_ENROLL_PATH, verifyBaseUrl } from '@/api/config';

/** ما يقبله التطبيق من إصدارات حمولة الرمز. */
const SUPPORTED_PAYLOAD_VERSION = 1;

export interface EnrolmentPayload {
  v: number;
  backend: string;
  challenge_id: string;
  nonce: string;
  expires_utc: string;
  contains_secret: boolean;
}

export type EnrolmentFailure =
  | 'MALFORMED'
  | 'UNSUPPORTED_VERSION'
  | 'CLAIMS_SECRET'
  | 'BACKEND_MISMATCH'
  | 'UNTRUSTED_BACKEND'
  | 'EXPIRED'
  | 'REJECTED'
  | 'NETWORK';

export interface EnrolmentResult {
  ok: boolean;
  failure?: EnrolmentFailure;
  reasonAr: string;
  session?: {
    accessToken: string;
    refreshToken: string;
    deviceId: string;
    accessExpiresAt: number;
  };
}

const fail = (failure: EnrolmentFailure, reasonAr: string): EnrolmentResult => ({
  ok: false,
  failure,
  reasonAr,
});

/** يُسقط الشرطة المائلة الأخيرة كي لا يفشل التطابق على فرق شكلي. */
const normalise = (url: string): string => url.trim().replace(/\/+$/, '');

/**
 * يفحص الحمولة الممسوحة **بلا أي طلب شبكة**.
 *
 * مفصولة عن `enrolDevice` كي تُختبَر وحدها: أغلب هجمات هذا المسار تُوقَف هنا.
 */
export function parseEnrolmentPayload(
  raw: string,
  now: number = Date.now(),
): { ok: true; payload: EnrolmentPayload } | { ok: false; result: EnrolmentResult } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {
      ok: false,
      result: fail('MALFORMED', 'هذا الرمز ليس رمز اقتران مآثر.'),
    };
  }

  if (typeof parsed !== 'object' || parsed === null) {
    return { ok: false, result: fail('MALFORMED', 'هذا الرمز ليس رمز اقتران مآثر.') };
  }
  const record = parsed as Record<string, unknown>;

  const shapeOk =
    typeof record.backend === 'string' &&
    typeof record.challenge_id === 'string' &&
    typeof record.nonce === 'string' &&
    typeof record.expires_utc === 'string' &&
    record.challenge_id.length > 0 &&
    record.nonce.length > 0;
  if (!shapeOk) {
    return { ok: false, result: fail('MALFORMED', 'رمز اقتران ناقص أو تالف.') };
  }

  if (record.v !== SUPPORTED_PAYLOAD_VERSION) {
    return {
      ok: false,
      result: fail(
        'UNSUPPORTED_VERSION',
        'إصدار رمز الاقتران غير مدعوم في هذه النسخة من التطبيق.',
      ),
    };
  }

  // رمزٌ يعترف بحمل سرّ يُرفَض بلا نقاش: رموز مآثر لا تحمل أسراراً أصلاً،
  // فالإقرار بخلاف ذلك دليل أن الرمز ليس منّا.
  if (record.contains_secret !== false) {
    return {
      ok: false,
      result: fail('CLAIMS_SECRET', 'رمز اقتران يدّعي حمل سرّ — رُفض.'),
    };
  }

  const backend = normalise(record.backend as string);
  const verdict = verifyBaseUrl(backend);
  if (!verdict.ok) {
    return { ok: false, result: fail('UNTRUSTED_BACKEND', verdict.reasonAr) };
  }

  // **الحارس الأهم.** عنوان الخادم مُثبَّت وقت البناء، فرمزٌ يشير إلى غيره
  // غير شرعي بالتعريف — ولو قُبل لأمكن لمن يصنع رمزاً أن يجعل الشاشة تكذب.
  if (backend !== normalise(API_BASE_URL)) {
    return {
      ok: false,
      result: fail(
        'BACKEND_MISMATCH',
        'هذا الرمز يشير إلى خادم آخر غير خادمك. لن يُسجَّل الجهاز.',
      ),
    };
  }

  const expiresAt = Date.parse(record.expires_utc as string);
  if (Number.isNaN(expiresAt)) {
    return { ok: false, result: fail('MALFORMED', 'وقت انتهاء الرمز غير مفهوم.') };
  }
  if (expiresAt <= now) {
    return {
      ok: false,
      result: fail('EXPIRED', 'انتهت صلاحية الرمز. ولّدي رمزاً جديداً من الخادم.'),
    };
  }

  return { ok: true, payload: record as unknown as EnrolmentPayload };
}

/**
 * يُكمل التسجيل: يفحص الحمولة ثم يطلب رموز الجلسة.
 *
 * `publicIdentity` **ليس مفتاحاً عاماً** في هذا الإصدار — هو معرّف عشوائي
 * يُولَّد على الجهاز ويُحفَظ، والخادم يخزّن بصمته لا قيمته. يُستعمل في
 * التدقيق للتمييز بين الأجهزة، ولا تقوم عليه أي مصادقة: المصادقة كلها
 * برموز الخادم قصيرة العمر.
 */
export async function enrolDevice(
  raw: string,
  publicIdentity: string,
  deviceName: string,
  options?: { fetchImpl?: typeof fetch; now?: number },
): Promise<EnrolmentResult> {
  const checked = parseEnrolmentPayload(raw, options?.now ?? Date.now());
  if (!checked.ok) {
    return checked.result;
  }

  const doFetch = options?.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await doFetch(`${API_BASE_URL}${SESSION_ENROLL_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({
        challenge_id: checked.payload.challenge_id,
        public_identity: publicIdentity,
        device_name: deviceName,
      }),
    });
  } catch {
    // لا يُطبع نصّ الخطأ: رسائل الشبكة تحمل عناوين ومسارات.
    return fail('NETWORK', 'تعذّر الوصول إلى الخادم. تأكّدي أنه يعمل وأنكِ على الشبكة الخاصة.');
  }

  if (!response.ok) {
    return fail(
      'REJECTED',
      'رفض الخادم هذا الرمز. غالباً انتهى أو استُعمل من قبل — ولّدي رمزاً جديداً.',
    );
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return fail('REJECTED', 'ردّ الخادم غير مفهوم. لم يُسجَّل الجهاز.');
  }
  if (typeof body !== 'object' || body === null) {
    return fail('REJECTED', 'ردّ الخادم غير مفهوم. لم يُسجَّل الجهاز.');
  }

  const record = body as Record<string, unknown>;
  const access = record.access_token;
  const refresh = record.refresh_token;
  const device = record.device as Record<string, unknown> | undefined;
  const deviceId = device?.device_id;

  if (
    typeof access !== 'string' ||
    typeof refresh !== 'string' ||
    typeof deviceId !== 'string'
  ) {
    return fail('REJECTED', 'ردّ الخادم ناقص. لم تُحفَظ أي رموز.');
  }

  // الثابت الذي يُفحَص في كل استجابة: التطبيق لا يأذن بتنفيذ.
  if (record.authorises_execution !== false) {
    return fail(
      'REJECTED',
      'الخادم لم يُعلن أن التطبيق لا يأذن بتنفيذ. أُوقف التسجيل.',
    );
  }

  const expiresAt = Date.parse(String(record.access_expires_utc ?? ''));
  return {
    ok: true,
    reasonAr: 'سُجِّل الجهاز.',
    session: {
      accessToken: access,
      refreshToken: refresh,
      deviceId,
      accessExpiresAt: Number.isNaN(expiresAt) ? Date.now() + 15 * 60 * 1000 : expiresAt,
    },
  };
}
