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

## Still to add (Phase 2)
Funding detail (`brokered_deposits`, `fhlb_advances`, `short_term_borrowings`) for the
funding-stability score; CET1/RWA **dollar** amounts for a precise CRE-to-capital ratio;
the CERT↔CIK↔RSSD crosswalk (`RSSDID` is available) to join Fed/SEC data.
