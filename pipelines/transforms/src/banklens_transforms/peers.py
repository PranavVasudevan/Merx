"""Peer analytics — percentile ranks across a bank population.

This is what turns an absolute number ("73.8% CRE") into a peer-relative one
("top 1% of banks its size"). It completes the peer dimension of Feature 11 and
is the input Feature 14 (peer clustering) will build on.

Percentile rank of a value = share of the population with a value <= it, in %.
So a high `percentile_rank_concentration_ratio_cre` means unusually concentrated;
a LOW `percentile_rank_cet1_ratio` means unusually thin capital.
"""

from __future__ import annotations

from collections import defaultdict

# Metrics we rank a bank against its peers on. Computed ONCE here and reused by every
# consumer (profile percentiles, X-Ray peer context, the metric-group tables, the
# heatmap) — the same "build Gold once" contract the rest of this layer follows.
RANK_METRICS = [
    "uninsured_deposit_pct",
    "loan_to_deposit_pct",
    "concentration_ratio_cre",
    "concentration_ratio_c_and_i",
    "concentration_ratio_residential_mortgage",
    "concentration_ratio_consumer",
    "concentration_ratio_agricultural",
    "max_loan_concentration_pct",
    "cre_to_equity_pct",
    "cre_to_total_capital_pct",
    "cet1_ratio",
    "tier1_rbc_ratio",
    "total_rbc_ratio",
    "leverage_ratio",
    "core_deposit_pct",
    # earnings
    "roa_pct",
    "net_interest_margin_pct",
    "efficiency_ratio_pct",
    # credit quality
    "npl_ratio_pct",
    "texas_ratio_pct",
    # funding composition
    "brokered_deposit_pct",
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


def _add_conditional_ranks(gold_rows: list[dict], metrics: list[str], *,
                           group_field: str, suffix: str) -> None:
    """Shared helper for the `_within_size`/`_within_cluster` passes below:
    group rows by `group_field`, rank each group against only its own peers,
    and set `percentile_rank_<metric><suffix>` on every row — `None` (not
    absent) for rows whose `group_field` is unknown, so every row carries the
    same key set regardless of data completeness."""
    by_group: dict[str, list[dict]] = defaultdict(list)
    for g in gold_rows:
        key = g.get(group_field)
        if key is not None:
            by_group[key].append(g)
    for rows in by_group.values():
        for m in metrics:
            population = [g.get(m) for g in rows]
            for g in rows:
                g[f"percentile_rank_{m}{suffix}"] = percentile_rank(g.get(m), population)
    for g in gold_rows:
        if g.get(group_field) is None:
            for m in metrics:
                g.setdefault(f"percentile_rank_{m}{suffix}", None)


def add_percentile_ranks(gold_rows: list[dict], metrics: list[str] = RANK_METRICS) -> list[dict]:
    """Attach THREE percentile bases to every row, all in the same single pass
    (C11) — the "build Gold once" contract this layer follows everywhere else:

      ``percentile_rank_<metric>``                — population-wide (global)
      ``percentile_rank_<metric>_within_size``     — against same-`asset_band` peers
      ``percentile_rank_<metric>_within_cluster``  — against same-`peer_cluster_label` peers

    The conditional bases exist because widening the landed population beyond
    the original $1B-$250B slice (B3) put a $1.2B community bank and a $900B
    GSIB in the same pool: a population-wide percentile is now partly a size
    percentile in disguise for any metric correlated with scale, and a peer
    cluster (behavioral similarity — funding mix, loan mix, size — see
    `clustering.py`) is often the more relevant comparison set than either raw
    size or the whole population. Rows with an unknown `asset_band` or
    `peer_cluster_label` get `None` for that conditional field, same as any
    other undetermined percentile — never silently dropped from the row.
    """
    for m in metrics:
        population = [g.get(m) for g in gold_rows]
        for g in gold_rows:
            g[f"percentile_rank_{m}"] = percentile_rank(g.get(m), population)

    _add_conditional_ranks(gold_rows, metrics, group_field="asset_band", suffix="_within_size")
    _add_conditional_ranks(gold_rows, metrics, group_field="peer_cluster_label", suffix="_within_cluster")
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
