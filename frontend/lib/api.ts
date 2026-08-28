const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export class ApiError extends Error {}

/**
 * كل استدعاء يفشل بصمت هو كذبة على الشاشة.
 * هذه الدالة ترمي خطأً واضحاً بدل إعادة بيانات فارغة تبدو كأنها حقيقة.
 */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new ApiError(`فشل الاتصال بالخادم (${res.status}) عند ${path}`);
  }
  return (await res.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const payload: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : `فشل الطلب (${res.status})`;
    throw new ApiError(detail);
  }
  return payload as T;
}

export type Today = {
  now_riyadh: string;
  market: { is_open: boolean; reason_ar: string; open_riyadh: string | null; close_riyadh: string | null };
  trading_allowed: boolean;
  broker: { name: string; connected: boolean; is_live: boolean };
  live_trading_enabled: boolean;
  risk_mode: string;
  risk_mode_purpose_ar: string;
  equity: { baseline: string; current: string };
  losses: { today: string; week: string; total: string };
  limits: {
    daily: string; weekly: string; total: string;
    target_risk_per_trade: string; max_risk_per_trade: string;
  };
  distance_to_kill_switch: string;
  open_positions: number;
  verdict_ar: string;
  no_trade_reason_ar: string | null;
  kill_switch: {
    active: boolean; trigger: string | null; reason_ar: string | null; at_riyadh: string | null;
  };
};

export type Health = {
  broker_connected: boolean; broker_name: string; broker_is_live: boolean;
  market_data_ok: boolean; database_ok: boolean; scheduler_ok: boolean;
  clock_ok: boolean; audit_chain_ok: boolean; kill_switch_active: boolean;
  details_ar: string[]; checked_at_riyadh: string;
};

export type AuditResponse = {
  chain_ok: boolean;
  chain_problem_ar: string | null;
  checked: number;
  events: Array<{
    sequence: number; at_riyadh: string; actor: string; action: string;
    decision: string; reason_ar: string; source: string;
    related_id: string | null; entry_hash: string;
  }>;
};

export type StrategiesResponse = {
  active_count: number;
  strategies: Array<{
    name: string; version: string; state: string; hypothesis_ar: string;
    markets: string[]; timeframe: string;
    entry_conditions_ar: string[]; exit_conditions_ar: string[];
    invalidations_ar: string[]; no_trade_conditions_ar: string[];
    assumed_costs_ar: string; backtest_evidence_ar: string;
    walkforward_evidence_ar: string; changelog_ar: string[];
  }>;
};

export type RiskResponse = {
  constitution_fingerprint: string;
  risk_mode: string;
  risk_mode_purpose_ar: string;
  economic_guards_enforced: boolean;
  editable_from_ui: boolean;
  modes: Record<
    string,
    {
      purpose_ar: string;
      max_risk_pct: string;
      daily_loss_pct: string;
      weekly_loss_pct: string;
      hard_total_loss_pct: string;
      max_lifetime_entry_orders: number | null;
      requires_per_order_approval: boolean;
      enforce_economic_viability: boolean;
    }
  >;
  limits: Record<string, string>;
  usage: Record<string, string | number>;
  triggers: Array<{ code: string; label_ar: string }>;
  history: Array<{ trigger: string; reason_ar: string; policy: string; at_riyadh: string }>;
};

export type Opportunities = {
  allowlist: Array<{
    symbol: string; name_ar: string; enabled: boolean;
    rationale_ar: string; strategy: string; status_ar: string;
  }>;
  denylist: Array<{ symbol: string; reason_ar: string }>;
};

export type TradesResponse = {
  error_ar?: string;
  positions: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  executions: Array<Record<string, unknown>>;
};

export type SettingsResponse = {
  mode: string; broker_mode: string; live_trading: boolean;
  display_timezone: string; baseline_equity_usd: string;
  risk_mode: string; risk_mode_changeable_from_ui: boolean;
  risk_constitution_editable: boolean; allowlist: string[];
  blackout_days_confirmed: string[];
};

export type BrokerState = {
  broker: string;
  is_demo: boolean;
  live_api_enabled_in_source: boolean;
  base_url: string;
  adapter_name: string;
  connected: boolean;
  account_masked: string | null;
  local_trading_paused: boolean;
  execution_lock: {
    unlocked: boolean;
    owner_authorization_reference: string | null;
    reason_ar: string;
    unlocked_at_utc: string | null;
  };
  risk_mode: string;
  risk_constitution_version: string;
  kill_switch: { active: boolean; trigger: string | null; reason_ar: string | null };
  credentials: Array<{ name: string; present: boolean; source: string }>;
  discovery_allowlist: string[];
  execution_allowlist: string[];
  api_key_pause_instructions_ar: string[];
};

export type CfdPreview = {
  epic: string;
  provisional: boolean;
  provisional_note_ar: string;
  display: {
    epic: string;
    size_broker_units: string;
    notional_exposure: string;
    margin_required: string;
    all_in_risk_at_stop: string;
    pip_value: string;
    stop_distance_pips: string;
    stop_kind: string;
    spread_cost: string;
    guaranteed_stop_premium: string;
    slippage_reserve: string;
    overnight_cost: string;
    conversion_cost: string;
    total_costs: string;
    net_reward: string;
    net_reward_risk_ratio: string;
    breakeven_move_pips: string;
    provisional: boolean;
    provenance_notes: string[];
  };
  caps: {
    preferred_max_risk: string;
    absolute_max_risk: string;
    within_preferred: boolean;
    within_absolute: boolean;
  };
  warnings_ar: string[];
  submitted: boolean;
  execution_locked: boolean;
};

// ---------------------------------------------------------------------------
// ملفات التداول (0.3.0)
// ---------------------------------------------------------------------------

export type ProfileLimitsView = {
  profile: string;
  name_ar: string;
  profile_system_version: string;
  equity_used: string;
  max_risk_per_trade: string;
  max_daily_loss: string;
  max_weekly_loss: string;
  operational_drawdown_stop: string;
  gap_slippage_reserve: string;
  absolute_loss_boundary: string;
  max_open_positions: number;
  max_entry_orders_per_day: number;
  full_risk_loss_ends_day: boolean;
  min_net_reward_risk: string;
  min_quality_score: number;
  allow_overnight: boolean;
  allow_weekend_hold: boolean;
  allowed_instruments: string[];
};

export type ProfilesState = {
  selected_profile: string;
  selected_name_ar: string;
  effective_profile: string;
  effective_name_ar: string;
  risk_level_ar: string;
  pending_profile: string | null;
  pending_available_at_utc: string | null;
  cooling_remaining_seconds: number;
  cooling_remaining_ar: string;
  change_blocked_reason: string | null;
  change_blocked_reason_ar: string;
  limits: ProfileLimitsView;
  fingerprint: string;
  non_resettable_counters: string[];
  counters: Record<string, string | number | boolean>;
  history_len: number;
  available_profiles: {
    profile: string;
    name_ar: string;
    description_ar: string;
    risk_rank: number;
    limits: ProfileLimitsView;
  }[];
  global_loss_constitution: {
    operational_drawdown_stop: string;
    gap_slippage_reserve: string;
    absolute_loss_boundary: string;
    cooling_hours: number;
    note_ar: string;
  };
  never_weakened_by_profile: string[];
};

export type ProfileChangeResponse = {
  accepted: boolean;
  effective_profile: string;
  pending_profile: string | null;
  refusal: string | null;
  message_ar: string;
  live_trading_enabled?: boolean;
  note_ar?: string;
};

export type StageView = {
  stage: string;
  name_ar: string;
  passed: boolean | null;
  mandatory?: boolean;
  detail_ar?: string;
};

export type StrategyView = {
  key: string;
  title_ar: string;
  state: string;
  live_eligible: boolean;
  compatible_regimes: string[];
  incompatible_regimes: string[];
  entry_rules_ar: string[];
  invalidation_rules_ar: string[];
  stop_rules_ar: string[];
  exit_rules_ar: string[];
  validation_notes_ar: string[];
};

export type IntelligenceState = {
  available: boolean;
  reason_ar?: string;
  decision?: string;
  reason_code?: string;
  snapshot_id?: string;
  profile?: string;
  stages: StageView[];
  score?: {
    total: number;
    max: number;
    has_mandatory_failure: boolean;
    mandatory_failures: { code: string; reason_ar: string }[];
    lines: {
      category: string;
      category_ar: string;
      awarded: number;
      maximum: number;
      reason_ar: string;
      source_ar: string;
    }[];
  } | null;
  contradictions?: {
    count: number;
    total_penalty: number;
    has_unresolved_material: boolean;
    items: {
      kind: string;
      side_a_ar: string;
      side_b_ar: string;
      severity_ar: string;
      resolution_ar: string;
      blocks_trading: boolean;
    }[];
  } | null;
  verification?: { passed: boolean; reason_ar: string; mismatches: string[] } | null;
  regime?: { regime: string; name_ar: string; tradable: boolean; reason_ar: string } | null;
  timeframes?: {
    primary_regime_trend: string;
    structural_trend: string;
    entry_trend: string;
    incomplete: string[];
  } | null;
  fundamentals?: {
    relative_bias_ar: string;
    completeness: string;
    usable: boolean;
    unknown_fields: string[];
  } | null;
  missing_providers?: string[];
  missing_data?: string[];
  explanation_ar?: string;
  decided_at_utc?: string | null;
  providers: {
    providers: { kind: string; configured: boolean; name: string; note_ar: string }[];
    missing: string[];
    missing_mandatory: string[];
    live_eligible_by_providers: boolean;
  };
  strategies: { strategies: StrategyView[]; approved_count: number; note_ar: string };
};
