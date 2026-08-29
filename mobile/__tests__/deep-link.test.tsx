import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import * as Linking from 'expo-linking';

import { AppShell } from '../app/_layout';
import SecureLaunchScreen from '../app/index';
import { ALLOWED_DEEP_LINK_TARGETS, resolveDeepLink } from '@/utils/deepLinks';
import { SessionProbe, renderWithHarness } from './helpers';

/**
 * الروابط العميقة **لا تُحلّ قبل المصادقة**.
 */

describe('قائمة الوجهات', () => {
  it('كل وجهة مسموحة تُحلّ إلى مسار داخلي', () => {
    for (const target of ALLOWED_DEEP_LINK_TARGETS) {
      const resolved = resolveDeepLink(`maather://${target}`);
      expect(resolved.path).toMatch(/^\/\(app\)\//);
    }
  });

  it('وجهة مجهولة تُهمَل', () => {
    expect(resolveDeepLink('maather://place-order').path).toBeNull();
    expect(resolveDeepLink('maather://../../etc/passwd').path).toBeNull();
  });

  it('مخطط خارجي يُهمَل', () => {
    expect(resolveDeepLink('https://example.invalid/home').path).toBeNull();
    expect(resolveDeepLink('otherapp://home').path).toBeNull();
  });

  it('رابط يحمل معاملات يُهمَل — لا حالة تدخل من الخارج', () => {
    const resolved = resolveDeepLink('maather://home?token=abc');
    expect(resolved.path).toBeNull();
    expect(resolved.reasonAr).toContain('معاملات');
  });

  it('رابط غير صالح يُهمَل بلا انفجار', () => {
    expect(resolveDeepLink('%%%').path).toBeNull();
    expect(resolveDeepLink('').path).toBeNull();
  });

  it('لا وجهة تفتح إجراءً — الطوارئ شاشة لا فعل', () => {
    for (const target of ALLOWED_DEEP_LINK_TARGETS) {
      expect(target).not.toMatch(/pause|killswitch|revoke|activate/);
    }
  });
});

/**
 * ## لماذا لا `act(async () => Promise.resolve())`
 *
 * `Promise.resolve()` يستنزف **دورة microtask واحدة**. و`getInitialURL()`
 * مُقلَّد بـ`mockResolvedValue`، فسلسلته تحتاج أكثر من دورة: وعدٌ في
 * `_layout` ثم `setState` ثم إعادة تصيير ثم تأثير التوجيه. فالانتظار بدورة
 * واحدة يؤكّد على حالة **لم تستقرّ بعد** — فيمرّ التأكيد السلبي («لم يوجّه»)
 * لأن التوجيه لم يحدث **بعد**، لا لأنه ممنوع. تأكيدٌ يمرّ للسبب الخطأ.
 *
 * البديل هنا: `waitFor` على علامة استقرار حقيقية (ظهور الشاشة)، ثم التأكيد.
 * وهو أيضاً ما يزيل تحذير React عن `setState` خارج `act`: التصيير الأول
 * يُنهي `readCapabilities()` قبل أن ينتهي الاختبار.
 */

const linkTarget = (path: string): string => `/(app)/${path}`;

describe('الاحتجاز حتى المصادقة', () => {
  const getInitialURL = Linking.getInitialURL as unknown as jest.Mock;

  /** مُقلِّد الموجّه يُصفَّر عالمياً في `jest.setup.ts` قبل كل اختبار. */
  const router = (): { push: jest.Mock; replace: jest.Mock } =>
    (globalThis as unknown as { __routerMock: { push: jest.Mock; replace: jest.Mock } })
      .__routerMock;

  beforeEach(() => {
    getInitialURL.mockResolvedValue(null);
  });

  it('رابط وارد والتطبيق مقفل: يُحتجَز ولا يُوجَّه', async () => {
    getInitialURL.mockResolvedValue('maather://position');

    renderWithHarness(<SecureLaunchScreen />, { status: 'LOCKED' });

    // علامة استقرار: شاشة القفل ظهرت ⇒ التصيير الأول اكتمل وتأثيراته جرت.
    expect(await screen.findByTestId('secure-launch')).toBeTruthy();
    expect(router().push).not.toHaveBeenCalled();
    expect(router().replace).not.toHaveBeenCalled();
  });

  it('الجذر يلتقط الرابط ولا يوجّه ما دام مقفلاً', async () => {
    getInitialURL.mockResolvedValue('maather://audit');

    renderWithHarness(
      <>
        <AppShell />
        <SessionProbe />
      </>,
      { status: 'LOCKED' },
    );

    // الرابط **احتُجِز فعلاً** — لا «لم يصل بعد».
    await waitFor(() => {
      expect(screen.getByTestId('probe-pending')).toHaveTextContent('maather://audit');
    });
    expect(screen.getByTestId('probe-status')).toHaveTextContent('LOCKED');
    expect(router().push).not.toHaveBeenCalled();
  });

  it('بعد الفتح يُحلّ الرابط المحتجَز **مرة واحدة**', async () => {
    getInitialURL.mockResolvedValue('maather://audit');

    renderWithHarness(
      <>
        <AppShell />
        <SessionProbe />
      </>,
      { status: 'UNLOCKED' },
    );

    await waitFor(() => {
      expect(router().push).toHaveBeenCalledWith(linkTarget('audit'));
    });

    // استُهلك: لم يعد محتجَزاً، فلا يمكن أن يُحلّ ثانيةً.
    await waitFor(() => {
      expect(screen.getByTestId('probe-pending')).toHaveTextContent('NONE');
    });

    // الاستهلاك مرّة واحدة: يُنتظر استقرار إضافي ثم يُعاد العدّ. الاكتفاء
    // بالتأكيد فور أول استدعاء يُثبت «وُجِّه»، لا «وُجِّه مرة واحدة».
    await waitFor(() => {
      expect(router().push).toHaveBeenCalledTimes(1);
    });
    expect(router().push).toHaveBeenCalledTimes(1);
  });

  it('رابط غير مسموح لا يوجّه حتى بعد الفتح', async () => {
    getInitialURL.mockResolvedValue('maather://place-order');

    renderWithHarness(
      <>
        <AppShell />
        <SessionProbe />
      </>,
      { status: 'UNLOCKED' },
    );

    // وصل واستُهلك — ومع ذلك **لم يوجّه**، لأن الوجهة خارج القائمة.
    await waitFor(() => {
      expect(screen.getByTestId('probe-pending')).toHaveTextContent('NONE');
    });
    expect(router().push).not.toHaveBeenCalled();
  });

  it('شاشة القفل تُعلم أن رابطاً بانتظار التحقق', async () => {
    getInitialURL.mockResolvedValue('maather://audit');

    renderWithHarness(
      <>
        <AppShell />
        <SecureLaunchScreen />
        <SessionProbe />
      </>,
      { status: 'LOCKED' },
    );

    // شاشة القفل تُظهر شريط «رابط بانتظار التحقق» — دليلٌ مرئي لا استنتاج.
    expect(await screen.findByTestId('deeplink-held')).toBeTruthy();
    expect(screen.getByTestId('probe-pending')).toHaveTextContent('maather://audit');
    expect(router().push).not.toHaveBeenCalled();
  });
});

/**
 * أقوى إثبات للخاصية المطلوبة: **الانتقال** نفسه.
 *
 * الاختبارات التي تبدأ من حالة `UNLOCKED` تثبت أن الرابط يُحلّ بعد الفتح،
 * لكنها لا تثبت أنه **كان محجوزاً قبله**: قد يكون النظام يُحلّ كل رابط فوراً
 * وتصادف أن الحالة مفتوحة. هذا الاختبار يمرّ بالحالتين في تصييرٍ واحد.
 */
describe('الانتقال من مقفل إلى مفتوح', () => {
  const getInitialURL = Linking.getInitialURL as unknown as jest.Mock;

  it('محتجَز وهو مقفل، ثم يُحلّ مرة واحدة بعد الفتح', async () => {
    getInitialURL.mockResolvedValue('maather://audit');
    const router = (globalThis as unknown as { __routerMock: { push: jest.Mock } })
      .__routerMock;

    renderWithHarness(
      <>
        <AppShell />
        <SessionProbe />
      </>,
      { status: 'LOCKED', unlockImpl: async () => ({ ok: true, method: 'BIOMETRIC' }) },
    );

    // (١) مقفل: الرابط محتجَز، ولا توجيه.
    await waitFor(() => {
      expect(screen.getByTestId('probe-pending')).toHaveTextContent('maather://audit');
    });
    expect(router.push).not.toHaveBeenCalled();

    // (٢) الفتح.
    fireEvent.press(screen.getByTestId('probe-unlock'));
    await waitFor(() => {
      expect(screen.getByTestId('probe-status')).toHaveTextContent('UNLOCKED');
    });

    // (٣) يُحلّ الآن — ومرة واحدة، والاحتجاز أُفرِغ.
    await waitFor(() => {
      expect(router.push).toHaveBeenCalledWith('/(app)/audit');
    });
    await waitFor(() => {
      expect(screen.getByTestId('probe-pending')).toHaveTextContent('NONE');
    });
    expect(router.push).toHaveBeenCalledTimes(1);
  });
});
