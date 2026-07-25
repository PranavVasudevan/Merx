import type {
  BankProfile, FilingDiffResult, MaFitResult, PeerClusterResult,
  PopulationBank, RiskScoreResult, StressResult, XrayResult,
} from './types';

const BASE = 'http://localhost:8791/api';

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&');
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ''}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface BankSearchResult { count: number; banks: { cert: number; name: string; state: string | null; assets_b: number; cluster: string | null }[] }

export const api = {
  health: () => get<{ status: string }>('/health'),
  population: () => get<{ banks: PopulationBank[] }>('/population'),
  searchBanks: (query?: string, state?: string, limit = 30) =>
    get<BankSearchResult>('/banks', { query, state, limit }),
  profile: (cert: number) => get<BankProfile>('/banks/profile', { cert }),
  xray: (cert: number) => get<XrayResult>('/banks/xray', { cert }),
  peerCluster: (cert: number) => get<PeerClusterResult>('/banks/peer-cluster', { cert }),
  maFit: (cert: number, top_n = 8) => get<MaFitResult>('/banks/ma-fit', { cert, top_n }),
  stressTest: (cert: number, loan_loss_pct: number, deposit_outflow_pct: number, rate_shock_bps: number) =>
    get<StressResult>('/banks/stress-test', { cert, loan_loss_pct, deposit_outflow_pct, rate_shock_bps }),
  filingDiff: (cert: number) => get<FilingDiffResult>('/banks/filing-diff', { cert }),
  riskScore: (cert: number) => get<RiskScoreResult>('/banks/risk-score', { cert }),
};
