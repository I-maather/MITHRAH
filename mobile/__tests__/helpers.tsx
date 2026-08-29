import React, { type ReactNode } from 'react';
import { render, type RenderResult } from '@testing-library/react-native';

import { SessionProvider } from '@/auth/SessionProvider';
import { ThemeProvider } from '@/theme';
import type { GateOutcome } from '@/auth/biometrics';

/**
 * أدوات الاختبار المشتركة.
 * لا شيء هنا يلمس الشبكة: `fetchImpl` يُحقَن دائماً.
 */

export interface HarnessOptions {
  mode?: 'light' | 'dark';
  reduceMotion?: boolean;
  status?: 'BOOTING' | 'NO_SESSION' | 'LOCKED' | 'UNLOCKED' | 'REVOKED';
  fetchImpl?: typeof fetch;
  autoLockMs?: number;
  unlockImpl?: () => Promise<GateOutcome>;
}

export function Harness({
  children,
  options,
}: {
  children: ReactNode;
  options?: HarnessOptions;
}): React.JSX.Element {
  const overrides: NonNullable<React.ComponentProps<typeof SessionProvider>['overrides']> = {};
  if (options?.status !== undefined) {
    overrides.initialStatus = options.status;
  }
  if (options?.fetchImpl !== undefined) {
    overrides.fetchImpl = options.fetchImpl;
  }
  if (options?.autoLockMs !== undefined) {
    overrides.autoLockMs = options.autoLockMs;
  }
  if (options?.unlockImpl !== undefined) {
    overrides.unlockImpl = options.unlockImpl;
  }

  return (
    <ThemeProvider
      {...(options?.mode !== undefined ? { forcedMode: options.mode } : {})}
      forcedReduceMotion={options?.reduceMotion ?? true}
    >
      <SessionProvider overrides={overrides}>{children}</SessionProvider>
    </ThemeProvider>
  );
}

export function renderWithHarness(
  ui: React.ReactElement,
  options?: HarnessOptions,
): RenderResult {
  return render(<Harness options={options}>{ui}</Harness>);
}

/** استجابة GET صالحة بالغلاف المتفق عليه. */
export function envelope<T>(route: string, data: T, overrides: Record<string, unknown> = {}) {
  return {
    route,
    server_time_utc: '2026-01-15T13:40:00+00:00',
    device_id: 'test-device',
    authorises_execution: false,
    data,
    ...overrides,
  };
}

/** fetch مُقلَّد يعيد جسماً واحداً بحالة واحدة. */
export function fetchReturning(body: unknown, status = 200): jest.Mock {
  return jest.fn(async () =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as unknown as Response,
  );
}
