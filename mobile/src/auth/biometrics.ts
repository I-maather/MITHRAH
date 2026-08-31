import * as LocalAuthentication from 'expo-local-authentication';

/**
 * بوابة الوصول المحلية.
 *
 * FACE ID IS NOT SERVER AUTHENTICATION.
 * Face ID unlocks the app *on this handset*. It proves nothing to the backend —
 * a jailbroken phone can defeat it. The real authentication is the short-lived
 * bearer token the server issued to this enrolled device. The two are layered:
 *
 *     Face ID          = بوابة وصول محلية (this file)
 *     رمز الخادم القصير = المصادقة الفعلية (src/api/client.ts)
 *
 * Consequently: passing this gate NEVER grants a permission the server has not
 * already granted the device, and failing it never revokes one — it only keeps
 * the screen closed.
 *
 * الاحتياط الموثَّق (documented fallback):
 *   1. Face ID / Touch ID إن كانت مُسجَّلة.
 *   2. وإلا: رمز الجهاز (passcode) — `disableDeviceFallback: false`.
 *   3. وإن لم يكن للجهاز رمز أصلاً: التطبيق **يُغلق** ولا يعرض شيئاً، لأن
 *      جهازاً بلا رمز لا يحمي سلسلة المفاتيح.
 */

export type GateOutcome =
  | { ok: true; method: 'BIOMETRIC' | 'DEVICE_PASSCODE' }
  | { ok: false; reason: GateFailure; messageAr: string };

export type GateFailure =
  | 'NO_HARDWARE'
  | 'NOT_ENROLLED'
  | 'NO_DEVICE_SECURITY'
  | 'CANCELLED'
  | 'LOCKOUT'
  | 'FAILED';

export interface GateCapabilities {
  hasHardware: boolean;
  isEnrolled: boolean;
  /** مستوى تأمين الجهاز نفسه. NONE يعني بلا رمز. */
  securityLevel: LocalAuthentication.SecurityLevel;
  /** الأنواع المدعومة (بصمة الوجه / بصمة الإصبع). */
  types: LocalAuthentication.AuthenticationType[];
}

export async function readCapabilities(): Promise<GateCapabilities> {
  const [hasHardware, isEnrolled, securityLevel, types] = await Promise.all([
    LocalAuthentication.hasHardwareAsync(),
    LocalAuthentication.isEnrolledAsync(),
    LocalAuthentication.getEnrolledLevelAsync(),
    LocalAuthentication.supportedAuthenticationTypesAsync(),
  ]);
  return { hasHardware, isEnrolled, securityLevel, types };
}

/** وصف عربي لطريقة الفتح المتاحة — يُعرض على شاشة القفل. */
export function describeGate(caps: GateCapabilities): string {
  if (caps.securityLevel === LocalAuthentication.SecurityLevel.NONE) {
    return 'هذا الجهاز بلا رمز قفل. لا يمكن فتح مثراة عليه.';
  }
  if (caps.hasHardware && caps.isEnrolled) {
    const faceId = caps.types.includes(
      LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION,
    );
    return faceId ? 'الفتح بـFace ID.' : 'الفتح ببصمة الإصبع.';
  }
  return 'الفتح برمز الجهاز.';
}

export const PROMPT_AR = 'افتحي مثراة';
export const FALLBACK_LABEL_AR = 'استعملي رمز الجهاز';

/**
 * يطلب الفتح. **لا يمرّر شيئاً إلى الخادم** ولا يقرأ رمزاً.
 * The result is a local boolean and nothing else.
 */
export async function requestUnlock(
  caps?: GateCapabilities,
): Promise<GateOutcome> {
  const capabilities = caps ?? (await readCapabilities());

  if (capabilities.securityLevel === LocalAuthentication.SecurityLevel.NONE) {
    return {
      ok: false,
      reason: 'NO_DEVICE_SECURITY',
      messageAr:
        'لا يوجد رمز قفل على هذا الجهاز. مثراة لا يفتح على جهاز غير محمي — فعّلي رمز القفل ثم أعيدي المحاولة.',
    };
  }

  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: PROMPT_AR,
    // الاحتياط مُفعَّل عمداً: رمز الجهاز بديل مقبول عن البصمة.
    disableDeviceFallback: false,
    fallbackLabel: FALLBACK_LABEL_AR,
    cancelLabel: 'إلغاء',
  });

  if (result.success) {
    const usedBiometric = capabilities.hasHardware && capabilities.isEnrolled;
    return { ok: true, method: usedBiometric ? 'BIOMETRIC' : 'DEVICE_PASSCODE' };
  }

  const error = 'error' in result ? result.error : 'unknown';
  if (error === 'user_cancel' || error === 'app_cancel' || error === 'system_cancel') {
    return { ok: false, reason: 'CANCELLED', messageAr: 'أُلغي الفتح. التطبيق ما يزال مقفلاً.' };
  }
  if (error === 'lockout' || error === 'lockout_permanent') {
    return {
      ok: false,
      reason: 'LOCKOUT',
      messageAr: 'تعطّل الفتح بعد محاولات كثيرة. افتحي الجهاز برمزه ثم أعيدي المحاولة.',
    };
  }
  if (error === 'not_enrolled') {
    return {
      ok: false,
      reason: 'NOT_ENROLLED',
      messageAr: 'لا بصمة مسجّلة. سيُطلب رمز الجهاز بدلاً منها.',
    };
  }
  if (error === 'not_available' || error === 'no_hardware') {
    return {
      ok: false,
      reason: 'NO_HARDWARE',
      messageAr: 'لا يدعم هذا الجهاز الفتح بالبصمة. سيُطلب رمز الجهاز.',
    };
  }
  return { ok: false, reason: 'FAILED', messageAr: 'لم يُقبل الفتح. أعيدي المحاولة.' };
}
