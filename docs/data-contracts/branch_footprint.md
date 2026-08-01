# Data contract — branch footprint (`banklens_transforms.footprint`)

Real, branch-level geographic footprint from the FDIC Summary of Deposits (SOD),
feeding Feature 15's (M&A Fit) geographic-overlap signal. Keyless (unlike Tiingo) —
public FDIC data, no API key.

## The finding that shaped this design — and its correction

This contract previously stated that FDIC's SOD had **no usable branch geography**,
because `STALP`/`CITY`/`ADDRESS` are frozen at the bank's headquarters on every branch
record. That freeze is real. The conclusion drawn from it was wrong: those are the
**institution-level** fields. FDIC also serves **branch-level** fields, and they are
correct and complete. Re-probed live against the same banks originally cited as evidence:

| Bank | Branches | Institution `STALP` | Branch `STALPBR` | Distinct counties | Null county |
|---|---|---|---|---|---|
| Citizens Bank (CERT 57957) | 984 | 1 | **16** | **140** | 0 |
| Wells Fargo (CERT 3511) | 4,214 | 1 | **40** | **787** | 0 |
| JPMorgan (CERT 628) | 4,993 | 1 | **49** | **611** | 0 |
| Dime Community (CERT 6976) | 63 | 1 | 1 | **8** | 0 |

Across the **entire landed 2025 dataset — 76,120 branches — 100% carry a branch-level
FIPS county code** (`STCNTYBR`), covering 3,194 counties. So this was a field-selection
bug on our side, not a source defect.

## The design: real FIPS counties, with the coordinate grid as fallback

Aggregation keys on `STCNTYBR` (FIPS state+county). This is the market definition the
**Federal Reserve and DOJ actually use** in the Bank Merger Competitive Review
guidelines — so a Herfindahl-Hirschman Index computed on it carries real meaning,
where an HHI over invented grid squares would not.

The 0.4° coordinate grid is retained as a **fallback** for any row lacking a county
code (none in the current landing, but the code must not assume that). Each footprint
reports `geo_basis` — `"county"` or `"grid"` — so a consumer always knows which it got.

## Structure (`build_footprints` output, keyed by CERT — bank-level, no crosswalk needed)

| Field | Meaning |
|---|---|
| `cert` | FDIC certificate number |
| `branch_count` | total branches (including any that can't be placed) |
| `cells` | set of market keys — FIPS county strings, or `(lat_bucket, lon_bucket)` under fallback |
| `deposits_by_cell` | `$` (from `DEPSUMBR`, thousands→USD) per market — for deposit-weighted overlap |
| `total_deposits` | sum across all branches |
| `centroid` | mean (lat, lon) of geocoded branches |
| `geo_basis` | `"county"` (real FIPS) or `"grid"` (coordinate fallback) |
| `counties` / `states` | distinct FIPS codes / branch-level state codes |

## Deposit-market concentration

`county_deposit_table(records)` → per-county totals and per-bank deposits;
`county_concentration(entry)` → HHI plus ranked bank shares; `herfindahl(shares)` uses
the **DOJ/Fed 0–10,000 convention** (a monopoly is 10,000, not 1.0) so the published
screening thresholds — 1,800 for "highly concentrated", +200 change — apply directly.

Computed over the **full** SOD (all 4,431 FDIC-insured certs), not just the $1B–$250B
analytical slice: a share against a partial denominator would overstate every bank.

**Caveat that must travel with any market-share number:** SOD reports deposits at the
**branch of record**, not where the customer is. A handful of charter/booking-center
counties therefore show extreme, non-competitive concentration — e.g. Minnehaha County,
SD (Sioux Falls) is 95.4% Wells Fargo on $361.6B, which reflects deposit booking, not
local retail dominance. Any UI presenting county HHI must say so.

## Overlap metrics

- `cell_overlap(fp_a, fp_b)` — plain Jaccard of market sets. The primary `geo_overlap`
  signal in Feature 15. Signature and semantics unchanged by the county migration —
  its inputs simply became real markets instead of invented squares.
- `deposit_weighted_overlap(fp_a, fp_b)` — intersection-over-union on shared-market
  **deposit dollars**, not just market counts: two banks sharing one huge-deposit
  market matters more than sharing one small branch's. A secondary,
  richer signal (`geo_overlap_deposit_weighted` in the M&A tool's output).

## Landing

`scripts/land_sod.ps1` → `pipelines/ingestion/src/banklens_ingestion/sources/sod.py`
paginates the full annual SOD dataset (76,120 records for 2025, ~8 requests of
10,000 rows each) to `data/bronze/source=fdic/sod/year=<YYYY>/records.json`, with a
`_provenance.json` sidecar carrying `fetched_at`, `record_count` and a SHA-256
checksum of the payload — written through `Provenance.create()`, so the recorded
endpoint always reproduces the landed file.
