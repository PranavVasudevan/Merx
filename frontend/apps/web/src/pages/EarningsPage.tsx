import { MetricGroupPage } from '../components/MetricGroupPage';
import { usd } from '../metricFormat';

// FDIC's own performance ratios (NIMY/ROA/ROE/EEFFR) are YEAR-TO-DATE ANNUALIZED —
// stated on the page itself, since that caveat is easy to lose sight of when scanning
// a ranked table.
const COLUMNS = [
  { key: 'roa_pct', label: 'ROA' },
  { key: 'roe_pct', label: 'ROE' },
  { key: 'net_interest_margin_pct', label: 'NIM' },
  { key: 'efficiency_ratio_pct', label: 'Efficiency' },
  { key: 'noninterest_income_share_pct', label: 'Fee income %' },
  { key: 'net_interest_income', label: 'Net interest income', format: usd },
];

export function EarningsPage() {
  return (
    <MetricGroupPage
      group="earnings"
      title="Earnings"
      subtitle="Profitability across the $1B–$250B population: return on assets/equity, net interest margin, operating efficiency, and how much of revenue is fee income versus the lending spread."
      columns={COLUMNS}
      defaultSort="roa_pct"
      highlightLabel="Highest return on assets"
    />
  );
}
