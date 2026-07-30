# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses SemVer once it hits `0.1.0`.

## [Unreleased]

### Added — Phase 8 started (containerization + Kubernetes manifests)
- Real Dockerfiles: `services/api-gateway/Dockerfile` (Python bridge, non-root, healthcheck, preserves the exact relative source-tree depth `REPO=Path(__file__).resolve().parents[N]` expects) and `frontend/apps/web/Dockerfile` (multi-stage Node build → nginx serve). `.dockerignore` at repo root and in the frontend dir.
- Fixed a real bug this surfaced: `bridge_server.py` bound to `localhost` unconditionally, which is unreachable from outside a container. Now configurable via `BANKLENS_BRIDGE_HOST` (defaults to `localhost` for local dev, containers set `0.0.0.0`).
- `platform/docker/docker-compose.app.yml` + `scripts/docker_up.ps1` for local compose-based testing (separate from the pre-existing `docker-compose.dev.yml`, which is data-infra scaffolding not yet wired to any real code — clarified in `platform/docker/README.md`).
- `platform/k8s/base/` (Deployment + Service for the bridge and web, deliberately modest resource requests/limits, health probes) and `platform/k8s/overlays/dev/` (a `banklens-dev` namespace, a `hostPath` volume patch for local `data/`, NodePort for the web UI) — **validated for real** with `kubectl kustomize` (zero warnings after fixing two deprecated Kustomize fields it flagged, correct resulting YAML). `overlays/staging` and `overlays/prod` are deliberately left as documented stubs rather than speculative, unvalidatable config.
### Verified — Docker build/run confirmed for real (Docker Desktop came up after a reinstall to a new per-user path)
- Both images built and ran for real via `docker compose -f platform/docker/docker-compose.app.yml up`. **Found and fixed a real bug this way:** the bridge image was missing `ml/` (the trained deposit-flight model card), surfacing as an honest "Deposit-flight model not trained yet" error rather than silently misbehaving — fixed with `COPY ml /app/ml` in the Dockerfile (small versioned model artifacts belong baked in like source, not volume-mounted like `data/`).
- Confirmed end-to-end in a real browser against the real containers: zero console errors, real Silver/Gold/X-Ray/clustering/stress/M&A/risk-score data served from the containerized bridge to the containerized frontend.
- Kubernetes: still not applied to a live cluster — Docker Desktop's Kubernetes is a separate opt-in GUI toggle (Settings → Kubernetes → Enable), which can't be driven from a terminal. The `kubectl kustomize` manifest validation from the item above stands; only the live-cluster `kubectl apply` step remains unverified, and it's a one-time manual toggle away.

### Changed — Phase 1o (Feature 15's geo-overlap upgraded to real FDIC branch data — with a real data-quality bug found and worked around)
- New keyless connector `sources/sod.py` (FDIC Summary of Deposits — real branch-level data, ~76,120 records for 2025, paginated ~8 requests). Landed via `scripts/land_sod.ps1`.
- **Real finding, verified live before building anything on top of it:** FDIC's own `STALP`/`CITY`/`ADDRESS` fields are frozen at the bank's HEADQUARTERS address for every branch record — checked on Citizens Bank (984 branches, all reading "Providence, RI, 1 Citizens Plz" despite `SIMS_LATITUDE`/`SIMS_LONGITUDE` on those same records spanning Florida to Washington state) and Dime Community Bank (63 branches, same pattern). Only the geocoded coordinates are trustworthy per-branch.
- New `transforms/footprint.py`: builds real branch footprints from coordinates only (grid-cell binning, ~0.4°≈27-30mi "local market" cells) rather than ever trusting the broken state/city fields. Two overlap metrics: plain cell-Jaccard (`cell_overlap`) and a deposit-weighted variant (`deposit_weighted_overlap`, using real branch-level `DEPSUMBR`).
- `ma_fit.py`'s `geo_overlap` now takes real footprint dicts instead of a crude single-HQ-state proxy; `rank_partners`/`fit_score` signatures updated (`footprints=` replaces `states=`); rationale text now says "N shared local market(s)" instead of "N shared state(s)". `mcp-server/data.py` gained a `footprints()` accessor (bank-level CERT keying — no crosswalk needed, unlike the ticker case); `find_ma_matches` MCP tool and `ma_fit_cli.py` updated.
- **The ranking genuinely changed, not just cosmetically:** Dime Community Bank's real footprint = 63 branches spanning 10 distinct local markets (correctly derived from coordinates alone despite the broken city/state fields). Geo-overlap now differentiates candidates meaningfully (Apple Bank 0.43, several others correctly 0.00) instead of a same-state/different-state binary. **The #1 M&A match changed from Flagstar to Provident Bank** once real geography replaced the proxy.
- 8 new tests (5 footprint.py incl. a regression fixture built from the real Citizens Bank coordinates, 3 sod.py pagination). 135 tests total (was 127). Docs: `docs/data-contracts/branch_footprint.md`, `config/sources.yaml` updated, `services/feature-services/ma-fit/README.md` rewritten. Verified end-to-end in-browser: M&A panel correctly shows the new ranking, zero console errors.

### Changed — Phase 1n (Feature 13 pooled across two real crises — 2023 + 2008)
- Verified real 2008 FDIC failure data before assuming anything fit: **Washington Mutual ($307.02B assets) exceeds the $1B-$250B population band by 10-60x** every other training example — documented as a deliberate `EXCLUDED_CANDIDATES` exclusion (size-confound risk), not silently dropped. **IndyMac Bank ($30.70B, CERT 29730)** fits cleanly and is thematically apt (a real, famous depositor run).
- Landed the 2008Q1 population (669 banks, the quarter before IndyMac's July-2008 failure) and 2007Q1 deposits (for the growth feature) to Bronze.
- Found and fixed a real data-quality bug live: FDIC uses **-1 as a "not reported" sentinel** in some pre-2008 dollar fields (found in IndyMac's historical `SCHA`/HTM data) — previously would've been silently misread as -$1,000. Fixed in `silver.py`'s `_to_usd`, with a test that also confirms a genuinely negative equity (an insolvent bank) is correctly preserved, not discarded.
- `deposit_flight.py`: `POSITIVE_CERTS` now pools 4 real failures across 2 crises; `train()` retrains on 2022Q4 + 2008Q1 combined (n=1,655).
- **Honest empirical result, not assumed:** IndyMac's 2008Q1 profile (13% uninsured, 0% HTM/equity) is a genuinely different failure archetype from the 2023 cohort (subprime-credit-driven, late retail panic vs. institutional deposit flight) — leave-one-out **does not flag it** (rank 1499/1655, 9.5th percentile), while SVB/Signature/First Republic still rank 93.9-98.5th percentile. In-sample AUC dropped from 0.992 to 0.938 — an expected, informative consequence of a harder, differently-shaped positive, not a regression to hide.
- Documentation updated to state this plainly rather than only report favorable numbers: `services/feature-services/risk-score/README.md`, the MCP tool's response `note`, and the frontend's Feature-13 heading (now reads the model's actual `model_trained_on` field dynamically instead of a hardcoded "2022Q4").
- 1 new test (`test_minus_one_sentinel_treated_as_missing_not_minus_1000`). 127 tests total.

### Added — Phase 2a (real market data — the last piece of the original "quant terminal" vision)
- `sources/tiingo.py`: EOD OHLCV connector, verified against Tiingo's own docs (endpoint, field names, `Authorization: Token` auth). Free tier (250 calls/day, 50 symbols/hour) but genuinely requires a key — the one BankLens source that isn't keyless, unlike FDIC/SEC/Fed/FRED.
- `transforms/market.py`: Silver OHLCV mapping + Gold derivations (realized volatility annualized, 52-week range, a single-row price snapshot). 9 hermetic tests.
- MCP tools `get_price_candles` / `get_market_snapshot` (11 tools total now) — reads a bank's ticker via the crosswalk, restricted to `exact`/`high_confidence` matches only (a `low_confidence` match, like Dime's real Community/Commercial discrepancy, is deliberately never used here — showing the wrong company's stock would be worse than no chart).
- `scripts/land_market_data.ps1` + `market_cli.py`: reads real tickers straight from the crosswalk built in Phase 1j (255 exact/high-confidence matches available), lands EOD history respecting the free-tier limits, skips already-fresh tickers on re-run.
- REST bridge endpoints `/api/banks/candles`, `/api/banks/market-snapshot`.
- Frontend: real candlestick chart (`CandlestickChart.tsx`, TradingView's `lightweight-charts`) plus a price/volatility/52-week snapshot bar. Verified in-browser: the honest empty-state renders correctly for both "no ticker match" (Dime) and "ticker matched, no data landed" (Zions) cases; the actual chart-rendering code path was verified separately with a temporarily mocked fetch response (realistic synthetic OHLC) — 7 canvas layers rendered, zero console errors. Real data was never pulled in this environment (no Tiingo key available).
- Docs: `docs/data-contracts/market_prices.md`; `config/sources.yaml` updated (Tiingo now the named vendor, SEC EDGAR corrected from "planned" to "active").
- 14 new tests (market.py + tiingo.py), total 126 (was 112).

### Fixed — Phase 6c (5 real bugs found running the agent live, plus an honest capability ceiling)
- `agent_ask.ps1`: PowerShell parameter binding sent a bare question string to `-Persona` instead of `-Question` (no explicit `Position` attributes → implicit positional binding in declaration order). Fixed with `[CmdletBinding(PositionalBinding = $false)]` + explicit `Position = 0` on `-Question`.
- `ollama_client.py`: the non-forced tool-call branch built a `tool_use` block from `parsed.get("arguments", {})` without checking it was actually a dict — a model emitting `{"tool": "x", "arguments": "cert 6976"}` (string, not object) crashed `agent.py`'s `_call_signature` (`.items()` on a str). Now validated with `isinstance(..., dict)` before use.
- `ollama_client._extract_json`: fixed at the source — now rejects any successfully-parsed JSON that isn't a dict (a bare quoted string, number, array, or boolean is valid JSON but not a valid tool-call object; every caller assumed dict semantics and crashed on `.get()`).
- `server.py`: `_coerce_arguments` ran *outside* the try/except in `tools/call`, so a malformed non-dict `arguments` value crashed the whole MCP server subprocess instead of producing a clean in-band tool error. Moved inside the try block.
- `agent.py`: `_looks_like_stray_tool_call` only caught one malformed shape (tool name as a dict key); broadened to also catch `{"tool": "name", ...flattened args...}` (tool name as a `"tool"` field's value). `_finalize()` also now gives an honest "couldn't parse, try again" message instead of showing a raw artifact when there's no real tool data to fall back on either.
- 8 new regression tests, one per bug. Total: 112 (was 106).
- **Documented, not fixed (because it isn't a code bug):** an open-ended multi-step question caused the model to hallucinate a fake certificate number and confabulate an answer instead of first looking up real candidates. A genuine reasoning-capability ceiling of a 1B local model — no further defensive parsing addresses it. Single-step, cert-specific questions are reliably grounded in real tool data; open-ended ones are where Ollama's limits show. See `services/agents/README.md`.

### Added — Phase 6b (multi-provider agents: Ollama default, Gemini multi-key, real bugs fixed)
- **Provider abstraction** (`providers.py`): `anthropic_client.py`, `gemini_client.py`, `ollama_client.py` all implement the identical `messages_create(...) -> {"content": [...], "stop_reason": ...}` shape, so `agent.py`/`supervisor.py` are fully provider-agnostic. Default is **`ollama`** (`BANKLENS_LLM_PROVIDER` env var overrides) — this project has a hard $0 spending rule.
- **`gemini_client.py`**: native Gemini function-calling, translating Anthropic-shaped messages/tools/tool_choice to/from Gemini's wire format (system_instruction/contents/function_declarations/tool_config). `gemini_keys.py` is a near-verbatim port of project-matcher's own key-rotation module — "1 main + 4 backups" via `GEMINI_API_KEY` + `GEMINI_API_KEY_1..4` (or `GEMINI_API_KEYS` comma list), rotating past 401/403/429.
- **`ollama_client.py`**: a plain-text tool-call protocol (describe tools in-prompt, extract JSON robustly) rather than Ollama's native `/api/chat` tool-calling — that native path returned corrupted output when tested live against `qwen2.5-coder:3b` on this machine (even a plain "say hello" came back garbled). Default model `llama3.2:1b`, confirmed working cleanly.
- **Three real bugs found and fixed by actually running the agent live** (Ollama, $0, no mocks):
  1. MCP server (`server.py`): a local model sent `{"cert": "6976"}` (string) for an integer param, failing a dict lookup with a misleading error. Added `_coerce_arguments()` against each tool's declared schema — benefits every MCP client, not just weak local models.
  2. `agent.py`: the model reliably got correct tool results but kept re-issuing the identical call instead of answering. Added duplicate-call detection (answered from cache, not re-invoked) + a nudge, escalating to a forced `tools=None` synthesis call after two repeats — guarantees loop termination with a real answer.
  3. `agent.py`: even with real data in hand, the model's "final answer" was sometimes itself a malformed tool-call-shaped JSON fragment. Added `_looks_like_stray_tool_call` detection with a fallback that surfaces the real underlying tool data instead of a confusing artifact.
  - After all three fixes: a real, live, fully-local run produced a coherent, factually-correct risk summary for Dime Community Bank, grounded in the real `get_bank_xray` result.
- 34 new tests, all hermetic (no API key, no live network) — `test_gemini_keys.py`, `test_gemini_client.py`, `test_ollama_client.py`, `test_providers.py` (incl. asserting the default IS the free provider), regression tests for all three bugs in `test_agent_loop.py`, coercion tests in `test_mcp.py`.
- `.env.example` documents the full provider setup; `cli.py`/`agent_ask.ps1`/`run_eval.py` gained `--provider`.

### Added — Phase 1j (CERT↔CIK↔RSSD crosswalk + SEC EDGAR connector)
- `sources/sec.py`: SEC EDGAR connector — the ticker/CIK directory (single request, 10,432 filers) and per-filer XBRL company facts. Politeness enforced (identifying UA, 10 req/s cap) per SEC's requirements.
- Added `NAMEHCR`/`RSSDHCR`/`RSSDID` (holding-company identity) to the FDIC connector + Silver — the join keys. Discovered some banks (Zions, Flagstar) have **no separate holding company** (eliminated their BHC structure) — the crosswalk falls back to the bank's own identity for those.
- `transforms/crosswalk.py`: dependency-free fuzzy name matching (stdlib `difflib`), symmetric corporate/banking-suffix stripping, and **first-token blocking** before fuzzy scoring — added after a real false positive was caught (Dime Community Bancshares almost matched an unrelated Kentucky bank, "Community Trust Bancorp," purely on generic word overlap; blocking on the first distinguishing token fixed it and cut runtime 25s → 0.4s). Transparent confidence tiers (exact/high/low/none) — low-confidence matches are surfaced for review, never silently dropped.
- Real result: 1,002 holding companies vs 8,017 SEC filers → 52.5% match rate (234 exact, 21 high-confidence, 271 low-confidence). A documented naming discrepancy survives correctly as low-confidence: FDIC says "Dime Community," SEC's registered title says "Dime Commercial" (same company, ticker DCOM).
- Live cross-source validation (`scripts/crosswalk.ps1 -Verify`): Zions' FDIC bank-level assets ($87.96B) exactly match its SEC holding-company assets (no separate HC); Wells Fargo's SEC figure ($2.15T) correctly exceeds its FDIC bank-subsidiary figure ($1.85T, superset as expected).
- 9 new tests including a regression test for the false-positive bug. Docs: `docs/data-contracts/crosswalk.md`.

### Added — Phase 6 (Agentic AI — supervisor + specialists over MCP)
- `services/agents`: a supervisor (forced-tool-call routing on Haiku) dispatches to one of 4 specialists (Risk Analyst, Filings Analyst, M&A Scout, Macro/Stress), each with a focused MCP tool subset and system prompt, matching the master plan's roster.
- `anthropic_client.py`: hand-rolled Messages API client over stdlib `urllib` — no `anthropic` pip package, same zero-install philosophy as the FDIC connector. Reads `ANTHROPIC_API_KEY` from env or `.env`, never hardcoded.
- `mcp_client.py`: reusable MCP stdio JSON-RPC client (refactored out of `scripts/mcp_demo.py`) — agents reach BankLens **only** through the same MCP surface the UI and CLI use.
- `agent.py`: the tool-calling loop (bounded to 6 turns), with every tool call recorded to a transcript saved at `data/agent_runs/<ts>.json` — a second, agent-side audit trail alongside the MCP server's own.
- `scripts/agent_ask.ps1` — `powershell -File scripts/agent_ask.ps1 "..."`.
- Tests runnable **without** an API key: real MCP round-trip, persona/tool-registry consistency, key-resolution, and the full tool-calling loop against the real MCP server with only the LLM call mocked (9 + 2 = 11 new tests, all passing). A routing-quality eval harness (`run_eval.py` + `eval_questions.json`) is included but needs a live key to run.
- **Honest limitation:** the live LLM-in-the-loop path (an actual Claude call) was not exercised in this environment — no Anthropic API key was available to this session. The user runs it with their own key.

### Added — Phase 7 (Quant Terminal UI — reference)
- `services/api-gateway/src/bridge_server.py`: dependency-free REST bridge (stdlib `http.server`) wrapping `banklens_mcp.tools` — the same logic the MCP server exposes, now callable from a browser. Extended `get_bank_profile` with full loan-composition + all capital ratios + peer percentiles (benefits both MCP and REST).
- `frontend/apps/web`: React + TypeScript + Vite quant terminal. Charts via Recharts, styled with the validated dataviz skill palette (light/dark via `prefers-color-scheme`). Colors resolved in JS (`colors.ts`) since SVG fill attributes don't reliably read CSS `var()`.
- Panels for all 6 features: KPI tiles, X-Ray (severity + peer percentile bars), loan-composition & capital-adequacy charts, Filing Diff, Peer Cluster card, Risk Score (gauge + diverging driver bars), M&A Fit (sequential-hue ranking), Stress Simulator (live sliders → waterfall + pass/fail), and a 1,000+ bank peer-position scatter (target vs population, avoiding the categorical color-cap problem).
- Bank search combobox, calling the population search endpoint.
- **Honest scope:** no market OHLC/candlesticks — that needs the not-yet-built market-data connector (Phase 2); every chart here reads real FDIC-derived data, nothing mocked.
- `scripts/dev_web.ps1`, `scripts/api_bridge.ps1`. Verified end-to-end (accessibility-tree + network trace): all panels render correct real data, bank-switching refetches everything, sliders drive live recalculation, filing-diff degrades gracefully for banks without landed multi-quarter history.

### Added — Phase 1i (Feature 13 — Deposit-Flight ML, the showcase) — ALL 6 FEATURES DONE
- `transforms/logreg.py`: pure-Python L2-regularized, class-weighted logistic regression + rank-AUC. Chosen over XGBoost on purpose (tiny labeled set → linear model is the honest choice; coefficients are the interpretability).
- `transforms/deposit_flight.py`: features (uninsured %, HTM/equity, securities/assets, loan/deposit, 1yr deposit growth), training, model card I/O, per-bank scoring with coefficient-contribution drivers.
- Trained on the **2022Q4 cross-section** (pre-crisis), positives = the real 2023 failures SVB/Signature/First Republic (CERTs from the FDIC failures list). **In-sample AUC 0.992.**
- **Honest leave-one-out validation:** trained *without* SVB, SVB still ranks 13/986 (98.8th pctile); Signature 99.7th; First Republic 95.9th. Uninsured-deposit reliance is the dominant coefficient.
- `deposit_flight_cli.py` + `scripts/deposit_flight.ps1`; model card at `ml/deposit_flight/model_card.json`.
- MCP `get_risk_score` tool scores current (2026Q1) banks with the trained model → the 9th tool. Applied to 2026Q1, median risk 0.002 with structurally-all-uninsured specialists at the top (resemblance ≠ certainty — documented).
- `test_deposit_flight.py` (logreg separation, AUC, feature math, monotonic scoring). Data landed: 2022Q4 + 2021Q4 populations, 2023 failures list.

### Added — Phase 1h (MCP server — the tool surface)
- `services/mcp-server`: dependency-free MCP server (JSON-RPC 2.0 over stdio) exposing the 5 working features as 8 tools (`list_banks`, `get_bank_profile`, `get_bank_xray`, `diff_filings`, `get_peer_cluster`, `find_ma_matches`, `run_stress_test`, `compare_banks`). Thin wrappers over `banklens_transforms` — same logic as the CLIs.
- Per-call audit to `data/mcp_audit.jsonl`; population Gold + percentiles + clusters cached on startup.
- `scripts/mcp_demo.py` drives the server over real stdio (handshake → tools/list → tool calls); `test_mcp.py` covers the protocol hermetically. Project-scoped `.mcp.json` makes the tools usable inside Claude Code.
- Re-landed the 1,049-bank population with capital-dollar fields so `run_stress_test` works across the slice.
- **Milestone: one backend, three consumers (CLI / SDK / agents) — the project thesis, working.**

### Added — Phase 1g (Feature 15 — M&A Fit Finder)
- `transforms/ma_fit.py`: ranks acquirer/partner candidates by funding complementarity (deposit-rich fills loan-heavy), business similarity (cosine on loan mix), size compatibility, and geographic overlap. Pure functions over Gold; geography uses home-state as a proxy (FDIC Summary of Deposits branch footprints = Phase-2 upgrade).
- `banklens_ingestion/ma_fit_cli.py` + `scripts/ma_fit.ps1`: ranked candidates with a per-match rationale.
- Real result: for Dime Community Bank (NY, CRE-heavy), the top fit is Flagstar (former NYCB) — a 5.8×-larger NY CRE lender — then other NY CRE banks. Textbook in-market consolidation, straight from the feature vectors.
- `test_ma_fit.py`: complementarity/ similarity/ size/ geo components + ranking.

### Added — Phase 1f (Feature 12 — Filing Diff)
- `transforms/filing_diff.py`: quarter-over-quarter change detection that flags a move when it is a statistical outlier vs *that bank's own* history (z-score on same-span changes, excluding the evaluated transition), gated by a materiality floor. Falls back to an absolute threshold when there's no volatility baseline.
- `banklens_ingestion/filing_diff_cli.py` + `scripts/filing_diff.ps1`: a structured "what changed and why it matters" report between two quarters.
- Real results: WF C&I loans +7.3% (z=+3.0); Dime HTM securities +4.7% but z=+21 — a tiny absolute move that's a huge outlier for that bank (exactly what absolute cutoffs miss).
- `test_filing_diff.py`: sudden jump flagged, smooth drift ignored, default compares two newest.

### Added — Phase 1e (Feature 16 — Capital Buffer Simulator)
- Verified FDIC capital-dollar codes: `RBCT1J` (Tier 1 $), `RBC` (Total $), `RWAJT` (RWA $), `ASSET5` (avg assets), `CHBAL` (cash), `SCHA` (HTM amortized cost — direct, replaces the SC−SCAF derivation). Wired into the connector + Silver.
- `transforms/stress.py`: deterministic Basel-style stress test — loan losses, rate shock (modified-duration AFS/HTM marks), and deposit outflow that forces HTM firesales (the SVB chain). Baseline reproduces reported ratios exactly; recomputes CET1/Tier1/Total/Leverage vs minimums with a capital waterfall + liquidity trace.
- `banklens_ingestion/stress_cli.py` + `scripts/stress_test.ps1`. On Wells Fargo: moderate scenario dips Total RBC just under 10.5%; a 70% deposit run forces a full HTM firesale ($55B realized) and wipes capital to 0% — SVB reproduced on a real balance sheet.
- `test_stress.py`: zero-shock reproduces reported ratios; monotonic in loss; severe breaches minimums; SVB chain realizes HTM.

### Added — Phase 1d (Feature 14 — Peer Group Redefiner)
- `transforms/clustering.py`: dependency-free K-Means (k-means++ init, standardized features), silhouette scoring, degenerate-k rejection, cluster labeling. (ML-platform phase swaps in scikit-learn/MLflow.)
- `banklens_ingestion/clustering_cli.py` + `scripts/cluster_report.ps1`: behavioral clusters, silhouette-by-k diagnostic, asset-size × cluster crosstab, and a bank's peer standing with a "misclassified by size" flag. Writes `peer_cluster_id` + `peer_cluster_label` to Gold.
- Result (2026Q1 slice): 7 behavioral archetypes; Dime Community Bank clusters with Flagstar/Valley/Bank OZK/Banc of California and is flagged behaviorally atypical for its size.
- `test_clustering.py` (K-Means recovery, silhouette, k-selection, imputation).

### Added — Phase 1c (peer set + percentile ranks)
- Population fetch of the MVP slice (US banks $1B–$250B, 1,049 banks for 2026Q1) landed to Bronze in a single filtered request.
- `transforms/peers.py`: `percentile_rank`, `add_percentile_ranks`, `summary_stats` — a bank's standing vs its peers.
- `gold.gold_features(row, prev=None)`: cross-sectional deriver (population = one quarter × many banks) refactored out of `derive_gold`.
- X-Ray flags now carry `peer_percentile` when ranks are attached.
- `banklens_ingestion.population` + `scripts/population_report.ps1`: slice distribution, leaderboards (CRE, uninsured, CET1), and one bank's peer standing. Dime Community Bank: 73.8% CRE = 93rd percentile of peers.

### Added — Phase 1b (Feature 11 X-Ray + real concentration/capital)
- Verified (probed, not guessed) FDIC codes for full loan composition, securities (AFS), and the four regulatory capital ratios (CET1/Tier1/Total/Leverage).
- Silver: loan-composition columns, `cre_loans` aggregate, `core_deposits`, capital-ratio pass-through, derived `securities_htm`.
- Gold: `concentration_ratio_*` per loan category, `max_loan_concentration_*`, `cre_to_equity_pct`, corrected `uninsured_deposit_pct` (uses reported `DEPUNINS`), `core_deposit_pct`.
- **Feature 11 — Balance-Sheet X-Ray** (`transforms/xray.py`): rule-based, auditable risk scoring with severity flags. Proven on real data (Wells Fargo → ELEVATED; Dime Community Bank → HIGH on 73.8% CRE, 471% of capital).
- Test that our computed ratios **match FDIC's own reported ratios** (LNLSDEPR, EQV).
- CLI: single-request fetch (fewer calls) + `--from-bronze` mode to re-run transforms offline.
- Connector hardened: cookie-aware opener, browser-like headers, wider retry set.

### Added — Phase 1a
- Repository scaffold (industry-grade polyglot monorepo).
- FDIC BankFind connector (Python, stdlib-only) landing raw records to Bronze with provenance.
- Silver normalisation (`bank_financials`) — units, dates, code mapping, uninsured-deposit derivation.
- Gold reference metrics — `uninsured_deposit_pct`, `loan_to_deposit_pct`, `equity_to_assets_pct`, QoQ deltas.
- Vertical-slice CLI + tests pinned to real Wells Fargo figures.
- Architecture plan, domain study guide, ADR seeds, data contract, source registry.
