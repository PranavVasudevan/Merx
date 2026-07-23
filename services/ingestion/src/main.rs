//! BankLens production connector SDK (Rust) — SKELETON.
//!
//! Mirrors the `Source` contract from the Python reference
//! (`pipelines/ingestion`): each source implements `discover -> fetch ->
//! checksum -> land`, emitting provenance with every Bronze record and
//! respecting robots.txt / documented rate limits.
//!
//! Fill in during Phase 3 (or earlier if ingestion throughput demands it).
//! Requires the Rust toolchain: https://rustup.rs

fn main() {
    println!("BankLens ingestion (Rust) — not yet implemented. See pipelines/ingestion for the Python reference.");
}

/// The connector contract every source implements.
pub trait Source {
    /// Stable id, e.g. "fdic.bankfind".
    fn name(&self) -> &'static str;
    /// License tag from config/sources.yaml.
    fn license(&self) -> &'static str;
    // async fn fetch(&self, params: FetchParams) -> anyhow::Result<Vec<serde_json::Value>>;
}
