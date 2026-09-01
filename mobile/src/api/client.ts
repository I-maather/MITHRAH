import { API_BASE_URL, API_PREFIX, SESSION_REFRESH_PATH, verifyBaseUrl } from './config';
import {
  LIVE_ENVIRONMENT_PHRASE,
  READ_ROUTES,
  RESUME_PHRASE,
  RISK_INCREASING_ROUTES,
  RISK_REDUCING_ROUTES,
  type MutatingRoute,
  type ReadRoute,
} from './routes';
import type {
  AuditData,
  DecisionData,
  DeviceRevokeResult,
  IntelligenceData,
  KillSwitchResult,
  MobileEnvelope,
  NotificationsData,
  EnvironmentSwitchResult,
  PauseResult,
  ResumeResult,
  ScanData,
  CandlesData,
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

/**
 * نتيجة محاولة التجديد — **ثلاث حالات لا اثنتان**.
 *
 * ## العطل الذي فرض هذا التمييز
 *
 * كان `refresh` يعيد `null` لكل إخفاق: رفضٌ من الخادم، وانقطاعُ شبكة،
 * وخطأُ 502 لحظةَ إعادة تشغيل الخدمة — كلّها سواء. والعميل يقرأ `null`
 * «الجهاز أُلغي» فيمسح سلسلة المفاتيح.
 *
 * والنتيجة: **كل نشرٍ يُعيد التطبيق إلى مسح رمز الاقتران.** النشر يعيد
 * تشغيل الخدمة، فيصادف تجديدٌ جارٍ خادماً لا يردّ، فتُمحى الجلسة — وهي
 * سليمة تماماً، والخادم لم يقل عنها شيئاً.
 *
 * فالمحو الآن لا يقع إلا حين **يقول الخادم صراحةً** إن هذا الجهاز لم يعد
 * معروفاً. وما دون ذلك: نبقى مقفلين، ويُفتح بالوجه.
 */
export type RefreshOutcome =
  /** رمزٌ جديد. */
  | { status: 'renewed'; accessToken: string }
  /** الخادم **رفض** الرمز: أُلغي الجهاز أو انتهى التجديد. تُمحى الجلسة. */
  | { status: 'rejected' }
  /** لم يُحسم: شبكة، أو مهلة، أو خادم يُعيد التشغيل. **لا تُمحى الجلسة.** */
  | { status: 'unavailable' };

export interface TokenSource {
  /** يعيد رمز الوصول الحالي أو null. */
  getAccessToken: () => Promise<string | null>;
  /** يحاول التجديد مرة واحدة. انظري `RefreshOutcome`. */
  refresh: () => Promise<RefreshOutcome>;
  /** يُستدعى عند رفضٍ صريح من الخادم — الجلسة انتهت ويجب الاقتران مجدداً. */
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
  private refreshing: Promise<RefreshOutcome> | null = null;

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

  /** ماذا رأى النظام في السوق كلّه هذه الدورة. */
  getScan(): Promise<MobileEnvelope<ScanData>> {
    return this.read<ScanData>('scan/latest');
  }

  getAudit(): Promise<MobileEnvelope<AuditData>> {
    return this.read<AuditData>('audit/recent');
  }

  /**
   * الشموع كما رآها النظام حين قرّر.
   *
   * لا نداءَ وسيطٍ خلفها: الخادم يحفظها في دورة المسح ويقرأها من ذاكرته.
   * فتصفّح الرسم لا يستهلك حدّ الوسيط ولا يزاحم القرار على نداءاته.
   */
  getCandles(): Promise<MobileEnvelope<CandlesData>> {
    return this.read<CandlesData>('market/candles');
  }

  // -- الإجراءات: ثلاثةٌ تقلّل المخاطرة وواحدٌ يستأنف --------------------

  /** طلب إيقاف مؤقت. يقلّل المخاطرة ولا يفتح شيئاً. */
  requestPause(): Promise<MobileEnvelope<PauseResult>> {
    return this.mutate<PauseResult>('pause/request', {});
  }

  /**
   * استئناف التداول — **يرفع الإيقاف المحلي وحده**.
   *
   * يحتاج العبارة كاملةً: الخادم يرفض أي شيء سواها. وزرٌّ يُضغط بالخطأ في
   * الجيب لا يكتب جملة.
   *
   * ويُرفَض ما دام قاطع الطوارئ مفعّلاً — والرفض يأتي من الخادم بنصّه،
   * فلا يُقلَّد هنا ولا يُخمَّن.
   */
  resumeTrading(): Promise<MobileEnvelope<ResumeResult>> {
    return this.mutate<ResumeResult>('pause/resume', { confirm: RESUME_PHRASE });
  }

  /**
   * تبديل الحساب المقروء منه — **ولا يفتح تداولاً**.
   *
   * `LIVE_TRADING` وقفل التنفيذ ورفض `is_live` ثلاثة أقفال في الخادم لا
   * يمسّها هذا النداء. وأقصى ما يفعله جهازٌ مسروق أن يرى رصيداً.
   *
   * والعبارة تُرسَل مع الاتجاه الخطر وحده؛ الخادم يفرضها ولا يُكتفى بحارس
   * الواجهة — حارسٌ في الواجهة وحدها يمرّ أي نداءٍ من حوله.
   */
  switchEnvironment(target: 'DEMO' | 'LIVE'): Promise<MobileEnvelope<EnvironmentSwitchResult>> {
    const payload: Record<string, unknown> = { target };
    if (target === 'LIVE') {
      payload.confirm = LIVE_ENVIRONMENT_PHRASE;
    }
    return this.mutate<EnvironmentSwitchResult>('broker/environment', payload);
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
    route: MutatingRoute,
    payload: Record<string, unknown>,
  ): Promise<MobileEnvelope<T>> {
    const reducing = (RISK_REDUCING_ROUTES as readonly string[]).includes(route);
    const increasing = (RISK_INCREASING_ROUTES as readonly string[]).includes(route);
    if (!reducing && !increasing) {
      throw new ApiError(
        'FORBIDDEN',
        'لا يملك التطبيق أي إجراء عدا ثلاثة تقلّل المخاطرة وواحدٍ يستأنف — رُفض في العميل.',
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
        const outcome = await this.refreshOnce();
        if (outcome.status === 'renewed') {
          return this.request<T>(method, route, payload, true);
        }
        if (outcome.status === 'unavailable') {
          // لم يقل الخادم شيئاً عن هذا الجهاز — لا تُمحى جلسة على ظنّ.
          throw new ApiError(
            'OFFLINE',
            'تعذّر تجديد الجلسة الآن. جلستك محفوظة — أعيدي المحاولة.',
          );
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
  private refreshOnce(): Promise<RefreshOutcome> {
    if (this.refreshing === null) {
      this.refreshing = this.tokens
        .refresh()
        // استثناءٌ غير متوقَّع ليس رفضاً من الخادم — لا يُمحى عليه شيء.
        .catch((): RefreshOutcome => ({ status: 'unavailable' }))
        .finally(() => {
          this.refreshing = null;
        });
    }
    return this.refreshing;
  }
}

export { SESSION_REFRESH_PATH };
