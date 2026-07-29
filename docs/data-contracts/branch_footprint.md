# Data contract — branch footprint (`banklens_transforms.footprint`)

Real, branch-level geographic footprint from the FDIC Summary of Deposits (SOD),
feeding Feature 15's (M&A Fit) geographic-overlap signal. Keyless (unlike Tiingo) —
public FDIC data, no API key.

## The finding that shaped this design

FDIC's own SOD `STALP`/`CITY`/`ADDRESS` fields are **frozen at the bank's
headquarters address for every branch record** — verified live, not assumed:

| Bank | Branches | Distinct (city, address) pairs reported | Real coordinate spread |
|---|---|---|---|
| Citizens Bank (CERT 57957) | 984 | 1 ("Providence, RI, 1 Citizens Plz") | lat 25.75–44.89, lon -122.5 to -69.99 (Florida to Washington state) |
| Dime Community Bank (CERT 6976) | 63 | 1 ("Hauppauge, NY, 898 Veterans Memorial Hwy") | genuinely distinct per branch |

Only `SIMS_LATITUDE`/`SIMS_LONGITUDE` are reliably branch-specific. Building a
footprint from the state/city fields would silently launder this bad data into a
confident-looking (and wrong) result — e.g. Citizens Bank would show as 100%
Rhode-Island-only, when it operates in roughly a dozen states.

## The design: grid cells, not states or counties

Real branch coordinates are binned into a **0.4° × 0.4° grid** (`CELL_SIZE_DEG` in
`footprint.py`) — roughly a 27-30 mile "local market" scale. This is deliberately
coarse (not survey-grade geocoding; error concentrates at cell edges) but is the
only approach that never depends on the broken state/city fields, and arguably
answers the real M&A question — "do these branch networks physically overlap" —
better than administrative boundaries would anyway.

## Structure (`build_footprints` output, keyed by CERT — bank-level, no crosswalk needed)

| Field | Meaning |
|---|---|
| `cert` | FDIC certificate number |
| `branch_count` | total branches (including any missing coordinates) |
| `cells` | set of `(lat_bucket, lon_bucket)` grid keys with a real geocoded branch |
| `deposits_by_cell` | `$` (from `DEPSUMBR`, thousands→USD) per cell — for deposit-weighted overlap |
| `total_deposits` | sum across all branches |
| `centroid` | mean (lat, lon) of geocoded branches |

## Overlap metrics

- `cell_overlap(fp_a, fp_b)` — plain Jaccard of cell sets. The primary `geo_overlap`
  signal in Feature 15.
- `deposit_weighted_overlap(fp_a, fp_b)` — intersection-over-union on shared-cell
  **deposit dollars**, not just cell counts: two banks sharing one huge-deposit
  market matters more than sharing one small branch's cell. A secondary,
  richer signal (`geo_overlap_deposit_weighted` in the M&A tool's output).

## Landing

`scripts/land_sod.ps1` → `pipelines/ingestion/src/banklens_ingestion/sources/sod.py`
paginates the full annual SOD dataset (~76,120 records for 2025, ~8 requests of
10,000 rows each) to `data/bronze/source=fdic/sod/year=<YYYY>/records.json`.
