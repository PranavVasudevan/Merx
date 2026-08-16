//! Capital Buffer Simulator (Feature 16) — real Rust port of
//! `pipelines/transforms/src/banklens_transforms/stress.py`, ported line-for-line
//! (not reimagined) so the two engines are provably interchangeable: same
//! inputs, same outputs. Byte-for-byte parity against the Python reference was
//! verified locally before this landed (see `CHANGELOG.md`'s Phase 9 entry) —
//! there is no committed automated parity harness that shells out to Python and
//! diffs on every CI run; the `tests` module below (deterministic cases plus
//! proptest property tests) is what actually runs in CI, see
//! `.github/workflows/ci.yml`'s `rust` job.
//!
//! Deliberately transparent, deterministic math — NOT a model — because
//! stress-test logic must be auditable. QuantLib is bridged in later for real
//! duration/curve analytics; this keeps the same modified-duration
//! approximation as the Python reference for now.
//!
//! The scenario that matters — the SVB chain: rate shock -> unrealized
//! securities losses -> deposit outflow forces selling -> those losses become
//! REAL -> capital erodes.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Regulatory minimums including the capital conservation buffer (Basel III).
pub fn minimums() -> HashMap<&'static str, f64> {
    HashMap::from([("cet1", 7.0), ("tier1", 8.5), ("total", 10.5), ("leverage", 4.0)])
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Shock {
    #[serde(default)]
    pub loan_loss_pct: f64,
    #[serde(default)]
    pub deposit_outflow_pct: f64,
    #[serde(default)]
    pub rate_shock_bps: f64,
    #[serde(default = "default_afs_duration")]
    pub afs_duration: f64,
    #[serde(default = "default_htm_duration")]
    pub htm_duration: f64,
    #[serde(default)]
    pub tax_rate: f64,
    #[serde(default = "default_true")]
    pub realize_htm_on_shortfall: bool,
}

fn default_afs_duration() -> f64 { 4.0 }
fn default_htm_duration() -> f64 { 6.0 }
fn default_true() -> bool { true }

impl Default for Shock {
    fn default() -> Self {
        Shock {
            loan_loss_pct: 0.0, deposit_outflow_pct: 0.0, rate_shock_bps: 0.0,
            afs_duration: default_afs_duration(), htm_duration: default_htm_duration(),
            tax_rate: 0.0, realize_htm_on_shortfall: true,
        }
    }
}

/// Raw Silver fields needed to build a starting position — the Rust analogue
/// of the `silver` dict `starting_position()` takes in the Python reference.
#[derive(Debug, Clone, Deserialize)]
pub struct Silver {
    pub name: Option<String>,
    pub quarter: Option<String>,
    pub tier1_capital: Option<f64>,
    pub total_capital: Option<f64>,
    pub risk_weighted_assets: Option<f64>,
    pub cet1_ratio: Option<f64>,
    pub leverage_ratio: Option<f64>,
    pub average_assets: Option<f64>,
    pub total_loans_gross: Option<f64>,
    pub total_deposits: Option<f64>,
    pub cash_and_balances: Option<f64>,
    pub securities_afs: Option<f64>,
    pub securities_htm: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct StartingPosition {
    pub name: Option<String>,
    pub quarter: Option<String>,
    pub cet1_capital: f64,
    pub tier1_capital: f64,
    pub total_capital: f64,
    // F6 (docs/audit/04-remediation-prompts.md) — a bank can genuinely have
    // no RWA (the CBLR framework: real leverage ratio, no risk-based ratios
    // at all) or no leverage denominator (no leverage_ratio AND no
    // average_assets fallback) disclosed at all. `Option`, not a silent
    // 0.0/unwrap_or, mirroring `pipelines/transforms/src/banklens_transforms/
    // stress.py`'s `starting_position()` returning `None` for either — see
    // that module's own F6 comment for the false-reassurance bug this fixes
    // (a missing denominator used to read as a fabricated "0.00%" that then
    // FAILED the regulatory minimum on a number that was never computed).
    pub rwa: Option<f64>,
    pub lev_denom: Option<f64>,
    pub total_loans: f64,
    pub total_deposits: f64,
    pub cash: f64,
    pub securities_afs: f64,
    pub securities_htm: f64,
}

/// Python truthiness for an `Option<f64>`: `None` and `Some(0.0)` are both falsy.
fn truthy(x: Option<f64>) -> bool {
    matches!(x, Some(v) if v != 0.0)
}

/// Build the deterministic starting point; derive RWA / leverage denominator
/// so the baseline reproduces the bank's reported ratios exactly.
pub fn starting_position(s: &Silver) -> StartingPosition {
    let cet1_capital = if truthy(s.cet1_ratio) && truthy(s.risk_weighted_assets) {
        (s.cet1_ratio.unwrap() / 100.0) * s.risk_weighted_assets.unwrap()
    } else {
        s.tier1_capital.unwrap_or(0.0)
    };
    let lev_denom = if truthy(s.tier1_capital) && truthy(s.leverage_ratio) {
        Some(s.tier1_capital.unwrap() / (s.leverage_ratio.unwrap() / 100.0))
    } else {
        s.average_assets
    };

    StartingPosition {
        name: s.name.clone(),
        quarter: s.quarter.clone(),
        cet1_capital,
        tier1_capital: s.tier1_capital.unwrap_or(0.0),
        total_capital: s.total_capital.unwrap_or(0.0),
        rwa: s.risk_weighted_assets,
        lev_denom,
        total_loans: s.total_loans_gross.unwrap_or(0.0),
        total_deposits: s.total_deposits.unwrap_or(0.0),
        cash: s.cash_and_balances.unwrap_or(0.0),
        securities_afs: s.securities_afs.unwrap_or(0.0),
        securities_htm: s.securities_htm.unwrap_or(0.0),
    }
}

fn round_to(x: f64, decimals: i32) -> f64 {
    let f = 10f64.powi(decimals);
    (x * f).round_ties_even() / f
}

// F6 — `den` is `None` for an undisclosed denominator (no fabricated 0.00%);
// mirrors stress.py's `_ratios()`: `round(num/den*100, 2) if den and den > 0
// else None`.
fn ratio(num: f64, den: Option<f64>) -> Option<f64> {
    match den {
        Some(d) if d > 0.0 => Some(round_to(num / d * 100.0, 2)),
        _ => None,
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Ratios {
    pub cet1: Option<f64>,
    pub tier1: Option<f64>,
    pub total: Option<f64>,
    pub leverage: Option<f64>,
}

fn ratios(cet1: f64, tier1: f64, total: f64, rwa: Option<f64>, lev_denom: Option<f64>) -> Ratios {
    Ratios {
        cet1: ratio(cet1, rwa), tier1: ratio(tier1, rwa),
        total: ratio(total, rwa), leverage: ratio(tier1, lev_denom),
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct CapitalWaterfall {
    pub loan_loss: f64,
    pub afs_mark_loss: f64,
    pub htm_realized_loss: f64,
    pub total_capital_hit: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Liquidity {
    pub deposit_outflow: f64,
    pub available_liquidity: f64,
    pub shortfall_forcing_htm_sales: f64,
    pub htm_sold_fraction: f64,
    pub htm_unrealized_loss_memo: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct StressResult {
    pub name: Option<String>,
    pub quarter: Option<String>,
    pub before: Ratios,
    pub after: Ratios,
    pub minimums: HashMap<&'static str, f64>,
    // F6 — only ratios that were actually computed get a verdict; a None
    // ratio (no disclosed denominator) is excluded here, not defaulted to a
    // failing entry.
    pub passes: HashMap<&'static str, bool>,
    // F6 — `None` when nothing could be assessed at all (e.g. neither RWA
    // nor a leverage denominator disclosed), mirroring stress.py's
    // `all(verdict.values()) if verdict else None`.
    pub passes_all: Option<bool>,
    pub ratios_not_computed: Vec<&'static str>,
    pub capital_waterfall: CapitalWaterfall,
    pub liquidity: Liquidity,
}

/// Apply shocks to a starting position and recompute capital ratios — the
/// exact logic of `stress.py::run_stress_test`, not a reinterpretation.
pub fn run_stress_test(pos: &StartingPosition, shock: &Shock) -> StressResult {
    let loans = pos.total_loans;
    let deposits = pos.total_deposits;
    let cash = pos.cash;
    let afs = pos.securities_afs;
    let htm = pos.securities_htm;

    // 1) credit losses on the loan book
    let loan_loss = shock.loan_loss_pct / 100.0 * loans;

    // 2) rate shock -> mark-to-market losses (modified-duration approximation)
    let dy = shock.rate_shock_bps / 10000.0;
    let afs_loss = afs * shock.afs_duration * dy;
    let htm_unrealized = htm * shock.htm_duration * dy; // a memo item unless realized

    // 3) deposit outflow -> may force selling HTM, realizing its loss (the SVB chain)
    let outflow = shock.deposit_outflow_pct / 100.0 * deposits;
    let liquidity_available = cash + afs;
    let shortfall = (outflow - liquidity_available).max(0.0);
    let htm_sold_frac = if htm > 0.0 && shock.realize_htm_on_shortfall {
        (shortfall / htm).min(1.0)
    } else {
        0.0
    };
    let realized_htm_loss = htm_unrealized * htm_sold_frac;

    // capital hit (AFS marks flow through AOCI -> CET1; loan + realized HTM losses too)
    let gross_hit = loan_loss + afs_loss + realized_htm_loss;
    let capital_hit = gross_hit * (1.0 - shock.tax_rate);

    let new_cet1 = (pos.cet1_capital - capital_hit).max(0.0);
    let new_tier1 = (pos.tier1_capital - capital_hit).max(0.0);
    let new_total = (pos.total_capital - capital_hit).max(0.0);
    // written-off loans leave the balance sheet -> RWA and total assets
    // shrink. F6 — an undisclosed denominator (None) stays None, never
    // "0.0 minus a real number".
    let new_rwa = pos.rwa.map(|r| (r - loan_loss).max(1.0));
    let new_lev_denom = pos.lev_denom.map(|d| (d - loan_loss - outflow).max(1.0));

    let before = ratios(pos.cet1_capital, pos.tier1_capital, pos.total_capital, pos.rwa, pos.lev_denom);
    let after = ratios(new_cet1, new_tier1, new_total, new_rwa, new_lev_denom);
    let mins = minimums();
    // F6 — only insert a verdict for a ratio that was actually computed;
    // mirrors stress.py's `{k: after[k] >= MINIMUMS[k] for k in MINIMUMS if
    // after[k] is not None}`.
    let mut passes: HashMap<&'static str, bool> = HashMap::new();
    let mut ratios_not_computed: Vec<&'static str> = Vec::new();
    for (key, value) in [("cet1", after.cet1), ("tier1", after.tier1),
                         ("total", after.total), ("leverage", after.leverage)] {
        match value {
            Some(v) => { passes.insert(key, v >= mins[key]); }
            None => ratios_not_computed.push(key),
        }
    }
    let passes_all = if passes.is_empty() { None } else { Some(passes.values().all(|&v| v)) };

    StressResult {
        name: pos.name.clone(),
        quarter: pos.quarter.clone(),
        before, after, minimums: mins, passes, passes_all, ratios_not_computed,
        capital_waterfall: CapitalWaterfall {
            loan_loss: round_to(loan_loss, 0),
            afs_mark_loss: round_to(afs_loss, 0),
            htm_realized_loss: round_to(realized_htm_loss, 0),
            total_capital_hit: round_to(capital_hit, 0),
        },
        liquidity: Liquidity {
            deposit_outflow: round_to(outflow, 0),
            available_liquidity: round_to(liquidity_available, 0),
            shortfall_forcing_htm_sales: round_to(shortfall, 0),
            htm_sold_fraction: round_to(htm_sold_frac, 3),
            htm_unrealized_loss_memo: round_to(htm_unrealized, 0),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn sample_position() -> StartingPosition {
        // Real-shaped figures (order of magnitude of an actual $20-40B regional
        // bank's balance sheet), not fabricated to make tests trivially pass.
        StartingPosition {
            name: Some("TEST BANK".into()), quarter: Some("2026Q1".into()),
            cet1_capital: 2_500_000_000.0, tier1_capital: 2_500_000_000.0,
            total_capital: 2_900_000_000.0, rwa: Some(17_000_000_000.0),
            lev_denom: Some(34_000_000_000.0), total_loans: 22_000_000_000.0,
            total_deposits: 28_000_000_000.0, cash: 2_000_000_000.0,
            securities_afs: 4_000_000_000.0, securities_htm: 3_000_000_000.0,
        }
    }

    #[test]
    fn zero_shock_leaves_ratios_unchanged() {
        let pos = sample_position();
        let res = run_stress_test(&pos, &Shock::default());
        assert!((res.before.cet1.unwrap() - res.after.cet1.unwrap()).abs() < 1e-9);
        assert!((res.before.tier1.unwrap() - res.after.tier1.unwrap()).abs() < 1e-9);
        assert!((res.before.total.unwrap() - res.after.total.unwrap()).abs() < 1e-9);
        assert!((res.before.leverage.unwrap() - res.after.leverage.unwrap()).abs() < 1e-9);
        assert_eq!(res.capital_waterfall.total_capital_hit, 0.0);
    }

    #[test]
    fn baseline_reproduces_reported_ratios_exactly() {
        // starting_position() must derive cet1_capital/lev_denom such that the
        // BEFORE ratios equal what a real filing would report, to the cent.
        let silver = Silver {
            name: Some("WELLS-LIKE".into()), quarter: Some("2026Q1".into()),
            tier1_capital: Some(150_000_000_000.0), total_capital: Some(180_000_000_000.0),
            risk_weighted_assets: Some(1_200_000_000_000.0), cet1_ratio: Some(11.2),
            leverage_ratio: Some(8.5), average_assets: Some(1_900_000_000_000.0),
            total_loans_gross: Some(900_000_000_000.0), total_deposits: Some(1_300_000_000_000.0),
            cash_and_balances: Some(150_000_000_000.0), securities_afs: Some(100_000_000_000.0),
            securities_htm: Some(200_000_000_000.0),
        };
        let pos = starting_position(&silver);
        let res = run_stress_test(&pos, &Shock::default());
        assert!((res.before.tier1.unwrap() - 12.5).abs() < 0.01); // 150B / 1.2T
        assert!((res.before.leverage.unwrap() - 8.5).abs() < 0.01);
    }

    // F6 — a bank with no disclosed RWA (the CBLR-framework shape: real
    // capital dollars and a real leverage ratio, no risk-based ratios/RWA at
    // all — see pipelines/transforms/src/banklens_transforms/data_quality.py's
    // capital_basis()) must report cet1/tier1/total as None, not a fabricated
    // 0.00% that then fails the regulatory minimum on a number that was
    // never computed. Mirrors pipelines/transforms/tests/test_stress.py's
    // test_no_disclosed_rwa_reports_cet1_tier1_total_as_none_not_zero.
    #[test]
    fn no_disclosed_rwa_reports_cet1_tier1_total_as_none_not_zero() {
        let mut pos = sample_position();
        pos.rwa = None;
        let res = run_stress_test(&pos, &Shock { loan_loss_pct: 3.0, ..Shock::default() });
        assert!(res.before.cet1.is_none());
        assert!(res.after.cet1.is_none());
        assert!(res.before.tier1.is_none());
        assert!(res.before.total.is_none());
        assert!(!res.passes.contains_key("cet1"));
        assert_eq!(
            res.ratios_not_computed.iter().collect::<std::collections::HashSet<_>>(),
            std::collections::HashSet::from([&"cet1", &"tier1", &"total"]),
        );
        // Leverage has a real denominator (untouched) -- unaffected by the RWA gap.
        assert!(res.after.leverage.is_some());
        assert!(res.passes.contains_key("leverage"));
    }

    #[test]
    fn no_leverage_denominator_reports_leverage_as_none_not_zero() {
        let mut pos = sample_position();
        pos.lev_denom = None;
        let res = run_stress_test(&pos, &Shock { loan_loss_pct: 3.0, ..Shock::default() });
        assert!(res.before.leverage.is_none());
        assert!(res.after.leverage.is_none());
        assert!(!res.passes.contains_key("leverage"));
        assert_eq!(res.ratios_not_computed, vec!["leverage"]);
        assert!(res.after.cet1.is_some());
        assert!(res.passes.contains_key("cet1"));
    }

    #[test]
    fn missing_every_denominator_gets_passes_all_none_not_a_fabricated_verdict() {
        let mut pos = sample_position();
        pos.rwa = None;
        pos.lev_denom = None;
        let res = run_stress_test(&pos, &Shock { loan_loss_pct: 3.0, ..Shock::default() });
        assert!(res.passes.is_empty());
        assert!(res.passes_all.is_none());
        assert_eq!(
            res.ratios_not_computed.iter().collect::<std::collections::HashSet<_>>(),
            std::collections::HashSet::from([&"cet1", &"tier1", &"total", &"leverage"]),
        );
    }

    #[test]
    fn missing_denominator_does_not_prevent_the_shock_from_being_applied() {
        // A missing RATIO denominator is orthogonal to whether the shock
        // itself ran -- capital_waterfall (real dollar amounts) must still
        // reflect the real loan loss even though the resulting percentage
        // can't be expressed.
        let mut pos = sample_position();
        pos.rwa = None;
        let res = run_stress_test(&pos, &Shock { loan_loss_pct: 10.0, ..Shock::default() });
        // 10% of a 22B loan book.
        assert!((res.capital_waterfall.loan_loss - 2_200_000_000.0).abs() < 1.0);
    }

    proptest! {
        #[test]
        fn ratios_are_monotonically_non_increasing_in_loan_loss_severity(
            loss_a in 0.0f64..30.0, loss_b in 0.0f64..30.0,
        ) {
            let pos = sample_position();
            let (lo, hi) = if loss_a <= loss_b { (loss_a, loss_b) } else { (loss_b, loss_a) };
            let res_lo = run_stress_test(&pos, &Shock { loan_loss_pct: lo, ..Shock::default() });
            let res_hi = run_stress_test(&pos, &Shock { loan_loss_pct: hi, ..Shock::default() });
            // A strictly larger loss can never leave you with MORE capital.
            prop_assert!(res_hi.after.cet1.unwrap() <= res_lo.after.cet1.unwrap() + 1e-9);
            prop_assert!(res_hi.after.tier1.unwrap() <= res_lo.after.tier1.unwrap() + 1e-9);
        }

        #[test]
        fn capital_ratios_never_negative(
            loan_loss in 0.0f64..100.0, outflow in 0.0f64..100.0, rate_bps in 0.0f64..1000.0,
        ) {
            let pos = sample_position();
            let shock = Shock {
                loan_loss_pct: loan_loss, deposit_outflow_pct: outflow,
                rate_shock_bps: rate_bps, ..Shock::default()
            };
            let res = run_stress_test(&pos, &shock);
            prop_assert!(res.after.cet1.unwrap() >= 0.0);
            prop_assert!(res.after.tier1.unwrap() >= 0.0);
            prop_assert!(res.after.total.unwrap() >= 0.0);
            prop_assert!(res.after.leverage.unwrap() >= 0.0);
        }

        #[test]
        fn htm_sold_fraction_always_in_unit_range(
            outflow in 0.0f64..200.0, rate_bps in 0.0f64..2000.0,
        ) {
            let pos = sample_position();
            let shock = Shock {
                deposit_outflow_pct: outflow, rate_shock_bps: rate_bps, ..Shock::default()
            };
            let res = run_stress_test(&pos, &shock);
            prop_assert!(res.liquidity.htm_sold_fraction >= 0.0);
            prop_assert!(res.liquidity.htm_sold_fraction <= 1.0);
        }
    }
}
