//! Feature 16 runner — the Rust engine's CLI, mirroring
//! `pipelines/ingestion/src/banklens_ingestion/stress_cli.py`'s UX so the two
//! are drop-in interchangeable for the same real landed Bronze data:
//!
//!     cargo run --release --bin banklens-stress -- --cert 3511 --loan-loss 4 --outflow 25 --rate-bps 250
//!
//! NOTE on scope: this extracts only the ~13 raw FDIC fields Feature 16 needs
//! (capital dollars, ratios, loans/deposits/cash/securities) using the same
//! unit-conversion rules as `banklens_transforms.silver.to_bank_financials`
//! (thousands -> USD, the FDIC "-1 means not reported" sentinel, REPDTE ->
//! quarter label). It is NOT a full port of silver.py — loan composition,
//! the CRE aggregate, and the CIK/RSSD crosswalk fields live only in Python
//! today. Porting exactly what this binary uses keeps the claim honest.

use serde_json::Value;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

use banklens_stress_engine::{run_stress_test, starting_position, Shock, Silver};

struct Args {
    cert: i64,
    data_dir: PathBuf,
    loan_loss: f64,
    outflow: f64,
    rate_bps: f64,
    json: bool,
}

fn parse_args() -> Result<Args, String> {
    let mut cert: Option<i64> = None;
    let mut data_dir = PathBuf::from("data");
    let mut loan_loss = 3.0;
    let mut outflow = 15.0;
    let mut rate_bps = 200.0;
    let mut json = false;

    let argv: Vec<String> = env::args().skip(1).collect();
    let mut i = 0;
    while i < argv.len() {
        match argv[i].as_str() {
            "--cert" => { i += 1; cert = Some(argv.get(i).ok_or("--cert needs a value")?.parse().map_err(|_| "bad --cert")?); }
            "--data-dir" => { i += 1; data_dir = PathBuf::from(argv.get(i).ok_or("--data-dir needs a value")?); }
            "--loan-loss" => { i += 1; loan_loss = argv.get(i).ok_or("--loan-loss needs a value")?.parse().map_err(|_| "bad --loan-loss")?; }
            "--outflow" => { i += 1; outflow = argv.get(i).ok_or("--outflow needs a value")?.parse().map_err(|_| "bad --outflow")?; }
            "--rate-bps" => { i += 1; rate_bps = argv.get(i).ok_or("--rate-bps needs a value")?.parse().map_err(|_| "bad --rate-bps")?; }
            "--json" => { json = true; }
            other => return Err(format!("unknown argument: {other}")),
        }
        i += 1;
    }
    Ok(Args {
        cert: cert.ok_or("--cert is required")?,
        data_dir, loan_loss, outflow, rate_bps, json,
    })
}

fn to_usd(v: Option<&Value>) -> Option<f64> {
    let n = v.and_then(|v| if v.is_null() { None } else { v.as_f64().or_else(|| v.as_str().and_then(|s| s.parse().ok())) })?;
    // FDIC's "-1 means not reported" sentinel (found live in pre-2008 SCHA data) —
    // NOT a real -$1,000. See silver.py::_to_usd for the same rule in Python.
    if n == -1.0 { None } else { Some(n * 1000.0) }
}

fn to_ratio(v: Option<&Value>) -> Option<f64> {
    v.and_then(|v| if v.is_null() { None } else { v.as_f64().or_else(|| v.as_str().and_then(|s| s.parse().ok())) })
}

fn parse_quarter(repdte: Option<&Value>) -> Option<String> {
    let s = repdte.and_then(|v| v.as_i64().map(|n| n.to_string()).or_else(|| v.as_str().map(String::from)))?;
    if s.len() < 8 { return None; }
    let month = &s[4..6];
    let year = &s[0..4];
    let q = match month { "03" => 1, "06" => 2, "09" => 3, "12" => 4, _ => return None };
    Some(format!("{year}Q{q}"))
}

fn silver_from_raw(raw: &Value) -> Silver {
    let g = |k: &str| raw.get(k);
    Silver {
        name: g("NAMEFULL").and_then(|v| v.as_str()).map(String::from),
        quarter: parse_quarter(g("REPDTE")),
        tier1_capital: to_usd(g("RBCT1J")),
        total_capital: to_usd(g("RBC")),
        risk_weighted_assets: to_usd(g("RWAJT")),
        cet1_ratio: to_ratio(g("IDT1CER")),
        leverage_ratio: to_ratio(g("RBC1AAJ")),
        average_assets: to_usd(g("ASSET5")),
        total_loans_gross: to_usd(g("LNLSGR")),
        total_deposits: to_usd(g("DEP")),
        cash_and_balances: to_usd(g("CHBAL")),
        securities_afs: to_usd(g("SCAF")),
        securities_htm: to_usd(g("SCHA")).or_else(|| {
            match (to_usd(g("SC")), to_usd(g("SCAF"))) {
                (Some(total), Some(afs)) => Some(total - afs),
                _ => None,
            }
        }),
    }
}

fn fmt_usd(v: f64) -> String {
    format!("${:.2}B", v / 1e9)
}

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => { eprintln!("error: {e}"); return ExitCode::FAILURE; }
    };

    let path = args.data_dir.join("bronze").join("source=fdic")
        .join(format!("cert={}", args.cert)).join("records.json");
    let raw_text = match fs::read_to_string(&path) {
        Ok(t) => t,
        Err(e) => { eprintln!("error reading {}: {e}", path.display()); return ExitCode::FAILURE; }
    };
    let records: Vec<Value> = match serde_json::from_str(&raw_text) {
        Ok(r) => r,
        Err(e) => { eprintln!("error parsing {}: {e}", path.display()); return ExitCode::FAILURE; }
    };
    let Some(latest) = records.first() else {
        eprintln!("no records in {}", path.display());
        return ExitCode::FAILURE;
    };

    let silver = silver_from_raw(latest);
    let pos = starting_position(&silver);
    if pos.tier1_capital == 0.0 || pos.rwa == 0.0 {
        println!("  Missing capital-dollar fields for CERT {}. Re-land Bronze with the extended field set (RBCT1J, RBC, RWAJT).", args.cert);
        return ExitCode::SUCCESS;
    }

    let shock = Shock {
        loan_loss_pct: args.loan_loss, deposit_outflow_pct: args.outflow,
        rate_shock_bps: args.rate_bps, ..Shock::default()
    };
    let res = run_stress_test(&pos, &shock);

    if args.json {
        println!("{}", serde_json::to_string_pretty(&res).unwrap());
        return ExitCode::SUCCESS;
    }

    let w = 72;
    println!("{}", "=".repeat(w));
    println!("  FEATURE 16 — CAPITAL BUFFER SIMULATOR (Rust engine)");
    println!("  {}  —  {}", res.name.as_deref().unwrap_or("?"), res.quarter.as_deref().unwrap_or("?"));
    println!("{}", "=".repeat(w));
    println!("  Starting balance sheet:  Tier1 {}   RWA {}", fmt_usd(pos.tier1_capital), fmt_usd(pos.rwa));
    println!("    loans {}   deposits {}   cash {}", fmt_usd(pos.total_loans), fmt_usd(pos.total_deposits), fmt_usd(pos.cash));
    println!("    securities AFS {} / HTM {}", fmt_usd(pos.securities_afs), fmt_usd(pos.securities_htm));
    println!("\n  SCENARIO");
    println!("    loan losses {:.1}%   deposit outflow {:.1}%   rate shock +{:.0} bps",
             args.loan_loss, args.outflow, args.rate_bps);
    println!("\n  CAPITAL WATERFALL (what erodes capital)");
    println!("    loan losses ......... {}", fmt_usd(res.capital_waterfall.loan_loss));
    println!("    AFS mark-to-market .. {}", fmt_usd(res.capital_waterfall.afs_mark_loss));
    println!("    realized HTM loss ... {}", fmt_usd(res.capital_waterfall.htm_realized_loss));
    println!("    -> total capital hit  {}", fmt_usd(res.capital_waterfall.total_capital_hit));
    println!("\n  LIQUIDITY / SVB CHAIN");
    println!("    deposit outflow {}  vs  liquidity {}",
             fmt_usd(res.liquidity.deposit_outflow), fmt_usd(res.liquidity.available_liquidity));
    if res.liquidity.shortfall_forcing_htm_sales > 0.0 {
        println!("    shortfall {} FORCES selling {:.0}% of HTM -> loss becomes REAL",
                 fmt_usd(res.liquidity.shortfall_forcing_htm_sales), res.liquidity.htm_sold_fraction * 100.0);
    } else {
        println!("    liquidity covers the outflow — HTM losses stay unrealized (memo: {} hidden)",
                 fmt_usd(res.liquidity.htm_unrealized_loss_memo));
    }
    println!("\n  CAPITAL RATIOS         before   ->   after     min    verdict");
    for (label, key) in [("CET1", "cet1"), ("Tier 1 RBC", "tier1"), ("Total RBC", "total"), ("Tier 1 leverage", "leverage")] {
        let (before, after, min, pass) = match key {
            "cet1" => (res.before.cet1, res.after.cet1, res.minimums["cet1"], res.passes["cet1"]),
            "tier1" => (res.before.tier1, res.after.tier1, res.minimums["tier1"], res.passes["tier1"]),
            "total" => (res.before.total, res.after.total, res.minimums["total"], res.passes["total"]),
            _ => (res.before.leverage, res.after.leverage, res.minimums["leverage"], res.passes["leverage"]),
        };
        let mark = if pass { "PASS" } else { "** FAIL **" };
        println!("    {label:<18} {before:>6.2}%  -> {after:>6.2}%   {min:>5.1}%   {mark}");
    }
    println!("\n  OVERALL: {}", if res.passes_all { "PASS — stays above all regulatory minimums" }
                                else { "FAIL — breaches a regulatory minimum" });
    println!("{}", "=".repeat(w));
    ExitCode::SUCCESS
}
