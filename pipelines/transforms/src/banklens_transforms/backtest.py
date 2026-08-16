"""Feature 17 (C14) — backtest harness.

Nothing in this product had ever been backtested before this: not the
deposit-flight score, not the X-Ray flags, not the filing-diff flags, not
the M&A weights (C9 handles that one separately, against real deal history).
This module answers, for any "flagged at quarter t" signal, the honest
question: did flagged banks subsequently look worse than the rest of the
population — deposit outflows, capital deterioration, credit deterioration,
or failure/exit — over the following quarter(s)? Reports hit rate, lift over
the base rate, and confidence intervals, and treats a null result as a
legitimate, publishable finding, not a failure of the analysis.

Pure functions only: callers (backtest_cli.py) supply the flagged sets and
before/after snapshots; this module never touches Bronze/data.py itself.
"""

from __future__ import annotations

import math

# ---- confidence intervals --------------------------------------------------

def wilson_ci(hits: int, n: int, z: float = 1.96) -> dict:
    """Wilson score interval for a proportion — more reliable than the naive
    normal approximation at the small n a handful of flagged banks produces,
    still closed-form (no scipy dependency, matching this codebase's other
    from-scratch statistics — see deposit_flight.bootstrap_stats)."""
    if n == 0:
        return {"point": None, "lo": None, "hi": None}
    p = hits / n
    denom = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / denom
    return {"point": round(p, 4), "lo": round(max(0.0, center - margin), 4),
           "hi": round(min(1.0, center + margin), 4)}


# ---- outcome definitions ----------------------------------------------------
# Each takes the bank's `before` (quarter t) and `after` (quarter t+k) Gold/
# Silver-merged rows and returns True/False/None — None when the inputs to
# judge it aren't disclosed, never a guessed default.

def deposit_outflow_outcome(before: dict, after: dict, threshold_pct: float = -3.0) -> bool | None:
    b, a = before.get("total_deposits"), after.get("total_deposits")
    if b is None or a is None or not b:
        return None
    return (a - b) / abs(b) * 100 <= threshold_pct


def capital_deterioration_outcome(before: dict, after: dict, threshold_pp: float = -1.0) -> bool | None:
    b, a = before.get("cet1_ratio"), after.get("cet1_ratio")
    if b is None or a is None:
        return None
    return (a - b) <= threshold_pp


def credit_deterioration_outcome(after: dict) -> bool | None:
    """Reuses C8's own `deterioration_flag` (computed from this bank's own
    trailing history as of the outcome quarter) rather than re-deriving
    credit deterioration a second, possibly inconsistent way."""
    return after.get("deterioration_flag")


def cluster_migration_outcome(before: dict, after: dict) -> bool | None:
    b, a = before.get("peer_cluster_label"), after.get("peer_cluster_label")
    if b is None or a is None:
        return None
    return b != a


def failed_or_exited_outcome(cert: int, still_present_at_after: bool, failed_certs: set[int]) -> bool:
    """True if the bank failed (FDIC's own `failures` endpoint, RESTYPE ==
    FAILURE — same source B6/deposit_flight already lands) or is no longer in
    the landed population at the outcome quarter (a proxy for acquisition or
    charter termination — B6's landed deal history could disambiguate this
    further; this harness doesn't attempt that split). Always a real
    True/False, never None: exit-from-population is directly observable from
    the two snapshots with no missing-data case.
    """
    return cert in failed_certs or not still_present_at_after


OUTCOMES = ("deposit_outflow", "capital_deterioration", "credit_deterioration",
           "cluster_migration", "failed_or_exited")

OUTCOME_LABELS = {
    "deposit_outflow": "Deposit outflow > 3%",
    "capital_deterioration": "CET1 declined > 1pp",
    "credit_deterioration": "Credit-deterioration flag (C8)",
    "cluster_migration": "Behavioral cluster changed",
    "failed_or_exited": "Failed or exited the landed population",
}


def _outcome(key: str, cert: int, before: dict | None, after: dict | None,
            still_present_at_after: bool, failed_certs: set[int]) -> bool | None:
    if key == "failed_or_exited":
        return failed_or_exited_outcome(cert, still_present_at_after, failed_certs)
    if before is None or after is None:
        return None
    if key == "deposit_outflow":
        return deposit_outflow_outcome(before, after)
    if key == "capital_deterioration":
        return capital_deterioration_outcome(before, after)
    if key == "credit_deterioration":
        return credit_deterioration_outcome(after)
    if key == "cluster_migration":
        return cluster_migration_outcome(before, after)
    raise ValueError(f"unknown outcome key {key!r}")


def backtest_signal(flagged_certs: set[int], population_certs: set[int],
                    before_by_cert: dict[int, dict], after_by_cert: dict[int, dict],
                    failed_certs: set[int]) -> dict[str, dict]:
    """One quarter transition's raw hit/n counts per outcome, flagged vs the
    rest of `population_certs` (the base rate). Returns RAW COUNTS (not yet a
    Wilson CI) so callers can pool across many quarter transitions before
    computing the final interval — a single transition's flagged set is
    almost always too small to say anything on its own; see
    `pool_backtest_results`.
    """
    out: dict[str, dict] = {}
    for key in OUTCOMES:
        flagged_hits = flagged_n = base_hits = base_n = 0
        for cert in population_certs:
            result = _outcome(key, cert, before_by_cert.get(cert), after_by_cert.get(cert),
                              cert in after_by_cert, failed_certs)
            if result is None:
                continue
            base_n += 1
            base_hits += int(result)
            if cert in flagged_certs:
                flagged_n += 1
                flagged_hits += int(result)
        out[key] = {"flagged_hits": flagged_hits, "flagged_n": flagged_n,
                    "base_hits": base_hits, "base_n": base_n}
    return out


def pool_backtest_results(per_quarter: list[dict[str, dict]]) -> dict[str, dict]:
    """Sum raw hit/n counts for each outcome across every quarter transition
    supplied, then compute ONE pooled Wilson CI per outcome — this is what
    turns "a handful of quarters, each too thin to trust alone" into a real
    sample (the reason B1's history backfill matters for this feature)."""
    pooled: dict[str, dict] = {}
    for key in OUTCOMES:
        fh = sum(r[key]["flagged_hits"] for r in per_quarter)
        fn = sum(r[key]["flagged_n"] for r in per_quarter)
        bh = sum(r[key]["base_hits"] for r in per_quarter)
        bn = sum(r[key]["base_n"] for r in per_quarter)
        flagged_ci, base_ci = wilson_ci(fh, fn), wilson_ci(bh, bn)
        lift = (round(flagged_ci["point"] / base_ci["point"], 2)
               if flagged_ci["point"] is not None and base_ci["point"] else None)
        pooled[key] = {
            "label": OUTCOME_LABELS[key],
            "flagged_hits": fh, "flagged_n": fn, "flagged_hit_rate": flagged_ci,
            "base_hits": bh, "base_n": bn, "base_hit_rate": base_ci,
            "lift": lift,
        }
    return pooled
