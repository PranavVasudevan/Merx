# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses SemVer once it hits `0.1.0`.

## [Unreleased]

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
