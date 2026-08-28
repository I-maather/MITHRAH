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
