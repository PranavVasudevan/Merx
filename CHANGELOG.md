# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses SemVer once it hits `0.1.0`.

## [Unreleased]

### Added
- **Phase 1 (in progress):** repository scaffold (industry-grade polyglot monorepo).
- FDIC BankFind connector (Python, stdlib-only) landing raw records to Bronze with provenance.
- Silver normalisation (`bank_financials`) — units, dates, code mapping, uninsured-deposit derivation.
- Gold reference metrics — `uninsured_deposit_pct`, `loan_to_deposit_pct`, `equity_to_assets_pct`, QoQ deltas.
- Vertical-slice CLI + tests pinned to real Wells Fargo figures.
- Architecture plan, domain study guide, ADR seeds, data contract, source registry.
