# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses SemVer once it hits `0.1.0`.

## [Unreleased]

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
