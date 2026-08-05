// Shapes returned by the REST bridge (services/api-gateway/src/bridge_server.py),
// which itself wraps banklens_mcp.tools 1:1 — these mirror the tool outputs exactly.

export interface BankSummary {
  cert: number;
  name: string;
  state: string | null;
  assets_b: number;
  cluster: string | null;
}

export interface MetricPctile {
  value: number | null;
  percentile: number | null;
}

export interface BankProfile {
  cert: number;
  name: string;
  state: string | null;
  quarter: string;
  assets_b: number;
  uninsured_deposit_pct: number | null;
  loan_to_deposit_pct: number | null;
  cre_concentration_pct: number | null;
  cet1_ratio: number | null;
  leverage_ratio: number | null;
  peer_cluster: string | null;
  concentration: {
    cre: MetricPctile;
    c_and_i: MetricPctile;
    residential_mortgage: MetricPctile;
    consumer: MetricPctile;
    agricultural: MetricPctile;
  };
  capital: {
    cet1: MetricPctile;
    tier1_rbc: MetricPctile;
    total_rbc: MetricPctile;
    leverage: MetricPctile;
  };
  funding: {
    uninsured_deposit_pct: MetricPctile;
    loan_to_deposit_pct: MetricPctile;
    core_deposit_pct: MetricPctile;
  };
}

export interface XrayFlag {
  factor: string;
  metric: string;
  value: number;
  threshold: number;
  severity: 'low' | 'elevated' | 'high';
  note: string;
  peer_percentile?: number;
}

export interface XrayResult {
  cert_number: number;
  name: string;
  quarter: string;
  overall_risk: 'low' | 'elevated' | 'high';
  flag_count: number;
  flags: XrayFlag[];
  key_metrics: {
    uninsured_deposit_pct: number | null;
    loan_to_deposit_pct: number | null;
    max_loan_concentration: { category: string | null; pct: number | null };
    cet1_ratio: number | null;
    leverage_ratio: number | null;
  };
}

export interface PeerClusterResult {
  cert: number;
  cluster_id: number;
  cluster_label: string;
  cluster_size: number;
  sample_peers: string[];
}

export interface MaCandidate {
  cert_number: number;
  name: string;
  fit_score: number;
  funding_complementarity: number;
  business_similarity: number;
  size_fit: number;
  geo_overlap: number | null;
  geo_overlap_deposit_weighted: number | null;
  rationale: string;
}

export interface MaFitResult {
  target: string;
  candidates: MaCandidate[];
}

export interface StressRatios {
  cet1: number;
  tier1: number;
  total: number;
  leverage: number;
}

export interface StressResult {
  name: string;
  quarter: string;
  shock: Record<string, number | boolean>;
  before: StressRatios;
  after: StressRatios;
  minimums: StressRatios;
  passes: Record<keyof StressRatios, boolean>;
  passes_all: boolean;
  capital_waterfall: {
    loan_loss: number;
    afs_mark_loss: number;
    htm_realized_loss: number;
    total_capital_hit: number;
  };
  liquidity: {
    deposit_outflow: number;
    available_liquidity: number;
    shortfall_forcing_htm_sales: number;
    htm_sold_fraction: number;
    htm_unrealized_loss_memo: number;
  };
}

export interface RiskDriver {
  feature: string;
  value: number;
  contribution: number;
}

export interface RiskScoreResult {
  risk_score: number;
  drivers: RiskDriver[];
  cert: number;
  name: string;
  model_trained_on: string;
  note: string;
}

export interface FilingDiffFlag {
  item: string;
  metric: string;
  kind: 'dollar' | 'ratio';
  change: number;
  unit: string;
  z: number | null;
  direction: 'up' | 'down';
  note: string;
}

export interface FilingDiffLineItem {
  item: string;
  metric: string;
  kind: 'dollar' | 'ratio';
  quarter_a_value: number | null;
  quarter_b_value: number | null;
  unit: string;
  change: number | null;
  z: number | null;
  direction: 'up' | 'down' | null;
  flagged: boolean;
  note: string;
}

export interface FilingDiffResult {
  name: string;
  from_quarter: string;
  to_quarter: string;
  span_quarters: number;
  n_flags: number;
  flags: FilingDiffFlag[];
  line_items: FilingDiffLineItem[];
}

// ---- trends + quarterly briefing ----

export interface BankTrendPoint {
  quarter: string;
  peer_cluster_label: string | null;
  [metric: string]: number | string | null;
}

export interface BankTrendsResult {
  cert: number;
  name: string;
  metrics: string[];
  quarters: string[];
  series: BankTrendPoint[];
}

export interface BriefingMover {
  cert: number;
  name: string;
  metric: string;
  label: string;
  from: number;
  to: number;
  change: number;
}

export interface ClusterMigration {
  cert: number;
  name: string;
  from: string;
  to: string;
}

export interface RiskLeaderboardEntrant {
  cert: number;
  name: string;
  risk_score: number;
}

export interface QuarterlyBriefingResult {
  quarter: string;
  prior_quarter: string;
  population_count: number;
  prior_population_count: number;
  entered: string[];
  exited: string[];
  top_movers: BriefingMover[];
  cluster_migrations: {
    count: number;
    by_transition: Record<string, number>;
    sample: ClusterMigration[];
  };
  risk_leaderboard_entrants: RiskLeaderboardEntrant[];
  risk_model_trained: boolean;
}

export interface PopulationBank {
  cert: number;
  name: string;
  state: string | null;
  assets_b: number;
  cre_pct: number;
  uninsured_pct: number;
  cet1: number | null;
  cluster_id: number;
  cluster_label: string;
}

export interface PriceBar {
  ticker: string;
  date: string; // "YYYY-MM-DD"
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  adj_close: number;
  adj_volume: number;
  div_cash: number;
  split_factor: number;
}

export interface CandlesResult {
  cert: number;
  name: string;
  ticker: string;
  bars: PriceBar[];
}

export interface RiskLeaderboardEntry {
  cert: number;
  name: string;
  risk_score: number;
}

export interface RiskLeaderboardResult {
  count: number;
  model_trained_on: string;
  note: string;
  top: RiskLeaderboardEntry[];
}

export interface CompareRow {
  cert: number;
  name: string;
  [metric: string]: number | string | null;
}

export interface CompareResult {
  metrics: string[];
  banks: CompareRow[];
}

export interface WatchlistItem {
  cert: number;
  created_at: string;
}

export interface AuditLogEntry {
  id: number;
  ts: string;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  latency_ms: number;
}

export interface AgentRunEntry {
  id: number;
  ts: string;
  persona: string;
  provider: string;
  model: string | null;
  question: string;
  answer: string;
  ok: boolean;
  transcript_path: string;
}

export interface ToolCallRecord {
  name: string;
  arguments: Record<string, unknown>;
  result_preview: string;
}

export interface AssistantResult {
  persona: string;
  question: string;
  answer: string;
  provider: string;
  turns: number;
  tool_calls: ToolCallRecord[];
}

export interface MarketSnapshot {
  cert: number;
  name: string;
  ticker: string | null;
  as_of: string | null;
  close: number | null;
  change_1d_pct: number | null;
  volatility_30d_pct: number | null;
  week52_high: number | null;
  week52_low: number | null;
}

// ---- population-wide metric groups (earnings/credit/funding/capital/concentration) ----

export type MetricGroup = 'earnings' | 'credit' | 'funding' | 'capital' | 'concentration';

// Identity columns plus every metric (and percentile_rank_<metric> where computed)
// for the requested group — the exact key set varies by group, so this is an index
// signature over the identity fields rather than an exhaustive interface.
export interface PopulationMetricRow {
  cert_number: number;
  name: string;
  state: string | null;
  total_assets: number | null;
  peer_cluster_label: string | null;
  [metric: string]: number | string | null;
}

export interface PopulationMetricsResult {
  group: MetricGroup;
  quarter: string;
  metrics: string[];
  count: number;
  banks: PopulationMetricRow[];
}

export interface DataQualityExclusion {
  cert: number;
  name: string;
  quarter: string;
  rule: string;
  reason: string;
  deposits_to_assets_pct?: number | null;
  total_assets?: number | null;
  total_deposits?: number | null;
  threshold_pct?: number;
}

export interface DataQualityDisclosure {
  threshold_pct: number;
  rule: string;
  excluded_count: number;
  total_considered: number;
  excluded_pct: number;
  excluded: DataQualityExclusion[];
}

export interface HistogramBin {
  lower: number;
  upper: number;
  count: number;
}

export interface HeatmapBank {
  cert: number;
  name: string;
  /** Percentile ranks (0-100), aligned to HeatmapResult.metrics. Null = not computed. */
  cells: (number | null)[];
}

export interface HeatmapResult {
  quarter: string;
  metrics: string[];
  banks: HeatmapBank[];
}

export interface TreemapNode {
  cert: number;
  name: string;
  value: number;
  cet1_ratio: number | null;
  overall_risk: 'low' | 'elevated' | 'high';
  uninsured_deposit_pct: number | null;
  npl_ratio_pct: number | null;
}

export interface TreemapGroup {
  name: string;
  children: TreemapNode[];
}

export interface TreemapResult {
  quarter: string;
  group_by: 'peer_cluster_label' | 'state';
  groups: TreemapGroup[];
}

export interface MetricDistributionResult {
  metric: string;
  quarter: string;
  count: number;
  min: number;
  max: number;
  mean: number;
  p10: number;
  p25: number;
  median: number;
  p75: number;
  p90: number;
  histogram_range: { lower: number; upper: number; note: string };
  histogram: HistogramBin[];
  exclusions: DataQualityDisclosure;
}
