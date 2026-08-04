import { MetricGroupPage } from '../components/MetricGroupPage';

// Deliberately not framed as "liquidity" — FDIC's summary data has no LCR/NSFR and no
// FHLB-advances field (probed and confirmed absent). This is funding COMPOSITION:
// how much of the deposit base is stable versus rate-sensitive/wholesale.
const COLUMNS = [
  { key: 'uninsured_deposit_pct', label: 'Uninsured deposits' },
  { key: 'brokered_deposit_pct', label: 'Brokered deposits' },
  { key: 'large_denomination_deposit_pct', label: 'Large-denomination' },
  { key: 'time_deposit_pct', label: 'Time deposits' },
  { key: 'volatile_liability_pct', label: 'Volatile liabilities' },
  { key: 'loan_to_deposit_pct', label: 'Loan / deposit' },
];

export function FundingPage() {
  return (
    <MetricGroupPage
      group="funding"
      title="Funding & deposit composition"
      subtitle="The SVB/Signature story, quantified: uninsured reliance, brokered and large-denomination deposits, and how much of the loan book is funded beyond the deposit base. Not a liquidity-coverage view — FDIC's summary data has no LCR/NSFR or FHLB-borrowings figures."
      columns={COLUMNS}
      defaultSort="uninsured_deposit_pct"
      highlightLabel="Highest uninsured-deposit reliance"
    />
  );
}
