"""Peer analytics — percentile ranks across a bank population.

This is what turns an absolute number ("73.8% CRE") into a peer-relative one
("top 1% of banks its size"). It completes the peer dimension of Feature 11 and
is the input Feature 14 (peer clustering) will build on.

Percentile rank of a value = share of the population with a value <= it, in %.
So a high `percentile_rank_concentration_ratio_cre` means unusually concentrated;
a LOW `percentile_rank_cet1_ratio` means unusually thin capital.
"""

from __future__ import annotations

# Metrics we rank a bank against its peers on.
RANK_METRICS = [
    "uninsured_deposit_pct",
    "loan_to_deposit_pct",
    "concentration_ratio_cre",
    "concentration_ratio_c_and_i",
    "concentration_ratio_residential_mortgage",
    "max_loan_concentration_pct",
    "cre_to_equity_pct",
    "cet1_ratio",
    "leverage_ratio",
    "core_deposit_pct",
]


def percentile_rank(value: float | None, population: list[float | None]) -> float | None:
    """Percentile rank of ``value`` within ``population`` (0-100, 'weak' <= definition)."""
    if value is None:
        return None
    vals = [v for v in population if v is not None]
    if not vals:
        return None
    count_leq = sum(1 for v in vals if v <= value)
    return round(count_leq / len(vals) * 100, 1)


def add_percentile_ranks(gold_rows: list[dict], metrics: list[str] = RANK_METRICS) -> list[dict]:
    """Attach ``percentile_rank_<metric>`` to every row, computed across all rows."""
    for m in metrics:
        population = [g.get(m) for g in gold_rows]
        for g in gold_rows:
            g[f"percentile_rank_{m}"] = percentile_rank(g.get(m), population)
    return gold_rows


def summary_stats(gold_rows: list[dict], metric: str) -> dict:
    """Median / p90 / max of a metric across the population (for reporting)."""
    vals = sorted(g[metric] for g in gold_rows if g.get(metric) is not None)
    if not vals:
        return {"n": 0}

    def q(p: float) -> float:
        idx = min(len(vals) - 1, int(p * len(vals)))
        return round(vals[idx], 2)

    return {"n": len(vals), "median": q(0.50), "p90": q(0.90), "max": round(vals[-1], 2)}
