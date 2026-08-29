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
 *   * **لا حقل خارج الأربعة المعروفة** — الحقل الزائد هو المكان الذي
 *     يُهرَّب فيه محتوى، فيُرفَض بوجوده لا باعترافه
 *   * الشكل صحيح والإصدار معروف
 *   * لم ينتهِ وقته (يُفحَص محلياً كي تُقال الرسالة فوراً، والخادم يفحص أيضاً)
 *   * العنوان يجتاز `verifyBaseUrl`
 *
 * **كل فحص يفشل مغلقاً** برسالة عربية تُعرض كما هي.
 */
import { API_BASE_URL, SESSION_ENROLL_PATH, verifyBaseUrl } from '@/api/config';

/**
 * إصدار حمولة الرمز المقبول.
 *
 * رُفع إلى 2 حين ضُغطت الحمولة: النسخة الأولى كانت 216 محرفاً فأنتجت رمزاً
 * بعرض 69 وحدة يتجاوز عرض الطرفية فيلتفّ — ورمزٌ ملتفّ **لا يُمسح**.
 * الحمولة الآن 98 محرفاً و45 وحدة.
 */
const SUPPORTED_PAYLOAD_VERSION = 2;

/**
 * المفاتيح المسموح بها في الحمولة — **لا واحد زائد**.
 *
 * هذا بديلٌ أقوى عن `contains_secret: false` الذي كان يُرسَل قبلاً: حقلٌ
 * إضافي هو المكان الذي يُهرَّب فيه سرّ، فيُرفَض **بوجوده** لا باعترافه.
 * والرفض بالبنية لا يعتمد على صدق من صنع الرمز.
 */
const ALLOWED_PAYLOAD_KEYS = ['v', 'b', 'c', 'e'] as const;

export interface EnrolmentPayload {
  /** إصدار الحمولة. */
  v: number;
  /** عنوان الخادم. */
  b: string;
  /** معرّف التحدّي. */
  c: string;
  /** لحظة الانتهاء — ثوانٍ منذ Epoch. */
  e: number;
}

export type EnrolmentFailure =
  | 'MALFORMED'
  | 'UNSUPPORTED_VERSION'
  | 'UNEXPECTED_FIELD'
  | 'BACKEND_MISMATCH'
  | 'UNTRUSTED_BACKEND'
  | 'EXPIRED'
  | 'REJECTED'
  | 'ROUTE_MISSING'
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

  // **لا حقل زائد.** يُفحَص قبل كل شيء: الحقل الإضافي هو المكان الذي
  // يُهرَّب فيه محتوى، فيُرفَض بوجوده.
  const unexpected = Object.keys(record).filter(
    (key) => !(ALLOWED_PAYLOAD_KEYS as readonly string[]).includes(key),
  );
  if (unexpected.length > 0) {
    return {
      ok: false,
      result: fail('UNEXPECTED_FIELD', 'رمز اقتران يحمل حقولاً غير متوقَّعة — رُفض.'),
    };
  }

  const shapeOk =
    typeof record.b === 'string' &&
    typeof record.c === 'string' &&
    typeof record.e === 'number' &&
    (record.c as string).length > 0;
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

  const backend = normalise(record.b as string);
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

  // ثوانٍ منذ Epoch لا نصّ ISO: عشرة محارف بدل اثنين وثلاثين.
  const expiresAt = (record.e as number) * 1000;
  if (!Number.isFinite(expiresAt)) {
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
        challenge_id: checked.payload.c,
        public_identity: publicIdentity,
        device_name: deviceName,
      }),
    });
  } catch {
    // لا يُطبع نصّ الخطأ: رسائل الشبكة تحمل عناوين ومسارات.
    return fail('NETWORK', 'تعذّر الوصول إلى الخادم. تأكّدي أنه يعمل وأنكِ على الشبكة الخاصة.');
  }

  if (!response.ok) {
    // **404 ليست رفضاً للرمز.** الخادم لا يعرف مسار التسجيل أصلاً — أي أنه
    // يعمل بنسخة أقدم من التي أضافت المسار. وقول «انتهى أو استُعمل» هنا
    // يوجّه المالكة إلى توليد رمز بعد رمز بلا فائدة. حدث ذلك فعلاً.
    if (response.status === 404) {
      return fail(
        'ROUTE_MISSING',
        'الخادم لا يعرف مسار التسجيل — يعمل بنسخة أقدم. أعيدي تشغيله ثم ولّدي رمزاً جديداً.',
      );
    }
    if (response.status === 503) {
      return fail('ROUTE_MISSING', 'طبقة الجوال غير مُهيّأة على الخادم. أعيدي تشغيله.');
    }
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
