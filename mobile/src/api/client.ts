import { API_BASE_URL, API_PREFIX, SESSION_REFRESH_PATH, verifyBaseUrl } from './config';
import { READ_ROUTES, RISK_REDUCING_ROUTES, type ReadRoute, type RiskReducingRoute } from './routes';
import type {
  AuditData,
  DecisionData,
  DeviceRevokeResult,
  IntelligenceData,
  KillSwitchResult,
  MobileEnvelope,
  NotificationsData,
  PauseResult,
  PerformanceData,
  PositionData,
  ProfilesData,
  ProvidersData,
  RiskData,
  StatusData,
  TradesData,
} from './types';

/**
 * عميل الشبكة الوحيد في التطبيق.
 *
 * قواعده الأربع:
 *   1. لا يصل إلى أي وسيط. الخادم وحده يفعل. (No broker host, ever.)
 *   2. لا يبلغ مساراً خارج القائمتين المُعلَنتين.
 *   3. يفشل مغلقاً عند الشك في هوية الخادم أو في شكل الاستجابة.
 *   4. لا يسجّل رمزاً ولا جسم استجابة. لا في التطوير ولا في الإنتاج.
 */

export type FailureKind =
  | 'UNAUTHORISED'
  | 'OFFLINE'
  | 'UNTRUSTED_ENDPOINT'
  | 'MALFORMED'
  | 'SERVER'
  | 'FORBIDDEN';

export class ApiError extends Error {
  readonly kind: FailureKind;
  readonly status: number | null;
  /** رسالة عربية صالحة للعرض. لا تحتوي رمزاً ولا مساراً خاصاً. */
  readonly messageAr: string;

  constructor(kind: FailureKind, messageAr: string, status: number | null = null) {
    super(`${kind}: ${messageAr}`);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.messageAr = messageAr;
  }
}

export interface TokenSource {
  /** يعيد رمز الوصول الحالي أو null. */
  getAccessToken: () => Promise<string | null>;
  /** يحاول التجديد مرة واحدة ويعيد رمزاً جديداً أو null. */
  refresh: () => Promise<string | null>;
  /** يُستدعى عند 401 نهائي — الجلسة انتهت ويجب القفل. */
  onSessionLost: () => Promise<void>;
}

export interface ClientOptions {
  baseUrl?: string;
  tokens: TokenSource;
  /** حقن fetch للاختبارات. */
  fetchImpl?: typeof fetch;
  /** مهلة الطلب بالمللي ثانية. */
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 12_000;

const isEnvelope = (value: unknown): value is MobileEnvelope<unknown> => {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.route === 'string' &&
    typeof candidate.server_time_utc === 'string' &&
    typeof candidate.device_id === 'string' &&
    'authorises_execution' in candidate &&
    'data' in candidate
  );
};

export class MobileApiClient {
  private readonly baseUrl: string;
  private readonly tokens: TokenSource;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private refreshing: Promise<string | null> | null = null;

  constructor(options: ClientOptions) {
    this.baseUrl = (options.baseUrl ?? API_BASE_URL).replace(/\/+$/, '');
    this.tokens = options.tokens;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  /** يُستعمل في شاشة «النظام» لعرض حالة الثقة بالخادم. */
  endpointVerdict(): { ok: boolean; reasonAr: string; baseUrl: string } {
    const verdict = verifyBaseUrl(this.baseUrl);
    return { ...verdict, baseUrl: this.baseUrl };
  }

  // -- القراءة --------------------------------------------------------------

  getStatus(): Promise<MobileEnvelope<StatusData>> {
    return this.read<StatusData>('status');
  }

  getIntelligence(): Promise<MobileEnvelope<IntelligenceData>> {
    return this.read<IntelligenceData>('intelligence/latest');
  }

  getDecision(): Promise<MobileEnvelope<DecisionData>> {
    return this.read<DecisionData>('decision/latest');
  }

  getRisk(): Promise<MobileEnvelope<RiskData>> {
    return this.read<RiskData>('risk');
  }

  getProfiles(): Promise<MobileEnvelope<ProfilesData>> {
    return this.read<ProfilesData>('profiles');
  }

  getCurrentPosition(): Promise<MobileEnvelope<PositionData>> {
    return this.read<PositionData>('positions/current');
  }

  getTrades(): Promise<MobileEnvelope<TradesData>> {
    return this.read<TradesData>('trades');
  }

  getPerformance(): Promise<MobileEnvelope<PerformanceData>> {
    return this.read<PerformanceData>('performance');
  }

  getProviderHealth(): Promise<MobileEnvelope<ProvidersData>> {
    return this.read<ProvidersData>('providers/health');
  }

  getNotifications(): Promise<MobileEnvelope<NotificationsData>> {
    return this.read<NotificationsData>('notifications');
  }

  getAudit(): Promise<MobileEnvelope<AuditData>> {
    return this.read<AuditData>('audit/recent');
  }

  // -- الإجراءات الثلاثة المُقلِّلة للمخاطرة ---------------------------------

  /** طلب إيقاف مؤقت. يقلّل المخاطرة ولا يفتح شيئاً. */
  requestPause(): Promise<MobileEnvelope<PauseResult>> {
    return this.mutate<PauseResult>('pause/request', {});
  }

  /**
   * تفعيل قاطع الطوارئ.
   * **لا إلغاء من الجهاز** — الإلغاء يزيد المخاطرة ويحتاج الخادم.
   */
  activateKillSwitch(): Promise<MobileEnvelope<KillSwitchResult>> {
    return this.mutate<KillSwitchResult>('killswitch/activate', {});
  }

  /** إلغاء جهاز — يقلّل سطح الهجوم. */
  revokeDevice(deviceId?: string, reasonAr?: string): Promise<MobileEnvelope<DeviceRevokeResult>> {
    const payload: Record<string, string> = {};
    if (deviceId !== undefined) {
      payload.device_id = deviceId;
    }
    if (reasonAr !== undefined) {
      payload.reason = reasonAr;
    }
    return this.mutate<DeviceRevokeResult>('device/revoke', payload);
  }

  // -- الداخل ---------------------------------------------------------------

  private read<T>(route: ReadRoute): Promise<MobileEnvelope<T>> {
    if (!READ_ROUTES.includes(route)) {
      throw new ApiError('FORBIDDEN', 'مسار قراءة غير مُعلَن — رُفض في العميل.');
    }
    return this.request<T>('GET', route, undefined);
  }

  private mutate<T>(
    route: RiskReducingRoute,
    payload: Record<string, unknown>,
  ): Promise<MobileEnvelope<T>> {
    if (!RISK_REDUCING_ROUTES.includes(route)) {
      throw new ApiError(
        'FORBIDDEN',
        'لا يملك التطبيق أي إجراء عدا ثلاثة تقلّل المخاطرة — رُفض في العميل.',
      );
    }
    return this.request<T>('POST', route, payload);
  }

  private async request<T>(
    method: 'GET' | 'POST',
    route: string,
    payload: Record<string, unknown> | undefined,
    isRetry = false,
  ): Promise<MobileEnvelope<T>> {
    const verdict = verifyBaseUrl(this.baseUrl);
    if (!verdict.ok) {
      // يفشل مغلقاً: لا يُرسَل رمز إلى خادم مجهول الهوية.
      throw new ApiError('UNTRUSTED_ENDPOINT', verdict.reasonAr);
    }

    const token = await this.tokens.getAccessToken();
    if (token === null) {
      throw new ApiError('UNAUTHORISED', 'لا جلسة صالحة. يلزم فتح التطبيق من جديد.');
    }

    const controller = new AbortController();
    const timer = setTimeout(() => {
      controller.abort();
    }, this.timeoutMs);

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${API_PREFIX}/${route}`, {
        method,
        headers: {
          authorization: `Bearer ${token}`,
          accept: 'application/json',
          ...(method === 'POST' ? { 'content-type': 'application/json' } : {}),
        },
        body: method === 'POST' ? JSON.stringify(payload ?? {}) : undefined,
        signal: controller.signal,
      });
    } catch {
      // لا نطبع الخطأ: قد يحمل العنوان أو ترويسة.
      throw new ApiError('OFFLINE', 'تعذّر الوصول إلى الخادم. البيانات المعروضة قديمة.');
    } finally {
      clearTimeout(timer);
    }

    if (response.status === 401) {
      if (!isRetry) {
        const fresh = await this.refreshOnce();
        if (fresh !== null) {
          return this.request<T>(method, route, payload, true);
        }
      }
      await this.tokens.onSessionLost();
      throw new ApiError('UNAUTHORISED', 'انتهت الجلسة أو أُلغي الجهاز. يلزم التحقق مجدداً.', 401);
    }

    if (response.status === 403) {
      throw new ApiError(
        'FORBIDDEN',
        'رفض الخادم الطلب. لا يملك هذا التطبيق أي صلاحية تنفيذ.',
        403,
      );
    }

    if (!response.ok) {
      throw new ApiError('SERVER', `تعذّرت الاستجابة من الخادم (${response.status}).`, response.status);
    }

    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new ApiError('MALFORMED', 'استجابة غير مفهومة من الخادم. أُهملت.');
    }

    if (!isEnvelope(body)) {
      throw new ApiError('MALFORMED', 'استجابة لا تطابق عقد الجوال. أُهملت.');
    }

    // الحارس الأخير: أي استجابة تدّعي الإذن بالتنفيذ تُرفض ولا تُعرض.
    if (body.authorises_execution !== false) {
      throw new ApiError(
        'MALFORMED',
        'استجابة تدّعي الإذن بالتنفيذ — رُفضت. هذا التطبيق لا ينفّذ شيئاً.',
      );
    }

    return body as MobileEnvelope<T>;
  }

  /** تجديد واحد متزامن مهما تعدّدت الطلبات المتوازية. */
  private refreshOnce(): Promise<string | null> {
    if (this.refreshing === null) {
      this.refreshing = this.tokens
        .refresh()
        .catch(() => null)
        .finally(() => {
          this.refreshing = null;
        });
    }
    return this.refreshing;
  }
}

export { SESSION_REFRESH_PATH };
