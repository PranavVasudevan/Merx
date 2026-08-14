# BankLens — Complete Issue Register

**95 issues** across 7 categories (A·12, B·10, C·15, D·14, E·15, F·20, G·9). Every
issue has a matching ready-to-run prompt in `04-remediation-prompts.md`, keyed by the
same ID.

**Legend**
- **Sev** — `P0` blocks a demo/deploy · `P1` blocks a paying user · `P2` quality/credibility · `P3` polish
- **Fixable?** — `Yes` (engineering only) · `Cost` (needs money or a paid tier) · `Data` (needs a source that does not exist publicly) · `Inherent` (a real limit of the domain — can only be *disclosed*, not solved)

---

## A · Deployability, hosting and $0-cost fit

| ID | Issue | Sev | Fixable? | Mitigation |
|---|---|---|---|---|
| **A1** | `frontend/apps/web/src/api.ts:12` hardcodes `BASE = 'http://localhost:8791/api'`. There is no deployable build. | P0 | Yes | `VITE_API_BASE` env var with the localhost value as fallback. |
| **A2** | `bridge_server.py:281` hardcodes `_ALLOWED_ORIGINS` to three localhost ports. Any deployed frontend is blocked by CORS. | P0 | Yes | `BANKLENS_ALLOWED_ORIGINS` comma-separated env var. |
| **A3** | Auth hard-couples to a self-hosted Keycloak (`auth.ts:10`, `auth.py:36`). No free always-on Keycloak host exists; the container idles at ~600 MB. | P0 | Yes | Make the OIDC provider config-driven so Auth0/Clerk/Supabase free tiers work unchanged (all are standards-compliant OIDC). |
| **A4** | Bridge is `http.server.ThreadingHTTPServer` — no request timeouts, no body-size limit, no rate limiting, unbounded thread creation. | P0 | Yes | Keep the stdlib handler for local dev; add a thin ASGI adapter (or gunicorn+`wsgiref`) for deployment, with timeouts and a concurrency cap. |
| **A5** | `data/` (96 MB of Bronze JSON, incl. a 37 MB SOD file) is a read-only volume mount. Free hosts have ephemeral disks. | P0 | Yes | Ship the Gold layer as a single DuckDB/Parquet artifact; host in free object storage (Cloudflare R2) or bake into the image. |
| **A6** | Bridge memory: 76,120 SOD rows + 8×1,049 population rows + a DuckDB table, all resident. Free tiers give 256–512 MB. | P0 | Yes | Lazy-load SOD per-state; move the Gold table to on-disk DuckDB; drop the NDJSON round-trip in `data.duckdb_gold()`. |
| **A7** | Assistant defaults to Ollama, which needs GBs of local weights. Unusable on any free host. | P1 | Yes | Default to the already-implemented Gemini free tier (`gemini_keys.py` 5-key rotation) when no local Ollama is reachable. |
| **A8** | Postgres/pgvector wiring only reads `POSTGRES_HOST/PORT/USER/PASSWORD/DB` — no connection string, no SSL, so Neon/Supabase free tiers cannot be used. | P1 | Yes | Accept `DATABASE_URL` with `sslmode=require`. |
| **A9** | `docker-compose.dev.yml` runs ClickHouse, MinIO and Redis. **No application code references any of them.** | P2 | Yes | Delete them, or move to a clearly-labelled `docker-compose.future.yml`. |
| **A10** | `refresh-cronjob.yaml` mounts `emptyDir` in base — the quarterly refresh writes data that vanishes on pod restart unless an overlay patches it. | P1 | Yes | Make the base require a PVC-backed volume; fail loudly rather than silently write to scratch. |
| **A11** | No static-hosting build path; the only frontend artifact is an nginx container. | P1 | Yes | Add a Cloudflare Pages / Netlify config and a `dist/` deploy job. |
| **A12** | Tiingo free tier is 250 calls/day, 50 symbols/hour. `market_cli` has a `limit` but no budget-aware scheduler, so coverage is arbitrary. | P2 | Cost | Round-robin the universe across days, persist a cursor, and surface coverage % in the UI. |

---

## B · Data coverage and sourcing

| ID | Issue | Sev | Fixable? | Mitigation |
|---|---|---|---|---|
| **B1** | Only 8 quarters landed (2024Q2–2026Q1). `growth_rate_3yr_pct` and `deposit_growth_rate_3yr_pct` are therefore **always `None`**, and `deposit_growth_1yr` — the highest-weighted feature in the deposit-flight model (2.81) — is **always imputed** at scoring time. | P1 | Yes | Backfill 16–20 quarters from FDIC (the connector already supports arbitrary REPDTEs). ~2.3 MB/quarter. |
| **B2** | EBA data lacks loan concentration, uninsured split, and deposit totals. EU banks are excluded from clustering, most X-Ray rules, and the deposit-flight model. | P2 | Data | Cannot be fixed — EBA does not publish it. Already disclosed well. Consider parsing `tr_cre.csv` (needs the SDD.xlsx dictionary) for partial credit-risk coverage. |
| **B3** | Population band is $1B–$250B: excludes the four GSIBs and every bank under $1B. | P1 | Yes | Add tiers above and below with explicit band labelling; keep percentiles computed *within* band. |
| **B4** | No FR Y-9C / FFIEC holding-company data. Deals, tickers, and analyst consensus are all at HoldCo level. `fed_nic` and `ffiec_cdr` are `status: planned` in `sources.yaml`. | P1 | Yes | Implement the NIC bulk-zip connector; the crosswalk already carries RSSD. |
| **B5** | No FRED macro series (`status: planned`). No rate environment, unemployment, or CRE price index for scenario conditioning. | P2 | Yes | Free API key; connector is a small stdlib addition. |
| **B6** | No FDIC failures list, no enforcement actions, no M&A deal comps as first-class data. The 4 training positives are hardcoded dicts. | P1 | Yes | Land the FDIC failures list + BankFind institution-history events as a real Bronze source. |
| **B7** | SOD is annual and only 2025 is landed; branch footprints are up to 18 months stale versus 2026Q1 financials. | P2 | Inherent | FDIC publishes SOD annually. Disclose the as-of date next to every footprint number. |
| **B8** | SEC 10-K risk-factor coverage is a small subset of filers. | P2 | Yes | Expand the landing loop; the honest coverage tool already exists. |
| **B9** | No point-in-time / restatement handling. Silver/Gold always read the latest landed file; FDIC restates. | P2 | Yes | Bronze is already append-only with checksums — add an `as_of` parameter that selects the partition snapshot. |
| **B10** | No data-freshness surface. A user cannot tell when a number was landed vs when the source published it. | P2 | Yes | Expose `_provenance.json` timestamps in a `/api/data-freshness` route and a header strip. |

---

## C · Analytics and model quality

| ID | Issue | Sev | Fixable? | Mitigation |
|---|---|---|---|---|
| **C1** | Deposit-flight model: **n=4 positives**, in-sample AUC 0.955, LOO over those same 4. No CV, no PR curve, no calibration, no coefficient CIs, no base-rate adjustment. | P1 | Inherent (n) / Yes (rigour) | Cannot manufacture more real failures. *Can* add: bootstrap CIs, calibration curve, PR curve with the true base rate, and a prominent "resemblance score, not probability" reframing. |
| **C2** | Hand-rolled logistic regression with fixed `lr=0.2, epochs=2000, l2=1.0`. No hyperparameter selection. Mean imputation. Standardisation fit on the pooled two-era sample. | P2 | Yes | Add a small CV loop for `l2`; report imputation rate per feature; standardise per-era or add an era indicator. |
| **C3** | k-means k=7 is fixed for stable IDs while `get_cluster_diagnostics` shows k=4 may score better on silhouette. Clusters are recomputed independently per quarter, so labels flicker. | P2 | Yes | Add a "fixed-centroid assignment" mode: fit once on a reference quarter, assign later quarters to those centroids. |
| **C4** | Stress engine: single-period, static balance sheet, **no PPNR/earnings offset**, no management actions, **AFS/HTM durations hardcoded at 4y/6y for every bank**, parallel shocks only, no correlation between legs, no LCR/NSFR/survival horizon. | P1 | Partly | Derive duration from the securities maturity distribution where FDIC discloses it; add a PPNR offset; add multi-period; add a correlated joint-scenario mode. Some legs are `Inherent` (FDIC does not disclose full maturity ladders). |
| **C5** | No IRRBB: no EVE, no ΔNII, no key-rate durations, no curve twist. This is the actual 2023 mechanism. | P1 | Partly | Build a repricing-gap approximation from disclosed maturity buckets; disclose the approximation clearly. |
| **C6** | Loan losses are a flat % of gross loans. No segment PD/LGD, no CECL, no vintage curves — despite Gold already holding a disjoint 8-category loan taxonomy. | P1 | Yes | Apply per-category historical loss rates (FDIC publishes charge-off rates by category) instead of one flat number. |
| **C7** | `quantlib_pricing` uses a single representative bond per book. | P2 | Inherent | Disclosed in the docstring. Improve only if maturity buckets are landed. |
| **C8** | No credit migration or vintage analysis; NPL is a single-snapshot ratio. | P2 | Yes | Compute NPL/NCO trajectories per bank across the landed quarters. |
| **C9** | M&A fit weights `{funding .45, business .25, size .15, geo .15}` are hand-set and never validated against completed deals. No pro-forma (combined CET1, TBV dilution, earn-back, combined county HHI). | P1 | Yes | Land real deal history (B6) and fit the weights; add a pro-forma calculator reusing `county_concentration`. |
| **C10** | No market-implied risk: no beta, no vol-vs-peers, no drawdown, no P/TBV, no P/E, no correlation between X-Ray flags and equity underperformance. | P1 | Yes | All computable from landed OHLCV + Gold equity. This is also the cheapest available *validation* of the X-Ray. |
| **C11** | Percentile ranks are population-wide with a weak `≤` definition and no interpolation. A $1.2B bank is ranked against a $200B bank. | P1 | Yes | Add size-bucket-conditional and cluster-conditional percentiles alongside the global one. |
| **C12** | Filing-diff z-scores are computed from ≤8 observations; small-sample σ makes flags unstable. Materiality floors are absolute constants (`2.0%` / `0.3pp`) not scaled to the bank. | P2 | Partly | Backfill history (B1) shrinks this; add a minimum-observations gate and report `n` alongside each z. |
| **C13** | No multiple-testing control anywhere. 13 tracked line items × 1,049 banks × a z≥2 threshold produces ~2,700 false flags per quarter by construction. | P2 | Yes | Report an expected-false-positive count, or apply a Benjamini–Hochberg FDR control at the population level. |
| **C14** | **No backtest harness exists for anything.** Not the risk score, not the X-Ray flags, not the diff flags, not the M&A weights. | P1 | Yes | 8 quarters is enough to build the harness. Publish the result even if it is "no detectable signal yet" — that is more credible than silence. |
| **C15** | FDIC performance ratios (NIM, ROA, ROE, efficiency) are year-to-date annualised. Only one caption says so; the trends chart plots them across quarters as if they were comparable. | P2 | Yes | Compute quarterly-isolated versions from the YTD deltas, or label the axis explicitly. |

---

## D · Product and workflow gaps

| ID | Issue | Sev | Fixable? | Mitigation |
|---|---|---|---|---|
| **D1** | **No export of any kind** — no CSV, no Excel, no PDF tearsheet, no chart-data download. | P0 | Yes | Client-side CSV from any table; server-side PDF tearsheet per bank. |
| **D2** | No alerts, no saved screens, no notifications. Watchlist is a bare cert list with no notes or thresholds. | P1 | Yes | Extend the watchlist schema with notes + threshold rules; add a digest job to the existing DAG. |
| **D3** | No quarter selector on 21 of 23 pages — everything is silently locked to the latest landed quarter. | P1 | Yes | A global quarter context, wired to `data.population(repdte)` which already accepts it. |
| **D4** | No holding-company roll-up or parent/subsidiary tree. | P1 | Yes | Depends on B4. |
| **D5** | No custom peer-set builder. Only k-means clusters and size buckets. | P1 | Yes | Persist named cert lists per user (same table pattern as the watchlist); make every population page respect an active peer set. |
| **D6** | Compare page has a fixed metric list and no charts. | P2 | Yes | Arbitrary metric picker + a small-multiples or radar rendering. |
| **D7** | No annotation/commentary layer on a bank or a quarter. | P2 | Yes | Notes table keyed on (user, cert, quarter). |
| **D8** | Almost no page state is in the URL — views are not shareable or bookmarkable. | P1 | Yes | Move filters/sorts/selections into search params (the pattern already exists on `/trends`). |
| **D9** | No drill-down from a Gold metric back to the FDIC field names and the Bronze checksum that produced it. | P1 | Yes | Add a `/api/metric-lineage` route; the provenance data is already captured. |
| **D10** | No scenario library. Three raw sliders only, no named/regulatory scenarios, no scenario save/share. | P1 | Yes | Ship a named-scenario JSON registry (2023 rate path, CCAR-style severely adverse, a 2008 replay) plus user-saved scenarios. |
| **D11** | No exposure/portfolio view — a user cannot enter counterparty positions and see aggregate risk. | P2 | Yes | New feature; sizeable. |
| **D12** | Assistant is single-turn, has no conversation memory, no citations linking back to pages, and can take minutes on the default provider. | P1 | Yes | Add multi-turn state, streaming, and answer→page deep links. |
| **D13** | No mobile/tablet layout; tables are wide and unvirtualised (up to 2,000 rows rendered). | P2 | Yes | Responsive breakpoints + row virtualisation. |
| **D14** | No glossary or onboarding. Texas Ratio, CBLR, HHI, brokered deposits, AOCI are unexplained. | P2 | Yes | A hover-glossary component fed by one JSON file. |

---

## E · Visualisation

| ID | Issue | Sev | Fixable? | Mitigation |
|---|---|---|---|---|
| **E1** | Candlestick chart has no volume pane, no moving averages, no comparison series, no range selector, no log scale, no crosshair readout. `lightweight-charts` (free, MIT) supports all of it. | P1 | Yes | Extend `CandlestickChart.tsx`. |
| **E2** | No market view outside the single bank page — no sector index, no relative performance, no cross-bank price comparison. | P1 | Yes | New `/market` page over landed OHLCV. |
| **E3** | Stress results render as numbers plus a simple bar chart. `capital_waterfall` already returns exactly the data for a **waterfall chart**, and nothing renders one. No tornado/sensitivity chart, no 2-D surface over (outflow × rate shock). | P1 | Yes | Waterfall + tornado + heatmap surface, all from data already returned. |
| **E4** | `/distributions` never marks where a selected bank sits in the histogram. | P1 | Yes | A `ReferenceLine` at the selected bank's value + its percentile. |
| **E5** | No box plot, violin, or ridgeline for cross-cluster / cross-state comparison. | P2 | Yes | ECharts boxplot over the existing population metrics. |
| **E6** | Heatmap has no clustered/dendrogram row ordering, no diverging-scale option, no export. | P2 | Yes | Hierarchical row ordering + a diverging scale toggle. |
| **E7** | Branch map has no state boundaries, no zoom/pan, no county choropleth, and excludes Alaska/Hawaii/PR/territories (634 of 76,120 branches). | P1 | Partly | Boundaries need a TopoJSON asset (free, US Census). AK/HI insets need real boundary data — currently `Inherent` without that asset. |
| **E8** | `/market-share` computes real county HHI but never renders it on a map. | P1 | Yes | County choropleth using the same boundary asset as E7. |
| **E9** | Network graph has no layout alternatives, no fit-threshold filter, no degree/path analysis, no cluster isolation. | P2 | Yes | Controls over the existing ECharts graph series. |
| **E10** | No small-multiples time series across a peer set — `/trends` is one bank only. | P1 | Yes | Reuse `get_bank_trends` across a peer set (D5). |
| **E11** | No Sankey/flow visual for funding-mix or loan-mix migration between quarters. | P2 | Yes | ECharts Sankey over QoQ Gold deltas. |
| **E12** | No sparklines in any table. Screener, earnings, credit, funding are flat numbers. | P2 | Yes | Inline SVG sparkline from `get_bank_trends`. |
| **E13** | `/model` has a driver beeswarm but no ROC curve, no PR curve, no calibration plot, no coefficient confidence intervals. The risk score is rendered as a red percentage bar, which visually asserts a probability the model does not produce. | P1 | Yes | Add the three diagnostic plots; reframe the bar as a percentile/decile rather than a percentage. |
| **E14** | No chart accessibility: no data table fallback, no stated colourblind verification, no "download chart data". | P2 | Yes | `<figure>`/`<figcaption>` + a toggleable data table per chart. |
| **E15** | Three chart libraries (Recharts SVG, ECharts canvas, lightweight-charts canvas) with three tooltip idioms, three animation models and inconsistent axis conventions. | P2 | Yes | Do not consolidate libraries (each is the right tool); consolidate the *contract* — one tooltip component, one axis/label/caption convention, one number formatter. |

---

## F · Engineering quality

| ID | Issue | Sev | Fixable? | Mitigation |
|---|---|---|---|---|
| **F1** | **Zero frontend tests.** CI runs typecheck + build only. | P1 | Yes | Vitest + Testing Library on `api.ts`, `colors.ts`, `metricFormat.ts`, and 3–4 page smoke tests. |
| **F2** | Code comments and CI narrative reference **11 files that do not exist**: the entire `docs/` tree, `CHANGELOG.md`, `platform/auth/README.md`, `services/api-gateway/tests/test_route_policy.py`, `pipelines/transforms/tests/test_quantlib_pricing.py`, `pipelines/ingestion/tests/test_fdic.py`, `pipelines/orchestration/README.md`, `docs/features/risk-score/README.md`, `docs/architecture/BankLens-Master-Architecture-Plan.md`, `docs/runbooks/disaster-recovery.md`, `docs/data-contracts/branch_footprint.md`, `docs/api/mcp-tools.md`. | P1 | Yes | Either write them or remove the references. The route/policy drift test in particular is *claimed to exist and to gate CI* and does neither. |
| **F3** | No tests for `filing_diff`, `ma_fit`, `deposit_flight`, `peers`, `footprint`, `market`, `logreg`, `data_quality`, `crosswalk`, `silver`, `quantlib_pricing`, the bridge routes, or `auth`. 7 test files for ~75 modules. | P1 | Yes | Prioritise `peers`, `data_quality`, `ma_fit`, `filing_diff` (pure functions, cheap to test). |
| **F4** | `get_asset_treemap`'s MCP `inputSchema` enum is `["peer_cluster_label", "state"]` but the handler accepts `"country"` — the **only pan-EU grouping is unreachable from any MCP/agent client**. | P2 | Yes | One-line enum fix. |
| **F5** | `banklens_mcp.data._cache` is an unbounded module-level dict with no TTL or invalidation, mutated from a `ThreadingHTTPServer`. Concurrent cold requests duplicate a ~17s computation. | P2 | Yes | A lock around cache fills; a size/TTL bound. |
| **F6** | `stress._ratios()` returns `0.0` when a denominator is missing, so a bank with no leverage denominator shows `0.00%` before *and* after and reports "fails minimum" — a fabricated number presented as a verdict. | P1 | Yes | Return `None` and render "n/a"; exclude from `passes_all`. |
| **F7** | `ma_fit.fit_score`'s no-geo renormalisation performs a double-normalise whose two steps algebraically cancel (`v/s * (s+gw)/s` then `/s2`). Correct result, three lines of dead math. | P3 | Yes | Replace with `v / sum(w.values())`. |
| **F8** | `peers.add_percentile_ranks` is O(n²·m) (~23M comparisons/quarter); `data.network_edges` is O(n²) at ~17s. Fine at 1,049 banks; breaks at 4,500 (B3). | P2 | Yes | Sort-once + `bisect` for percentiles; a blocked/approximate neighbour search for the network. |
| **F9** | `get_branch_map()` with no `state` returns **all ~75,000 branch objects** in one JSON response to the browser. | P1 | Yes | Server-side aggregation to county/H3 cells at low zoom; full detail only when a state is selected. |
| **F10** | No gzip, no `ETag`, no `Cache-Control` on any bridge response. `/api/population` ships the full population on every Overview/Screener/Stress-Lab visit. | P1 | Yes | gzip + `ETag` from a content hash; quarterly data is trivially cacheable. |
| **F11** | Stray `data;C` directory in the repo root — a PowerShell quoting accident. | P3 | Yes | Delete; add to `.gitignore`. |
| **F12** | `.gitignore:` `Cargo.lock  # keep for binaries, ignore for libs` — gitignore has no inline comments, so the pattern is the literal string and never matches. | P3 | Yes | Move the comment to its own line. |
| **F13** | No static type checking on Python (ruff only, no mypy/pyright). | P2 | Yes | Add mypy in non-strict mode to CI. |
| **F14** | No Python lockfile. The bridge Dockerfile does an unpinned `pip install duckdb prometheus-client`. Builds are not reproducible. | P1 | Yes | Pin versions; add `uv.lock` or `requirements.txt` with hashes. |
| **F15** | No SBOM, no dependency scanning, no Dependabot/Renovate. | P2 | Yes | Enable Dependabot; add `pip-audit` + `npm audit` to CI. |
| **F16** | `/api/assistant/ask` has no timeout and no cancellation. A hung Ollama pins a request thread indefinitely (documented as intentional in the code). | P1 | Yes | Server-side deadline + streaming (SSE) so the client sees progress. |
| **F17** | No structured logging, no request IDs, no correlation between a bridge log line and a Grafana metric. `traceback.print_exc()` to stderr. | P2 | Yes | JSON logging with a request ID; expose it in the response header. |
| **F18** | `_dispatch` catches bare `Exception` and returns **400** for everything. A genuine server fault is reported as a client error, so 5xx alerting is impossible. | P1 | Yes | Map `ValueError`/`KeyError` → 400, everything else → 500. |
| **F19** | No OpenAPI/JSON-Schema spec for the 33 REST routes; `types.ts` (676 lines) is hand-maintained and can silently drift. | P1 | Yes | Generate OpenAPI from `ROUTES` + the MCP `inputSchema`s; generate `types.ts` from it. |
| **F20** | `README.md` still says *"Data refreshes are not currently scheduled automatically"* — commit `dd0afe3` added the K8s CronJob. Docs contradict the code. | P2 | Yes | Update the README; add a docs-drift check. |

---

## G · Security, licensing and governance

| ID | Issue | Sev | Fixable? | Mitigation |
|---|---|---|---|---|
| **G1** | The **MCP server has no authorization whatsoever**. Any process that can spawn it gets all 27 tools. `policy.rego` acknowledges this and says the single `/api/assistant/ask` endpoint gate is "the SOLE enforcement point for the entire agent fleet". | P1 | Yes | Per-tool authorization inside the MCP server, driven by the same OPA policy. |
| **G2** | No per-tool authz inside the agent loop: a persona's tool list is a static tuple, unrelated to the caller's roles. | P1 | Yes | Pass caller roles into `run_agent` and filter `_to_tool_schemas` by policy. |
| **G3** | `config/sources.yaml` states *"The serving / MCP layer enforces `license.redistributable` at its boundary."* **No code enforces it.** Tiingo OHLCV is marked non-redistributable and is served raw to any authenticated viewer, with no export gate. | P1 | Yes | Implement the check, or amend the claim. Currently the claim is false in the repo. |
| **G4** | No data-retention policy, no audit-log retention limit, no GDPR posture for a product that explicitly serves EU bank data to EU users. | P2 | Yes | Retention job + a privacy note. |
| **G5** | `BANKLENS_AUTH_ENABLED=false` escape hatch plus `Access-Control-Allow-Headers: *`. Documented, but one env var away from an open service. | P2 | Yes | Refuse to start with auth disabled unless bound to localhost. |
| **G6** | No secrets management. Env files only; K8s manifests contain no `Secret`/SealedSecret/ExternalSecret. | P1 | Yes | K8s `Secret` refs + a documented secret-provisioning step. |
| **G7** | **No disclaimer anywhere in the UI.** The product renders "deposit-flight risk 62%" next to real, named, operating banks with no statement that this is not investment advice, not a supervisory rating, and not a regulatory capital calculation. | P0 | Yes | Persistent footer disclaimer + a first-run modal + disclaimer text embedded in every export. |
| **G8** | Retraining overwrites `ml/deposit_flight/model_card.json` in place. No version, no hash, no history. A score shown in Q1 cannot be reproduced after a Q2 retrain. | P1 | Yes | Content-addressed model cards; record the card hash on every scored result. |
| **G9** | Provenance (source URL, timestamp, checksum) is captured in Bronze but never surfaced — no path from a displayed number to the bytes it came from. | P1 | Yes | Same route as D9. |

---

## Suggested sequencing

**Wave 1 — make it demonstrable (2–3 days).**
A1, A2, A11, G7, F11, F12, F4, F6, F18, F20.
*Outcome: a real URL you can send, with a defensible disclaimer and no fabricated `0.00%` verdicts.*

**Wave 2 — make it deployable for $0 (1 week).**
A3, A4, A5, A6, A7, A8, A9, A10, F10, F14, F16.
*Outcome: static frontend on Cloudflare Pages, bridge on a free VM, Gold as a DuckDB artifact, Neon Postgres, Auth0/Clerk identity, Gemini assistant.*

**Wave 3 — make it credible (1–2 weeks).**
B1, C14, C1, C11, E13, E4, E3, F1, F2, F3, F19, G3, G8, G9, D9.
*Outcome: 20 quarters of history, a real backtest harness, honest model diagnostics, percentiles that mean something, and documentation that matches the code.*

**Wave 4 — make it a workflow tool (2–3 weeks).**
D1, D2, D3, D5, D8, D10, E1, E2, E10, E12, C10.
*Outcome: export, alerts, time travel, custom peer sets, shareable URLs, a scenario library, and market-implied risk.*

**Wave 5 — make it a franchise product (ongoing).**
B3, B4, B6, C4, C5, C6, C9, D4, D11, E7, E8, E11.
*Outcome: the full banking universe, holding companies, real IRRBB/CECL stress modelling, M&A pro-formas, and proper geospatial visualisation.*
