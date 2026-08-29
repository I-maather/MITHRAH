import { act, screen, waitFor } from '@testing-library/react-native';
import { readFileSync } from 'fs';
import React from 'react';
import { join } from 'path';

import HomeScreen from '../app/(app)/home';
import DecisionScreen from '../app/(app)/decision';
import PositionScreen from '../app/(app)/position';
import ProfilesScreen from '../app/(app)/profiles';
import ProvidersScreen from '../app/(app)/providers';
import PerformanceScreen from '../app/(app)/performance';
import SystemScreen from '../app/(app)/system';
import { CrashGuard } from '@/components';
import { fixtures } from '@/fixtures';
import { tokenStore } from '@/auth/tokenStore';
import { renderWithHarness } from './helpers';

/**
 * الشاشات على **بيانات الخادم الحقيقية اليوم**: أغلبها `null`.
 *
 * ## لماذا لم تكفِ الاختبارات السابقة
 *
 * كانت كلها على بيانات المعاينة — وهي كاملة وجميلة ولا تشبه ما يرسله
 * الخادم الآن: لا استراتيجية، ولا حدث، ولا نتيجة، ولا مزوّد واحد مُعدّ.
 * فمرّت الشاشات على بيانات لا تصل إليها أبداً.
 *
 * هنا تُبنى الحالة الأسوأ آلياً: **كل حقل يسمح العقد بأن يكون `null`
 * يصير `null`**، ويبقى ما لا يسمح. ثم تُصيَّر الشاشات.
 *
 * والمقياس بسيط: لا انهيار، وتظهر الشاشة. «غير متاح» نتيجة صحيحة —
 * أما الشاشة السوداء فليست نتيجة.
 */

/**
 * **إطفاء وضع المعاينة لهذا الملف وحده.**
 *
 * `PREVIEW_DATA_ENABLED` تصير `true` تلقائياً حين `__DEV__`، و`__DEV__`
 * صحيحة داخل Jest. فكل اختبارات الشاشات كانت — بلا أن ننتبه — تعمل على
 * بيانات المعاينة **ولا تلمس مسار الخادم إطلاقاً**.
 *
 * وهذا بالضبط ما سمح لاختلاف الشكل أن يُشحَن: الشاشات مُختبَرة على بيانات
 * لا تصلها أبداً.
 */
jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: false,
}));

const CONTRACT = JSON.parse(
  readFileSync(join(__dirname, '..', '..', 'docs', 'mobile-contract.json'), 'utf8'),
) as { __non_nullable_paths__: string[] };

const KEEP = new Set(CONTRACT.__non_nullable_paths__);

/**
 * يُفرّغ كل ما يسمح العقد بتفريغه.
 *
 * `depth === 0` هو القسم نفسه ولا يُفرَّغ أبداً: الخادم يرسل القسم دائماً،
 * وتفريغُه هنا يختبر حالةً لا تقع.
 */
const emptied = (value: unknown, path: string, depth = 0): unknown => {
  const keep = depth === 0 || KEEP.has(path);
  if (Array.isArray(value)) {
    // القوائم التي لا تقبل null تبقى قوائم — فارغة، وهو ما يرسله الخادم.
    return keep ? [] : null;
  }
  if (value !== null && typeof value === 'object') {
    if (!keep) {
      return null;
    }
    const out: Record<string, unknown> = {};
    for (const [key, sub] of Object.entries(value as Record<string, unknown>)) {
      out[key] = emptied(sub, `${path}.${key}`, depth + 1);
    }
    return out;
  }
  return keep ? value : null;
};

const sparse: Record<string, unknown> = {};
for (const [section, value] of Object.entries(fixtures)) {
  sparse[section] = emptied(value, section);
}

const ROUTE_TO_SECTION: Record<string, string> = {
  status: 'status',
  'intelligence/latest': 'intelligence',
  'decision/latest': 'decision',
  risk: 'risk',
  profiles: 'profiles',
  'positions/current': 'position',
  trades: 'trades',
  performance: 'performance',
  'providers/health': 'providers',
  notifications: 'notifications',
  'audit/recent': 'audit',
};

const fetchSparse = jest.fn(async (url: string) => {
  const route = String(url).split('/api/mobile/v1/')[1] ?? '';
  const section = ROUTE_TO_SECTION[route];
  return {
    ok: true,
    status: 200,
    json: async () => ({
      route,
      server_time_utc: '2026-08-29T13:00:00+00:00',
      device_id: 'test-device',
      authorises_execution: false,
      data: section === undefined ? {} : sparse[section],
    }),
  } as unknown as Response;
});

const SCREENS: Array<[string, () => React.JSX.Element, string]> = [
  ['الرئيسية', HomeScreen, 'home-screen'],
  ['القرار', DecisionScreen, 'decision-screen'],
  ['المركز', PositionScreen, 'position-screen'],
  ['الملفات', ProfilesScreen, 'profiles-screen'],
  ['المزوّدون', ProvidersScreen, 'providers-screen'],
  ['الأداء', PerformanceScreen, 'performance-screen'],
  ['النظام', SystemScreen, 'system-screen'],
];

describe('الشاشات لا تنهار على بيانات شبه فارغة', () => {
  beforeEach(async () => {
    fetchSparse.mockClear();
    // بلا رمز محفوظ يرفض العميل الطلب قبل الشبكة، فلا يُختبَر شيء.
    await tokenStore.save({
      accessToken: 'test-access',
      refreshToken: 'test-refresh',
      deviceId: 'test-device',
      accessExpiresAt: Date.now() + 900_000,
    });
  });

  it.each(SCREENS)('«%s» تُعرض ولا تنهار', async (_label, Screen, testID) => {
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
    renderWithHarness(
      <CrashGuard showDetail>
        <Screen />
      </CrashGuard>,
      { status: 'UNLOCKED', fetchImpl: fetchSparse as unknown as typeof fetch },
    );

    // الحارس على الاختبار نفسه: لو عاد وضع المعاينة يعمل، لن يُلمس الخادم
    // ويمرّ هذا الملف على لا شيء.
    await waitFor(() => expect(fetchSparse).toHaveBeenCalled());
    // **والانتظار حتى تُطبَّق البيانات فعلاً.** الانهيار يقع عند التصيير
    // الثاني — بعد وصول الردّ — لا عند الأول. وفحصٌ يسبقه يمرّ على شاشة
    // تحميل ثم تنهار بعده.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByTestId('crash-guard')).toBeNull();
    expect(screen.getByTestId(testID)).toBeTruthy();
  });
});
