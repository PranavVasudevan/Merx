# services/ingestion — production connector SDK (Rust)

The throughput- and safety-oriented rewrite of `pipelines/ingestion`. Same
`Source` contract, but async (tokio), Arrow-native writes, and object-store
landing for real Bronze tables.

**Status:** skeleton. Build begins when ingestion volume/backfill demands leaving
Python — until then the Python reference in `pipelines/ingestion` is authoritative.

Install Rust first: https://rustup.rs — then `cargo run`.
