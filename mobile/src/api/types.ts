/**
 * أشكال الاستجابات — مطابقة لعقد `/api/mobile/v1` في الخادم.
 *
 * Every field is nullable-tolerant on purpose. When the backend has not
 * computed something yet, it sends `null` and the UI says «غير متاح» — it never
 * invents a value. See `src/components/Value.tsx`.
 */

/** الغلاف المشترك لكل استجابة GET. */
export interface MobileEnvelope<TData> {
  route: string;
  server_time_utc: string;
  device_id: string;
  /** ثابت `false` — يرفض العميل أي استجابة بغير ذلك. */
  authorises_execution: false;
  data: TData;
}

// ---------------------------------------------------------------------------
// status
// ---------------------------------------------------------------------------

export type SystemPhase =
  | 'RUNNING'
  | 'PAUSED'
  | 'KILL_SWITCH'
  | 'STARTING'
  | 'DEGRADED'
  | 'UNKNOWN';

export interface KillSwitchView {
  active: boolean;
  trigger: string | null;
  reason_ar: string | null;
  at_utc: string | null;
}

export interface BrokerView {
  name: string;
  connected: boolean;
  is_demo: boolean;
  /** معرّف حساب مقنَّع — الخادم لا يرسل المعرّف كاملاً أبداً. */
  account_masked: string | null;
  execution_locked: boolean;
  /** سبب الانقطاع بالنصّ. «غير متصل» وحدها لا تقول شيئاً يُتصرَّف عليه. */
  note_ar: string | null;
}

export interface MarketView {
  is_open: boolean;
  reason_ar: string;
  next_open_utc: string | null;
  next_close_utc: string | null;
}

export interface CompletenessView {
  complete: boolean;
  /** 0..1 أو null إذا لم تُحسب. */
  ratio: number | null;
  missing: string[];
}

export interface StrategyStateView {
  key: string;
  title_ar: string;
  state: string;
  live_eligible: boolean;
}

export interface UpcomingEventView {
  title_ar: string;
  at_utc: string;
  impact_ar: string;
  blocks_trading: boolean;
}

export interface StatusData {
  system_state: SystemPhase;
  system_state_ar: string | null;
  locally_paused: boolean;
  kill_switch: KillSwitchView;
  broker: BrokerView;
  market: MarketView;
  data_completeness: CompletenessView;
  strategy_state: StrategyStateView | null;
  upcoming_event: UpcomingEventView | null;
  last_refresh_utc: string | null;
  /** رسالة الخادم عند التوقف — تُعرض كما هي بلا صياغة من التطبيق. */
  no_trade_reason_ar: string | null;
}

// ---------------------------------------------------------------------------
// intelligence/latest
// ---------------------------------------------------------------------------

export interface StageView {
  stage: string;
  name_ar: string;
  passed: boolean | null;
  mandatory: boolean;
  detail_ar: string | null;
}

export interface ScoreLine {
  category: string;
  category_ar: string;
  awarded: number;
  maximum: number;
  reason_ar: string;
  source_ar: string;
}

export interface ScoreView {
  total: number;
  max: number;
  has_mandatory_failure: boolean;
  mandatory_failures: Array<{ code: string; reason_ar: string }>;
  lines: ScoreLine[];
}

export interface ContradictionItem {
  kind: string;
  side_a_ar: string;
  side_b_ar: string;
  severity_ar: string;
  resolution_ar: string;
  blocks_trading: boolean;
}

export interface RegimeView {
  regime: string;
  name_ar: string;
  tradable: boolean;
  reason_ar: string;
}

export interface TimeframesView {
  primary_regime_trend: string;
  structural_trend: string;
  entry_trend: string;
  incomplete: string[];
}

export interface IntelligenceData {
  available: boolean;
  reason_ar: string | null;
  snapshot_id: string | null;
  decided_at_utc: string | null;
  regime: RegimeView | null;
  timeframes: TimeframesView | null;
  stages: StageView[];
  score: ScoreView | null;
  contradictions: {
    count: number;
    total_penalty: number;
    has_unresolved_material: boolean;
    items: ContradictionItem[];
  } | null;
  missing_providers: string[];
  missing_data: string[];
  explanation_ar: string | null;
}

// ---------------------------------------------------------------------------
// decision/latest
// ---------------------------------------------------------------------------

export type FinalDecision = 'NO_TRADE' | 'ELIGIBLE' | 'WAIT' | 'BLOCKED' | 'UNKNOWN';

export interface DecisionData {
  decision: FinalDecision;
  decision_ar: string | null;
  reason_code: string | null;
  explanation_ar: string | null;
  /** النتيجة الحتمية — عدد ونهاية سلّم. */
  score: { total: number; max: number } | null;
  snapshot_id: string | null;
  decided_at_utc: string | null;
  /** أسباب المنع بترتيب الخادم — لا يعيد التطبيق ترتيبها. */
  blocking_reasons_ar: string[];
  stages: StageView[];
  /** صريح: القرار وصفي، ولا يأذن بتنفيذ. */
  authorises_execution: false;
}

// ---------------------------------------------------------------------------
// risk
// ---------------------------------------------------------------------------

export interface RiskData {
  profile: string | null;
  profile_name_ar: string | null;
  currency: string;
  equity_used: string | null;
  risk_used_today: string | null;
  risk_remaining_today: string | null;
  risk_used_week: string | null;
  risk_remaining_week: string | null;
  max_risk_per_trade: string | null;
  max_daily_loss: string | null;
  max_weekly_loss: string | null;
  operational_drawdown_stop: string | null;
  absolute_loss_boundary: string | null;
  distance_to_kill_switch: string | null;
  open_positions: number | null;
  max_open_positions: number | null;
  entry_orders_today: number | null;
  max_entry_orders_per_day: number | null;
  consecutive_losses: number | null;
  two_loss_lock_active: boolean;
  /** الحدود لا تُعدَّل من الجهاز — الخادم يكرّرها كي تُعرض. */
  editable_from_device: false;

  /**
   * المحفظة — ثلاثة أرقام لا واحد، **والخلاف بينها معلومة لا خطأ**.
   *
   * عرضُ رصيد الوسيط وحده يُخفي أن الحدود قد تُحسب على رقمٍ آخر، وهو ما
   * بقي صامتاً حتى انكشف بالمصادفة: ١٥٠ مرجعاً و١٤٠ في الحساب.
   */
  portfolio: {
    /** الرقم الذي تُحسب منه كل الحدود. */
    baseline_equity: string | null;
    /** ما يقوله الوسيط الآن. `null` حين يتعذّر — لا صفر ولا قيمة قديمة. */
    broker_equity: string | null;
    /** المرجعي زائد ما تحقّق. */
    current_equity: string | null;
    diverged: boolean;
    note_ar: string | null;
  };
}

// ---------------------------------------------------------------------------
// profiles
// ---------------------------------------------------------------------------

export interface ProfileLimits {
  max_risk_per_trade: string;
  max_daily_loss: string;
  max_weekly_loss: string;
  operational_drawdown_stop: string;
  absolute_loss_boundary: string;
  max_open_positions: number;
  max_entry_orders_per_day: number;
  min_net_reward_risk: string;
  min_quality_score: number;
  allow_overnight: boolean;
  allow_weekend_hold: boolean;
}

export interface ProfileSummary {
  profile: string;
  name_ar: string;
  description_ar: string;
  risk_rank: number;
  limits: ProfileLimits;
}

export interface ProfilesData {
  selected_profile: string | null;
  selected_name_ar: string | null;
  effective_profile: string | null;
  effective_name_ar: string | null;
  risk_level_ar: string | null;
  pending_profile: string | null;
  pending_available_at_utc: string | null;
  cooling_remaining_seconds: number | null;
  change_blocked_reason_ar: string | null;
  available_profiles: ProfileSummary[];
  fingerprint: string | null;
  /** الترقية تحتاج الخادم وتبريداً — الجهاز لا يستطيعها. */
  upgrade_requires_server: true;
}

// ---------------------------------------------------------------------------
// positions/current
// ---------------------------------------------------------------------------

export interface PositionData {
  has_position: boolean;
  instrument_ar: string | null;
  instrument: string | null;
  direction_ar: string | null;
  opened_utc: string | null;
  entry_price: string | null;
  current_price: string | null;
  stop_price: string | null;
  take_profit_price: string | null;
  size_display: string | null;
  notional_display: string | null;
  unrealised_pnl: string | null;
  unrealised_pnl_sign: 'POSITIVE' | 'NEGATIVE' | 'FLAT' | null;
  risk_at_stop: string | null;
  /** الوقف والهدف **لدى الوسيط** — لا يعتمدان على التطبيق. */
  protection_held_by_broker: boolean;
  strategy_ar: string | null;
  notes_ar: string[];
}

// ---------------------------------------------------------------------------
// trades
// ---------------------------------------------------------------------------

export interface TradeRecord {
  id: string;
  instrument: string;
  instrument_ar: string | null;
  direction_ar: string;
  opened_utc: string;
  closed_utc: string | null;
  entry_price: string | null;
  exit_price: string | null;
  realised_pnl: string | null;
  realised_pnl_sign: 'POSITIVE' | 'NEGATIVE' | 'FLAT' | null;
  outcome_ar: string | null;
  strategy_ar: string | null;
  exit_reason_ar: string | null;
}

export interface TradesData {
  trades: TradeRecord[];
}

// ---------------------------------------------------------------------------
// performance
// ---------------------------------------------------------------------------

export interface CalibrationBucket {
  band_ar: string;
  predicted: number;
  observed: number | null;
  sample_size: number;
  /** الخادم يقول متى تكون العيّنة أصغر من أن تُقرأ. */
  sufficient: boolean;
}

export interface PerformanceData {
  sample_size: number;
  sufficient_sample: boolean;
  insufficient_sample_note_ar: string | null;
  wins: number | null;
  losses: number | null;
  win_rate: number | null;
  average_r: string | null;
  expectancy: string | null;
  max_drawdown: string | null;
  realised_pnl_total: string | null;
  calibration: CalibrationBucket[];
  period_start_utc: string | null;
  period_end_utc: string | null;
}

// ---------------------------------------------------------------------------
// providers/health
// ---------------------------------------------------------------------------

export interface ProviderView {
  kind: string;
  name: string;
  name_ar: string | null;
  configured: boolean;
  healthy: boolean | null;
  mandatory: boolean;
  last_success_utc: string | null;
  note_ar: string;
}

export interface ProvidersData {
  providers: ProviderView[];
  missing: string[];
  missing_mandatory: string[];
  live_eligible_by_providers: boolean;
}

// ---------------------------------------------------------------------------
// notifications
// ---------------------------------------------------------------------------

export type NotificationKind =
  | 'ELIGIBLE_SETUP_DETECTED'
  | 'NO_TRADE_EVENT_RISK'
  | 'BROKER_CONFIRMATION'
  | 'STOP_LOSS_EVENT'
  | 'TAKE_PROFIT_EVENT'
  | 'SPREAD_ANOMALY'
  | 'STALE_DATA'
  | 'PROVIDER_FAILURE'
  | 'BROKER_DISCONNECT'
  | 'DAILY_LIMIT_REACHED'
  | 'WEEKLY_LIMIT_REACHED'
  | 'TWO_LOSS_LOCK'
  | 'KILL_SWITCH_ACTIVATED'
  | 'DAILY_SUMMARY';

export interface NotificationRecord {
  type: NotificationKind;
  created_utc: string;
  /** التفصيل يُعرض **بعد المصادقة فقط**. لا يظهر على شاشة القفل. */
  in_app_detail_ar: string;
  deep_link: string | null;
  read: boolean;
}

export interface NotificationsData {
  notifications: NotificationRecord[];
}

// ---------------------------------------------------------------------------
// audit/recent
// ---------------------------------------------------------------------------

export interface AuditEntry {
  at_utc: string;
  action: string;
  device_id: string | null;
  detail_ar: string;
  success: boolean;
}

export interface AuditData {
  entries: AuditEntry[];
}

// ---------------------------------------------------------------------------
// الإجراءات الثلاثة المُقلِّلة للمخاطرة
// ---------------------------------------------------------------------------

export interface PauseResult {
  action: 'PAUSE_REQUESTED';
  accepted: boolean;
  at_utc: string;
  note_ar: string;
}

export interface KillSwitchResult {
  action: 'KILL_SWITCH_ACTIVATED';
  accepted: boolean;
  at_utc: string;
  note_ar: string;
}

export interface DeviceRevokeResult {
  action: 'DEVICE_REVOKED';
  accepted: boolean;
  device_id: string;
  at_utc: string;
}
