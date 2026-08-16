// Shapes returned by the REST bridge (services/api-gateway/src/bridge_server.py),
// which itself wraps banklens_mcp.tools 1:1 — these mirror the tool outputs exactly.

// B10: per-source landing vintage, read from the same _provenance.json every
// Bronze landing already writes — see banklens_mcp.data.data_freshness.
export interface DataFreshnessSource {
  landed: boolean;
  fetched_at: string | null;
  endpoint: string | null;
  record_count: number | null;
  expected_next_publication: string | null;
}

export interface DataFreshnessResult {
  sources: Record<string, DataFreshnessSource>;
}

// D9/G9: one Gold metric traced back to its Bronze source — see
// banklens_mcp.data.metric_lineage. `provenance_available: false` means the
// bank/quarter's Silver row was built without a Bronze provenance reference
// (a disclosed gap, e.g. EU/EBA rows or a legacy un-provenanced landing).
export interface MetricLineageSourceField {
  silver_field: string;
  fdic_field: string;
  value: number | null;
}

export interface MetricLineageResult {
  cert: number;
  metric: string;
  quarter: string | null;
  gold_function: string;
  formula: string;
  metric_value: number | null;
  source_fields: MetricLineageSourceField[];
  bronze_partition: string | null;
  checksum: string | null;
  fetched_at: string | null;
  source_url: string | null;
  provenance_available: boolean;
}

// B7: FDIC's Summary of Deposits is landed annually, so every branch-derived
// figure (footprints, county HHI, the branch map, M&A geo-overlap) can be up
// to ~18 months stale relative to a quarterly financial figure — every tool
// response that touches SOD data carries this, not just one hardcoded string.
export interface SodVintage {
  sod_year: number | null;
  fetched_at: string | null;
}

export interface BankSummary {
  cert: number;
  name: string;
  state: string | null;
  country: string | null;
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
  country: string | null;
  quarter: string;
  assets_b: number;
  uninsured_deposit_pct: number | null;
  loan_to_deposit_pct: number | null;
  cre_concentration_pct: number | null;
  cet1_ratio: number | null;
  leverage_ratio: number | null;
  peer_cluster: string | null;
  // C11 — which population every "percentile" field below is computed against.
  peer_basis: 'global' | 'size' | 'cluster';
  footprint: {
    branch_count: number;
    total_deposits: number;
    centroid: [number, number] | null;
    geo_basis: 'county' | 'grid';
    states: string[];
    county_count: number;
    sod_vintage: SodVintage;
  } | null;
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
  // C8 — credit-quality trend/acceleration, not just today's level.
  credit_trajectory: {
    npl_ratio_pct: MetricPctile;
    npl_trend_pp_per_qtr: number | null;
    npl_acceleration: number | null;
    net_charge_off_rate_pct: MetricPctile;
    net_charge_off_trend_pp_per_qtr: number | null;
    allowance_coverage_pct: MetricPctile;
    allowance_coverage_trend_pp_per_qtr: number | null;
    deterioration_flag: boolean;
    deterioration_signal_count: number;
    deterioration_signals_available: number;
    trajectory_quarters: number;
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
  // C11 — 'within_cluster' (default, a behaviorally-similar peer group) or
  // 'global' (fallback when this bank has no cluster assignment).
  peer_percentile_basis?: 'within_cluster' | 'global';
}

export interface XrayResult {
  cert_number: number;
  name: string;
  quarter: string;
  overall_risk: 'low' | 'elevated' | 'high';
  flag_count: number;
  flags: XrayFlag[];
  // Coverage: `overall_risk` is only as complete as `rules_evaluated`. EU/EBA banks
  // disclose far less than US Call Reports, so a low flag count there reflects fewer
  // checks run, not necessarily a safer bank.
  rules_evaluated: number;
  rules_total: number;
  rules_not_evaluated: string[];
  fully_assessed: boolean;
  key_metrics: {
    uninsured_deposit_pct: number | null;
    loan_to_deposit_pct: number | null;
    max_loan_concentration: { category: string | null; pct: number | null };
    cet1_ratio: number | null;
    leverage_ratio: number | null;
  };
}

// D4 — holding-company roll-up (B4's Fed NIC FR Y-9C data).
export interface SiblingCharter {
  cert: number;
  name: string;
  total_assets: number | null;
}

export interface HoldingCompanyResult {
  cert: number;
  name: string;
  has_holding_company: boolean;
  holding_company_rssd?: number;
  sibling_charters?: SiblingCharter[];
  charter_level?: { total_assets: number | null; cet1_ratio: number | null; leverage_ratio: number | null };
  holding_company?: {
    rssd: number;
    period: string;
    name: string | null;
    short_name: string | null;
    total_assets: number | null;
    total_liabilities: number | null;
    total_equity_capital: number | null;
    risk_weighted_assets: number | null;
    tier1_capital: number | null;
    total_capital: number | null;
    net_income: number | null;
    goodwill: number | null;
    cet1_ratio: number | null;
    tier1_capital_ratio: number | null;
    total_capital_ratio: number | null;
    tier1_leverage_ratio: number | null;
  } | null;
  note?: string;
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
  sod_vintage: SodVintage;
}

// C9 — M&A pro-forma calculator.
export interface MaCountyImpact {
  fips: string;
  name: string | null;
  state: string | null;
  hhi_before: number | null;
  hhi_after: number | null;
  crosses_threshold: boolean;
  already_above_threshold: boolean;
}

export interface MaProFormaResult {
  target: { cert: number; name: string; total_assets: number; tangible_book_value: number };
  acquirer: { cert: number; name: string; total_assets: number; tangible_book_value: number };
  assumptions: {
    premium_to_tbv_pct: number;
    cost_synergies_pct_of_target_opex: number;
    tax_rate_pct: number;
  };
  combined: {
    combined_assets: number;
    deal_price: number;
    goodwill_created: number;
    combined_cet1_ratio_pct: number | null;
    tangible_book_value_dilution_pct: number | null;
    annual_synergy_after_tax: number;
    earn_back_years: number | null;
  };
  note: string;
  county_impact: {
    sod_vintage: SodVintage;
    hhi_concentrated_threshold: number;
    counties_affected: number;
    counties_crossing_threshold: number;
    counties: MaCountyImpact[];
  };
}

export interface MaWeightDeal {
  target_cert: number;
  acquirer_cert: number;
  target_name: string;
  acquirer_name: string;
  fail_year: string;
  acquirer_percentile: number;
}

export interface MaWeightQuarterResult {
  n_matched_deals: number;
  n: number;
  mean_percentile: number | null;
  median_percentile: number | null;
  deals: MaWeightDeal[];
}

export interface MaWeightValidationResult {
  default_weights: { funding: number; business: number; size: number; geo: number };
  overall_mean_percentile: number | null;
  n_deals_total: number;
  per_quarter: Record<string, MaWeightQuarterResult>;
  refit: Record<string, { weights: Record<string, number> | null; n: number; mean_percentile: number | null }>;
  // Deal-count-weighted DEFAULT-vs-REFIT comparison — this drives `decision`,
  // not best_refit_mean_percentile (a small-n quarter can top that by chance).
  weighted_default_mean_percentile: number | null;
  weighted_refit_mean_percentile: number | null;
  weighted_n: number;
  best_refit_weights: Record<string, number> | null;
  best_refit_mean_percentile: number | null;
  margin_pp: number;
  decision: 'refit' | 'default';
  note: string;
}

// C10 — X-Ray forward-return validation.
export interface XraySeverityStats {
  n: number;
  mean: number | null;
  stdev: number | null;
}

export interface XrayValidationResult {
  horizon_trading_days: number;
  tickers_with_landed_price_data: number;
  quarters_covered: string[];
  by_severity: { low: XraySeverityStats; elevated: XraySeverityStats; high: XraySeverityStats };
  high_vs_low_spread_pp: number | null;
  z_score: number | null;
  p_value: number | null;
  significant_at_05: boolean;
  n_total: number;
  note: string;
}

// C14 — backtest harness.
export interface BacktestRate {
  point: number | null;
  lo: number | null;
  hi: number | null;
}

export interface BacktestOutcome {
  label: string;
  flagged_hits: number;
  flagged_n: number;
  flagged_hit_rate: BacktestRate;
  base_hits: number;
  base_n: number;
  base_hit_rate: BacktestRate;
  lift: number | null;
}

export interface BacktestResults {
  quarters_covered: string[];
  n_transitions: number;
  horizon_quarters: number;
  signal_definitions: Record<string, string>;
  results: Record<string, Record<string, BacktestOutcome>>;
  note: string;
}

export interface StressRatios {
  cet1: number;
  tier1: number;
  total: number;
  leverage: number;
}

// F6 — before/after ratios are null when the underlying denominator (RWA /
// leverage exposure) wasn't disclosed for this bank, rather than a
// fabricated 0.00% that would silently fail the regulatory minimum on a
// number that was never actually computed.
export interface StressRatiosOrNull {
  cet1: number | null;
  tier1: number | null;
  total: number | null;
  leverage: number | null;
}

export interface StressResult {
  name: string;
  quarter: string;
  shock: Record<string, number | boolean>;
  before: StressRatiosOrNull;
  after: StressRatiosOrNull;
  minimums: StressRatios;
  // Only ratios that were actually computed appear here — a ratio with no
  // disclosed denominator has no entry at all (not `false`).
  passes: Partial<Record<keyof StressRatios, boolean>>;
  // null when NONE of the four ratios could be computed (nothing to assess),
  // distinct from a real pass/fail verdict over whatever WAS computed.
  passes_all: boolean | null;
  // Which of the four ratios (if any) couldn't be computed at all.
  ratios_not_computed: (keyof StressRatios)[];
  // Non-empty when a requested shock leg could not be applied because the driving
  // input isn't disclosed for this bank (e.g. EU/EBA banks report no deposit total,
  // so a deposit-run leg is skipped). When present, `passes_all` reflects FEWER
  // shocks than were asked for and must not be read as a clean pass.
  legs_not_applied: { leg: string; reason: string; requested_pct?: number; requested_bps?: number }[];
  fully_covered: boolean;
  capital_waterfall: {
    loan_loss: number;
    // C6: non-empty only when the scenario used per-category loan-loss rates
    // (run_segmented_stress_test) — decomposes loan_loss by category.
    loan_loss_by_category: Record<string, number>;
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
  // E3 — the real starting/ending capital DOLLARS behind before/after's ratios
  // (already computed server-side, previously unreturned) — what a capital-bridge
  // waterfall needs to show "starting CET1 -> stressed CET1" without inventing a
  // number. Optional: only present from stress-test/-compare/-bulk callers that
  // run the C4-era engine (every current one does; the `?` guards older cached data).
  capital_dollars?: {
    cet1_before: number; cet1_after: number;
    tier1_before: number; tier1_after: number;
    total_before: number; total_after: number;
  };
  // C4: which duration each rate-shock leg actually used — 'disclosed' (real
  // FDIC maturity data, not yet landed by any connector), 'fallback_default'
  // (the flat 4y/6y assumption), or 'user_override' (an explicit slider value).
  duration_sources?: {
    afs: 'disclosed' | 'fallback_default' | 'user_override';
    htm: 'disclosed' | 'fallback_default' | 'user_override';
    afs_duration_used: number;
    htm_duration_used: number;
  };
  correlated_severity?: 'mild' | 'moderate' | 'severe';
  derived_shock?: { loan_loss_pct: number; deposit_outflow_pct: number; rate_shock_bps: number };
}

// C4 — multi-period projection: the shock phased in over a horizon, with
// disclosed PPNR earning back part of each period's loss.
export interface StressProjectionPeriod {
  quarter_offset: number;
  shock_fraction_applied: number;
  gross_capital_hit: number;
  ppnr_offset_applied: number;
  net_capital_hit: number;
  after: StressRatiosOrNull;
  passes: Partial<Record<keyof StressRatios, boolean>>;
  passes_all: boolean | null;
  ratios_not_computed: (keyof StressRatios)[];
}

export interface StressProjectionResult {
  name: string;
  quarter: string;
  horizon_quarters: number;
  phase_in: boolean;
  ppnr_offset_applied: boolean;
  ppnr_quarterly_estimated: number | null;
  path: StressProjectionPeriod[];
  breach_quarter: number | null;
  survives_full_horizon: boolean;
}

// C4 — quarters of on-balance-sheet liquidity under a SUSTAINED (not one-time)
// quarterly deposit-outflow rate.
export interface LiquiditySurvivalResult {
  applicable: boolean;
  reason?: string;
  quarters_survived: number | null;
  breach_quarter: number | null;
  max_quarters_checked?: number;
  quarterly_outflow_pct?: number;
}

export type CorrelatedStressResult = StressResult;

// C5 — Interest Rate Risk in the Banking Book (EVE / NII sensitivity).
export interface IrrbbScenario {
  scenario: 'parallel' | 'steepener';
  shock_bps?: number;
  short_bps?: number;
  long_bps?: number;
  eve_delta: number;
  eve_delta_pct_of_equity: number | null;
  nii_delta_12mo: number;
}

export interface IrrbbResult {
  name: string;
  quarter: string;
  parallel: IrrbbScenario;
  non_parallel: IrrbbScenario;
  inputs: {
    securities_total: number;
    securities_blended_duration_years: number;
    securities_duration_source: 'disclosed' | 'fallback_default';
    loans_total: number;
    loans_assumed_duration_years: number;
    deposits_total: number;
    deposits_assumed_duration_years: number;
  };
  bucket_coarseness: string;
}

export interface RiskDriver {
  feature: string;
  value: number;
  contribution: number;
}

export interface RiskScoreResult {
  risk_score: number;
  // C1: risk_score is the model's raw sigmoid output, not a calibrated
  // probability of failure — see the model card's calibration_curve. Every
  // UI surface should display resemblance_percentile/_decile instead.
  resemblance_percentile: number | null;
  resemblance_decile: number | null;
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
  // C12 — how many historical same-span observations the z was computed from.
  n: number;
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
  // C12 — sample size behind z, why z is null below MIN_OBSERVATIONS, and the
  // (bank-typical-magnitude-scaled) materiality floor actually applied.
  n: number;
  z_reason: string | null;
  materiality_floor?: number;
  direction: 'up' | 'down' | null;
  flagged: boolean;
  note: string;
}

export interface FilingDiffResult {
  cert: number | null;
  name: string;
  from_quarter: string;
  to_quarter: string;
  span_quarters: number;
  n_flags: number;
  flags: FilingDiffFlag[];
  line_items: FilingDiffLineItem[];
}

// C13 — population-level multiple-testing context.
export interface FilingDiffFdrFlag {
  cert: number | null;
  name: string | null;
  item: string;
  metric: string;
  change: number;
  unit: string;
  z: number;
  p: number;
  flagged_raw: boolean;
}

export interface FilingDiffPopulationSummary {
  quarters_available: string[];
  n_banks_diffed: number;
  n_banks_skipped_insufficient_history: number;
  n_tests: number;
  z_threshold: number;
  raw_flag_count: number;
  expected_false_positives_at_threshold: number;
  fdr_alpha: number;
  fdr_flag_count: number;
  fdr_flags: FilingDiffFdrFlag[];
  note: string;
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
  // C3: 'fixed' when peer_cluster_label above comes from persisted reference-
  // quarter centroids; 'refit' fallback if none are persisted yet.
  cluster_mode: 'fixed' | 'refit';
}

// E10 — same per-bank shape get_bank_trends returns, for a whole peer set at
// once. `skipped` mirrors compare_banks/run_bulk_stress_test's pattern for
// certs with no landed history in any quarter.
export interface BulkBankTrendsBank {
  cert: number;
  name: string;
  quarters: string[];
  series: BankTrendPoint[];
}

export interface BulkBankTrendsResult {
  metrics: string[];
  quarters: string[];
  cluster_mode: 'fixed' | 'refit';
  requested: number;
  banks: BulkBankTrendsBank[];
  skipped: { cert: number; reason: string }[];
}

// E12 — batched trailing-quarter series for a table's sparkline column
// (screener/earnings/credit/funding). Every bank's `values[metric]` array is
// aligned 1:1 to `quarters` (null where that bank has no landed row that
// quarter) so a caller never has to reconcile a per-bank offset.
export interface PopulationTrendSparklinesResult {
  metrics: string[];
  quarters: string[];
  requested: number;
  banks: { cert: number; values: Record<string, (number | null)[]> }[];
  skipped: { cert: number; reason: string }[];
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
  resemblance_percentile: number | null;
  resemblance_decile: number | null;
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
    // C3: "fixed_centroids" when a reference-quarter fit is persisted (the
    // real migration signal); "refit" fallback otherwise.
    method: 'fixed_centroids' | 'refit';
    refit_comparison: {
      fixed_centroids_available: boolean;
      refit_migration_count?: number;
      fixed_migration_count?: number;
      refit_only_count?: number;
      note: string;
    };
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
  resemblance_percentile: number | null;
  resemblance_decile: number | null;
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
  note: string | null;
}

// D2 — threshold rules on a watched bank, evaluated after every quarterly
// refresh (see pipelines/orchestration/src/banklens_orchestration/alerts_cli.py).
export type WatchlistRuleType =
  'metric_threshold' | 'metric_delta' | 'xray_severity_increase' | 'risk_leaderboard_entry';

export interface WatchlistRule {
  id: number;
  user_sub: string;
  cert: number;
  rule_type: WatchlistRuleType;
  metric: string | null;
  operator: 'gt' | 'lt' | null;
  threshold: number | null;
  top_n: number | null;
  created_at: string;
}

export interface SavedScreen {
  id: number;
  name: string;
  filters: Record<string, string | number | undefined>;
  created_at: string;
}

// D5 — named, persisted peer sets.
export interface PeerSetItem {
  id: number;
  name: string;
  certs: number[];
  created_at: string;
}

// D7 — analyst annotations, shared across users for one bank.
export interface AnnotationItem {
  id: number;
  user_sub: string;
  cert: number;
  quarter: string | null;
  note_md: string;
  created_at: string;
}

// D10 — named scenario registry + user-saved custom scenarios.
export interface NamedScenario {
  id: string;
  name: string;
  description: string;
  loan_loss_pct: number;
  deposit_outflow_pct: number;
  rate_shock_bps: number;
  assumptions: string;
  provenance: string;
}

export interface ScenarioLibraryResult {
  version: number;
  scenarios: NamedScenario[];
}

export interface CustomScenarioItem {
  id: number;
  name: string;
  loan_loss_pct: number;
  deposit_outflow_pct: number;
  rate_shock_bps: number;
  created_at: string;
}

// D11 — exposure/portfolio positions.
export interface PortfolioPosition {
  id: number;
  cert: number;
  exposure_amount: number;
  exposure_type: string;
  created_at: string;
}

export interface PortfolioBankSummary {
  cert: number;
  name: string;
  exposure: number;
  xray_severity: 'low' | 'elevated' | 'high' | null;
  risk_resemblance_percentile: number | null;
}

export interface PortfolioStressSummary {
  scenario: Record<string, unknown>;
  exposure_passing: number;
  exposure_failing: number;
  exposure_untested: number;
}

export interface PortfolioSummaryResult {
  positions: number;
  total_exposure: number;
  banks: PortfolioBankSummary[];
  exposure_weighted_xray_severity?: 'low' | 'elevated' | 'high' | null;
  exposure_weighted_risk_resemblance_percentile?: number | null;
  concentration_by_cluster?: Record<string, number>;
  concentration_by_state?: Record<string, number>;
  stress_summary?: PortfolioStressSummary | null;
}

export interface AlertItem {
  id: number;
  cert: number;
  rule_id: number | null;
  message: string;
  quarter: string | null;
  triggered_at: string;
  seen: boolean;
}

export interface AuditLogEntry {
  id: number;
  ts: string;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  latency_ms: number;
  requester: string;
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
  // D12 — deep link to the frontend page that shows the data this call
  // returned, so a claim in the answer can be verified in place; null when
  // no single page is an obvious home for that tool's result.
  citation_url: string | null;
}

// D12 — one earlier turn of the conversation, as sent to/from
// /api/assistant/ask's `history` field (see bridge_server.py's
// _assistant_ask_sse for the exact shape it accepts and echoes back).
export interface AssistantHistoryTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface AssistantResult {
  persona: string;
  question: string;
  answer: string;
  provider: string;
  turns: number;
  // F16 — true when the answer came back because the server-side deadline
  // (BANKLENS_ASSISTANT_DEADLINE_S) was reached, not because the model
  // actually finished reasoning — see AssistantPage's partial-answer banner.
  partial: boolean;
  roles: string[];
  effective_tools: string[];
  tool_calls: ToolCallRecord[];
  // D12 — this turn's question/answer appended to whatever `history` was
  // sent in; pass straight back as `history` on the next ask() call to keep
  // the conversation's context across a follow-up question.
  history: AssistantHistoryTurn[];
}

// F16 — POST /api/assistant/ask now streams Server-Sent Events instead of
// returning one JSON blob; see api.ts's streamAssistantAsk. Payload shape
// per event kind mirrors bridge_server.py's _sse_line call sites exactly.
export type AssistantStreamEvent =
  | { event: 'tool_call'; data: { name: string; input: Record<string, unknown>; repeat?: boolean } }
  | { event: 'tool_result'; data: { name: string; preview: string; citation_url: string | null } }
  | { event: 'final'; data: string }
  | { event: 'timeout'; data: { message: string } }
  | { event: 'error'; data: { error: string; request_id?: string } }
  | { event: 'result'; data: AssistantResult };

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
  // D5 — non-null when `certs` restricted this to a peer set; percentiles
  // are then computed WITHIN that set, not the full population.
  peer_set_size?: number | null;
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
  /** Every Gold metric with a computed percentile_rank_<metric> — the real,
   * server-side catalog a metric picker should be built from (not a
   * hand-duplicated frontend list, which could drift from what's actually
   * computed). */
  available_metrics: string[];
  // D5 — non-null when `certs` restricted this to a peer set.
  peer_set_size?: number | null;
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
  group_by: 'peer_cluster_label' | 'state' | 'country';
  groups: TreemapGroup[];
}

export interface MetricDistributionResult {
  metric: string;
  quarter: string;
  count: number;
  // D5 — non-null when `certs` restricted this to a peer set.
  peer_set_size?: number | null;
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

// ---- cluster + model governance ----

export interface SilhouetteByK {
  k: number;
  silhouette: number;
  max_share: number;
}

export interface ClusterCentroid {
  cluster_id: number;
  label: string;
  size: number;
  centroid: Record<string, number>;
}

export interface SizeBucketSummary {
  bucket: string;
  size: number;
  modal_behavioral_cluster: string;
  modal_share: number;
  mismatch_count: number;
}

export interface ClusterMismatch {
  cert: number;
  name: string;
  conventional_bucket: string;
  bucket_modal_cluster: string;
  behavioral_cluster: string;
  assets_b: number;
}

export interface ClusterDiagnosticsResult {
  quarter: string;
  served_k: number;
  silhouette_by_k: SilhouetteByK[];
  centroids: ClusterCentroid[];
  size_bucket_summary: SizeBucketSummary[];
  sample_mismatches: ClusterMismatch[];
}

export interface ModelCardPositive {
  cert: number;
  name: string;
}

export interface ModelCardExcludedCandidate {
  cert: number;
  name: string;
  reason: string;
}

export interface ModelCardLeaveOneOut {
  cert: number;
  name: string;
  risk: number;
  rank: number;
  n: number;
  percentile: number;
}

export interface ModelCardDriverPoint {
  cert: number;
  name: string;
  feature: string;
  value: number;
  contribution: number;
  risk_score: number;
}

export interface ModelCardCI {
  lo: number | null;
  median: number | null;
  hi: number | null;
}

export interface ModelCardBootstrap {
  n_boot: number;
  n_boot_used: number;
  coefficients: Record<string, ModelCardCI>;
  bias: ModelCardCI;
  auc: ModelCardCI;
}

export interface ModelCardPrPoint {
  threshold: number;
  precision: number | null;
  recall: number | null;
  tp: number;
  fp: number;
}

export interface ModelCardCalibrationPoint {
  mean_predicted: number;
  observed_rate: number;
  n: number;
}

export interface ModelCardRocPoint {
  threshold: number | null;
  fpr: number;
  tpr: number;
  tp: number;
  fp: number;
}

export interface ModelCardResult {
  features: string[];
  weights: number[];
  bias: number;
  auc: number;
  trained_on: string;
  positives: ModelCardPositive[];
  excluded_candidates: ModelCardExcludedCandidate[];
  training_exclusions: DataQualityDisclosure;
  leave_one_out: ModelCardLeaveOneOut[];
  scored_quarter: string;
  driver_points: ModelCardDriverPoint[];
  imputation_rates: Record<string, number>;
  bootstrap: ModelCardBootstrap | null;
  pr_curve: ModelCardPrPoint[];
  roc_curve: ModelCardRocPoint[];
  calibration_curve: ModelCardCalibrationPoint[];
}

// ---- geography + market share ----

export interface CountyShare {
  cert: number;
  name: string;
  deposits: number;
  share_pct: number;
}

export interface CountyConcentration {
  fips: string;
  name: string | null;
  state: string | null;
  branch_count: number;
  total_deposits: number;
  hhi: number | null;
  concentrated: boolean;
  shares: CountyShare[];
}

export interface CountyConcentrationResult {
  as_of: string;
  sod_vintage: SodVintage;
  hhi_concentrated_threshold: number;
  county_count: number;
  concentrated_count: number;
  counties: CountyConcentration[];
}

export interface BranchPoint {
  cert: number;
  lat: number;
  lon: number;
  deposits: number;
  fips: string | null;
}

// F9 — server-side county/grid aggregate, returned instead of individual
// BranchPoints for the default (no-state) national view.
export interface BranchCell {
  fips: string | null;
  lat: number;
  lon: number;
  branch_count: number;
  deposits: number;
}

export interface BranchMapResult {
  aggregated: boolean;
  branch_count: number;
  excluded_non_contiguous: number;
  bank_names: Record<number, string>;
  branches: BranchPoint[];
  cells: BranchCell[];
  sod_vintage: SodVintage;
}

// ---- M&A network + stress lab ----

export interface NetworkNode {
  cert: number;
  name: string;
  assets_b: number;
  cluster_id: number | null;
  cluster_label: string | null;
  is_seed: boolean;
}

export interface NetworkEdge {
  source: number;
  target: number;
  fit_score: number;
}

export interface NetworkGraphResult {
  quarter: string;
  seed_count: number;
  nodes: NetworkNode[];
  edges: NetworkEdge[];
}

export interface BulkStressSkip {
  cert: number;
  name: string | null;
  reason: string;
}

export interface BulkStressBankResult extends StressResult {
  cert: number;
}

export interface BulkStressResult {
  shock: Record<string, number | boolean>;
  requested: number;
  tested: number;
  skipped: BulkStressSkip[];
  fail_count: number;
  results: BulkStressBankResult[];
}

// E3 — (deposit_outflow x rate_shock) grid for one bank, loan_loss_pct held
// fixed. Powers the Stress Lab's CET1 surface heatmap.
export interface StressSurfaceCell {
  deposit_outflow_pct: number;
  rate_shock_bps: number;
  cet1_after: number | null;
  passes_cet1: boolean | undefined;
}

export interface StressSurfaceResult {
  cert: number;
  name: string;
  quarter: string;
  loan_loss_pct: number;
  deposit_outflow_values: number[];
  rate_shock_values: number[];
  steps: number;
  cells: StressSurfaceCell[];
  cet1_minimum_pct: number;
  // True if any cell fell back to the flat 4y/6y AFS/HTM duration assumption
  // (no per-bank maturity data disclosed) rather than a disclosed duration.
  fallback_duration_used: boolean;
  // Same disclosure contract as StressResult.legs_not_applied, collected once
  // across the whole grid rather than repeated per cell.
  legs_not_applied: { leg: string; reason: string; requested_pct?: number; requested_bps?: number }[];
}

export interface StressComparisonResult {
  cert: number;
  name: string;
  linear: StressResult & { pricing_engine: string };
  quantlib: StressResult & { pricing_engine: string };
}

// ---- filings RAG search ----

export interface FilingSearchResult {
  cik: number;
  cert: number | null;
  ticker: string | null;
  name: string;
  accession: string;
  filing_date: string;
  report_date: string;
  extraction_confidence: string;
  chunk_index: number;
  chunk_text: string;
  similarity: number;
}

export interface FilingSearchResponse {
  query: string;
  count: number;
  results: FilingSearchResult[];
}

export interface FilingsCoverageResult {
  filers: number;
  chunks: number;
  by_confidence: Record<string, number>;
}

export interface MarketCoverageResult {
  eligible: number;
  landed: number;
  coverage_pct: number;
  oldest_bar_age_days: number | null;
  updated_at: string | null;
  landed_yet: boolean;
}

// ---- E2: cross-bank market view (/market) ----

export interface MarketOverviewBank {
  cert: number;
  name: string;
  ticker: string | null;
  has_price_data: boolean;
}

export interface MarketRebasedPoint {
  date: string;
  value: number;
}

export interface MarketPerformanceSeries {
  cert: number;
  name: string;
  ticker: string | null;
  series: MarketRebasedPoint[];
}

export interface MarketScatterPoint {
  cert: number;
  name: string;
  return_pct: number | null;
  volatility_pct: number | null;
}

export interface MarketCorrelationMatrix {
  certs: number[];
  labels: string[];
  /** Pairwise Pearson correlation of daily returns; null where fewer than 10 shared trading days. */
  matrix: (number | null)[][];
}

export interface MarketMetricsRow {
  cert: number;
  name: string;
  ticker: string | null;
  total_return_pct: number | null;
  realized_volatility_pct: number | null;
  vol_vs_peer_median_pct: number | null;
  max_drawdown_pct: number | null;
  /** Beta vs an equal-weighted basket of every priced bank in view — see MarketOverviewResult.benchmark. */
  beta_vs_peer_basket: number | null;
  tangible_book_value_usd: number | null;
  /** Always null today — see MarketOverviewResult.per_share_metrics_note. */
  price_to_tangible_book_value: number | null;
  /** Always null today — see MarketOverviewResult.per_share_metrics_note. */
  price_to_earnings: number | null;
  bars_used: number;
}

export interface MarketOverviewResult {
  quarter: string;
  window_days: number;
  requested_count: number;
  priced_count: number;
  coverage_note: string;
  banks: MarketOverviewBank[];
  performance_series: MarketPerformanceSeries[];
  scatter: MarketScatterPoint[];
  correlation: MarketCorrelationMatrix;
  metrics: MarketMetricsRow[];
  benchmark: 'equal_weighted_peer_basket';
  per_share_metrics_available: false;
  per_share_metrics_note: string;
}
