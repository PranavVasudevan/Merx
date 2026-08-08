"""Feature 16 — Capital Buffer Simulator (deterministic stress test).

Stress-tests one bank's REAL filed balance sheet under user-defined shocks and shows
how CET1 / Tier 1 / Total / Leverage ratios move against regulatory minimums.

Deliberately transparent math — NOT a model — because stress-test logic must be
auditable. `run_stress_test()` uses a modified-duration approximation for rate
shocks (standard, easy to inspect, and what the Rust port in
services/stress-engine mirrors exactly — verified byte-for-byte, see
CHANGELOG.md). `run_stress_test_quantlib()` is a real upgrade: it replaces that
linear approximation with an actual QuantLib DCF re-price (see
quantlib_pricing.py) that captures convexity, which the linear formula can't.
Both share the same loan-loss/liquidity/SVB-chain logic below via
`_apply_shocks()` — only how the AFS/HTM rate-shock dollar loss gets computed
differs between the two.

Baseline reproduces the bank's reported ratios exactly (we derive RWA / leverage
denominator from the reported capital dollars + ratios), so any change you see is
purely the shock.

The scenario that matters — the SVB chain:
    rate shock -> unrealized securities losses -> deposit outflow forces selling ->
    those losses become REAL -> capital erodes.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

# Regulatory minimums incl. the capital conservation buffer (Basel III).
MINIMUMS = {"cet1": 7.0, "tier1": 8.5, "total": 10.5, "leverage": 4.0}


@dataclass
class Shock:
    loan_loss_pct: float = 0.0        # % of gross loans that go bad
    deposit_outflow_pct: float = 0.0  # % of deposits that leave
    rate_shock_bps: float = 0.0       # parallel rate rise, basis points
    afs_duration: float = 4.0         # modified duration of the AFS book (years)
    htm_duration: float = 6.0         # modified duration of the HTM book (years)
    tax_rate: float = 0.0             # loss tax shield (0 = conservative)
    realize_htm_on_shortfall: bool = True  # forced HTM sales realize their loss
    base_yield: float = 0.045         # assumed current book yield (only used by
                                       # run_stress_test_quantlib's DCF re-price;
                                       # ignored by the linear approximation)


def starting_position(silver: dict) -> dict:
    """Build the deterministic starting point; derive RWA / leverage denom so the
    baseline reproduces the reported ratios exactly."""
    tier1 = silver.get("tier1_capital")
    total_cap = silver.get("total_capital")
    rwa = silver.get("risk_weighted_assets")
    cet1_ratio = silver.get("cet1_ratio")
    lev_ratio = silver.get("leverage_ratio")

    # CET1 capital from its ratio (for WF it equals Tier 1; differs when AT1 exists).
    cet1_cap = (cet1_ratio / 100.0) * rwa if (cet1_ratio and rwa) else tier1
    # Leverage denominator that reproduces the reported leverage ratio.
    lev_denom = tier1 / (lev_ratio / 100.0) if (tier1 and lev_ratio) else silver.get("average_assets")

    return {
        "name": silver.get("name"),
        "quarter": silver.get("quarter"),
        "cet1_capital": cet1_cap,
        "tier1_capital": tier1,
        "total_capital": total_cap,
        "rwa": rwa,
        "lev_denom": lev_denom,
        "total_loans": silver.get("total_loans_gross"),
        "total_deposits": silver.get("total_deposits"),
        "cash": silver.get("cash_and_balances"),
        "securities_afs": silver.get("securities_afs"),
        "securities_htm": silver.get("securities_htm"),
    }


def _ratios(cet1, tier1, total, rwa, lev_denom) -> dict:
    r = lambda num, den: round(num / den * 100, 2) if den and den > 0 else 0.0
    return {"cet1": r(cet1, rwa), "tier1": r(tier1, rwa),
            "total": r(total, rwa), "leverage": r(tier1, lev_denom)}


def _apply_shocks(pos: dict, shock: Shock, afs_loss: float, htm_unrealized: float) -> dict:
    """Shared loan-loss / liquidity / SVB-chain / capital-ratio logic for both
    run_stress_test() and run_stress_test_quantlib() — identical for both,
    only how `afs_loss`/`htm_unrealized` (the rate-shock dollar marks) get
    computed differs between the two callers."""
    loans = pos["total_loans"] or 0.0
    deposits = pos["total_deposits"] or 0.0
    cash = pos["cash"] or 0.0
    afs = pos["securities_afs"] or 0.0
    htm = pos["securities_htm"] or 0.0

    # A missing input is NOT the same as a zero input. The `or 0.0` coercions above
    # are what let the arithmetic run at all, but if the caller asked for a shock leg
    # whose driving input was never disclosed, the result silently comes back with
    # that leg contributing nothing — i.e. a bank asked to survive a 25% deposit run
    # reports completely unchanged ratios, which reads as "immune" rather than
    # "unknown". That is a false reassurance, and worse than an honest gap. Found
    # live on EU (EBA-sourced) banks, which disclose no deposit total at all.
    # Every such leg is named here and surfaced in the result.
    legs_not_applied = []
    if shock.loan_loss_pct and pos.get("total_loans") is None:
        legs_not_applied.append({
            "leg": "loan_loss", "requested_pct": shock.loan_loss_pct,
            "reason": "no total loan balance disclosed for this bank"})
    if shock.deposit_outflow_pct and pos.get("total_deposits") is None:
        legs_not_applied.append({
            "leg": "deposit_outflow", "requested_pct": shock.deposit_outflow_pct,
            "reason": "no deposit total disclosed for this bank (EBA reports a combined "
                      "amortised-cost liabilities figure that also contains issued debt, "
                      "so a deposit run cannot be modelled honestly)"})
    if shock.rate_shock_bps and pos.get("securities_afs") is None and pos.get("securities_htm") is None:
        legs_not_applied.append({
            "leg": "rate_shock", "requested_bps": shock.rate_shock_bps,
            "reason": "no securities portfolio disclosed for this bank"})

    # 1) credit losses on the loan book
    loan_loss = shock.loan_loss_pct / 100.0 * loans

    # 2) deposit outflow -> may force selling HTM, realizing its loss (the SVB chain)
    outflow = shock.deposit_outflow_pct / 100.0 * deposits
    liquidity = cash + afs                            # AFS is sellable; cash on hand
    shortfall = max(0.0, outflow - liquidity)
    htm_sold_frac = min(1.0, shortfall / htm) if (htm > 0 and shock.realize_htm_on_shortfall) else 0.0
    realized_htm_loss = htm_unrealized * htm_sold_frac

    # capital hit (AFS marks flow through AOCI -> CET1; loan + realized HTM losses too)
    gross_hit = loan_loss + afs_loss + realized_htm_loss
    capital_hit = gross_hit * (1.0 - shock.tax_rate)

    new_cet1 = max(0.0, pos["cet1_capital"] - capital_hit)
    new_tier1 = max(0.0, pos["tier1_capital"] - capital_hit)
    new_total = max(0.0, pos["total_capital"] - capital_hit)
    # written-off loans leave the balance sheet -> RWA and total assets shrink
    new_rwa = max(1.0, pos["rwa"] - loan_loss)
    new_lev_denom = max(1.0, pos["lev_denom"] - loan_loss - outflow)

    before = _ratios(pos["cet1_capital"], pos["tier1_capital"], pos["total_capital"],
                     pos["rwa"], pos["lev_denom"])
    after = _ratios(new_cet1, new_tier1, new_total, new_rwa, new_lev_denom)
    verdict = {k: after[k] >= MINIMUMS[k] for k in MINIMUMS}

    return {
        "name": pos["name"], "quarter": pos["quarter"],
        "shock": asdict(shock),
        "before": before, "after": after, "minimums": MINIMUMS,
        "passes": verdict, "passes_all": all(verdict.values()),
        # Empty for a fully-covered bank; non-empty means the headline verdict above
        # reflects FEWER shocks than were requested — read it as partial, not passing.
        "legs_not_applied": legs_not_applied,
        "fully_covered": not legs_not_applied,
        "capital_waterfall": {
            "loan_loss": round(loan_loss, 0),
            "afs_mark_loss": round(afs_loss, 0),
            "htm_realized_loss": round(realized_htm_loss, 0),
            "total_capital_hit": round(capital_hit, 0),
        },
        "liquidity": {
            "deposit_outflow": round(outflow, 0),
            "available_liquidity": round(liquidity, 0),
            "shortfall_forcing_htm_sales": round(shortfall, 0),
            "htm_sold_fraction": round(htm_sold_frac, 3),
            "htm_unrealized_loss_memo": round(htm_unrealized, 0),
        },
    }


def run_stress_test(pos: dict, shock: Shock) -> dict:
    """Apply shocks to a starting position and recompute capital ratios, using
    a modified-duration approximation for rate shocks. This is the version the
    Rust port (services/stress-engine) mirrors exactly."""
    afs = pos["securities_afs"] or 0.0
    htm = pos["securities_htm"] or 0.0

    # rate shock -> mark-to-market losses (modified-duration approximation)
    dy = shock.rate_shock_bps / 10000.0
    afs_loss = afs * shock.afs_duration * dy
    htm_unrealized = htm * shock.htm_duration * dy   # a memo item unless realized

    return _apply_shocks(pos, shock, afs_loss, htm_unrealized)


def run_stress_test_quantlib(pos: dict, shock: Shock) -> dict:
    """Same as run_stress_test(), except the AFS/HTM rate-shock dollar marks
    come from a real QuantLib DCF re-price (quantlib_pricing.py) instead of
    the linear duration approximation — this captures bond convexity, so the
    resulting loss is consistently SMALLER in magnitude than run_stress_test's
    for the same shock (verified in test_quantlib_pricing.py and
    test_stress.py). See quantlib_pricing.py's module docstring for the
    single-representative-bond modeling scope.
    """
    from . import quantlib_pricing  # local: only pay for the QuantLib import on this path

    afs = pos["securities_afs"] or 0.0
    htm = pos["securities_htm"] or 0.0

    afs_loss = quantlib_pricing.loss_from_reprice(
        afs, shock.afs_duration, shock.base_yield, shock.rate_shock_bps)
    htm_unrealized = quantlib_pricing.loss_from_reprice(
        htm, shock.htm_duration, shock.base_yield, shock.rate_shock_bps)

    result = _apply_shocks(pos, shock, afs_loss, htm_unrealized)
    result["pricing_engine"] = "quantlib_dcf_reprice"
    return result
