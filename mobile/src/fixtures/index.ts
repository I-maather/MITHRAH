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
  RiskData,
  StatusData,
  TradesData,
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
    next_open_utc: '2026-01-16T14:30:00+00:00',
    next_close_utc: null,
  },
  data_completeness: {
    complete: false,
    ratio: 0.5,
    missing: ['تقويم اقتصادي', 'أخبار', 'بيانات كلية'],
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
    },
  ],
};

const performance: PerformanceData = {
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

export const fixtures = {
  status,
  intelligence,
  decision,
  risk,
  profiles,
  position,
  trades,
  performance,
  providers,
  notifications,
  audit,
} as const;
