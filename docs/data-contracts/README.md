# Data contracts

Versioned, tested descriptions of the medallion tables. A contract is the
agreement between producers (pipelines) and consumers (features/tools/agents):
change it deliberately, and CI fails a breaking change.

- [`bank_financials.silver.md`](bank_financials.silver.md) — the canonical per-bank-per-quarter row.

Machine-readable schemas live in [`../../schemas/`](../../schemas/).
