import * as SecureStore from 'expo-secure-store';

import { ALLOWED_KEYCHAIN_KEYS, maskToken, tokenStore } from '@/auth/tokenStore';

/**
 * سلسلة المفاتيح تحمل **رموز جلسة التطبيق فقط**.
 */

const memory = (): Map<string, string> =>
  (globalThis as unknown as { __secureStoreMemory: Map<string, string> }).__secureStoreMemory;

describe('ما يُكتب في سلسلة المفاتيح', () => {
  it('ثلاثة مفاتيح لا غير، وكلها تخصّ جلسة التطبيق', async () => {
    await tokenStore.save({
      accessToken: 'A',
      refreshToken: 'R',
      deviceId: 'D',
      accessExpiresAt: Date.now(),
    });
    expect([...memory().keys()].sort()).toEqual([...ALLOWED_KEYCHAIN_KEYS].sort());
    expect(ALLOWED_KEYCHAIN_KEYS).toHaveLength(3);
  });

  it('لا اسم مفتاح يشير إلى وسيط أو مزوّد أو قاعدة بيانات', () => {
    for (const key of ALLOWED_KEYCHAIN_KEYS) {
      expect(key).toMatch(/^maather\.session\./);
      expect(key.toLowerCase()).not.toMatch(/broker|provider|apns|database|order|signing/);
    }
  });

  it('الحفظ يستعمل أضيق مستوى وصول ولا يُزامَن', async () => {
    await tokenStore.save({
      accessToken: 'A',
      refreshToken: 'R',
      deviceId: 'D',
      accessExpiresAt: Date.now(),
    });
    const setItem = SecureStore.setItemAsync as unknown as jest.Mock;
    for (const call of setItem.mock.calls) {
      expect(call[2]).toEqual({
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      });
    }
  });
});

describe('التدوير والمحو', () => {
  it('التدوير يكتب فوق القديم ولا يتركه', async () => {
    await tokenStore.save({
      accessToken: 'A1',
      refreshToken: 'R1',
      deviceId: 'D',
      accessExpiresAt: 0,
    });
    await tokenStore.rotate('A2', 'R2');
    expect(await tokenStore.loadAccessToken()).toBe('A2');
    expect(await tokenStore.loadRefreshToken()).toBe('R2');
    expect([...memory().values()]).not.toContain('R1');
  });

  it('المحو يُفرغ كل شيء', async () => {
    await tokenStore.save({
      accessToken: 'A',
      refreshToken: 'R',
      deviceId: 'D',
      accessExpiresAt: 0,
    });
    await tokenStore.clear();
    expect(memory().size).toBe(0);
    expect(await tokenStore.hasSession()).toBe(false);
  });
});

describe('التقنيع', () => {
  it('لا يعرض الرمز كاملاً', () => {
    const masked = maskToken('abcdefghijklmnop');
    expect(masked.startsWith('abcd')).toBe(true);
    expect(masked).not.toContain('efghijklmnop');
  });

  it('يعرض شرطة عند الغياب', () => {
    expect(maskToken(null)).toBe('—');
    expect(maskToken('')).toBe('—');
  });
});
