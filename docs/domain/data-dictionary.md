# Data dictionary — FDIC financial field codes

The FDIC BankFind `financials` endpoint uses short codes. Every code below is
**verified live** against the API (probed, not guessed). Example values are Wells
Fargo Bank NA (CERT 3511), 2026-03-31, in **$ thousands** unless marked a ratio.
Full reference: https://banks.data.fdic.gov/docs/

## Identity & headline
| Code | Meaning | Canonical column |
|---|---|---|
| `CERT` | FDIC certificate number | `cert_number` |
| `REPDTE` | Report date (YYYYMMDD) | → `filing_date`, `quarter` |
| `NAMEFULL` | Legal name | `name` |
| `STALP` | State (2-letter) | `state` |
| `ASSET` | Total assets | `total_assets` |

## Deposits
| Code | Meaning | Canonical column |
|---|---|---|
| `DEP` | Total deposits | `total_deposits` |
| `DEPDOM` | Domestic-office deposits | `domestic_deposits` |
| `DEPINS` | Estimated **insured** deposits | `insured_deposits` |
| `DEPUNINS` | Estimated **uninsured** deposits | `uninsured_deposits` |
| `COREDEP` | Core (stable) deposits | `core_deposits` |

> **Correction learned from the data:** use the reported `DEPUNINS` for uninsured
> deposits, **not** `DEP − DEPINS`. The insured/uninsured estimates use a different
> base than total deposits, so the reported figure is authoritative. (WF: DEPUNINS
> = 723,812 thousand ⇒ 47.7% of deposits, vs 44.7% if wrongly derived.)

## Loans & leases (RC-C schedule)
| Code | Meaning | Canonical column | WF value |
|---|---|---|---|
| `LNLSGR` | Gross loans & leases | `total_loans_gross` | 985,437 |
| `LNLSNET` | Net loans & leases | `total_loans_net` | 971,566 |
| `LNRE` | Total real-estate loans | `real_estate_loans` | 361,336 |
| `LNRECONS` | Construction & land dev | `construction_loans` | 13,459 |
| `LNREMULT` | Multifamily residential | `multifamily_loans` | 26,383 |
| `LNRENRES` | Nonfarm nonresidential (CRE core) | `nonfarm_nonres_loans` | 83,180 |
| `LNRELOC` | Home-equity lines of credit | `heloc_loans` | 10,018 |
| `LNRERES` | 1-4 family residential | `residential_mortgage_loans` | 233,117 |
| `LNREAG` | Farmland | `farmland_loans` | 793 |
| `LNAG` | Agricultural production | `agricultural_loans` | 3,285 |
| `LNCI` | Commercial & industrial | `c_and_i_loans` | 198,483 |
| `LNCON` | Consumer (total) | `consumer_loans` | 116,977 |
| `LNCRCD` | Consumer: credit card | `credit_card_loans` | 57,277 |
| `LNAUTO` | Consumer: auto | `auto_loans` | 53,794 |
| `LNCONOTH` | Consumer: other | `consumer_other_loans` | 4,508 |

**CRE (commercial real estate)** aggregate = `LNRECONS + LNREMULT + LNRENRES`
(incl. owner-occupied). WF: 123,022 thousand ⇒ 12.5% of gross loans.

## Securities
| Code | Meaning | Canonical column |
|---|---|---|
| `SC` | Total securities | `securities_total` |
| `SCAF` | Available-for-sale (fair value) | `securities_afs` |
| — | Held-to-maturity (derived `SC − SCAF`) | `securities_htm` |

> `SCHTM`/`SCHTMV` came back null for WF; HTM is derived as `SC − SCAF` and flagged
> as a derivation. Refine when a reliable direct HTM code is confirmed per bank.

## Capital & performance RATIOS (already %, do NOT rescale)
| Code | Meaning | Canonical column | WF value |
|---|---|---|---|
| `IDT1CER` | Common Equity Tier 1 (CET1) ratio | `cet1_ratio` | 12.58 |
| `IDT1RWAJR` | Tier 1 risk-based capital ratio | `tier1_rbc_ratio` | 12.58 |
| `RBCRWAJ` | Total risk-based capital ratio | `total_rbc_ratio` | 14.06 |
| `RBC1AAJ` | Tier 1 leverage ratio | `leverage_ratio` | 8.40 |
| `EQV` | Equity / assets | `equity_to_assets_ratio_reported` | 9.34 |
| `LNLSDEPR` | Net loans / deposits | `loan_to_deposit_ratio_reported` | 64.05 |

We recompute loan-to-deposit and equity-to-assets from the dollar fields and
**assert they match** `LNLSDEPR`/`EQV` in tests — proof the pipeline math is correct.

## Capital & balance-sheet DOLLARS (for the stress simulator, Feature 16)
| Code | Meaning | Canonical column | WF value ($k) |
|---|---|---|---|
| `RBCT1J` | Tier 1 capital | `tier1_capital` | 151,450,000 |
| `RBC` | Total risk-based capital | `total_capital` | 169,159,000 |
| `RWAJT` | Risk-weighted assets | `risk_weighted_assets` | 1,203,546,500 |
| `ASSET5` | Average assets | `average_assets` | 1,837,466,000 |
| `CHBAL` | Cash & balances due | `cash_and_balances` | 173,552,000 |
| `SCHA` | HTM securities (amortized cost) | `securities_htm_reported` | 204,169,000 |

Shortcut used: `RWA = RBCT1J ÷ (IDT1RWAJR/100)` reproduces `RWAJT` exactly, so the
stress baseline recomputes the reported ratios precisely before any shock is applied.
`SCHA` is the direct HTM figure (preferred over the earlier `SC − SCAF` derivation).

## Data-quality caveats (observed in the 1,049-bank MVP slice)
- **Foreign-bank US branches/agencies** (e.g. Bank of China, State Bank of India, Standard Chartered) report **0/null CET1** — they are capitalized at the parent level and don't file the ratio the same way. They pollute "lowest CET1" rankings. Phase 2: treat 0/null CET1 as *missing* (exclude from capital percentiles) rather than as a real 0.
- The cohort is **CRE-heavy by nature** (median ~48% CRE), so peer-relative percentiles — not absolute thresholds alone — should drive the X-Ray's concentration verdict.

## Holding-company identity (for the CERT↔CIK↔RSSD crosswalk — DONE, see below)
| Code | Meaning | Canonical column |
|---|---|---|
| `RSSDID` | Bank-level Fed RSSD ID | `rssd_id` |
| `NAMEHCR` | Holding-company name (blank if none — see crosswalk.md) | `holding_company_name` |
| `RSSDHCR` | Holding-company RSSD ID (blank if none) | `holding_company_rssd` |

## SEC EDGAR (via the crosswalk)
`company_tickers.json` → `{cik_str, ticker, title}` per filer (10,432 filers). XBRL
company facts (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`) use concept
`us-gaap:Assets` (units USD) for total assets — verified against Wells Fargo & Zions.
Full contract: [`docs/data-contracts/crosswalk.md`](../data-contracts/crosswalk.md).

## Still to map (Phase 2)
Brokered deposits, FHLB advances, short-term borrowings (funding-stability score);
the CET1/RWA **dollar** amounts (for a precise CRE-to-capital ratio); FFIEC Call
Report / UBPR and NIC FR Y-9C connectors.
