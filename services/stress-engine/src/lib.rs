//! Capital Buffer Simulator (Feature 16) — SKELETON.
//!
//! Stress-tests a bank's *real, filed* balance sheet under user-defined shocks
//! (loan losses, deposit outflows, rate shock) and recomputes CET1/Tier-1/leverage
//! ratios. Deterministic transparent math — NOT a model — so it is auditable.
//!
//! The signature below fixes the shape; Phase 3 fills the implementation and adds
//! property tests (e.g. "zero shock => ratios unchanged", "ratios monotonic in
//! loss severity").

/// Shock parameters applied to a starting balance sheet.
#[derive(Debug, Clone)]
pub struct ShockParams {
    pub loan_loss_pct: f64,       // % of loans that go bad
    pub deposit_outflow_pct: f64, // % of deposits that leave
    pub rate_shock_bps: f64,      // parallel rate move, basis points
}

/// Before/after capital ratios and the pass/fail verdict vs regulatory minimums.
#[derive(Debug, Clone)]
pub struct StressResult {
    pub cet1_before: f64,
    pub cet1_after: f64,
    pub passes_minimums: bool,
}

/// Placeholder — see Phase 3. Real inputs come from the Gold layer.
pub fn run_stress_test(_starting: &serde_placeholder::BalanceSheet, _shock: &ShockParams) -> StressResult {
    unimplemented!("Phase 3: recompute ratios under shocks against Basel-style minimums")
}

// Temporary stand-in so the skeleton documents intent without extra deps.
pub mod serde_placeholder {
    #[derive(Debug, Clone)]
    pub struct BalanceSheet {
        pub cet1_capital: f64,
        pub risk_weighted_assets: f64,
        pub total_loans: f64,
        pub total_deposits: f64,
    }
}
