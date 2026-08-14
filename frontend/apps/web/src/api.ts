import type {
  AgentRunEntry, AlertItem, AssistantResult, AuditLogEntry, BankProfile, BankTrendsResult, BranchMapResult,
  BulkStressResult, CandlesResult, ClusterDiagnosticsResult, CompareResult,
  CountyConcentrationResult, DataFreshnessResult, FilingDiffResult, FilingSearchResponse,
  FilingsCoverageResult, HeatmapResult, MaFitResult, MaProFormaResult, MaWeightValidationResult,
  MarketCoverageResult, MarketOverviewResult, MarketSnapshot,
  MetricDistributionResult, MetricGroup, ModelCardResult, NetworkGraphResult, PeerClusterResult,
  PopulationBank, PopulationMetricsResult, QuarterlyBriefingResult, RiskLeaderboardResult,
  CorrelatedStressResult, IrrbbResult, LiquiditySurvivalResult, RiskScoreResult, SavedScreen,
  StressComparisonResult, StressProjectionResult, StressResult, StressSurfaceResult, TreemapResult,
  WatchlistItem, WatchlistRule, WatchlistRuleType, XrayResult, XrayValidationResult,
} from './types';
import { getCurrentUser } from './auth';

// VITE_API_BASE lets a deployed build point at a non-localhost bridge (see
// frontend/apps/web/.env.example) — falls back to the local dev bridge so
// `npm run dev` is unchanged. Same pattern src/auth.ts uses for VITE_KEYCLOAK_URL.
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8791/api';

// The bridge gates every route except /api/health behind a real Keycloak
// token (see services/api-gateway/src/auth.py) — attach it on every call.
async function authHeaders(): Promise<HeadersInit> {
  const user = await getCurrentUser();
  return user?.access_token ? { Authorization: `Bearer ${user.access_token}` } : {};
}

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&');
  return qs ? `?${qs}` : '';
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}${toQuery(params)}`, { headers: await authHeaders() });
  return unwrap<T>(res);
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { ...(await authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return unwrap<T>(res);
}

async function del<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}${toQuery(params)}`, {
    method: 'DELETE',
    headers: await authHeaders(),
  });
  return unwrap<T>(res);
}

// D1 — the tearsheet route returns a raw PDF (see bridge_server.py's
// BinaryResponse), not JSON, so it can't go through get()/unwrap(). Triggers
// a same-shape browser download to the filename the bridge's
// Content-Disposition header names.
async function downloadBinary(path: string, params: Record<string, string | number | undefined>, fallbackName: string): Promise<void> {
  const res = await fetch(`${BASE}${path}${toQuery(params)}`, { headers: await authHeaders() });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `${res.status} ${res.statusText}`);
  }
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = /filename="([^"]+)"/.exec(disposition);
  const filename = match?.[1] ?? fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export interface BankSearchResult {
  count: number;
  banks: {
    cert: number; name: string; state: string | null; country: string | null;
    assets_b: number; cluster: string | null;
    roa_pct: number | null; npl_ratio_pct: number | null; cet1_ratio: number | null;
  }[];
}

export interface ScreenerFilters {
  query?: string;
  state?: string;
  country?: string;
  min_assets_b?: number;
  max_assets_b?: number;
  limit?: number;
}

export const api = {
  health: () => get<{ status: string }>('/health'),
  population: () => get<{ banks: PopulationBank[] }>('/population'),
  // D3 — every landed quarter (newest first) + which is "latest", for the
  // global quarter selector.
  quarters: () => get<{ quarters: string[]; latest: string }>('/quarters'),
  searchBanks: (query?: string, state?: string, limit = 30) =>
    get<BankSearchResult>('/banks', { query, state, limit }),
  // Full-filter version of the same /api/banks route (real DuckDB SQL,
  // banklens_mcp.data.query_banks()) — searchBanks() above is the small
  // header combobox's narrower call shape, kept as-is so it's untouched by
  // the Screener page's needs.
  screenBanks: (filters: ScreenerFilters) =>
    get<BankSearchResult>('/banks', { ...filters, limit: filters.limit ?? 50 }),
  // `quarter` (D3, REPDTE e.g. "20260331"): view a DIFFERENT landed quarter
  // than the latest — omit (or pass undefined/null) for unchanged behavior.
  // C11 — peerBasis: 'global' (default) | 'size' | 'cluster'.
  profile: (cert: number, quarter?: string | null, peerBasis?: string) =>
    get<BankProfile>('/banks/profile', { cert, quarter: quarter ?? undefined, peer_basis: peerBasis }),
  xray: (cert: number, quarter?: string | null) =>
    get<XrayResult>('/banks/xray', { cert, quarter: quarter ?? undefined }),
  peerCluster: (cert: number, quarter?: string | null) =>
    get<PeerClusterResult>('/banks/peer-cluster', { cert, quarter: quarter ?? undefined }),
  maFit: (cert: number, top_n = 8, quarter?: string | null) =>
    get<MaFitResult>('/banks/ma-fit', { cert, top_n, quarter: quarter ?? undefined }),
  // C9 — pro-forma calculator + weight validation governance.
  maProForma: (targetCert: number, acquirerCert: number, opts: {
    premiumToTbvPct?: number; costSynergiesPct?: number; taxRatePct?: number;
  } = {}) =>
    get<MaProFormaResult>('/banks/ma-pro-forma', {
      target_cert: targetCert, acquirer_cert: acquirerCert,
      premium_to_tbv_pct: opts.premiumToTbvPct, cost_synergies_pct_of_target_opex: opts.costSynergiesPct,
      tax_rate_pct: opts.taxRatePct,
    }),
  maWeightValidation: () => get<MaWeightValidationResult>('/ma-weight-validation'),
  // C10 — X-Ray forward-return validation.
  xrayValidation: () => get<XrayValidationResult>('/xray-forward-return-validation'),
  stressTest: (cert: number, loan_loss_pct: number, deposit_outflow_pct: number, rate_shock_bps: number) =>
    get<StressResult>('/banks/stress-test', { cert, loan_loss_pct, deposit_outflow_pct, rate_shock_bps }),
  filingDiff: (cert: number, quarter_a?: string, quarter_b?: string) =>
    get<FilingDiffResult>('/banks/filing-diff', { cert, quarter_a, quarter_b }),
  bankTrends: (cert: number) => get<BankTrendsResult>('/banks/trends', { cert }),
  riskScore: (cert: number, quarter?: string | null) =>
    get<RiskScoreResult>('/banks/risk-score', { cert, quarter: quarter ?? undefined }),
  candles: (cert: number, limit_days = 180) => get<CandlesResult>('/banks/candles', { cert, limit_days }),
  marketSnapshot: (cert: number) => get<MarketSnapshot>('/banks/market-snapshot', { cert }),
  marketCoverage: () => get<MarketCoverageResult>('/market/coverage'),
  // E2 — cross-bank market view: a peer set (certs) or, absent one, the
  // top_n largest-by-assets banks. certs travels comma-separated, same
  // reason compareBanks()/bulkStressTest() do.
  marketOverview: (opts: { certs?: number[]; top_n?: number; window_days?: number } = {}) =>
    get<MarketOverviewResult>('/market/overview', {
      certs: opts.certs?.length ? opts.certs.join(',') : undefined,
      top_n: opts.top_n, window_days: opts.window_days,
    }),
  riskLeaderboard: (top_n = 25, opts: { state?: string; cluster_label?: string; quarter?: string | null } = {}) =>
    get<RiskLeaderboardResult>('/risk-leaderboard', {
      top_n, state: opts.state, cluster_label: opts.cluster_label, quarter: opts.quarter ?? undefined,
    }),
  // certs travels as one comma-separated string — do_GET's query parser
  // collapses repeated keys, so a real list param isn't representable.
  compareBanks: (certs: number[], metrics?: string[], quarter?: string | null) =>
    get<CompareResult>('/compare', {
      certs: certs.join(','), ...(metrics ? { metrics: metrics.join(',') } : {}), quarter: quarter ?? undefined,
    }),
  getWatchlist: () => get<{ items: WatchlistItem[] }>('/watchlist'),
  addToWatchlist: (cert: number) => post<{ items: WatchlistItem[] }>('/watchlist', { cert }),
  removeFromWatchlist: (cert: number) => del<{ items: WatchlistItem[] }>('/watchlist', { cert }),
  // D2 — free-text notes, threshold-rule alerts and saved screener definitions.
  setWatchlistNote: (cert: number, note: string) =>
    post<{ items: WatchlistItem[] }>('/watchlist/note', { cert, note }),
  getWatchlistRules: () => get<{ items: WatchlistRule[] }>('/watchlist/rules'),
  addWatchlistRule: (cert: number, rule_type: WatchlistRuleType,
                     opts: { metric?: string; operator?: 'gt' | 'lt'; threshold?: number; top_n?: number } = {}) =>
    post<{ items: WatchlistRule[] }>('/watchlist/rules', { cert, rule_type, ...opts }),
  removeWatchlistRule: (rule_id: number) =>
    del<{ items: WatchlistRule[] }>('/watchlist/rules', { rule_id }),
  getSavedScreens: () => get<{ items: SavedScreen[] }>('/screens'),
  saveScreen: (name: string, filters: Record<string, string | number | undefined>) =>
    post<{ items: SavedScreen[] }>('/screens', { name, filters }),
  deleteSavedScreen: (screen_id: number) => del<{ items: SavedScreen[] }>('/screens', { screen_id }),
  getAlerts: (opts: { limit?: number; unseenOnly?: boolean } = {}) =>
    get<{ items: AlertItem[] }>('/alerts', {
      limit: opts.limit ?? 50, unseen_only: opts.unseenOnly ? 'true' : undefined,
    }),
  markAlertSeen: (alert_id: number) => post<{ items: AlertItem[] }>('/alerts/seen', { alert_id }),
  // No client-side timeout — a real answer from the $0 default (Ollama) can
  // legitimately take several minutes (see AssistantPage's own wait copy).
  askAssistant: (persona: string, question: string) =>
    post<AssistantResult>('/assistant/ask', { persona, question }),
  agentRuns: (limit = 50) => get<{ items: AgentRunEntry[] }>('/activity/agent-runs', { limit }),
  auditLog: (limit = 50) => get<{ items: AuditLogEntry[] }>('/activity/audit-log', { limit }),
  populationMetrics: (group: MetricGroup, opts: { limit?: number; sortBy?: string; descending?: boolean; quarter?: string | null } = {}) =>
    get<PopulationMetricsResult>('/population-metrics', {
      group, limit: opts.limit ?? 2000, sort_by: opts.sortBy,
      descending: opts.descending === false ? 'false' : undefined, quarter: opts.quarter ?? undefined,
    }),
  metricDistribution: (metric: string, bins = 30, quarter?: string | null) =>
    get<MetricDistributionResult>('/metric-distribution', { metric, bins, quarter: quarter ?? undefined }),
  percentileHeatmap: (top_n = 40, sort_by = 'total_assets', metrics?: string[], quarter?: string | null) =>
    get<HeatmapResult>('/percentile-heatmap', {
      top_n, sort_by, metrics: metrics && metrics.length > 0 ? metrics.join(',') : undefined,
      quarter: quarter ?? undefined,
    }),
  assetTreemap: (group_by: 'peer_cluster_label' | 'state' | 'country' = 'peer_cluster_label', quarter?: string | null) =>
    get<TreemapResult>('/asset-treemap', { group_by, quarter: quarter ?? undefined }),
  quarterlyBriefing: (top_n = 8) => get<QuarterlyBriefingResult>('/briefing', { top_n }),
  clusterDiagnostics: () => get<ClusterDiagnosticsResult>('/cluster-diagnostics'),
  modelCard: () => get<ModelCardResult>('/model-card'),
  countyConcentration: (opts: { state?: string; top_n?: number } = {}) =>
    get<CountyConcentrationResult>('/county-concentration', { state: opts.state, top_n: opts.top_n ?? 100 }),
  branchMap: (state?: string) => get<BranchMapResult>('/branch-map', { state }),
  network: (top_n = 150) => get<NetworkGraphResult>('/network', { top_n }),
  bulkStressTest: (certs: number[], loan_loss_pct: number, deposit_outflow_pct: number, rate_shock_bps: number) =>
    get<BulkStressResult>('/banks/stress-test-bulk', {
      certs: certs.join(','), loan_loss_pct, deposit_outflow_pct, rate_shock_bps,
    }),
  stressComparison: (cert: number, loan_loss_pct: number, deposit_outflow_pct: number, rate_shock_bps: number) =>
    get<StressComparisonResult>('/banks/stress-test-compare', {
      cert, loan_loss_pct, deposit_outflow_pct, rate_shock_bps,
    }),
  // E3 — (deposit_outflow x rate_shock) grid for one bank, loan_loss_pct held
  // fixed, computed server-side in one request for the Stress Lab's CET1
  // surface heatmap.
  stressSurface: (cert: number, loan_loss_pct: number, deposit_outflow_max_pct = 90,
                  rate_shock_max_bps = 500, steps = 7) =>
    get<StressSurfaceResult>('/banks/stress-test-surface', {
      cert, loan_loss_pct, deposit_outflow_max_pct, rate_shock_max_bps, steps,
    }),
  // C4 — multi-period projection, sustained-outflow liquidity horizon, and a
  // single joint correlated scenario instead of three independent sliders.
  stressProjection: (cert: number, loan_loss_pct: number, deposit_outflow_pct: number,
                     rate_shock_bps: number, horizon_quarters = 4, phase_in = true, apply_ppnr_offset = true) =>
    get<StressProjectionResult>('/banks/stress-test-projection', {
      cert, loan_loss_pct, deposit_outflow_pct, rate_shock_bps, horizon_quarters,
      phase_in: phase_in ? 'true' : 'false', apply_ppnr_offset: apply_ppnr_offset ? 'true' : 'false',
    }),
  liquiditySurvival: (cert: number, quarterly_outflow_pct = 15.0) =>
    get<LiquiditySurvivalResult>('/banks/liquidity-survival', { cert, quarterly_outflow_pct }),
  correlatedStress: (cert: number, rate_shock_bps: number, severity: 'mild' | 'moderate' | 'severe' = 'moderate') =>
    get<CorrelatedStressResult>('/banks/correlated-stress', { cert, rate_shock_bps, severity }),
  // C5 — EVE / 12-month NII sensitivity.
  irrbb: (cert: number, parallel_shock_bps = 200.0) =>
    get<IrrbbResult>('/banks/irrbb', { cert, parallel_shock_bps }),
  // C6 — per-category loan-loss rates, defaulted to this bank's own disclosed
  // charge-off rate per category scaled by severity_multiplier.
  segmentedStressTest: (cert: number, severity_multiplier = 3.0, deposit_outflow_pct = 15.0, rate_shock_bps = 200.0) =>
    get<StressResult>('/banks/segmented-stress-test', {
      cert, severity_multiplier, deposit_outflow_pct, rate_shock_bps,
    }),
  searchFilings: (query: string, top_n = 8) =>
    get<FilingSearchResponse>('/filings/search', { query, top_n }),
  filingsCoverage: () => get<FilingsCoverageResult>('/filings/coverage'),
  dataFreshness: () => get<DataFreshnessResult>('/data-freshness'),
  // D1 — server-side per-bank PDF tearsheet; triggers a browser download
  // rather than returning parsed data (see downloadBinary above).
  downloadTearsheet: (cert: number) =>
    downloadBinary('/banks/tearsheet', { cert }, `banklens-tearsheet-${cert}.pdf`),
};
