# Data contract — bank financials (Silver layer)

Source: `pipelines/transforms/src/banklens_transforms/silver.py`'s
`to_bank_financials(raw: dict) -> dict`, which normalises one raw FDIC
`financials` record (see `docs/domain/data-dictionary.md` for the raw field
codes) into the canonical schema every downstream Gold computation, tool and
UI page reads.

## Normalisation rules

1. **FDIC codes become canonical column names** — e.g. `ASSET` →
   `total_assets`, `LNRENRES` → `nonfarm_nonres_loans`. The full raw→canonical
   mapping lives in `_DOLLAR_FIELDS`/`_RATIO_FIELDS` in `silver.py`.
2. **Dollar fields are converted from thousands of USD to actual USD**
   (`_to_usd`, `value * 1000`) — Bronze stays raw in FDIC's native thousands
   convention; Silver is the first layer that reports real dollars.
3. **Ratio fields pass through unchanged** — they are already percentages in
   the raw feed and must **not** be rescaled. Mixing this up with rule 2 was a
   real, documented bug class (see `silver.py`'s module docstring).
4. **`REPDTE` (YYYYMMDD int) is parsed into an ISO date + a quarter label**
   (`_parse_repdte`), e.g. `20260331` → `("2026-03-31", "2026Q1")`.
5. **A missing value is `None`, never silently zero-filled.** A bank that
   didn't report a field is structurally different from a bank that reported
   zero, and every downstream consumer (X-Ray, the stress simulator, the
   deposit-flight model) depends on being able to tell the two apart.
6. **CRE (commercial real estate) is aggregated from its RC-C components** —
   not a single raw FDIC field, but a derived sum the Silver layer computes
   once so Gold doesn't reimplement the aggregation.

## Two corrections learned from the live data (documented in `silver.py`)

1. **Uninsured deposits** are taken directly from FDIC's own reported
   `DEPUNINS` estimate, not derived as `total_deposits - insured_deposits` —
   the insured/uninsured estimates use a different base internally, so the
   reported figure is the authoritative one.
2. **Capital ratios** (CET1, Tier 1, Total, Leverage) arrive from FDIC already
   as percentages and must not be multiplied by 1000 the way dollar fields
   are — a real bug class this module's field-classification (`_DOLLAR_FIELDS`
   vs `_RATIO_FIELDS`) exists specifically to prevent.

## Canonical fields

### Dollar amounts (real USD, converted from FDIC's thousands)

`total_assets`, `total_deposits`, `domestic_deposits`, `insured_deposits`,
`uninsured_deposits`, `core_deposits`, `total_loans_gross`,
`total_loans_net`, `total_equity`, `real_estate_loans`, `construction_loans`,
`multifamily_loans`, `nonfarm_nonres_loans`, `heloc_loans`,
`residential_mortgage_loans`, `farmland_loans`, `agricultural_loans`,
`c_and_i_loans`, `consumer_loans`, `credit_card_loans`, `auto_loans`,
`consumer_other_loans`, `securities_total`, `securities_afs`,
`securities_htm_reported`, `tier1_capital`, `total_capital`,
`risk_weighted_assets`, `average_assets`, `cash_and_balances`, `net_income`,
`interest_income`, `interest_expense`, `noninterest_income`,
`noninterest_expense`, `provision_for_credit_losses`, `noncurrent_loans`,
`net_charge_offs`, `net_charge_offs_construction`,
`net_charge_offs_multifamily`, `net_charge_offs_nonfarm_nonres`,
`net_charge_offs_residential_mortgage`, `net_charge_offs_farmland`,
`net_charge_offs_agricultural`, `net_charge_offs_c_and_i`,
`net_charge_offs_consumer`, `allowance_for_credit_losses`,
`assets_past_due_30_89`, `assets_past_due_90_plus`,
`other_real_estate_owned`, `intangible_assets`, `brokered_deposits`,
`volatile_liabilities`, `large_denomination_deposits`, `time_deposits`.

`assets_past_due_30_89` / `assets_past_due_90_plus` are **asset-level**
past-due figures (FDIC's `P3ASSET`/`P9ASSET`), not loan-level — named
accordingly so nobody divides them by a loan-book denominator by accident.

### Ratio fields (already percentages, passed through unchanged)

`cet1_ratio`, `tier1_rbc_ratio`, `total_rbc_ratio`, `leverage_ratio`,
`equity_to_assets_ratio_reported`, `loan_to_deposit_ratio_reported`,
`net_interest_margin_reported`, `roa_reported`, `roe_reported`,
`efficiency_ratio_reported`, `noncurrent_assets_ratio_reported`,
`loans_to_core_deposits_reported`.

`net_interest_margin_reported`, `roa_reported`, `roe_reported` and
`efficiency_ratio_reported` are FDIC's own computed performance ratios and
are **year-to-date annualized** — a Q1 value and a Q4 value are not
like-for-like. Anything comparing them across quarters within a year must
de-annualize from the underlying `net_income`/`average_assets` dollar fields
instead of differencing these ratios directly (see `docs/audit/
04-remediation-prompts.md`'s C15 for the fuller fix — quarterly-isolated
Gold fields derived from the YTD deltas).

### Identity / period

Parsed separately from `REPDTE`: an ISO date and a `"YYYYQn"` quarter label
(rule 4 above), plus whatever identity fields (`cert`, `name`, `state`, ...)
pass through from the raw record's own identity columns.
