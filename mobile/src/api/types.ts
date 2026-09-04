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

export interface InstrumentMarketView {
  symbol: string;
  /** ما أعلنه الوسيط عن هذه الأداة. `null` = لم يُعلن. */
  status: string | null;
  tradable: boolean | null;
  reason_ar: string;
}

export interface MarketView {
  is_open: boolean;
  reason_ar: string;
  /**
   * **نطاق هذه الحالة** — ساعات الفوركس، لا حالةَ كل أداة.
   *
   * كانت اللوحة تقول «سوق الفوركس مفتوح» عن ذهبٍ يقول الوسيط إنه مقفل:
   * الفوركس متّصلٌ من الأحد إلى الجمعة بلا انقطاع، وللذهب استراحةٌ يومية
   * عند إقفال شيكاغو. فالنطاق يُقال، وحالةُ كل أداةٍ تُعرض معه.
   */
  scope_ar: string;
  per_instrument: InstrumentMarketView[];
  next_open_utc: string | null;
  next_close_utc: string | null;
}

export interface CompletenessView {
  complete: boolean;
  /**
   * 0..1 على **الإلزاميين وحدهم**، أو null إذا لم تُحسب.
   *
   * كانت تُحسب على كل المزوّدين، ومنهم واحدٌ اختياري لا تنفيذ له أصلاً —
   * فكانت النسبة لا تبلغ ١٠٠٪ بحال، وتوحي بنقصٍ يمنع التداول وهو لا يمنعه.
   */
  ratio: number | null;
  /** الإلزاميون الناقصون — هؤلاء يمنعون التداول. */
  missing: string[];
  /** اختياريون ناقصون: يُذكرون ولا يُخصمون من النسبة. */
  optional_missing: string[];
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
  /**
   * أيّ الحدّين يعمل — **بنصّ الخادم لا بتفسير العميل**.
   *
   * كانت الشاشة تعرض حدود الملف والمحرّك ينفّذ حدود الدستور، فتَعِد بحدٍّ
   * أشدّ من العامل: 0.75 لليوم معروضة و6.00 منفَّذة. والأرقام الآن هي
   * المنفَّذة، وهذا السطر يقول ذلك صراحةً.
   */
  profile_binding_ar: string;
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

/**
 * حالةُ قراءة المحفظة من الوسيط.
 *
 * تُقرأ **قبل** أي حقلٍ آخر. `ok=false` تعني «لم أقرأ»، ولا تعني «لا شيء» —
 * والخلط بينهما هو ما جعل الشاشة تقول «لا مركز مفتوح» وعلى الحساب خمسة.
 */
export interface SyncView {
  ok: boolean;
  reason_code: string;
  error_ar: string;
  last_sync_utc: string | null;
  age_seconds: number | null;
  stale: boolean;
}

export interface OpenPositionView {
  id: string | null;
  instrument: string | null;
  instrument_ar: string | null;
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
  /** الوقف **لدى الوسيط**. `false` = مركزٌ بلا حماية، وهي حالة حرجة. */
  protection_held_by_broker: boolean;
  strategy_ar: string | null;
  /** `STRATEGY` أو `COMMISSIONING` أو `UNATTRIBUTED` — لا يُخمَّن. */
  kind: string;
}

export interface PositionData {
  sync: SyncView;
  /** `null` = تعذّرت القراءة. ليست `false`، لأن «لا أعرف» ليست «لا». */
  has_position: boolean | null;
  open_count: number | null;
  positions: OpenPositionView[];
  unprotected_count: number | null;
  total_unrealised: string | null;
  /** الحقول المفردة تصف **أوّل** مركزٍ مفتوح — للشاشة القديمة. */
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
  protection_held_by_broker: boolean;
  strategy_ar: string | null;
  notes_ar: string[];
}

// ---------------------------------------------------------------------------
// trades
// ---------------------------------------------------------------------------

export interface TradeRecord {
  /**
   * دفترُ المعاملات عند الوسيط يعطي الأداة والزمن والمحقَّق، ولا يعطي سعرَ
   * الدخول والخروج وسببَ الخروج والاتجاه. فتبقى `null` **ولا تُخمَّن**:
   * رقمٌ مخترعٌ في شاشة نتائج أسوأ من خانةٍ فارغة.
   */
  id: string | null;
  instrument: string | null;
  instrument_ar: string | null;
  direction_ar: string | null;
  opened_utc: string | null;
  closed_utc: string | null;
  entry_price: string | null;
  exit_price: string | null;
  realised_pnl: string | null;
  realised_pnl_sign: 'POSITIVE' | 'NEGATIVE' | 'FLAT' | null;
  outcome_ar: string | null;
  strategy_ar: string | null;
  exit_reason_ar: string | null;
  /** يفصل صفقةَ التشغيل عن الصفقة الاستراتيجية. */
  kind: string;
}

export interface TradesData {
  sync: SyncView;
  trades: TradeRecord[];
  /** `true` = لم تُقرأ الصفقات. القائمة الفارغة حينها ليست «لا صفقات». */
  unavailable: boolean;
  realised_pnl_total: string | null;
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
  sync: SyncView;
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

/** صفٌّ لكل أداة نُظِر فيها هذه الدورة. */
export interface ScanInstrument {
  symbol: string;
  decision: string | null;
  reason_code: string | null;
  reason_ar: string | null;
  stage: string | null;
  /** عطلٌ عندنا لا حالةُ سوق — يُعرض مميَّزاً لأنه يحتاج يداً. */
  needs_a_hand: boolean;
  /** فارغةٌ حين يقف الخط قبل مرحلة الاستراتيجية — وذلك صادق: لم تُسأل. */
  strategies?: StrategyAssessment[];
}

/**
 * **ماذا رأى النظام في السوق كلّه** — لا ماذا قرّر في أداة واحدة.
 *
 * وهي الوظيفة التي لم يجدها بحث المنافسين في ٦٩ لقطة: لا شاشة تقول «لماذا
 * لم أتداول». والأربعة هنا غير قابلة للغياب (`__non_nullable_paths__`):
 * تُقرأ في كل عرض بلا حارس.
 */
/** شرطٌ واحد من شروط الاستراتيجية، وحكمه، **ورقمه**. */
export interface StrategyCheck {
  name_ar: string;
  passed: boolean;
  detail_ar: string;
}

/**
 * تشخيص استراتيجيةٍ واحدة على أداةٍ واحدة.
 *
 * كان الرفض جملةً واحدة («لا فرصة مطابقة») هي نفسها سواء كان ADX عند 24.9
 * أو عند 8 — والفرق بينهما هو الفرق بين «انتظري» و«الاستراتيجية في السوق
 * الخطأ».
 */
export interface StrategyAssessment {
  key: string;
  summary_ar: string;
  checks: StrategyCheck[];
}

export interface ScanData {
  instruments: ScanInstrument[];
  scanned: number;
  faults: number;
  summary_ar: string;
}

// ---------------------------------------------------------------------------
// market/candles
// ---------------------------------------------------------------------------

/**
 * شمعة واحدة — **نصوصٌ لا أرقام**.
 *
 * الخادم يحسب بـ`Decimal` ويرسل نصّاً بكامل الدقّة. ولو أرسلها `number`
 * لعبَر السعرُ خانةَ الفاصلة العائمة في JavaScript، فيصير `1.10105` شيئاً
 * قريباً منه لا هو. والتحويل إلى رقم يقع هنا **عند الرسم وحده**، وما لا
 * يُقرأ رقماً تُهمَل شمعتُه ولا تُرسَم على تخمين.
 */
export interface Candle {
  /** بداية الشمعة، UTC. */
  t: string;
  o: string;
  h: string;
  l: string;
  c: string;
}

/**
 * مستويات المركز المفتوح — تُرسَم فوق السعر.
 *
 * `null` هنا تعني «لا مركز»، **لا صفر**. وخطٌّ عند الصفر على رسم سعرٍ عند
 * 1.10 يسحب المقياس كلّه ويجعل الشموع خيطاً.
 */
export interface CandleLevels {
  symbol: string | null;
  entry: string | null;
  stop: string | null;
  target: string | null;
}

/**
 * الشموع كما رآها النظام في آخر دورة مسح — لا أحدث منها.
 *
 * وهذا مقصود: شمعةٌ أحدث من القرار تجعل السبب المكتوب في «القرار» يبدو
 * خاطئاً وهو صحيح على بياناته. والشاشة تقول ذلك بنصّ `note_ar` ولا تدّعي
 * «مباشر» أبداً.
 */
export interface CandlesData {
  /** خريطة: أداة ⇐ إطار ⇐ شموعه بالترتيب الزمني. */
  instruments: Record<string, Record<string, Candle[]>>;
  /** الرموز مرتّبة — الخادم يرتّبها فلا تختلف الشاشة عن السجلّ. */
  symbols: string[];
  /** الأطر المتاحة، من الأطول إلى الأقصر. الترتيب من الخادم لا من العميل. */
  resolutions: string[];
  /**
   * الإطار الذي **يُقاس عليه القرار**.
   *
   * يُعرض مميَّزاً: تصفّح إطارٍ آخر لا يعني أن النظام يقرّر عليه. وقيدُ
   * الوسيط (أدنى وقف 100 نقطة) يمنع التداول على ما دون اليومي أصلاً.
   */
  decision_resolution: string;
  levels: CandleLevels;
  note_ar: string;
}

/**
 * نتيجة تبديل الحساب.
 *
 * `note_ar` يقول صراحةً إن **التداول لم يُفتح**: شاشةٌ تقول «انتقلتِ إلى
 * الحقيقي» بلا أكثر تُقرأ «صار يتداول بمالي».
 */
export interface EnvironmentSwitchResult {
  action: 'ENVIRONMENT_SWITCHED';
  accepted: boolean;
  environment: 'DEMO' | 'LIVE' | null;
  is_demo: boolean | null;
  broker_name: string | null;
  at_utc: string;
  note_ar: string;
}

export interface PauseResult {
  action: 'PAUSE_REQUESTED';
  accepted: boolean;
  at_utc: string;
  note_ar: string;
}

/**
 * نتيجة الاستئناف — **المسار الوحيد في هذا المجال الذي يزيد المخاطرة**.
 *
 * ولا يفتح إلا الإيقاف المحلي: الأقفال الأربعة الباقية لا يمسّها، وقاطع
 * الطوارئ لا يُلغى من الجهاز أبداً. `note_ar` يقول ذلك للمالكة بنصّه.
 */
export interface ResumeResult {
  action: 'RESUMED';
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
