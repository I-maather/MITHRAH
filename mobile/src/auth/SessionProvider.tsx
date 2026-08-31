import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { AppState, type AppStateStatus } from 'react-native';

import { MobileApiClient, type RefreshOutcome, type TokenSource } from '@/api/client';
import { API_BASE_URL, AUTO_LOCK_MINUTES, SESSION_REFRESH_PATH, verifyBaseUrl } from '@/api/config';
import { requestUnlock, type GateOutcome } from './biometrics';
import { tokenStore, type StoredSession } from './tokenStore';

/**
 * حالة الجلسة والقفل.
 *
 * ثلاث طبقات مستقلة، وسقوط أيّها يُغلق الشاشة:
 *   1. جلسة مسجَّلة على الخادم (رمز تجديد في سلسلة المفاتيح).
 *   2. بوابة محلية مفتوحة (Face ID أو رمز الجهاز) — انظري biometrics.ts.
 *   3. خمول أقل من الحد ⇒ وإلا قفل تلقائي.
 *
 * الروابط العميقة **لا تُحلّ** قبل اكتمال الثلاث. الرابط يُحتجَز ويُفتح بعد
 * الفتح، فلا يستطيع رابط من إشعار أو رسالة أن يعرض شاشة دون مصادقة.
 */

export type SessionStatus =
  | 'BOOTING'
  | 'NO_SESSION'
  | 'LOCKED'
  | 'UNLOCKED'
  | 'REVOKED';

export interface SessionContextValue {
  status: SessionStatus;
  /** سبب آخر إخفاق في الفتح، للعرض على شاشة القفل. */
  lastGateMessageAr: string | null;
  /** true بينما التطبيق في الخلفية أو الانتقال — يُستعمل لستر المحتوى. */
  obscured: boolean;
  deviceId: string | null;
  client: MobileApiClient;
  endpointTrusted: boolean;
  endpointReasonAr: string;
  /** رابط عميق محتجَز حتى الفتح. */
  pendingDeepLink: string | null;
  unlock: () => Promise<GateOutcome>;
  lock: () => void;
  /** تُستدعى مع كل تفاعل كي يُعاد ضبط مؤقّت الخمول. */
  registerActivity: () => void;
  capturePendingDeepLink: (url: string) => void;
  consumePendingDeepLink: () => string | null;
  /** تبنّي جلسة بعد تسجيل ناجح من رمز QR. ينتهي إلى `LOCKED`. */
  adoptSession: (session: StoredSession) => Promise<void>;
  /** إنهاء الجلسة محلياً ومحو الرموز. */
  signOut: () => Promise<void>;
  /** تُستدعى بعد نجاح `device/revoke` على الجهاز نفسه. */
  markRevoked: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

interface SessionProviderProps {
  children: ReactNode;
  /** حقن للاختبارات فقط. */
  overrides?: Partial<{
    fetchImpl: typeof fetch;
    autoLockMs: number;
    initialStatus: SessionStatus;
    unlockImpl: () => Promise<GateOutcome>;
  }>;
}

export function SessionProvider({
  children,
  overrides,
}: SessionProviderProps): React.JSX.Element {
  const [status, setStatus] = useState<SessionStatus>(overrides?.initialStatus ?? 'BOOTING');
  const [lastGateMessageAr, setLastGateMessageAr] = useState<string | null>(null);
  const [obscured, setObscured] = useState(false);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [pendingDeepLink, setPendingDeepLink] = useState<string | null>(null);

  const lastActivityRef = useRef<number>(Date.now());
  const autoLockMs = overrides?.autoLockMs ?? AUTO_LOCK_MINUTES * 60 * 1000;
  const statusRef = useRef<SessionStatus>(status);
  statusRef.current = status;

  const lock = useCallback(() => {
    setStatus((current) => (current === 'UNLOCKED' ? 'LOCKED' : current));
  }, []);

  const signOut = useCallback(async () => {
    await tokenStore.clear();
    setDeviceId(null);
    setPendingDeepLink(null);
    setStatus('NO_SESSION');
  }, []);

  /**
   * تبنّي جلسة جديدة بعد نجاح التسجيل من رمز QR.
   *
   * ينتهي إلى **`LOCKED` لا `UNLOCKED`**: التسجيل يثبت أن الجهاز مأذون له
   * لدى الخادم، ولا يثبت أن حامل الجهاز هو المالكة. بوابة Face ID تبقى
   * قائمة بعده مباشرةً.
   */
  const adoptSession = useCallback(async (session: StoredSession) => {
    await tokenStore.save(session);
    setDeviceId(session.deviceId);
    setStatus('LOCKED');
  }, []);

  const markRevoked = useCallback(async () => {
    await tokenStore.clear();
    setDeviceId(null);
    setPendingDeepLink(null);
    setStatus('REVOKED');
  }, []);

  /**
   * مصدر الرموز للعميل.
   *
   * التجديد يقع على مسار **خارج** مجال `v1`: ذلك المجال لا يقبل POST غير
   * الثلاثة المُقلِّلة للمخاطرة. إن لم يكن المسار مُتاحاً بعد على الخادم،
   * يفشل التجديد ونُغلق الجلسة بدل الاستمرار برمز منتهٍ.
   */
  const tokens = useMemo<TokenSource>(
    () => ({
      getAccessToken: () => tokenStore.loadAccessToken(),
      refresh: async (): Promise<RefreshOutcome> => {
        const refreshToken = await tokenStore.loadRefreshToken();
        if (refreshToken === null) {
          // لا رمز أصلاً — لا شيء يُجدَّد ولا شيء يُمحى.
          return { status: 'rejected' };
        }
        const verdict = verifyBaseUrl(API_BASE_URL);
        if (!verdict.ok) {
          // عنوانٌ غير صالح عطلُ إعداد لا إلغاءُ جهاز.
          return { status: 'unavailable' };
        }
        const doFetch = overrides?.fetchImpl ?? fetch;
        let response: Response;
        try {
          response = await doFetch(`${API_BASE_URL}${SESSION_REFRESH_PATH}`, {
            method: 'POST',
            headers: { 'content-type': 'application/json', accept: 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
          });
        } catch {
          // شبكة. **لا تُمحى جلسة لأن الخادم لم يُجب.**
          return { status: 'unavailable' };
        }

        // 401/403 وحدهما رفضٌ صريح لهذا الجهاز. و5xx خادمٌ متعثّر —
        // وإعادةُ تشغيل الخدمة عند كل نشر تمرّ من هنا بالضبط.
        if (response.status === 401 || response.status === 403) {
          return { status: 'rejected' };
        }
        if (!response.ok) {
          return { status: 'unavailable' };
        }

        try {
          const body: unknown = await response.json();
          if (typeof body !== 'object' || body === null) {
            return { status: 'unavailable' };
          }
          const record = body as Record<string, unknown>;
          const access = record.access_token;
          const nextRefresh = record.refresh_token;
          if (typeof access !== 'string' || typeof nextRefresh !== 'string') {
            return { status: 'unavailable' };
          }
          // التدوير إجباري: الرمز القديم يُكتب فوقه فوراً.
          await tokenStore.rotate(access, nextRefresh);
          return { status: 'renewed', accessToken: access };
        } catch {
          return { status: 'unavailable' };
        }
      },
      onSessionLost: async () => {
        await tokenStore.clear();
        setDeviceId(null);
        setStatus('NO_SESSION');
      },
    }),
    [overrides?.fetchImpl],
  );

  const client = useMemo(
    () =>
      new MobileApiClient({
        tokens,
        ...(overrides?.fetchImpl !== undefined ? { fetchImpl: overrides.fetchImpl } : {}),
      }),
    [tokens, overrides?.fetchImpl],
  );

  const endpoint = useMemo(() => verifyBaseUrl(API_BASE_URL), []);

  // -- الإقلاع --------------------------------------------------------------

  useEffect(() => {
    if (overrides?.initialStatus !== undefined) {
      return;
    }
    let alive = true;
    void (async () => {
      const [hasSession, storedDeviceId] = await Promise.all([
        tokenStore.hasSession(),
        tokenStore.loadDeviceId(),
      ]);
      if (!alive) {
        return;
      }
      setDeviceId(storedDeviceId);
      setStatus(hasSession ? 'LOCKED' : 'NO_SESSION');
    })();
    return () => {
      alive = false;
    };
  }, [overrides?.initialStatus]);

  // -- ستر المحتوى في مبدّل التطبيقات + القفل التلقائي -----------------------

  useEffect(() => {
    const handle = (next: AppStateStatus): void => {
      if (next === 'active') {
        setObscured(false);
        const idle = Date.now() - lastActivityRef.current;
        if (idle >= autoLockMs && statusRef.current === 'UNLOCKED') {
          setStatus('LOCKED');
          setLastGateMessageAr('أُقفل التطبيق بعد خمول. افتحيه من جديد.');
        }
      } else {
        // `inactive` تسبق لقطة مبدّل التطبيقات، فالستر يبدأ قبلها لا بعدها.
        setObscured(true);
        lastActivityRef.current = Date.now();
      }
    };
    const sub = AppState.addEventListener('change', handle);
    return () => {
      sub.remove();
    };
  }, [autoLockMs]);

  // مؤقّت خمول داخل التطبيق نفسه.
  useEffect(() => {
    if (status !== 'UNLOCKED') {
      return;
    }
    const interval = setInterval(() => {
      if (Date.now() - lastActivityRef.current >= autoLockMs) {
        setStatus('LOCKED');
        setLastGateMessageAr('أُقفل التطبيق بعد خمول. افتحيه من جديد.');
      }
    }, 15_000);
    return () => {
      clearInterval(interval);
    };
  }, [status, autoLockMs]);

  const registerActivity = useCallback(() => {
    lastActivityRef.current = Date.now();
  }, []);

  const unlock = useCallback(async (): Promise<GateOutcome> => {
    const outcome = await (overrides?.unlockImpl ?? requestUnlock)();
    if (outcome.ok) {
      lastActivityRef.current = Date.now();
      setLastGateMessageAr(null);
      setStatus('UNLOCKED');
    } else {
      setLastGateMessageAr(outcome.messageAr);
    }
    return outcome;
  }, [overrides?.unlockImpl]);

  const pendingDeepLinkRef = useRef<string | null>(null);
  pendingDeepLinkRef.current = pendingDeepLink;

  const capturePendingDeepLink = useCallback((url: string) => {
    pendingDeepLinkRef.current = url;
    setPendingDeepLink(url);
  }, []);

  /** الرابط يُقرأ **مرة واحدة** ثم يُمحى، فلا يُعاد فتحه بعد قفل جديد. */
  const consumePendingDeepLink = useCallback((): string | null => {
    const taken = pendingDeepLinkRef.current;
    pendingDeepLinkRef.current = null;
    setPendingDeepLink(null);
    return taken;
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      lastGateMessageAr,
      obscured,
      deviceId,
      client,
      endpointTrusted: endpoint.ok,
      endpointReasonAr: endpoint.reasonAr,
      pendingDeepLink,
      unlock,
      lock,
      registerActivity,
      capturePendingDeepLink,
      consumePendingDeepLink,
      adoptSession,
      signOut,
      markRevoked,
    }),
    [
      status,
      lastGateMessageAr,
      obscured,
      deviceId,
      client,
      endpoint,
      pendingDeepLink,
      unlock,
      lock,
      registerActivity,
      capturePendingDeepLink,
      consumePendingDeepLink,
      adoptSession,
      signOut,
      markRevoked,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error('useSession يجب أن يُستدعى داخل SessionProvider.');
  }
  return value;
}
