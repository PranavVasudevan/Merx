import { MetricGroupPage } from '../components/MetricGroupPage';

function fmtTrend(v: number | string | null): string {
  if (v === null || typeof v !== 'number') return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(3)}pp/qtr`;
}

function fmtSignalCount(v: number | string | null): string {
  if (v === null || typeof v !== 'number') return '—';
  return `${v} of 3`;
}

// npl_ratio_pct uses noncurrent LOANS (NCLNLS) over gross loans — deliberately not
// FDIC's asset-level P3ASSET/P9ASSET past-due fields, which would be a unit mismatch
// against a loan denominator. See banklens_transforms.gold.npl_ratio_pct.
const COLUMNS = [
  { key: 'npl_ratio_pct', label: 'NPL ratio' },
  { key: 'net_charge_off_rate_pct', label: 'Net charge-off rate' },
  { key: 'allowance_to_loans_pct', label: 'Allowance / loans' },
  { key: 'allowance_coverage_pct', label: 'Allowance / NPL' },
  { key: 'texas_ratio_pct', label: 'Texas Ratio' },
  // C8 — trend/acceleration, not just where a bank sits today.
  { key: 'npl_trend_pp_per_qtr', label: 'NPL trend', format: fmtTrend },
  { key: 'npl_acceleration', label: 'NPL acceleration', format: fmtTrend },
  { key: 'net_charge_off_trend_pp_per_qtr', label: 'NCO trend', format: fmtTrend },
  { key: 'allowance_coverage_trend_pp_per_qtr', label: 'Allowance coverage trend', format: fmtTrend },
  { key: 'deterioration_signal_count', label: 'Deterioration signals', format: fmtSignalCount },
];

export function CreditPage() {
  return (
    <MetricGroupPage
      group="credit"
      title="Credit quality"
      subtitle="Asset quality across the population: noncurrent loans, net charge-offs, reserve adequacy, and the Texas Ratio — troubled assets against the capital and reserves available to absorb them. Trend/acceleration columns (C8) rank by DETERIORATION, not just level: NPL/NCO trending up and allowance coverage trending down, together, over the bank's own landed history."
      columns={COLUMNS}
      defaultSort="deterioration_signal_count"
      highlightLabel="Fastest-deteriorating credit quality (multiple adverse signals moving together)"
    />
  );
}
