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

export interface FilingDiffResult {
  name: string;
  from_quarter: string;
  to_quarter: string;
  span_quarters: number;
  n_flags: number;
  flags: FilingDiffFlag[];
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
