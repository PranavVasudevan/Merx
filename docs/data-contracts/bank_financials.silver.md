# Data contract — `bank_financials` (Silver)

**Grain:** one row per bank (`cert_number`) per quarter (`quarter`).
**Units:** actual USD (converted from FDIC's reported thousands).
**Machine schema:** [`schemas/jsonschema/bank_financials.schema.json`](../../schemas/jsonschema/bank_financials.schema.json)

## Columns (Phase 1 subset)

| Column | Type | Source (FDIC code) | Notes |
|---|---|---|---|
| `cert_number` | int | `CERT` | Primary bank identity |
| `cik` | int? | (crosswalk) | SEC filer id — Phase 1 leaves null |
| `rssd_id` | int? | (crosswalk) | Fed id — the join linchpin, Phase 1 null |
| `name` | str? | `NAMEFULL` | |
| `state` | str? | `STALP` | 2-letter |
| `quarter` | str | derived from `REPDTE` | `YYYYQn` |
| `filing_date` | date | `REPDTE` | ISO-8601 |
| `restated_flag` | bool | — | restatement dedupe: Phase 2 |
| `total_assets` | num? | `ASSET` | ×1000 → USD |
| `total_deposits` | num? | `DEP` | ×1000 |
| `domestic_deposits` | num? | `DEPDOM` | ×1000 |
| `insured_deposits` | num? | `DEPINS` | ×1000, *estimated* |
| `uninsured_deposits` | num? | `DEP − DEPINS` | derived estimate |
| `total_loans_gross` | num? | `LNLSGR` | ×1000 |
| `total_loans_net` | num? | `LNLSNET` | ×1000 |
| `total_equity` | num? | `EQ` | ×1000 |

## Cleaning rules
1. **Units:** every FDIC dollar field is in thousands → multiply by 1,000.
2. **Dates:** `REPDTE` (`YYYYMMDD`) → ISO date + `YYYYQn`.
3. **Missing values:** represent as `null`, never zero-fill.
4. **Restatements (Phase 2):** when a bank refiles a quarter, keep the latest and set `restated_flag`.
5. **Identity crosswalk (Phase 2):** populate `cik`/`rssd_id` via the CERT↔CIK↔RSSD map so FDIC, SEC, and Fed data join.

## Implemented in Phase 1b (verified codes — see data-dictionary.md)
- **Uninsured** now uses reported `DEPUNINS` (not `DEP − DEPINS`); added `core_deposits`.
- **Loan composition:** `real_estate_loans`, `construction_loans`, `multifamily_loans`, `nonfarm_nonres_loans`, `heloc_loans`, `residential_mortgage_loans`, `farmland_loans`, `agricultural_loans`, `c_and_i_loans`, `consumer_loans` (+ `credit_card_loans`, `auto_loans`, `consumer_other_loans`), and the derived `cre_loans` aggregate.
- **Securities:** `securities_total`, `securities_afs`, derived `securities_htm`.
- **Capital ratios (from FDIC, already %):** `cet1_ratio`, `tier1_rbc_ratio`, `total_rbc_ratio`, `leverage_ratio`, plus reported `equity_to_assets_ratio_reported`, `loan_to_deposit_ratio_reported`.

## Added in the roadmap expansion (every code probed live against the FDIC API first)

**Income statement** ($ thousands): `net_income` (NETINC), `interest_income` (INTINC),
`interest_expense` (EINTEXP), `noninterest_income` (NONII), `noninterest_expense`
(NONIX), `provision_for_credit_losses` (ELNATR).

**Asset quality** ($ thousands): `noncurrent_loans` (NCLNLS), `net_charge_offs`
(NTLNLS), `allowance_for_credit_losses` (LNATRES), `other_real_estate_owned` (ORE),
`intangible_assets` (INTAN), `assets_past_due_30_89` (P3ASSET),
`assets_past_due_90_plus` (P9ASSET).

> ⚠️ `P3ASSET`/`P9ASSET` are **asset-level** past-due totals, not loan-level. They are
> named accordingly so nothing divides them by a loan denominator. Loan-level
> noncurrency is `noncurrent_loans` (NCLNLS), and that is what `npl_ratio_pct` uses.

**Funding composition** ($ thousands): `brokered_deposits` (BRO),
`volatile_liabilities` (VOLIAB), `large_denomination_deposits` (DEPLGAMT),
`time_deposits` (NTRTIME).

**FDIC-computed ratios** (already %, passed through): `net_interest_margin_reported`
(NIMY), `roa_reported` (ROA), `roe_reported` (ROE), `efficiency_ratio_reported`
(EEFFR), `noncurrent_assets_ratio_reported` (NPERFV), `loans_to_core_deposits_reported`
(IDLNCORR).

> ⚠️ FDIC's computed performance ratios are **year-to-date annualized**, so Q1 and Q4
> are not like-for-like. Anything comparing profitability across quarters must
> de-annualize from `net_income`/`average_assets` rather than differencing these.

Codes probed and found **invalid** (do not re-add): `DEPBR`, `IDDEPBR`, `TIMEB1`,
`OTBFHLB`. There is consequently **no FHLB/wholesale-borrowings field** and no
LCR/NSFR in FDIC data — funding analytics must not be labelled "liquidity" in the
regulatory sense.

## Still to add
`fhlb_advances`/`short_term_borrowings` (not exposed under the codes tried above —
needs the FFIEC Call Report schedule rather than FDIC's summary endpoint); the
CERT↔CIK↔RSSD crosswalk beyond `RSSDID` to join Fed/SEC data.
