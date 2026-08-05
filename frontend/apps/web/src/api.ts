import type {
  AgentRunEntry, AssistantResult, AuditLogEntry, BankProfile, BankTrendsResult, BranchMapResult,
  CandlesResult, ClusterDiagnosticsResult, CompareResult, CountyConcentrationResult,
  FilingDiffResult, HeatmapResult, MaFitResult, MarketSnapshot, MetricDistributionResult,
  MetricGroup, ModelCardResult, PeerClusterResult, PopulationBank, PopulationMetricsResult,
  QuarterlyBriefingResult, RiskLeaderboardResult, RiskScoreResult, StressResult, TreemapResult,
  WatchlistItem, XrayResult,
} from './types';
import { getCurrentUser } from './auth';

const BASE = 'http://localhost:8791/api';

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

export interface BankSearchResult { count: number; banks: { cert: number; name: string; state: string | null; assets_b: number; cluster: string | null }[] }

export interface ScreenerFilters {
  query?: string;
  state?: string;
  min_assets_b?: number;
  max_assets_b?: number;
  limit?: number;
}

export const api = {
  health: () => get<{ status: string }>('/health'),
  population: () => get<{ banks: PopulationBank[] }>('/population'),
  searchBanks: (query?: string, state?: string, limit = 30) =>
    get<BankSearchResult>('/banks', { query, state, limit }),
  // Full-filter version of the same /api/banks route (real DuckDB SQL,
  // banklens_mcp.data.query_banks()) — searchBanks() above is the small
  // header combobox's narrower call shape, kept as-is so it's untouched by
  // the Screener page's needs.
  screenBanks: (filters: ScreenerFilters) =>
    get<BankSearchResult>('/banks', { ...filters, limit: filters.limit ?? 50 }),
  profile: (cert: number) => get<BankProfile>('/banks/profile', { cert }),
  xray: (cert: number) => get<XrayResult>('/banks/xray', { cert }),
  peerCluster: (cert: number) => get<PeerClusterResult>('/banks/peer-cluster', { cert }),
  maFit: (cert: number, top_n = 8) => get<MaFitResult>('/banks/ma-fit', { cert, top_n }),
  stressTest: (cert: number, loan_loss_pct: number, deposit_outflow_pct: number, rate_shock_bps: number) =>
    get<StressResult>('/banks/stress-test', { cert, loan_loss_pct, deposit_outflow_pct, rate_shock_bps }),
  filingDiff: (cert: number, quarter_a?: string, quarter_b?: string) =>
    get<FilingDiffResult>('/banks/filing-diff', { cert, quarter_a, quarter_b }),
  bankTrends: (cert: number) => get<BankTrendsResult>('/banks/trends', { cert }),
  riskScore: (cert: number) => get<RiskScoreResult>('/banks/risk-score', { cert }),
  candles: (cert: number, limit_days = 180) => get<CandlesResult>('/banks/candles', { cert, limit_days }),
  marketSnapshot: (cert: number) => get<MarketSnapshot>('/banks/market-snapshot', { cert }),
  riskLeaderboard: (top_n = 25) => get<RiskLeaderboardResult>('/risk-leaderboard', { top_n }),
  // certs travels as one comma-separated string — do_GET's query parser
  // collapses repeated keys, so a real list param isn't representable.
  compareBanks: (certs: number[], metrics?: string[]) =>
    get<CompareResult>('/compare', { certs: certs.join(','), ...(metrics ? { metrics: metrics.join(',') } : {}) }),
  getWatchlist: () => get<{ items: WatchlistItem[] }>('/watchlist'),
  addToWatchlist: (cert: number) => post<{ items: WatchlistItem[] }>('/watchlist', { cert }),
  removeFromWatchlist: (cert: number) => del<{ items: WatchlistItem[] }>('/watchlist', { cert }),
  // No client-side timeout — a real answer from the $0 default (Ollama) can
  // legitimately take several minutes (see AssistantPage's own wait copy).
  askAssistant: (persona: string, question: string) =>
    post<AssistantResult>('/assistant/ask', { persona, question }),
  agentRuns: (limit = 50) => get<{ items: AgentRunEntry[] }>('/activity/agent-runs', { limit }),
  auditLog: (limit = 50) => get<{ items: AuditLogEntry[] }>('/activity/audit-log', { limit }),
  populationMetrics: (group: MetricGroup, opts: { limit?: number; sortBy?: string; descending?: boolean } = {}) =>
    get<PopulationMetricsResult>('/population-metrics', {
      group, limit: opts.limit ?? 2000, sort_by: opts.sortBy,
      descending: opts.descending === false ? 'false' : undefined,
    }),
  metricDistribution: (metric: string, bins = 30) =>
    get<MetricDistributionResult>('/metric-distribution', { metric, bins }),
  percentileHeatmap: (top_n = 40, sort_by = 'total_assets') =>
    get<HeatmapResult>('/percentile-heatmap', { top_n, sort_by }),
  assetTreemap: (group_by: 'peer_cluster_label' | 'state' = 'peer_cluster_label') =>
    get<TreemapResult>('/asset-treemap', { group_by }),
  quarterlyBriefing: (top_n = 8) => get<QuarterlyBriefingResult>('/briefing', { top_n }),
  clusterDiagnostics: () => get<ClusterDiagnosticsResult>('/cluster-diagnostics'),
  modelCard: () => get<ModelCardResult>('/model-card'),
  countyConcentration: (opts: { state?: string; top_n?: number } = {}) =>
    get<CountyConcentrationResult>('/county-concentration', { state: opts.state, top_n: opts.top_n ?? 100 }),
  branchMap: (state?: string) => get<BranchMapResult>('/branch-map', { state }),
};
