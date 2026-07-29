# ma-fit — Feature 15, M&A Fit Finder

Given a target bank, ranks best-fit acquirers/partners on funding complementarity
(a deposit-rich bank fills a loan-heavy one's funding gap), business similarity
(cosine on loan mix — integration/strategic fit), size compatibility, and **real
branch-network geographic overlap**. Output: a ranked list with a short rationale
per match.

## Status: logic implemented, real geo-overlap upgrade done (Phase 1o), gRPC serving pending (Phase 4)

Engine: [`pipelines/transforms/src/banklens_transforms/ma_fit.py`](../../../pipelines/transforms/src/banklens_transforms/ma_fit.py)
+ [`footprint.py`](../../../pipelines/transforms/src/banklens_transforms/footprint.py)
— pure functions over Gold feature vectors + real FDIC branch data. Runner:
`banklens_ingestion.ma_fit_cli` / `scripts/ma_fit.ps1`.

### Geography: real branch footprints, NOT states/counties — a real data-quality finding drove this
The original home-state proxy was upgraded to the FDIC **Summary of Deposits**
(`scripts/land_sod.ps1`, ~76k branches/year, keyless) — but a live check found FDIC's
own `STALP`/`CITY`/`ADDRESS` fields are **frozen at the bank's headquarters address
for every branch record**, for every multi-branch bank checked (Citizens Bank: 984
branches, all reading "Providence, RI, 1 Citizens Plz" even though the same records'
`SIMS_LATITUDE`/`SIMS_LONGITUDE` genuinely span Florida to Washington state; Dime
Community Bank: same pattern, all 63 branches reading its Hauppauge HQ). Only the
geocoded coordinates are reliably branch-specific.

So geography is computed from coordinates alone: real branches are binned into a
~0.4°×0.4° grid (~27-30 mile "local market" cells — see `footprint.py`), and overlap
is the Jaccard of two banks' cell sets (plus a deposit-weighted variant, using real
branch-level `DEPSUMBR`, as a secondary signal). This also arguably answers the
actual M&A question — "do these branch networks physically overlap" — better than
administrative state boundaries would.

### Proven on real data — the ranking genuinely changed
- Target **Dime Community Bank**: real footprint = 63 branches spanning **10 distinct
  local markets** (correctly derived from coordinates alone, despite Dime's own
  STALP/CITY data being stuck at its HQ). Geo-overlap now genuinely differentiates
  candidates instead of a crude same-state/different-state binary: Apple Bank scores
  0.43 (6 shared markets), while Bank OZK/Simmons Bank/Merchants Bank of Indiana
  correctly score 0.00 (no real overlap). **The #1 match changed from Flagstar
  (state-proxy era) to Provident Bank** once real geography was used — concrete proof
  this wasn't a cosmetic change.

### Run
```powershell
powershell -File scripts/land_sod.ps1              # one-time: land real branch data (keyless)
powershell -File scripts/ma_fit.ps1 -TargetCert 6976 -TopN 8
```

### Next (Phase 4)
Wrap as gRPC; expose branch-footprint maps in the quant terminal (deck.gl/MapLibre,
per the original master plan); a smarter grid (variable cell size by population
density) would sharpen dense-metro overlap detection further.
