import { MetricGroupPage } from '../components/MetricGroupPage';

// npl_ratio_pct uses noncurrent LOANS (NCLNLS) over gross loans — deliberately not
// FDIC's asset-level P3ASSET/P9ASSET past-due fields, which would be a unit mismatch
// against a loan denominator. See banklens_transforms.gold.npl_ratio_pct.
const COLUMNS = [
  { key: 'npl_ratio_pct', label: 'NPL ratio' },
  { key: 'net_charge_off_rate_pct', label: 'Net charge-off rate' },
  { key: 'allowance_to_loans_pct', label: 'Allowance / loans' },
  { key: 'allowance_coverage_pct', label: 'Allowance / NPL' },
  { key: 'texas_ratio_pct', label: 'Texas Ratio' },
];

export function CreditPage() {
  return (
    <MetricGroupPage
      group="credit"
      title="Credit quality"
      subtitle="Asset quality across the population: noncurrent loans, net charge-offs, reserve adequacy, and the Texas Ratio — troubled assets against the capital and reserves available to absorb them."
      columns={COLUMNS}
      defaultSort="texas_ratio_pct"
      highlightLabel="Highest Texas Ratio (troubled assets vs. loss-absorbing capacity)"
    />
  );
}
