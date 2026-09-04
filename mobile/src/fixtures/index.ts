import { PREVIEW_DATA_ENABLED } from '@/api/config';
import type {
  AuditData,
  DecisionData,
  IntelligenceData,
  NotificationsData,
  PerformanceData,
  PositionData,
  ProfilesData,
  ProvidersData,
  ScanData,
  Candle,
  CandlesData,
  RiskData,
  StatusData,
  TradesData,
  SyncView,
  ManagementData,
} from '@/api/types';

/**
 * بيانات معاينة للتطوير — **ليست حالة النظام**.
 *
 * كل شاشة تعرض شيئاً من هنا تعرض فوقه شريط «معاينة / Preview» بنصّه الصريح.
 * `previewOr()` هي البوابة الوحيدة: خارج التطوير، أو مع إطفاء العلم، تعيد
 * `null` فتذهب الشاشة إلى الخادم. لا يوجد مسار يجعل هذه القيم تظهر بلا وسم.
 *
 * الأرقام هنا مُصطنعة عمداً وواضحة الاصطناع (قيم مستديرة، أداة واحدة، تواريخ
 * ثابتة) كي لا تُقرأ يوماً على أنها نتيجة حقيقية.
 */

/** الطابع الزمني المرجعي للمعاينة — ثابت كي لا تبدو البيانات «حيّة». */
const T0 = '2026-01-15T13:40:00+00:00';
const T_MINUS_1H = '2026-01-15T12:40:00+00:00';
const T_MINUS_1D = '2026-01-14T15:05:00+00:00';

/**
 * البوابة. تُستدعى من كل شاشة:
 *
 *     const preview = previewOr(fixtures.status);
 *     const { data } = useEndpoint((c) => c.getStatus(), { previewData: preview });
 */
export function previewOr<T>(value: T): T | null {
  return PREVIEW_DATA_ENABLED ? value : null;
}

/** true حين يجب أن تحمل الشاشة وسم المعاينة. */
export const isPreviewMode = (): boolean => PREVIEW_DATA_ENABLED;

const status: StatusData = {
  backend_commit: 'preview',
  system_state: 'PAUSED',
  system_state_ar: 'موقوف محلياً (معاينة)',
  locally_paused: true,
  kill_switch: { active: false, trigger: null, reason_ar: null, at_utc: null },
  broker: {
    name: 'وسيط المعاينة',
    connected: false,
    is_demo: true,
    account_masked: '••••00',
    execution_locked: true,
    note_ar: 'تعذّر الوصل عند الإقلاع — يُعاد كل أربع دقائق.',
  },
  market: {
    is_open: false,
    reason_ar: 'خارج جلسة التداول (معاينة).',
    scope_ar: 'ساعات الفوركس — ولكل أداةٍ حالتُها أدناه. (معاينة)',
    // الأوّل هو **حالة الغياب** عمداً: العقد يصف شكل العنصر من أوّله،
    // و«لم يُعلن» هي الحالة التي يجب أن تبقى مقبولةً في العقد — فلا يصير
    // حقلٌ إلزاميّاً لأن أوّل مثالٍ صادف أن يحمل قيمة.
    per_instrument: [
      {
        symbol: 'EURUSD',
        status: null,
        tradable: null,
        reason_ar: 'الوسيط لم يُعلن حالتها — لا تُملأ بحالة الفوركس. (معاينة)',
      },
      { symbol: 'GOLD', status: 'CLOSED', tradable: false, reason_ar: 'الوسيط يقول: CLOSED' },
    ],
    next_open_utc: '2026-01-16T14:30:00+00:00',
    next_close_utc: null,
  },
  data_completeness: {
    complete: false,
    ratio: 0.5,
    missing: ['تقويم اقتصادي', 'أخبار', 'بيانات كلية'],
    optional_missing: ['السياق الأساسي'],
  },
  strategy_state: {
    key: 'trend_pullback_v1',
    title_ar: 'ارتداد داخل اتجاه (معاينة)',
    state: 'SHADOW',
    live_eligible: false,
  },
  upcoming_event: {
    title_ar: 'قرار سعر فائدة (معاينة)',
    at_utc: '2026-01-16T19:00:00+00:00',
    impact_ar: 'أثر مرتفع — نافذة امتناع.',
    blocks_trading: true,
  },
  last_refresh_utc: T0,
  no_trade_reason_ar:
    'لا مزوّد بيانات مُعدّ، والاستراتيجية في وضع الظل. لا دخول قبل اكتمال الاثنين. (معاينة)',
};

const intelligence: IntelligenceData = {
  available: true,
  reason_ar: null,
  snapshot_id: 'PREVIEW-0001',
  decided_at_utc: T0,
  regime: {
    regime: 'RANGE',
    name_ar: 'نطاق عرضي',
    tradable: false,
    reason_ar: 'النطاق ضيق ولا حافة إحصائية معلومة فيه. (معاينة)',
  },
  timeframes: {
    primary_regime_trend: 'محايد',
    structural_trend: 'محايد',
    entry_trend: 'غير مكتمل',
    incomplete: ['إطار الدخول'],
  },
  stages: [
    { stage: 'PROVIDERS', name_ar: 'اكتمال المزوّدين', passed: false, mandatory: true, detail_ar: 'ثلاثة مزوّدين غير مُعدّين.' },
    { stage: 'REGIME', name_ar: 'تصنيف النظام', passed: true, mandatory: true, detail_ar: 'نطاق عرضي.' },
    { stage: 'CONTRADICTION', name_ar: 'فحص التناقض', passed: true, mandatory: true, detail_ar: 'لا تناقض مادي.' },
    { stage: 'STRATEGY', name_ar: 'أهلية الاستراتيجية', passed: false, mandatory: true, detail_ar: 'وضع الظل.' },
    { stage: 'SCORE', name_ar: 'النتيجة الحتمية', passed: false, mandatory: false, detail_ar: 'دون العتبة.' },
  ],
  score: {
    total: 38,
    max: 100,
    has_mandatory_failure: true,
    mandatory_failures: [
      { code: 'PROVIDERS_MISSING', reason_ar: 'مزوّدون إلزاميون غير مُعدّين. (معاينة)' },
      { code: 'STRATEGY_NOT_LIVE', reason_ar: 'الاستراتيجية لم تُجَز للتنفيذ. (معاينة)' },
    ],
    lines: [
      { category: 'REGIME', category_ar: 'النظام السائد', awarded: 10, maximum: 25, reason_ar: 'نطاق لا اتجاه.', source_ar: 'بيانات سعرية' },
      { category: 'STRUCTURE', category_ar: 'البنية', awarded: 12, maximum: 25, reason_ar: 'قمم وقيعان غير حاسمة.', source_ar: 'بيانات سعرية' },
      { category: 'FUNDAMENTAL', category_ar: 'الأساسيات', awarded: 0, maximum: 25, reason_ar: 'لا مزوّد كلي.', source_ar: 'غير متاح' },
      { category: 'EVENT', category_ar: 'الأحداث', awarded: 16, maximum: 25, reason_ar: 'حدث قادم ضمن النافذة.', source_ar: 'تقويم معاينة' },
    ],
  },
  contradictions: { count: 0, total_penalty: 0, has_unresolved_material: false, items: [] },
  missing_providers: ['تقويم اقتصادي', 'أخبار', 'بيانات كلية'],
  missing_data: ['اتجاه إطار الدخول'],
  explanation_ar:
    'القراءة غير كافية للدخول: مزوّدان إلزاميان ناقصان، والنظام السائد نطاق لا اتجاه. (معاينة)',
};

const decision: DecisionData = {
  decision: 'NO_TRADE',
  decision_ar: 'امتناع',
  reason_code: 'PROVIDERS_MISSING',
  explanation_ar:
    'الامتناع قرار مكتمل لا نقص: شرط إلزامي لم يتحقق، فلا دخول. (معاينة)',
  score: { total: 38, max: 100 },
  snapshot_id: 'PREVIEW-0001',
  decided_at_utc: T0,
  blocking_reasons_ar: [
    'مزوّدون إلزاميون غير مُعدّين.',
    'الاستراتيجية في وضع الظل ولم تُجَز.',
    'حدث عالي الأثر ضمن نافذة الامتناع.',
  ],
  stages: intelligence.stages,
  authorises_execution: false,
};

const risk: RiskData = {
  profile: 'CONSERVATIVE',
  profile_name_ar: 'متحفّظ (معاينة)',
  profile_binding_ar:
    'الأرقام هنا هي التي ينفّذها المحرّك. حدود ملفك «متحفّظ» أشدّ ولا تُنفَّذ بعد — سريانها قرارٌ معلّق. (معاينة)',
  currency: 'USD',
  equity_used: '1,000.00',
  risk_used_today: '0.00',
  risk_remaining_today: '10.00',
  risk_used_week: '0.00',
  risk_remaining_week: '25.00',
  max_risk_per_trade: '5.00',
  max_daily_loss: '10.00',
  max_weekly_loss: '25.00',
  operational_drawdown_stop: '80.00',
  absolute_loss_boundary: '150.00',
  distance_to_kill_switch: '150.00',
  open_positions: 0,
  max_open_positions: 1,
  entry_orders_today: 0,
  max_entry_orders_per_day: 2,
  consecutive_losses: 0,
  two_loss_lock_active: false,
  editable_from_device: false,
  portfolio: {
    baseline_equity: '140.00',
    broker_equity: '140.00',
    current_equity: '140.00',
    diverged: false,
    note_ar: 'المرجع 140.00 والرصيد 140.00 — ضمن المدى.',
  },
};

const profiles: ProfilesData = {
  selected_profile: 'CONSERVATIVE',
  selected_name_ar: 'متحفّظ (معاينة)',
  effective_profile: 'CONSERVATIVE',
  effective_name_ar: 'متحفّظ (معاينة)',
  risk_level_ar: 'منخفض',
  pending_profile: null,
  pending_available_at_utc: null,
  cooling_remaining_seconds: null,
  change_blocked_reason_ar: 'التغيير من الخادم فقط، وبتبريد ٢٤ ساعة. (معاينة)',
  available_profiles: [
    {
      profile: 'CONSERVATIVE',
      name_ar: 'متحفّظ',
      description_ar: 'أصغر مخاطرة لكل صفقة، وأقل عدد دخول في اليوم. (معاينة)',
      risk_rank: 1,
      limits: {
        max_risk_per_trade: '5.00',
        max_daily_loss: '10.00',
        max_weekly_loss: '25.00',
        operational_drawdown_stop: '80.00',
        absolute_loss_boundary: '150.00',
        max_open_positions: 1,
        max_entry_orders_per_day: 2,
        min_net_reward_risk: '2.00',
        min_quality_score: 70,
        allow_overnight: false,
        allow_weekend_hold: false,
      },
    },
    {
      profile: 'BALANCED',
      name_ar: 'متوازن',
      description_ar: 'مخاطرة أعلى قليلاً بشروط جودة أشد. (معاينة)',
      risk_rank: 2,
      limits: {
        max_risk_per_trade: '10.00',
        max_daily_loss: '20.00',
        max_weekly_loss: '40.00',
        operational_drawdown_stop: '80.00',
        absolute_loss_boundary: '150.00',
        max_open_positions: 1,
        max_entry_orders_per_day: 3,
        min_net_reward_risk: '1.80',
        min_quality_score: 65,
        allow_overnight: false,
        allow_weekend_hold: false,
      },
    },
  ],
  fingerprint: 'preview-fingerprint',
  upgrade_requires_server: true,
};

const position: PositionData = {
    sync: {
      ok: true,
      reason_code: 'OK',
      error_ar: '',
      last_sync_utc: '2026-09-04T17:24:41Z',
      age_seconds: 3,
      stale: false,
    },
    open_count: 1,
    positions: [
      {
        id: 'PREVIEW-P1',
        instrument: 'EURUSD',
        instrument_ar: 'يورو/دولار',
        direction_ar: 'شراء',
        opened_utc: '2026-09-04T16:01:48Z',
        entry_price: '1.16194',
        current_price: '1.16210',
        stop_price: '1.15935',
        take_profit_price: '1.16712',
        size_display: '300',
        notional_display: '348.58',
        unrealised_pnl: '0.05',
        unrealised_pnl_sign: 'POSITIVE',
        risk_at_stop: '0.78',
        protection_held_by_broker: true,
        strategy_ar: 'معاينة',
        kind: 'STRATEGY',
      },
    ],
    unprotected_count: 0,
    total_unrealised: null,
  has_position: false,
  instrument_ar: null,
  instrument: null,
  direction_ar: null,
  opened_utc: null,
  entry_price: null,
  current_price: null,
  stop_price: null,
  take_profit_price: null,
  size_display: null,
  notional_display: null,
  unrealised_pnl: null,
  unrealised_pnl_sign: null,
  risk_at_stop: null,
  protection_held_by_broker: true,
  strategy_ar: null,
  notes_ar: ['لا مركز مفتوح في بيانات المعاينة.'],
};

const trades: TradesData = {
  sync: {
    ok: true,
    reason_code: 'OK',
    error_ar: '',
    last_sync_utc: '2026-09-04T17:24:41Z',
    age_seconds: 3,
    stale: false,
  },
  unavailable: false,
  realised_pnl_total: '-0.35',
  trades: [
    {
      id: 'PREVIEW-T1',
      instrument: 'EURUSD',
      instrument_ar: 'يورو/دولار',
      direction_ar: 'شراء',
      opened_utc: T_MINUS_1D,
      closed_utc: T_MINUS_1H,
      entry_price: '1.08500',
      exit_price: '1.08720',
      realised_pnl: '+4.40',
      realised_pnl_sign: 'POSITIVE',
      outcome_ar: 'هدف',
      strategy_ar: 'ارتداد داخل اتجاه',
      exit_reason_ar: 'بلوغ الهدف لدى الوسيط.',
      kind: 'STRATEGY',
    },
    {
      id: 'PREVIEW-T2',
      instrument: 'EURUSD',
      instrument_ar: 'يورو/دولار',
      direction_ar: 'شراء',
      opened_utc: '2026-01-12T10:00:00+00:00',
      closed_utc: '2026-01-12T11:30:00+00:00',
      entry_price: '1.08900',
      exit_price: '1.08650',
      realised_pnl: '-5.00',
      realised_pnl_sign: 'NEGATIVE',
      outcome_ar: 'وقف',
      strategy_ar: 'ارتداد داخل اتجاه',
      exit_reason_ar: 'ضرب الوقف المحفوظ لدى الوسيط.',
      kind: 'STRATEGY',
    },
  ],
};

const performance: PerformanceData = {
    sync: {
      ok: true,
      reason_code: 'OK',
      error_ar: '',
      last_sync_utc: '2026-09-04T17:24:41Z',
      age_seconds: 3,
      stale: false,
    },
  sample_size: 2,
  sufficient_sample: false,
  insufficient_sample_note_ar:
    'صفقتان لا تكفيان لاستنتاج. لا نسبة ربح تُقرأ من عيّنة بهذا الصغر. (معاينة)',
  wins: 1,
  losses: 1,
  win_rate: null,
  average_r: null,
  expectancy: null,
  max_drawdown: '5.00',
  realised_pnl_total: '-0.60',
  calibration: [
    { band_ar: '٦٠–٦٩٪', predicted: 0.65, observed: null, sample_size: 1, sufficient: false },
    { band_ar: '٧٠–٧٩٪', predicted: 0.75, observed: null, sample_size: 1, sufficient: false },
  ],
  period_start_utc: '2026-01-12T00:00:00+00:00',
  period_end_utc: T0,
};

const scan: ScanData = {
  instruments: [
    {
      symbol: 'EURUSD', decision: 'NO_TRADE', reason_code: 'NO_SETUP',
      reason_ar: 'لا فرصة مطابقة.',
      stage: 'strategy', needs_a_hand: false,
      strategies: [
        {
          key: 'TREND_PULLBACK@2.0.0',
          summary_ar: 'الظرف: ADX14 = 18.3 دون 25 — سوقٌ متذبذب لا متّجه.',
          checks: [
            { name_ar: 'المؤشرات', passed: true, detail_ar: 'EMA10 = 1.10420 · EMA30 = 1.10310 · ATR14 = 0.00810' },
            { name_ar: 'الظرف', passed: false, detail_ar: 'ADX14 = 18.3 دون 25 — سوقٌ متذبذب لا متّجه.' },
          ],
        },
      ],
    },
    {
      symbol: 'GBPUSD', decision: 'NO_TRADE', reason_code: 'NO_APPROVED_STRATEGY',
      reason_ar: 'لا استراتيجية معتمدة — الثلاث ما زالت قيد البحث.',
      stage: 'strategy', needs_a_hand: false,
    },
    {
      symbol: 'GOLD', decision: 'NO_TRADE', reason_code: 'INSUFFICIENT_BARS',
      reason_ar: 'GOLD: وصلت 41 شمعة فقط — لا تكفي لتقييم.',
      stage: 'runtime', needs_a_hand: true,
    },
    {
      symbol: 'USDJPY', decision: 'NO_TRADE', reason_code: 'NO_APPROVED_STRATEGY',
      reason_ar: 'لا استراتيجية معتمدة — الثلاث ما زالت قيد البحث.',
      stage: 'strategy', needs_a_hand: false,
    },
  ],
  scanned: 4,
  faults: 1,
  summary_ar: 'نُظِر في 4 أداة، و1 منها لم تُقرأ بياناتها.',
};

const providers: ProvidersData = {
  providers: [
    { kind: 'MARKET_DATA', name: 'market-data', name_ar: 'بيانات السوق', configured: false, healthy: null, mandatory: true, last_success_utc: null, note_ar: 'غير مُعدّ. (معاينة)' },
    { kind: 'CALENDAR', name: 'calendar', name_ar: 'التقويم الاقتصادي', configured: false, healthy: null, mandatory: true, last_success_utc: null, note_ar: 'غير مُعدّ. (معاينة)' },
    { kind: 'NEWS', name: 'news', name_ar: 'الأخبار', configured: false, healthy: null, mandatory: false, last_success_utc: null, note_ar: 'غير مُعدّ. (معاينة)' },
    { kind: 'MACRO', name: 'macro', name_ar: 'البيانات الكلية', configured: false, healthy: null, mandatory: true, last_success_utc: null, note_ar: 'غير مُعدّ. (معاينة)' },
  ],
  missing: ['بيانات السوق', 'التقويم الاقتصادي', 'الأخبار', 'البيانات الكلية'],
  missing_mandatory: ['بيانات السوق', 'التقويم الاقتصادي', 'البيانات الكلية'],
  live_eligible_by_providers: false,
};

const notifications: NotificationsData = {
  notifications: [
    {
      type: 'NO_TRADE_EVENT_RISK',
      created_utc: T0,
      in_app_detail_ar: 'امتناع بسبب حدث عالي الأثر ضمن النافذة. (معاينة)',
      deep_link: 'maather://decision',
      read: false,
    },
    {
      type: 'PROVIDER_FAILURE',
      created_utc: T_MINUS_1H,
      in_app_detail_ar: 'مزوّد التقويم غير مُعدّ. (معاينة)',
      deep_link: 'maather://providers',
      read: true,
    },
    {
      type: 'DAILY_SUMMARY',
      created_utc: T_MINUS_1D,
      in_app_detail_ar: 'يوم بلا دخول. لا خسارة ولا ربح. (معاينة)',
      deep_link: null,
      read: true,
    },
  ],
};

const audit: AuditData = {
  entries: [
    { at_utc: T0, action: 'MOBILE_SESSION_OPENED', device_id: 'preview-device', detail_ar: 'فُتحت جلسة معاينة.', success: true },
    { at_utc: T_MINUS_1H, action: 'DEVICE_ENROLLED', device_id: 'preview-device', detail_ar: 'سُجِّل جهاز المعاينة.', success: true },
    { at_utc: T_MINUS_1D, action: 'ENROLLMENT_REJECTED', device_id: null, detail_ar: 'تحدّي منتهٍ — رُفض.', success: false },
  ],
};

/**
 * شموع المعاينة — **مولَّدة بدالّة ثابتة، لا مسجَّلة من سوق**.
 *
 * ولا تُكتب أربعون شمعة يدوياً: قائمةٌ طويلة من الأرقام المكتوبة تُقرأ يوماً
 * على أنها تسجيلٌ حقيقي. والدالّة هنا موجةٌ حسابية صريحة لا تشبه سعراً —
 * تكفي لاختبار الرسم والمقياس، ولا تدّعي أنها EURUSD في يومٍ ما.
 *
 * وتُقرَّب إلى خمس خانات لأن الخادم يرسل نصّاً بكامل دقّة `Decimal`؛ فلو
 * أعطتها المعاينة خانتين لاختُبر الرسم على دقّةٍ غير التي يعمل عليها.
 */
/**
 * شموع المعاينة. و**الخطوة الزمنية وسيطٌ للإطار**: كانت ساعةً واحدة لكل
 * الأطر، فيقرأ محورُ الوقت «09:00 10:00» على إطارٍ اسمه «يومي» — ووسمٌ
 * يناقض عنوانه يعلّم قراءةً خاطئة حتى في معاينة.
 */
const previewCandles = (stepMs: number): Candle[] => {
  const rows: Candle[] = [];
  const base = 1.1;
  for (let i = 0; i < 40; i += 1) {
    const drift = Math.sin(i / 6) * 0.004 + i * 0.00012;
    const open = base + drift;
    const close = base + Math.sin((i + 1) / 6) * 0.004 + (i + 1) * 0.00012;
    const high = Math.max(open, close) + 0.0007;
    const low = Math.min(open, close) - 0.0007;
    const at = new Date(Date.parse('2026-01-14T00:00:00Z') + i * stepMs);
    rows.push({
      t: at.toISOString().replace('.000Z', '+00:00'),
      o: open.toFixed(5),
      h: high.toFixed(5),
      l: low.toFixed(5),
      c: close.toFixed(5),
    });
  }
  return rows;
};

const candles: CandlesData = {
  instruments: {
    EURUSD: { DAY: previewCandles(86_400_000), HOUR_4: previewCandles(14_400_000) },
  },
  symbols: ['EURUSD'],
  resolutions: ['DAY', 'HOUR_4'],
  decision_resolution: 'DAY',
  // لا مركز في المعاينة ⇒ أربعتها `null`. وصفرٌ هنا كان يرسم خطّاً عند الصفر
  // فيسحب المقياس ويجعل الشموع خيطاً.
  levels: { symbol: null, entry: null, stop: null, target: null },
  note_ar: 'شموع معاينة مولَّدة — ليست سوقاً. (معاينة)',
};

/**
 * حالةُ المزامنة وحدها — تُطلَب بلا جلب كل شيء.
 *
 * أُضيفت يوم ظهر أن الشاشة تعرض «لا مركز مفتوح» وعلى الحساب خمسة: تحتاج
 * الشاشة أن تسأل «هل قرأتَ؟» قبل «ماذا رأيت؟».
 */
const sync: SyncView = {
  ok: true,
  reason_code: 'OK',
  error_ar: '',
  last_sync_utc: '2026-09-04T17:24:41Z',
  age_seconds: 3,
  stale: false,
};

const management: ManagementData = {
  sync,
  available: true,
  reason_ar: '',
  plan_at_utc: '2026-09-04T17:24:41+00:00',
  action_count: 1,
  actions: [
    {
      deal_id: 'PREVIEW-1',
      symbol: 'EURUSD',
      kind: 'MOVE_STOP',
      kind_ar: 'نقلُ الوقف',
      reason_ar: 'ربحٌ بلغ 1.0R — الوقف إلى نقطة الدخول (معاينة).',
      policy_version: 'preview-1',
      strategy: 'PREVIEW',
      strategy_version: 'v0',
      old_value: '1.15900',
      new_value: '1.16000',
      at_utc: '2026-09-04T17:24:41+00:00',
    },
  ],
  skipped: [
    {
      deal_id: 'PREVIEW-2',
      symbol: 'GOLD',
      code: 'FIXED_ONLY',
      code_ar: 'سياسةُ خروجٍ ثابت',
      reason_ar: 'سياسة fixed-1: خروجٌ ثابتٌ بلا تحريك.',
    },
  ],
  declared_policies: [
    {
      strategy: 'PREVIEW',
      strategy_version: 'v0',
      policy_version: 'preview-1',
      capabilities: ['BREAK_EVEN', 'FIXED_EXIT'],
      fixed_only: false,
    },
  ],
  dynamic_enabled: true,
  notes_ar: ['بيانات معاينة — ليست حالة النظام.'],
};

export const fixtures = {
  status,
  intelligence,
  decision,
  risk,
  profiles,
  position,
  sync,
  management,
  trades,
  performance,
  providers,
  scan,
  candles,
  notifications,
  audit,
} as const;
