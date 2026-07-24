# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses SemVer once it hits `0.1.0`.

## [Unreleased]

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
