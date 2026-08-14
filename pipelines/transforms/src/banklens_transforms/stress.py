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

from .gold import LOAN_CATEGORIES

# Regulatory minimums incl. the capital conservation buffer (Basel III).
MINIMUMS = {"cet1": 7.0, "tier1": 8.5, "total": 10.5, "leverage": 4.0}

# C4 fallback — unchanged from the pre-C4 hardcoded Shock defaults, so a caller
# that never touches duration still gets the exact same numbers as before.
_DEFAULT_AFS_DURATION = 4.0
_DEFAULT_HTM_DURATION = 6.0


@dataclass
class Shock:
    loan_loss_pct: float = 0.0        # % of gross loans that go bad
    deposit_outflow_pct: float = 0.0  # % of deposits that leave
    rate_shock_bps: float = 0.0       # parallel rate rise, basis points
    # C4: None = use this bank's own estimate (starting_position's
    # afs/htm_duration_estimated, see estimate_durations) instead of a single
    # duration assumed for every bank. Pass an explicit float to override.
    afs_duration: float | None = None
    htm_duration: float | None = None
    tax_rate: float = 0.0             # loss tax shield (0 = conservative)
    # C6 — per-category loss rates, keyed by gold.LOAN_CATEGORIES labels
    # (construction, multifamily, nonfarm_nonres, residential_mortgage,
    # farmland, agricultural, c_and_i, consumer — see
    # gold.charge_off_rates_by_category for real disclosed rates to seed
    # these with), applied to that category's OWN gross balance instead of
    # `loan_loss_pct` applied to the whole book. None (default) preserves the
    # pre-C6 single-blended-rate behavior exactly.
    category_loan_loss_pct: dict[str, float] | None = None
    realize_htm_on_shortfall: bool = True  # forced HTM sales realize their loss
    base_yield: float = 0.045         # assumed current book yield (only used by
                                       # run_stress_test_quantlib's DCF re-price;
                                       # ignored by the linear approximation)
    # C4 — multi-period projection (project_multi_period only; ignored by the
    # single-period run_stress_test/run_stress_test_quantlib, which stay exactly
    # as they were for Rust parity).
    horizon_quarters: int = 1
    phase_in: bool = True             # ramp the shock in linearly over the horizon
                                       # rather than applying it all in period 1
    apply_ppnr_offset: bool = True    # let disclosed pre-provision earnings absorb
                                       # part of each period's loss


def estimate_durations(silver: dict) -> dict:
    """C4 — per-bank securities duration from FDIC-disclosed maturity/repricing
    data, falling back to the flat 4y/6y default (the single largest error
    source the stress test has, per this feature's own priority ordering) when
    unavailable — WITH that fallback flagged, never silent.

    Today this always falls back: no FDIC maturity-bucket connector is landed
    (`silver` carries no weighted-average-life field), and this repo's own
    discipline for FDIC field codes is "VERIFIED live against the FDIC API, not
    guessed" (see sources/fdic.py's module docstring) — inventing an unverified
    RC-B maturity-bucket mnemonic here would violate that discipline worse than
    an honest, flagged fallback does. The hook (`securities_afs_weighted_avg_life_years`
    / `_htm_`) is real and wired end to end; landing the source data is the
    follow-up this flags rather than hides.
    """
    afs_wal = silver.get("securities_afs_weighted_avg_life_years")
    htm_wal = silver.get("securities_htm_weighted_avg_life_years")
    return {
        "afs_duration": afs_wal if afs_wal else _DEFAULT_AFS_DURATION,
        "afs_duration_source": "disclosed" if afs_wal else "fallback_default",
        "htm_duration": htm_wal if htm_wal else _DEFAULT_HTM_DURATION,
        "htm_duration_source": "disclosed" if htm_wal else "fallback_default",
    }


def estimate_ppnr_quarterly(silver: dict) -> float | None:
    """C4 — pre-provision net revenue for ONE quarter: (interest income - interest
    expense) + noninterest income - noninterest expense, all disclosed FDIC
    dollar fields. This is the earnings a bank can use to absorb a mild shock
    instead of every shock reading as a pure, one-shot capital hit.

    FDIC's income-statement dollar fields are YTD CUMULATIVE through the
    reporting quarter — the same convention gold.py's YTD-annualized ratios
    are built from (see C15) — so this divides by the quarter number rather
    than treating a Q4 YTD figure as a single quarter's run rate (which would
    overstate a Q1 bank's PPNR by ~4x). `None` if any input is undisclosed or
    the quarter can't be parsed, not a silent zero.
    """
    ii, ie = silver.get("interest_income"), silver.get("interest_expense")
    noi, nox = silver.get("noninterest_income"), silver.get("noninterest_expense")
    if None in (ii, ie, noi, nox):
        return None
    q = silver.get("quarter") or ""
    qnum = int(q[-1]) if q and q[-1].isdigit() and 1 <= int(q[-1]) <= 4 else None
    if not qnum:
        return None
    ytd_ppnr = (ii - ie) + noi - nox
    return ytd_ppnr / qnum


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

    durations = estimate_durations(silver)
    return {
        "name": silver.get("name"),
        "quarter": silver.get("quarter"),
        "cet1_capital": cet1_cap,
        "tier1_capital": tier1,
        "total_capital": total_cap,
        "rwa": rwa,
        "lev_denom": lev_denom,
        "total_loans": silver.get("total_loans_gross"),
        # C6 — per-category gross balances (the same disjoint 8-leaf set
        # gold.concentration_ratios uses), for category_loan_loss_pct.
        "loans_by_category": {label: silver.get(col) for col, label in LOAN_CATEGORIES.items()},
        "total_deposits": silver.get("total_deposits"),
        "cash": silver.get("cash_and_balances"),
        "securities_afs": silver.get("securities_afs"),
        "securities_htm": silver.get("securities_htm"),
        # C4
        "afs_duration_estimated": durations["afs_duration"],
        "afs_duration_source": durations["afs_duration_source"],
        "htm_duration_estimated": durations["htm_duration"],
        "htm_duration_source": durations["htm_duration_source"],
        "ppnr_quarterly_estimated": estimate_ppnr_quarterly(silver),
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
    if shock.category_loan_loss_pct:
        loans_by_category = pos.get("loans_by_category") or {}
        for label, pct in shock.category_loan_loss_pct.items():
            if pct and loans_by_category.get(label) is None:
                legs_not_applied.append({
                    "leg": f"loan_loss:{label}", "requested_pct": pct,
                    "reason": f"no gross loan balance disclosed for category '{label}'"})
    elif shock.loan_loss_pct and pos.get("total_loans") is None:
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

    # 1) credit losses on the loan book — either one blended rate applied to
    # the whole book (pre-C6 behavior, unchanged), or a per-category rate
    # applied to each category's OWN gross balance (C6), decomposed in the
    # result so a CRE-concentrated bank and a consumer-lender respond
    # differently to the same headline "3% loan loss" scenario.
    loss_by_category: dict[str, float] = {}
    if shock.category_loan_loss_pct:
        loans_by_category = pos.get("loans_by_category") or {}
        for label, pct in shock.category_loan_loss_pct.items():
            bal = loans_by_category.get(label) or 0.0
            loss_by_category[label] = round(pct / 100.0 * bal, 0)
        loan_loss = sum(loss_by_category.values())
    else:
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
            # C6 — non-empty only when the shock specified category_loan_loss_pct;
            # decomposes `loan_loss` above by the same disjoint 8-leaf category
            # set gold.concentration_ratios uses.
            "loan_loss_by_category": loss_by_category,
            "afs_mark_loss": round(afs_loss, 0),
            "htm_realized_loss": round(realized_htm_loss, 0),
            "total_capital_hit": round(capital_hit, 0),
        },
        # E3 — the real starting/ending capital DOLLARS behind `before`/`after`'s
        # ratios, already computed above (new_cet1/new_tier1/new_total) but never
        # previously returned: a capital-bridge waterfall needs the actual dollar
        # bookends, not just the ratio move, to show "starting CET1 -> stressed
        # CET1" without inventing a number. Additive-only key, same as
        # `duration_sources` — every existing caller is unaffected.
        "capital_dollars": {
            "cet1_before": round(pos["cet1_capital"], 0), "cet1_after": round(new_cet1, 0),
            "tier1_before": round(pos["tier1_capital"], 0), "tier1_after": round(new_tier1, 0),
            "total_before": round(pos["total_capital"], 0), "total_after": round(new_total, 0),
        },
        "liquidity": {
            "deposit_outflow": round(outflow, 0),
            "available_liquidity": round(liquidity, 0),
            "shortfall_forcing_htm_sales": round(shortfall, 0),
            "htm_sold_fraction": round(htm_sold_frac, 3),
            "htm_unrealized_loss_memo": round(htm_unrealized, 0),
        },
    }


def _resolve_durations(pos: dict, shock: Shock) -> tuple[float, float, dict]:
    """C4 — an explicit Shock.afs_duration/htm_duration (what every caller
    passed before C4, and what the Rust port still assumes) wins; otherwise
    fall back to this bank's own estimate from starting_position. When no
    caller ever overrides and no maturity data is landed, this resolves to
    exactly (4.0, 6.0) — the pre-C4 numeric behavior, unchanged — so
    run_stress_test's `before`/`after`/`capital_waterfall`/`liquidity` stay
    byte-identical to the Rust port for every existing caller; only the new
    `duration_sources` key is additive."""
    afs_dur = shock.afs_duration if shock.afs_duration is not None else \
        pos.get("afs_duration_estimated", _DEFAULT_AFS_DURATION)
    htm_dur = shock.htm_duration if shock.htm_duration is not None else \
        pos.get("htm_duration_estimated", _DEFAULT_HTM_DURATION)
    sources = {
        "afs": "user_override" if shock.afs_duration is not None else
               pos.get("afs_duration_source", "fallback_default"),
        "htm": "user_override" if shock.htm_duration is not None else
               pos.get("htm_duration_source", "fallback_default"),
        "afs_duration_used": afs_dur, "htm_duration_used": htm_dur,
    }
    return afs_dur, htm_dur, sources


def run_stress_test(pos: dict, shock: Shock) -> dict:
    """Apply shocks to a starting position and recompute capital ratios, using
    a modified-duration approximation for rate shocks. This is the version the
    Rust port (services/stress-engine) mirrors exactly."""
    afs = pos["securities_afs"] or 0.0
    htm = pos["securities_htm"] or 0.0
    afs_dur, htm_dur, duration_sources = _resolve_durations(pos, shock)

    # rate shock -> mark-to-market losses (modified-duration approximation)
    dy = shock.rate_shock_bps / 10000.0
    afs_loss = afs * afs_dur * dy
    htm_unrealized = htm * htm_dur * dy   # a memo item unless realized

    result = _apply_shocks(pos, shock, afs_loss, htm_unrealized)
    result["duration_sources"] = duration_sources  # C4 — additive; Rust doesn't emit this
    return result


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
    afs_dur, htm_dur, duration_sources = _resolve_durations(pos, shock)

    afs_loss = quantlib_pricing.loss_from_reprice(
        afs, afs_dur, shock.base_yield, shock.rate_shock_bps)
    htm_unrealized = quantlib_pricing.loss_from_reprice(
        htm, htm_dur, shock.base_yield, shock.rate_shock_bps)

    result = _apply_shocks(pos, shock, afs_loss, htm_unrealized)
    result["pricing_engine"] = "quantlib_dcf_reprice"
    result["duration_sources"] = duration_sources
    return result


def project_multi_period(pos: dict, shock: Shock, horizon_quarters: int | None = None) -> dict:
    """C4 — phase the requested shock in linearly over a multi-quarter horizon
    (clamped to [1, 8]) and let each period's disclosed PPNR
    (`estimate_ppnr_quarterly`, on `pos`) earn back part of that period's loss
    — a mild, sustained shock a bank can out-earn looks different from an
    instantaneous one-shot hit, and the single-period engine can't show that.

    Documented simplification: each period applies its CUMULATIVE share
    (period/horizon of the full requested shock) against the ORIGINAL starting
    balance sheet via `run_stress_test`, then nets that period's PPNR against
    the cumulative capital hit. It does not re-derive a new balance sheet each
    period (no compounding loan-mix/deposit dynamics) — a full multi-period ALM
    model is out of scope for a "deliberately transparent math, not a model"
    module (see the module docstring). `apply_ppnr_offset=False` on the shock
    reproduces the pure, un-offset path.
    """
    horizon = shock.horizon_quarters if horizon_quarters is None else horizon_quarters
    horizon = max(1, min(8, horizon))
    ppnr_q = pos.get("ppnr_quarterly_estimated")
    path = []
    breach_quarter = None
    for period in range(1, horizon + 1):
        frac = (period / horizon) if shock.phase_in else 1.0
        period_shock = Shock(
            loan_loss_pct=shock.loan_loss_pct * frac,
            deposit_outflow_pct=shock.deposit_outflow_pct * frac,
            rate_shock_bps=shock.rate_shock_bps * frac,
            afs_duration=shock.afs_duration, htm_duration=shock.htm_duration,
            tax_rate=shock.tax_rate, realize_htm_on_shortfall=shock.realize_htm_on_shortfall,
            base_yield=shock.base_yield,
        )
        base = run_stress_test(pos, period_shock)
        gross_hit = base["capital_waterfall"]["total_capital_hit"]
        ppnr_available = (ppnr_q * period) if (shock.apply_ppnr_offset and ppnr_q) else 0.0
        ppnr_used = min(ppnr_available, gross_hit) if ppnr_available else 0.0
        net_hit = max(0.0, gross_hit - ppnr_used)

        new_cet1 = max(0.0, pos["cet1_capital"] - net_hit)
        new_tier1 = max(0.0, pos["tier1_capital"] - net_hit)
        new_total = max(0.0, pos["total_capital"] - net_hit)
        new_rwa = max(1.0, pos["rwa"] - base["capital_waterfall"]["loan_loss"])
        new_lev_denom = max(1.0, pos["lev_denom"] - base["capital_waterfall"]["loan_loss"]
                            - base["liquidity"]["deposit_outflow"])
        after = _ratios(new_cet1, new_tier1, new_total, new_rwa, new_lev_denom)
        passes = {k: after[k] >= MINIMUMS[k] for k in MINIMUMS}
        if breach_quarter is None and not all(passes.values()):
            breach_quarter = period
        path.append({
            "quarter_offset": period, "shock_fraction_applied": round(frac, 3),
            "gross_capital_hit": round(gross_hit, 0),
            "ppnr_offset_applied": round(ppnr_used, 0),
            "net_capital_hit": round(net_hit, 0),
            "after": after, "passes": passes, "passes_all": all(passes.values()),
        })
    return {
        "name": pos.get("name"), "quarter": pos.get("quarter"),
        "horizon_quarters": horizon, "phase_in": shock.phase_in,
        "ppnr_offset_applied": shock.apply_ppnr_offset,
        "ppnr_quarterly_estimated": ppnr_q,
        "path": path,
        "breach_quarter": breach_quarter,
        "survives_full_horizon": breach_quarter is None,
    }


def liquidity_survival_horizon(pos: dict, shock: Shock, *, max_quarters: int = 8) -> dict:
    """C4 — a real liquidity metric the engine never had: given a SUSTAINED
    per-quarter deposit-outflow rate (`shock.deposit_outflow_pct`, read here as
    "this fraction of REMAINING deposits leaves EVERY quarter", not a one-time
    shock), how many full quarters of on-balance-sheet liquidity (cash + AFS,
    the same sellable definition `_apply_shocks` uses, plus HTM if
    `realize_htm_on_shortfall`) does the bank have before a quarter's outflow
    can't be covered? Same SVB-chain liquidity ordering as the single-period
    engine — HTM is the last resort, not the first.
    """
    deposits = pos.get("total_deposits") or 0.0
    cash = pos.get("cash") or 0.0
    afs = pos.get("securities_afs") or 0.0
    htm = pos.get("securities_htm") or 0.0
    if not deposits or not shock.deposit_outflow_pct:
        return {"applicable": False,
                "reason": "no deposits disclosed, or no sustained outflow rate given",
                "quarters_survived": None, "breach_quarter": None}

    remaining_deposits = deposits
    remaining_liquidity = cash + afs + (htm if shock.realize_htm_on_shortfall else 0.0)
    for q in range(1, max_quarters + 1):
        outflow = remaining_deposits * (shock.deposit_outflow_pct / 100.0)
        if outflow > remaining_liquidity:
            return {"applicable": True, "quarters_survived": q - 1, "breach_quarter": q,
                    "max_quarters_checked": max_quarters,
                    "quarterly_outflow_pct": shock.deposit_outflow_pct}
        remaining_liquidity -= outflow
        remaining_deposits -= outflow
    return {"applicable": True, "quarters_survived": max_quarters, "breach_quarter": None,
            "max_quarters_checked": max_quarters, "quarterly_outflow_pct": shock.deposit_outflow_pct}


# C4 — documented modeling ASSUMPTIONS for the correlated joint-scenario mode
# (NOT empirically fit), matching the module's own "SVB chain" causal story: a
# rate shock is the trigger, and the deposit-outflow / loan-loss legs move WITH
# it, not as three sliders a user has to coordinate by hand. Publish/replace
# with a fitted relationship once the backtest harness (C14) has enough real
# cases (B6's failure/M&A history) to estimate one instead of assume it.
CORRELATION_ASSUMPTIONS = {
    "mild":     {"deposit_outflow_per_100bps": 1.5, "loan_loss_per_100bps": 0.3},
    "moderate": {"deposit_outflow_per_100bps": 3.0, "loan_loss_per_100bps": 0.6},
    "severe":   {"deposit_outflow_per_100bps": 6.0, "loan_loss_per_100bps": 1.2},
}


def correlated_scenario(rate_shock_bps: float, severity: str = "moderate", **overrides) -> Shock:
    """C4 — one JOINT, correlated scenario instead of three independent legs a
    user sets by hand: a rate shock is the trigger, and deposit-outflow/loan-
    loss scale with it via `CORRELATION_ASSUMPTIONS`. `severity` in
    {"mild","moderate","severe"}. `**overrides` still lets a caller pin any
    other Shock field (e.g. `tax_rate`, `horizon_quarters`) on top of the
    derived legs.
    """
    if severity not in CORRELATION_ASSUMPTIONS:
        raise ValueError(f"severity must be one of {sorted(CORRELATION_ASSUMPTIONS)}, got '{severity}'")
    coef = CORRELATION_ASSUMPTIONS[severity]
    hundreds_of_bps = rate_shock_bps / 100.0
    fields = {
        "rate_shock_bps": rate_shock_bps,
        "deposit_outflow_pct": round(hundreds_of_bps * coef["deposit_outflow_per_100bps"], 3),
        "loan_loss_pct": round(hundreds_of_bps * coef["loan_loss_per_100bps"], 3),
    }
    fields.update(overrides)
    return Shock(**fields)
