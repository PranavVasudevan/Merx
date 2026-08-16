// D14 — glossary fed by a single source of truth, used by both the hover/
// click GlossaryTerm affordance and the standalone /glossary page.
export interface GlossaryEntry {
  key: string;
  label: string;
  definition: string;
  formula: string;
  source_field: string;
  why_it_matters: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    key: 'texas_ratio',
    label: 'Texas Ratio',
    definition: "A rough early-warning measure of how much of a bank's capital cushion its troubled assets could consume.",
    formula: '(Nonperforming assets + loans 90+ days past due) / (Tangible common equity + loan loss reserves)',
    source_field: 'FDIC Call Report Schedule RC-N (past-due/nonaccrual) and RC (equity, reserves)',
    why_it_matters: 'A ratio above ~100% historically correlates with elevated failure risk (used informally since the 1980s Texas banking crisis) — it is a screening heuristic, not a regulatory capital measure.',
  },
  {
    key: 'cblr',
    label: 'CBLR (Community Bank Leverage Ratio)',
    definition: 'An optional, simplified capital framework a qualifying community bank can elect instead of full risk-based capital rules.',
    formula: 'Tier 1 capital / average total consolidated assets, must exceed the regulatory threshold to qualify',
    source_field: 'FDIC Call Report Schedule RC-R Part I',
    why_it_matters: 'A CBLR electer reports zero/blank risk-weighted-asset fields — reading those as thin capital would be a false flag, not a real one.',
  },
  {
    key: 'hhi',
    label: 'HHI (Herfindahl-Hirschman Index)',
    definition: 'A standard concentration measure: the sum of squared market shares of every competitor in a market.',
    formula: 'Sum over banks in a county of (deposit market share %)^2',
    source_field: 'FDIC Summary of Deposits, aggregated to county (FIPS)',
    why_it_matters: 'The Federal Reserve and DOJ use HHI ≥ 1800 as their own screening threshold for a bank-merger competitive review — the same threshold this product highlights.',
  },
  {
    key: 'brokered_deposits',
    label: 'Brokered deposits',
    definition: "Deposits placed by a third-party broker rather than sourced directly from the depositor's own relationship with the bank.",
    formula: 'Reported directly by the bank, as a $ total',
    source_field: 'FDIC Call Report Schedule RC-E',
    why_it_matters: "Brokered funding is generally considered less \"sticky\" than core deposits — a bank leaning on it is more exposed to funding cost spikes and faster outflows under stress.",
  },
  {
    key: 'aoci',
    label: 'AOCI (Accumulated Other Comprehensive Income)',
    definition: 'An equity-account line that captures unrealized gains/losses on available-for-sale securities without running them through net income.',
    formula: 'Cumulative mark-to-market change on AFS securities (and a few other items), reported directly',
    source_field: 'FDIC Call Report Schedule RC',
    why_it_matters: 'A large negative AOCI signals real, though unrealized, securities losses sitting in equity — this is exactly the mechanism behind SVB\'s failure.',
  },
  {
    key: 'uninsured_deposits',
    label: 'Uninsured deposits',
    definition: "The portion of a bank's deposits above the $250,000 FDIC insurance limit per depositor, per ownership category.",
    formula: 'Total deposits − estimated insured deposits, both reported directly',
    source_field: 'FDIC Call Report Schedule RC-O',
    why_it_matters: 'Uninsured depositors have the strongest incentive to run first in a crisis of confidence — this was the single largest driver of the March 2023 regional-bank failures.',
  },
  {
    key: 'behavioral_clusters',
    label: 'Behavioral clusters',
    definition: 'A data-driven grouping of banks by how their balance sheet actually behaves (funding mix, concentration, deposit stability) rather than just by asset size.',
    formula: 'K-means clustering (k=7) over a fixed feature set',
    source_field: 'Derived from Gold-layer Call Report ratios, not a single FDIC field',
    why_it_matters: "Two banks the same size can behave completely differently — a size bucket alone hides that a $2B commercial lender and a $2B trust company aren't real peers.",
  },
  {
    key: 'cet1',
    label: 'CET1 (Common Equity Tier 1) ratio',
    definition: "The strictest, highest-quality slice of a bank's regulatory capital, as a share of its risk-weighted assets.",
    formula: 'Common equity Tier 1 capital / total risk-weighted assets',
    source_field: 'FDIC Call Report Schedule RC-R',
    why_it_matters: 'CET1 is the primary regulatory capital-adequacy measure under Basel III — the minimum shown is a binding regulatory floor, not just a benchmark.',
  },
  {
    key: 'npl_ratio',
    label: 'NPL (nonperforming loan) ratio',
    definition: 'The share of a bank\'s loan book that is no longer accruing interest as expected because of credit deterioration.',
    formula: '(Nonaccrual loans + loans 90+ days past due still accruing) / total loans',
    source_field: 'FDIC Call Report Schedule RC-N',
    why_it_matters: 'A rising NPL ratio is the most direct, leading signal of credit-quality deterioration — see the credit-trajectory trend/acceleration fields for whether it\'s improving or worsening.',
  },
  {
    key: 'sod',
    label: 'SOD (Summary of Deposits)',
    definition: "FDIC's annual, branch-level census of every insured bank's physical branches and their deposits.",
    formula: 'Reported directly by each bank, per branch',
    source_field: 'FDIC Summary of Deposits, landed annually (not quarterly)',
    why_it_matters: "Because it's annual, every branch-derived figure (footprints, county HHI, the branch map) can be up to ~18 months stale relative to the quarterly financials shown alongside it — always check its vintage.",
  },
];

export const GLOSSARY_BY_KEY: Record<string, GlossaryEntry> = Object.fromEntries(
  GLOSSARY.map((e) => [e.key, e]),
);
