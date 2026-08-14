"""Feature 16 (C5) — Interest Rate Risk in the Banking Book (IRRBB): a
repricing-gap approximation for Economic Value of Equity (EVE) sensitivity and
12-month Net Interest Income (NII) sensitivity.

Interest-rate risk is the mechanism behind the 2023 failures this product is
built around (SVB) and was, before this module, entirely unmodeled outside the
stress simulator's one-off rate-shock leg. Doing nothing here would leave the
single most relevant risk in the product's own origin story unaddressed.

WHY this is an approximation, not a precise model: a real EVE/NII calculation
needs a bank's repricing-bucket schedule (FFIEC Schedule RC-B/RC broken out by
maturity/repricing bucket). FDIC's public BankFind API — the only source this
repo lands, under a strict "VERIFIED live against the API, not guessed" field
discipline (see sources/fdic.py's module docstring) — does not expose that
schedule as landed fields today. Inventing an unverified bucket field code
would violate that discipline worse than an honest, coarse approximation with
the gap named. `bucket_coarseness` on every result says exactly that: which
inputs are real disclosed dollars, which durations are per-bank estimates
(shared with the stress engine's own rate-shock leg — the SAME
stress.estimate_durations call, not a second parallel guess), and which are
industry-typical ASSUMED durations for books FDIC doesn't disclose a schedule
for at all (loans, deposits).
"""

from __future__ import annotations

# C5 — documented ASSUMED average durations for books FDIC discloses only a
# dollar TOTAL for, never a repricing/maturity schedule. Not bank-specific, not
# fitted to real data — coarse, industry-typical figures, flagged as such in
# every result's `bucket_coarseness`. Securities use the REAL per-bank estimate
# from stress.estimate_durations instead (see starting_position, C4).
ASSUMED_LOAN_DURATION_YEARS = 3.0      # mixed loan book: blend of fixed/adjustable-rate
ASSUMED_DEPOSIT_DURATION_YEARS = 1.5   # blended non-maturity + time-deposit repricing


def _reprice_fraction(duration_years: float, horizon_years: float = 1.0) -> float:
    """Coarse repricing-within-horizon share from an average duration: a book
    with average duration D reprices roughly 1/D of its balance per year — a
    straight-line approximation, not a real cash-flow ladder."""
    if duration_years <= 0:
        return 1.0
    return min(1.0, horizon_years / duration_years)


def compute_irrbb(pos: dict, *, parallel_shock_bps: float = 200.0,
                  steepener_short_bps: float = -100.0, steepener_long_bps: float = 100.0) -> dict:
    """`pos` is a `stress.starting_position()` dict — it already carries the
    real disclosed AFS/HTM/loan/deposit totals and the C4 per-bank duration
    estimates this reuses rather than recomputing. Returns EVE sensitivity and
    12-month NII sensitivity under a parallel rate shift and one non-parallel
    (steepener: short rates down, long rates up) scenario.
    """
    securities = (pos.get("securities_afs") or 0.0) + (pos.get("securities_htm") or 0.0)
    loans = pos.get("total_loans") or 0.0
    deposits = pos.get("total_deposits") or 0.0
    equity = pos.get("cet1_capital") or 0.0

    afs, htm = pos.get("securities_afs") or 0.0, pos.get("securities_htm") or 0.0
    afs_d = pos.get("afs_duration_estimated", 4.0)
    htm_d = pos.get("htm_duration_estimated", 6.0)
    sec_duration = (afs * afs_d + htm * htm_d) / securities if securities else 0.0

    def eve_delta(dy_short_bps: float, dy_long_bps: float) -> float:
        # Standard duration-gap EVE approximation: -(D_A*A - D_L*L) * dy — but
        # with no bucket data to split WITHIN a book, this maps each BOOK
        # (not each bucket) to whichever end of the curve its typical
        # repricing character resembles: securities (the longer-duration
        # book here) take the long-end shock; loans/deposits (shorter,
        # ASSUMED durations) take the short-end shock. A pure parallel shift
        # passes the same bps to both ends, which reduces this to the
        # standard single-shock duration-gap formula.
        dy_s, dy_l = dy_short_bps / 10000.0, dy_long_bps / 10000.0
        d_assets = securities * sec_duration * dy_l + loans * ASSUMED_LOAN_DURATION_YEARS * dy_s
        d_liabs = deposits * ASSUMED_DEPOSIT_DURATION_YEARS * dy_s
        return -(d_assets - d_liabs)

    def nii_delta_12mo(dy_short_bps: float, dy_long_bps: float) -> float:
        dy_s, dy_l = dy_short_bps / 10000.0, dy_long_bps / 10000.0
        rsa = (securities * _reprice_fraction(sec_duration) * dy_l
               + loans * _reprice_fraction(ASSUMED_LOAN_DURATION_YEARS) * dy_s)
        rsl = deposits * _reprice_fraction(ASSUMED_DEPOSIT_DURATION_YEARS) * dy_s
        return rsa - rsl

    def scenario(label: str, dy_short_bps: float, dy_long_bps: float, **extra) -> dict:
        eve = eve_delta(dy_short_bps, dy_long_bps)
        return {
            "scenario": label, **extra,
            "eve_delta": round(eve, 0),
            "eve_delta_pct_of_equity": round(eve / equity * 100, 2) if equity else None,
            "nii_delta_12mo": round(nii_delta_12mo(dy_short_bps, dy_long_bps), 0),
        }

    parallel = scenario("parallel", parallel_shock_bps, parallel_shock_bps, shock_bps=parallel_shock_bps)
    non_parallel = scenario("steepener", steepener_short_bps, steepener_long_bps,
                            short_bps=steepener_short_bps, long_bps=steepener_long_bps)

    return {
        "name": pos.get("name"), "quarter": pos.get("quarter"),
        "parallel": parallel,
        "non_parallel": non_parallel,
        "inputs": {
            "securities_total": round(securities, 0),
            "securities_blended_duration_years": round(sec_duration, 2),
            "securities_duration_source": pos.get("afs_duration_source", "fallback_default"),
            "loans_total": round(loans, 0), "loans_assumed_duration_years": ASSUMED_LOAN_DURATION_YEARS,
            "deposits_total": round(deposits, 0), "deposits_assumed_duration_years": ASSUMED_DEPOSIT_DURATION_YEARS,
        },
        "bucket_coarseness": (
            "FDIC's public Call Report API exposes no repricing-bucket schedule (Schedule RC-B/RC "
            "by maturity bucket) among this repo's landed, VERIFIED fields — so EVE/NII here are a "
            "single-bucket duration-gap approximation, not a precise regulatory IRRBB calculation. "
            f"Securities duration ({round(sec_duration, 2)}y blended) is the SAME per-bank estimate "
            f"the stress engine's rate-shock leg uses ({pos.get('afs_duration_source', 'fallback_default')}"
            f"); loan ({ASSUMED_LOAN_DURATION_YEARS}y) and deposit ({ASSUMED_DEPOSIT_DURATION_YEARS}y) "
            "durations are industry-typical ASSUMPTIONS, not bank-specific or FDIC-disclosed. Read "
            "every figure below as directional, not precise."
        ),
    }
