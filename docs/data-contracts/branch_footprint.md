# Data contract — branch footprint (Feature 15)

Source: FDIC Summary of Deposits (`fdic_sod` in `config/sources.yaml`),
`https://banks.data.fdic.gov/api/sod`. Public domain, no auth, published
**annually** (not quarterly — see "Vintage" below). ~76,000 branch rows
across all FDIC-insured banks.

## Which fields are trustworthy

SOD returns both institution-level and branch-level location fields for
every row. **Only the branch-level fields are correct**; the
institution-level ones are frozen at the bank's headquarters address on
every single branch row, which was originally (and wrongly) taken as a
source defect rather than a field-selection bug — re-probed live, the
branch-level fields are correct and complete (Citizens Bank NA: 984 branches
→ 16 states, 140 counties, 0 null; Wells Fargo: 4,214 branches → 40 states,
787 counties, 0 null; JPMorgan: 4,993 branches → 49 states, 611 counties,
0 null).

| Use this (branch-level) | Not this (institution-level, frozen at HQ) |
|---|---|
| `STCNTYBR` (FIPS state+county of the branch) | `STALP`/`CITY`/`ADDRESS` |
| `STALPBR` (branch state) | — |
| `SIMS_LATITUDE` / `SIMS_LONGITUDE` | — |
| `DEPSUMBR` (branch deposits, $ thousands) | — |

## Market definition: county, not an invented grid

Aggregation keys on `STCNTYBR` — the **same market definition the Federal
Reserve and DOJ use** for deposit-concentration and bank-merger review — so
an HHI or overlap score computed on it is a real regulatory-style figure,
not an artifact of an arbitrary binning choice.

A 0.4-degree coordinate grid (`footprint.grid_cell`, ~27-30 miles per cell)
exists as a **fallback only**, for the small number of rows with no FIPS
county code but real coordinates. Every footprint reports which basis it
actually used:

```
geo_basis: "county" | "grid"
```

so a consumer can tell whether a given bank's overlap/HHI figure rests on
the real regulatory market definition or the coordinate fallback.

## The `footprint` object

Built once per landed SOD year by `pipelines/transforms/src/banklens_transforms/
footprint.build_footprints()`, one entry per `cert`:

| Field | Type | Notes |
|---|---|---|
| `cert` | int | FDIC certificate number |
| `branch_count` | int | **Every** branch row for this cert, including ones that couldn't be placed geographically (see Exclusions below) — never silently dropped from the count |
| `cells` | set of county FIPS or grid-cell keys | The bank's markets |
| `deposits_by_cell` | dict, cell → $ | Branch deposits summed per market |
| `total_deposits` | float ($) | Sum of `DEPSUMBR * 1000` across all branches |
| `centroid` | `(lat, lon)` or `null` | Deposit-network centroid; `null` if no branch had usable coordinates |
| `geo_basis` | `"county"` \| `"grid"` | Which market definition this footprint actually used |
| `counties` | set of FIPS strings | |
| `states` | set of state codes | From `STALPBR`, the branch-level field |

`cell_overlap(fp_a, fp_b)` — Jaccard overlap (intersection/union) of two
banks' `cells` sets, used by `ma_fit.geo_overlap` for M&A geographic fit.
Returns `None` if either footprint is missing.

`deposit_weighted_overlap(fp_a, fp_b)` — the richer secondary signal:
overlap weighted by branch deposits in *shared* markets, not just market
counts, so two banks sharing one huge-deposit market score higher than two
sharing one small branch's market.

## Exclusions (disclosed, never silently dropped)

- Branches with neither a FIPS county code nor usable coordinates are
  counted in `branch_count` but excluded from `cells`/`deposits_by_cell` —
  they exist, but can't be placed on any map.
- The branch map (`get_branch_map`, `BranchMapCanvas.tsx`) additionally
  excludes non-contiguous-US branches (Alaska/Hawaii/territories — no
  boundary/projection support yet) and a handful of corrupt-coordinate rows
  outside the plausible CONUS lat/lon range. Both counts are returned as
  `excluded_non_contiguous` on the tool response, not silently dropped from
  a total.

## Vintage

FDIC publishes SOD **once a year** (around June), not every quarter. Every
footprint-derived figure — the bank-page footprint panel, county
concentration, the branch map, M&A geo-fit — is therefore up to ~18 months
stale relative to the same bank's quarterly financials, and carries a
`sod_vintage` field (`{sod_year, fetched_at}`, from `banklens_mcp.data.sod_vintage()`)
specifically so no branch-derived number is ever shown without its real
vintage next to it.
