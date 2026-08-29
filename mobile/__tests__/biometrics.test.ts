import * as LocalAuthentication from 'expo-local-authentication';

import { describeGate, readCapabilities, requestUnlock } from '@/auth/biometrics';

/**
 * البوابة المحلية واحتياطها الموثَّق.
 *
 * الاحتياط ليس تنازلاً: جهاز بلا بصمة مسجّلة يبقى محمياً برمزه، وجهاز بلا رمز
 * أصلاً لا يُفتح عليه التطبيق إطلاقاً.
 */

const auth = LocalAuthentication.authenticateAsync as unknown as jest.Mock;
const hasHardware = LocalAuthentication.hasHardwareAsync as unknown as jest.Mock;
const isEnrolled = LocalAuthentication.isEnrolledAsync as unknown as jest.Mock;
const enrolledLevel = LocalAuthentication.getEnrolledLevelAsync as unknown as jest.Mock;
const supportedTypes = LocalAuthentication.supportedAuthenticationTypesAsync as unknown as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  hasHardware.mockResolvedValue(true);
  isEnrolled.mockResolvedValue(true);
  enrolledLevel.mockResolvedValue(LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG);
  supportedTypes.mockResolvedValue([LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION]);
  auth.mockResolvedValue({ success: true });
});

describe('الفتح بـFace ID', () => {
  it('ينجح ويُبلغ أن الطريقة حيوية', async () => {
    const outcome = await requestUnlock();
    expect(outcome).toEqual({ ok: true, method: 'BIOMETRIC' });
  });

  it('يطلب دائماً مع تفعيل احتياط رمز الجهاز', async () => {
    await requestUnlock();
    expect(auth).toHaveBeenCalledWith(
      expect.objectContaining({ disableDeviceFallback: false }),
    );
  });
});

describe('الاحتياط الموثَّق', () => {
  it('بلا بصمة مسجّلة: يُفتح برمز الجهاز', async () => {
    isEnrolled.mockResolvedValue(false);
    enrolledLevel.mockResolvedValue(LocalAuthentication.SecurityLevel.SECRET);
    const outcome = await requestUnlock();
    expect(outcome).toEqual({ ok: true, method: 'DEVICE_PASSCODE' });
  });

  it('بلا عتاد حيوي: يُفتح برمز الجهاز', async () => {
    hasHardware.mockResolvedValue(false);
    enrolledLevel.mockResolvedValue(LocalAuthentication.SecurityLevel.SECRET);
    const outcome = await requestUnlock();
    expect(outcome).toEqual({ ok: true, method: 'DEVICE_PASSCODE' });
  });

  it('جهاز بلا رمز قفل: لا يُفتح التطبيق إطلاقاً ولا يُستدعى الفتح', async () => {
    enrolledLevel.mockResolvedValue(LocalAuthentication.SecurityLevel.NONE);
    const outcome = await requestUnlock();
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.reason).toBe('NO_DEVICE_SECURITY');
    }
    expect(auth).not.toHaveBeenCalled();
  });
});

describe('الإخفاق', () => {
  it('الإلغاء يبقي التطبيق مقفلاً', async () => {
    auth.mockResolvedValue({ success: false, error: 'user_cancel' });
    const outcome = await requestUnlock();
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.reason).toBe('CANCELLED');
      expect(outcome.messageAr).toContain('مقفل');
    }
  });

  it('التعطيل بعد محاولات كثيرة يُشرَح للمستخدمة', async () => {
    auth.mockResolvedValue({ success: false, error: 'lockout' });
    const outcome = await requestUnlock();
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.reason).toBe('LOCKOUT');
    }
  });
});

describe('وصف البوابة', () => {
  it('يقول Face ID حين تكون متاحة', async () => {
    const caps = await readCapabilities();
    expect(describeGate(caps)).toContain('Face ID');
  });

  it('يقول رمز الجهاز حين لا بصمة', async () => {
    isEnrolled.mockResolvedValue(false);
    enrolledLevel.mockResolvedValue(LocalAuthentication.SecurityLevel.SECRET);
    const caps = await readCapabilities();
    expect(describeGate(caps)).toContain('رمز الجهاز');
  });

  it('يقول إن الجهاز غير محمي حين لا رمز له', async () => {
    enrolledLevel.mockResolvedValue(LocalAuthentication.SecurityLevel.NONE);
    const caps = await readCapabilities();
    expect(describeGate(caps)).toContain('بلا رمز قفل');
  });
});
