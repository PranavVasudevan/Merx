"""MCP tool contracts for BankLens — thin wrappers over the feature logic.

Each tool: read Gold / feature functions, return a JSON-serialisable result. The
same functions power the CLI. See docs/api/mcp-tools.md.
"""

from __future__ import annotations

from banklens_transforms.deposit_flight import features_from, load_card, score_vector
from banklens_transforms.filing_diff import build_quarters, diff
from banklens_transforms.ma_fit import rank_partners
from banklens_transforms.market import price_snapshot
from banklens_transforms.stress import Shock, run_stress_test, starting_position
from banklens_transforms.data_quality import capital_basis, exclusion_for, summarize
from banklens_transforms.xray import evaluate_xray

from . import data


def _need_bank(cert: int) -> dict:
    row = data.population()["by_cert"].get(cert)
    if row is None:
        raise ValueError(f"CERT {cert} is not in the $1B-$250B population slice (2026Q1).")
    return row


# ---- handlers ------------------------------------------------------------
def list_banks(query: str = None, state: str = None, min_assets_b: float = None,
               max_assets_b: float = None, limit: int = 20) -> dict:
    """Search/filter the Gold population — real SQL via data.query_banks()
    (DuckDB), not a hand-rolled Python filter/sort."""
    hits = data.query_banks(query=query, state=state, min_assets_b=min_assets_b,
                            max_assets_b=max_assets_b, limit=limit)
    return {"count": len(hits), "banks": [{
        "cert": g["cert_number"], "name": g["name"], "state": g.get("state"),
        "assets_b": round((g.get("total_assets") or 0) / 1e9, 1),
        "cluster": g.get("peer_cluster_label"),
    } for g in hits]}


def get_bank_profile(cert: int) -> dict:
    g = _need_bank(cert)
    def pct(key):
        return {"value": g.get(key), "percentile": g.get(f"percentile_rank_{key}")}
    return {
        "cert": cert, "name": g["name"], "state": g.get("state"), "quarter": g["quarter"],
        "assets_b": round((g.get("total_assets") or 0) / 1e9, 1),
        "uninsured_deposit_pct": g.get("uninsured_deposit_pct"),
        "loan_to_deposit_pct": g.get("loan_to_deposit_pct"),
        "cre_concentration_pct": g.get("concentration_ratio_cre"),
        "cet1_ratio": g.get("cet1_ratio"), "leverage_ratio": g.get("leverage_ratio"),
        "peer_cluster": g.get("peer_cluster_label"),
        "concentration": {
            "cre": pct("concentration_ratio_cre"),
            "c_and_i": pct("concentration_ratio_c_and_i"),
            "residential_mortgage": pct("concentration_ratio_residential_mortgage"),
            "consumer": {"value": g.get("concentration_ratio_consumer"), "percentile": None},
            "agricultural": {"value": g.get("concentration_ratio_agricultural"), "percentile": None},
        },
        "capital": {
            "cet1": pct("cet1_ratio"),
            "tier1_rbc": {"value": g.get("tier1_rbc_ratio"), "percentile": None},
            "total_rbc": {"value": g.get("total_rbc_ratio"), "percentile": None},
            "leverage": pct("leverage_ratio"),
        },
        "funding": {
            "uninsured_deposit_pct": pct("uninsured_deposit_pct"),
            "loan_to_deposit_pct": pct("loan_to_deposit_pct"),
            "core_deposit_pct": pct("core_deposit_pct"),
        },
    }


def get_bank_xray(cert: int) -> dict:
    # Gold row carries percentile ranks -> flags get peer context. Which capital rules
    # apply depends on the bank's regulatory capital regime: 195 CBLR electers and 13
    # foreign-bank branches report zeros for reasons that are not thin capital, and
    # were otherwise all flagged "CET1 below the Basel minimum".
    silver = data.population()["silver_by_cert"].get(cert) or {}
    return evaluate_xray(_need_bank(cert), capital_basis=capital_basis(silver))


def get_peer_cluster(cert: int) -> dict:
    pop = data.population()
    g = _need_bank(cert)
    cid = g.get("peer_cluster_id")
    mates = [c for c in pop["cluster_members"].get(cid, []) if c != cert]
    names = [pop["by_cert"][c]["name"] for c in mates[:6]]
    return {"cert": cert, "cluster_id": cid, "cluster_label": pop["cluster_labels"].get(cid),
            "cluster_size": len(pop["cluster_members"].get(cid, [])),
            "sample_peers": names}


def find_ma_matches(cert: int, top_n: int = 8) -> dict:
    pop = data.population()
    target = _need_bank(cert)
    ranked = rank_partners(target, pop["gold"], top_n=top_n, footprints=data.footprints())
    return {"target": target["name"], "candidates": ranked}


def run_stress(cert: int, loan_loss_pct: float = 3.0, deposit_outflow_pct: float = 15.0,
               rate_shock_bps: float = 200.0) -> dict:
    silver = data.population()["silver_by_cert"].get(cert)
    if silver is None:
        raise ValueError(f"CERT {cert} not in the population slice.")
    pos = starting_position(silver)
    if pos.get("tier1_capital") is None or pos.get("rwa") is None:
        raise ValueError(f"CERT {cert} is missing capital-dollar fields; cannot stress test.")
    return run_stress_test(pos, Shock(loan_loss_pct=loan_loss_pct,
                                      deposit_outflow_pct=deposit_outflow_pct,
                                      rate_shock_bps=rate_shock_bps))


def diff_filings(cert: int, quarter_a: str = None, quarter_b: str = None) -> dict:
    # Prefer the population-based history (data.bank_history — Wave 0d's 8 landed
    # quarters) over the legacy per-bank Bronze partition. This used to be the other
    # way around on the assumption the per-bank land "can run deeper than the
    # population history" — measured, that's now backwards: all 4 individually-landed
    # certs (2270, 3511, 6672, 6976) cap at 6 quarters (2024Q4-2026Q1), strictly
    # SHALLOWER than the 8-quarter population land (2024Q2-2026Q1). Worse, the
    # frontend's quarter picker is built from get_bank_trends, which always reads
    # bank_history — so preferring the shorter source here silently disagreed with
    # what the UI offered, live-verified as `ValueError: '2024Q2' is not in list`
    # when a user picked a quarter the UI itself listed as available. Falling back to
    # bank_quarters only covers a cert that somehow isn't in ANY landed population
    # quarter but was individually landed some other way.
    rows = data.bank_history(cert) or data.bank_quarters(cert)
    if not rows:
        raise ValueError(
            f"No multi-quarter data for CERT {cert}. Landed population quarters: "
            f"{', '.join(data.available_quarters()) or 'none'}.")
    if len(rows) < 2:
        raise ValueError(
            f"CERT {cert} appears in only {len(rows)} landed quarter(s); a filing diff "
            f"needs at least two.")
    return diff(build_quarters(rows), quarter_a, quarter_b)


def get_risk_score(cert: int) -> dict:
    card = load_card()
    if card is None:
        raise ValueError("Deposit-flight model not trained yet; run deposit_flight_cli.")
    pop = data.population()
    silver = pop["silver_by_cert"].get(cert)
    g = pop["by_cert"].get(cert)
    if silver is None:
        raise ValueError(f"CERT {cert} not in the population slice.")
    res = score_vector(card, features_from(silver, g, None))   # growth imputed (no prior-yr landed)
    res.update({"cert": cert, "name": g["name"], "model_trained_on": card["trained_on"],
                "note": "structural resemblance to real bank failures (2023: SVB/Signature/First "
                       "Republic; 2008: IndyMac — though IndyMac's own archetype, subprime-credit-"
                       "driven with a late retail run, is NOT reliably caught by this feature set, "
                       "see risk-score README); growth feature imputed for 2026Q1."})
    return res


def get_risk_leaderboard(top_n: int = 25) -> dict:
    """Feature 13, population-wide: score every bank in the $1B-$250B slice
    and rank by deposit-flight resemblance. Same model as get_risk_score
    (score_vector is a handful of multiplications + a sigmoid — verified
    live that scoring the full ~1,049-bank population takes well under a
    second in pure Python, so this needs no caching/precomputation to be
    viable on every request)."""
    card = load_card()
    if card is None:
        raise ValueError("Deposit-flight model not trained yet; run deposit_flight_cli.")
    pop = data.population()
    scored = []
    for g in pop["gold"]:
        cert = g.get("cert_number")
        silver = pop["silver_by_cert"].get(cert)
        if silver is None:
            continue
        res = score_vector(card, features_from(silver, g, None))
        scored.append({"cert": cert, "name": g["name"], "risk_score": res["risk_score"]})
    scored.sort(key=lambda r: r["risk_score"], reverse=True)
    return {
        "count": len(scored),
        "model_trained_on": card["trained_on"],
        # Same honesty caveat get_risk_score carries per-bank — a leaderboard
        # of bare numbers with no caveat would overstate what this model is.
        "note": "structural resemblance to real bank failures (2023: SVB/Signature/First "
               "Republic; 2008: IndyMac — though IndyMac's own archetype, subprime-credit-"
               "driven with a late retail run, is NOT reliably caught by this feature set, "
               "see risk-score README); growth feature imputed for 2026Q1.",
        "top": scored[:top_n],
    }


def get_price_candles(cert: int, limit_days: int = 180) -> dict:
    """Real EOD OHLCV candles for a bank's crosswalk-matched ticker (never a
    low-confidence guess). Needs `scripts/land_market_data.ps1` to have been run
    (requires the user's own free Tiingo key — the one BankLens source that isn't
    keyless)."""
    g = _need_bank(cert)
    ticker = data.ticker_for_cert(cert)
    if not ticker:
        raise ValueError(f"CERT {cert} ({g['name']}) has no exact/high-confidence "
                         f"ticker match in the crosswalk.")
    bars = data.price_bars(ticker)
    if bars is None:
        raise ValueError(f"No price data landed for {ticker} yet. Run "
                         f"scripts/land_market_data.ps1 (needs a free TIINGO_API_KEY).")
    return {"cert": cert, "name": g["name"], "ticker": ticker,
            "bars": bars[-limit_days:] if limit_days else bars}


def get_market_snapshot(cert: int) -> dict:
    """Latest price, 1-day change, 30-day realized volatility, 52-week range —
    same data source/caveats as get_price_candles."""
    g = _need_bank(cert)
    ticker = data.ticker_for_cert(cert)
    if not ticker:
        raise ValueError(f"CERT {cert} ({g['name']}) has no exact/high-confidence "
                         f"ticker match in the crosswalk.")
    bars = data.price_bars(ticker)
    if bars is None:
        raise ValueError(f"No price data landed for {ticker} yet. Run "
                         f"scripts/land_market_data.ps1 (needs a free TIINGO_API_KEY).")
    snap = price_snapshot(bars)
    snap.update({"cert": cert, "name": g["name"]})
    return snap


def compare_banks(certs: list[int], metrics: list[str] = None) -> dict:
    metrics = metrics or ["uninsured_deposit_pct", "loan_to_deposit_pct",
                          "concentration_ratio_cre", "cet1_ratio"]
    by = data.population()["by_cert"]
    out = []
    for c in certs:
        g = by.get(c)
        if g:
            row = {"cert": c, "name": g["name"]}
            row.update({m: g.get(m) for m in metrics})
            out.append(row)
    return {"metrics": metrics, "banks": out}


# Named slices of the Gold layer. One tool serves several pages rather than a
# near-identical tool per page — "build Gold once, every consumer reads it": these are
# projections of the same feature row, not new analysis.
METRIC_GROUPS: dict[str, list[str]] = {
    "earnings": ["net_interest_margin_pct", "roa_pct", "roe_pct", "efficiency_ratio_pct",
                 "noninterest_income_share_pct", "net_interest_income"],
    "credit": ["npl_ratio_pct", "net_charge_off_rate_pct", "allowance_to_loans_pct",
               "allowance_coverage_pct", "texas_ratio_pct", "noncurrent_assets_ratio_pct"],
    "funding": ["uninsured_deposit_pct", "core_deposit_pct", "brokered_deposit_pct",
                "large_denomination_deposit_pct", "time_deposit_pct",
                "volatile_liability_pct", "loans_to_core_deposits_pct",
                "loan_to_deposit_pct"],
    "capital": ["cet1_ratio", "tier1_rbc_ratio", "total_rbc_ratio", "leverage_ratio",
                "cre_to_total_capital_pct", "construction_to_total_capital_pct"],
    "concentration": ["concentration_ratio_construction", "concentration_ratio_multifamily",
                      "concentration_ratio_nonfarm_nonres",
                      "concentration_ratio_residential_mortgage",
                      "concentration_ratio_farmland", "concentration_ratio_agricultural",
                      "concentration_ratio_c_and_i", "concentration_ratio_consumer",
                      "concentration_ratio_cre", "max_loan_concentration_pct",
                      "max_loan_concentration_category"],
}

_IDENTITY = ["cert_number", "name", "state", "total_assets", "peer_cluster_label"]


def get_population_metrics(group: str, limit: int = 2000, sort_by: str = None,
                           descending: bool = True) -> dict:
    """One named metric group across the whole population, with peer percentiles.

    Powers the earnings / credit / funding / capital / concentration views. Returns
    identity columns plus the group's metrics and any `percentile_rank_*` already
    computed for them, so a page never has to re-derive a rank the Gold layer holds.
    """
    metrics = METRIC_GROUPS.get(group)
    if metrics is None:
        raise ValueError(f"unknown metric group '{group}' — choose one of {sorted(METRIC_GROUPS)}")
    pop = data.population()
    if sort_by is not None and sort_by not in metrics:
        raise ValueError(f"cannot sort '{group}' by '{sort_by}' — not in that group")

    rows = []
    for g in pop["gold"]:
        row = {k: g.get(k) for k in _IDENTITY}
        for m in metrics:
            row[m] = g.get(m)
            pr = g.get(f"percentile_rank_{m}")
            if pr is not None:
                row[f"percentile_rank_{m}"] = pr
        rows.append(row)

    if sort_by:
        rows = [r for r in rows if r.get(sort_by) is not None]
        rows.sort(key=lambda r: r[sort_by], reverse=descending)
    else:
        rows.sort(key=lambda r: r.get("total_assets") or 0, reverse=True)
    return {"group": group, "quarter": pop["quarter"], "metrics": metrics,
            "count": len(rows), "banks": rows[:limit]}


# A curated cross-group set for the heatmap — one glance across risk, credit, and
# earnings rather than 17 columns nobody can scan. Every one already has a computed
# percentile rank (peers.RANK_METRICS), so this is a projection, not new analysis.
HEATMAP_METRICS = [
    "uninsured_deposit_pct", "loan_to_deposit_pct", "max_loan_concentration_pct",
    "cre_to_total_capital_pct", "cet1_ratio", "leverage_ratio", "roa_pct",
    "net_interest_margin_pct", "npl_ratio_pct", "texas_ratio_pct",
]


def get_percentile_heatmap(top_n: int = 40, sort_by: str = "total_assets") -> dict:
    """A bank x metric percentile matrix for `top_n` banks (by `sort_by`, default the
    largest by assets). Powers /heatmap. Cells are `percentile_rank_<metric>`
    (0-100), not the raw value — that is the point of a heatmap like this: it reads
    across metrics on one shared scale instead of mixing percent, ratio, and dollar
    units in the same row.
    """
    pop = data.population()
    rows = [g for g in pop["gold"] if g.get(sort_by) is not None]
    rows.sort(key=lambda g: g[sort_by], reverse=True)
    rows = rows[:top_n]
    return {
        "quarter": pop["quarter"], "metrics": HEATMAP_METRICS,
        "banks": [{
            "cert": g["cert_number"], "name": g["name"],
            "cells": [g.get(f"percentile_rank_{m}") for m in HEATMAP_METRICS],
        } for g in rows],
    }


# Curated for /trends line charts. Every one is a Gold field already computed by
# gold_features — this is a projection, not new analysis.
TREND_METRICS = [
    "total_assets", "uninsured_deposit_pct", "loan_to_deposit_pct", "cet1_ratio",
    "roa_pct", "net_interest_margin_pct", "npl_ratio_pct", "texas_ratio_pct",
    "brokered_deposit_pct", "max_loan_concentration_pct",
]


def get_bank_trends(cert: int) -> dict:
    """One bank's Gold-derived metrics across every landed quarter, oldest first —
    the real trajectory Wave 0d's 8-quarter land makes possible for the whole
    population, not just the 4 individually-landed certs.

    Reuses `data.population(q)` per quarter rather than a parallel per-bank
    pipeline: same Gold computation, same peer percentiles, same stable cluster ids
    the rest of the app already uses, and the same cache — a second bank's trends
    request pays nothing for a quarter this one already warmed.
    """
    quarters = list(reversed(data.available_quarters()))  # oldest first, for charting
    series = []
    for q in quarters:
        g = data.population(q)["by_cert"].get(cert)
        if g is not None:
            series.append(g)
    if not series:
        raise ValueError(
            f"CERT {cert} has no landed history in any of {', '.join(quarters) or 'no landed quarters'}.")
    return {
        "cert": cert, "name": series[-1]["name"], "metrics": TREND_METRICS,
        "quarters": [s["quarter"] for s in series],
        "series": [{**{"quarter": s["quarter"]}, **{m: s.get(m) for m in TREND_METRICS},
                   "peer_cluster_label": s.get("peer_cluster_label")} for s in series],
    }


# The set of headline metrics /briefing screens for "biggest movers". Each maps to
# whether a HIGHER value is the more concerning direction, purely for how a mover is
# framed in the summary text — both directions are always reported.
_BRIEFING_METRICS = {
    "roa_pct": "Return on assets", "npl_ratio_pct": "NPL ratio",
    "texas_ratio_pct": "Texas Ratio", "cet1_ratio": "CET1 ratio",
    "uninsured_deposit_pct": "Uninsured deposits", "brokered_deposit_pct": "Brokered deposits",
}


def get_quarterly_briefing(top_n: int = 8) -> dict:
    """Population-wide "what changed this quarter" — real QoQ analysis across the
    latest two landed quarters, not a per-bank drill-down (that's /trends and
    /filing-diff). Four real signals:

      - population churn: certs present in one quarter's $1B-$250B slice but not
        the other (crossed a size threshold, or a data-landing gap)
      - biggest movers on headline metrics, both directions
      - behavioral cluster migrations, using the STABLE cluster ids Wave 0d added
        (without those, every k-means run assigns different arbitrary integers to
        the same behavioral group, and this would report fake migration)
      - risk-leaderboard churn: banks newly in the top `top_n` riskiest this
        quarter that weren't last quarter, scored with the SAME deposit-flight
        model card against both quarters' populations

    Raises if fewer than 2 quarters are landed — there is nothing to compare.
    """
    quarters = data.available_quarters()
    if len(quarters) < 2:
        raise ValueError(
            f"need at least 2 landed quarters to brief, have {len(quarters)}: {quarters}")
    cur_q, prev_q = quarters[0], quarters[1]
    cur, prev = data.population(cur_q), data.population(prev_q)

    cur_certs, prev_certs = set(cur["by_cert"]), set(prev["by_cert"])
    entered = sorted(cur["by_cert"][c]["name"] for c in (cur_certs - prev_certs))
    exited = sorted(prev["by_cert"][c]["name"] for c in (prev_certs - cur_certs))

    movers = []
    for c in cur_certs & prev_certs:
        g_cur, g_prev = cur["by_cert"][c], prev["by_cert"][c]
        for key, label in _BRIEFING_METRICS.items():
            a, b = g_prev.get(key), g_cur.get(key)
            if a is None or b is None:
                continue
            movers.append({"cert": c, "name": g_cur["name"], "metric": key, "label": label,
                           "from": round(a, 2), "to": round(b, 2), "change": round(b - a, 2)})
    movers.sort(key=lambda m: abs(m["change"]), reverse=True)

    migrations = []
    for c in cur_certs & prev_certs:
        a = prev["by_cert"][c].get("peer_cluster_label")
        b = cur["by_cert"][c].get("peer_cluster_label")
        if a and b and a != b:
            migrations.append({"cert": c, "name": cur["by_cert"][c]["name"], "from": a, "to": b})
    migration_pairs: dict[str, int] = {}
    for m in migrations:
        key = f"{m['from']} -> {m['to']}"
        migration_pairs[key] = migration_pairs.get(key, 0) + 1

    risk_entrants: list[dict] = []
    card = load_card()
    if card is not None:
        def _top_certs(pop: dict) -> dict[int, float]:
            scored = {}
            for g in pop["gold"]:
                c = g.get("cert_number")
                silver = pop["silver_by_cert"].get(c)
                if silver is None:
                    continue
                scored[c] = score_vector(card, features_from(silver, g, None))["risk_score"]
            top = sorted(scored.items(), key=lambda t: t[1], reverse=True)[:top_n]
            return dict(top)
        cur_top, prev_top = _top_certs(cur), _top_certs(prev)
        for c, score in cur_top.items():
            if c not in prev_top:
                risk_entrants.append({"cert": c, "name": cur["by_cert"][c]["name"],
                                      "risk_score": round(score, 4)})
        risk_entrants.sort(key=lambda r: r["risk_score"], reverse=True)

    return {
        "quarter": cur_q, "prior_quarter": prev_q,
        "population_count": len(cur_certs), "prior_population_count": len(prev_certs),
        "entered": entered, "exited": exited,
        "top_movers": movers[:top_n * 2],
        "cluster_migrations": {
            "count": len(migrations), "by_transition": migration_pairs,
            "sample": migrations[:top_n],
        },
        "risk_leaderboard_entrants": risk_entrants,
        "risk_model_trained": card is not None,
    }


def get_asset_treemap(group_by: str = "peer_cluster_label") -> dict:
    """Every bank in the population, sized by assets and grouped for a treemap —
    `group_by` in {"peer_cluster_label", "state"}. Colored client-side by whichever
    risk metric the user picks (X-Ray severity, risk score, a percentile rank), since
    baking one color choice in here would make this three tools instead of one.
    """
    if group_by not in ("peer_cluster_label", "state"):
        raise ValueError(f"group_by must be 'peer_cluster_label' or 'state', got '{group_by}'")
    pop = data.population()
    groups: dict[str, list[dict]] = {}
    for g in pop["gold"]:
        key = g.get(group_by) or "Unclassified"
        assets = g.get("total_assets")
        if not assets:
            continue
        silver = pop["silver_by_cert"].get(g["cert_number"]) or {}
        overall_risk = evaluate_xray(g, capital_basis=capital_basis(silver))["overall_risk"]
        groups.setdefault(key, []).append({
            "cert": g["cert_number"], "name": g["name"], "value": assets,
            "cet1_ratio": g.get("cet1_ratio"), "overall_risk": overall_risk,
            "uninsured_deposit_pct": g.get("uninsured_deposit_pct"),
            "npl_ratio_pct": g.get("npl_ratio_pct"),
        })
    return {
        "quarter": pop["quarter"], "group_by": group_by,
        "groups": [{"name": k, "children": sorted(v, key=lambda b: b["value"], reverse=True)}
                  for k, v in sorted(groups.items(), key=lambda kv: sum(b["value"] for b in kv[1]),
                                     reverse=True)],
    }


def get_metric_distribution(metric: str, bins: int = 30) -> dict:
    """Histogram + order statistics for one Gold metric across the population.

    Real analysis rather than data shipping, so it belongs server-side: the binning,
    the percentile cuts, and — importantly — the disclosure of which institutions were
    excluded and why. A distribution rendered without naming its exclusions would be a
    quietly misleading chart, which is the thing `data_quality` exists to prevent.
    """
    pop = data.population()
    values, excluded = [], []
    for g in pop["gold"]:
        silver = pop["silver_by_cert"].get(g.get("cert_number")) or {}
        # Exclusion is checked BEFORE the null check: a non-deposit-funded charter's
        # deposit-sensitive metric is usually None (division by ~zero deposits), which
        # used to make it silently vanish from BOTH the distribution and the
        # disclosure — the exact quietly-misleading outcome this function exists to
        # prevent. Measured on loan_to_deposit_pct: 8 banks are genuinely excluded,
        # but 7 of them have a null value and were being dropped with no record.
        exc = exclusion_for(silver) if metric in _DEPOSIT_SENSITIVE else None
        if exc is not None:
            excluded.append(exc)
            continue
        v = g.get(metric)
        if v is None:
            continue
        values.append(v)
    if not values:
        raise ValueError(f"no values for metric '{metric}' in {pop['quarter']}")

    vals = sorted(values)
    n = len(vals)
    def q(p):
        return vals[min(int(n * p), n - 1)]
    lo, hi = vals[0], vals[-1]

    # Equal-width bins over the FULL range collapse to one bin for any heavy-tailed
    # metric — measured on texas_ratio_pct (median 4.1%, max 162.4%): 991 of 1,035
    # banks landed in a single bin. Bin the BODY of the distribution (p1-p99) at full
    # resolution and fold the tails into the first/last bin instead — every value is
    # still counted (sum of histogram counts always equals n), just not spread thin
    # across dozens of empty tail bins.
    p_lo, p_hi = q(0.01), q(0.99)
    if p_hi <= p_lo:
        p_lo, p_hi = lo, hi
    width = (p_hi - p_lo) / bins if p_hi > p_lo else 1.0
    counts = [0] * bins
    for v in vals:
        idx = 0 if v <= p_lo else (bins - 1 if v >= p_hi else int((v - p_lo) / width))
        counts[min(max(idx, 0), bins - 1)] += 1
    assert sum(counts) == n, "histogram must account for every value"

    return {
        "metric": metric, "quarter": pop["quarter"], "count": n,
        "min": lo, "max": hi, "mean": round(sum(vals) / n, 4),
        "p10": q(0.10), "p25": q(0.25), "median": q(0.50), "p75": q(0.75), "p90": q(0.90),
        "histogram_range": {"lower": p_lo, "upper": p_hi,
                            "note": "first/last bin includes everything at or beyond "
                                    "the 1st/99th percentile, not just that bin's width"},
        "histogram": [{"lower": round(p_lo + i * width, 4),
                       "upper": round(p_lo + (i + 1) * width, 4),
                       "count": c} for i, c in enumerate(counts)],
        "exclusions": summarize(excluded, n + len(excluded)),
    }


# Metrics whose denominator is deposits — the only ones where a non-deposit-funded
# charter distorts the distribution (see data_quality). Capital or loan-mix metrics are
# perfectly meaningful for a trust company, so they are not filtered.
_DEPOSIT_SENSITIVE = {
    "loan_to_deposit_pct", "uninsured_deposit_pct", "core_deposit_pct",
    "brokered_deposit_pct", "large_denomination_deposit_pct", "time_deposit_pct",
    "loans_to_core_deposits_pct",
}


# ---- registry ------------------------------------------------------------
_CERT = {"type": "integer", "description": "FDIC certificate number"}

TOOLS = [
    {"name": "list_banks",
     "description": "Search/filter banks in the $1B-$250B slice by name, state, or asset range.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "state": {"type": "string"},
         "min_assets_b": {"type": "number"}, "max_assets_b": {"type": "number"},
         "limit": {"type": "integer"}}},
     "handler": list_banks},
    {"name": "get_bank_profile",
     "description": "Core Silver/Gold profile for one bank.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_bank_profile},
    {"name": "get_bank_xray",
     "description": "Feature 11 — concentration & structural risk breakdown with peer percentiles.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_bank_xray},
    {"name": "get_peer_cluster",
     "description": "Feature 14 — the bank's behavioral peer cluster and sample peers.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_peer_cluster},
    {"name": "find_ma_matches",
     "description": "Feature 15 — ranked M&A partner candidates with rationale.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "top_n": {"type": "integer"}}, "required": ["cert"]},
     "handler": find_ma_matches},
    {"name": "run_stress_test",
     "description": "Feature 16 — stress capital ratios under loan-loss / deposit-outflow / rate shocks.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "loan_loss_pct": {"type": "number"},
         "deposit_outflow_pct": {"type": "number"}, "rate_shock_bps": {"type": "number"}},
         "required": ["cert"]},
     "handler": run_stress},
    {"name": "get_risk_score",
     "description": "Feature 13 — deposit-flight risk score (model trained on real 2023 + 2008 failures) with drivers.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_risk_score},
    {"name": "get_risk_leaderboard",
     "description": "Feature 13, population-wide — deposit-flight risk score for every bank in "
                    "the $1B-$250B slice, ranked descending.",
     "inputSchema": {"type": "object", "properties": {"top_n": {"type": "integer"}}},
     "handler": get_risk_leaderboard},
    {"name": "diff_filings",
     "description": "Feature 12 — side-by-side quarter comparison for every tracked "
                    "line item, flagging moves that are unusual vs the bank's own history.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "quarter_a": {"type": "string"}, "quarter_b": {"type": "string"}},
         "required": ["cert"]},
     "handler": diff_filings},
    {"name": "get_bank_trends",
     "description": "One bank's headline Gold metrics across every landed quarter, "
                    "oldest first — real QoQ trajectories for earnings, credit, "
                    "funding and capital.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_bank_trends},
    {"name": "get_quarterly_briefing",
     "description": "Population-wide 'what changed this quarter': population churn, "
                    "biggest movers, behavioral-cluster migrations, and risk-"
                    "leaderboard entrants vs the prior landed quarter.",
     "inputSchema": {"type": "object", "properties": {"top_n": {"type": "integer"}}},
     "handler": get_quarterly_briefing},
    {"name": "compare_banks",
     "description": "Side-by-side comparison of banks across chosen metrics.",
     "inputSchema": {"type": "object", "properties": {
         "certs": {"type": "array", "items": {"type": "integer"}},
         "metrics": {"type": "array", "items": {"type": "string"}}}, "required": ["certs"]},
     "handler": compare_banks},
    {"name": "get_population_metrics",
     "description": "One named metric group (earnings, credit, funding, capital, "
                    "concentration) across the whole population, with peer percentiles.",
     "inputSchema": {"type": "object", "properties": {
         "group": {"type": "string", "enum": sorted(METRIC_GROUPS)},
         "limit": {"type": "integer"}, "sort_by": {"type": "string"},
         "descending": {"type": "boolean"}}, "required": ["group"]},
     "handler": get_population_metrics},
    {"name": "get_percentile_heatmap",
     "description": "Bank x metric percentile matrix (top N by a sort metric, default "
                    "assets) — cells are percentile ranks, not raw values.",
     "inputSchema": {"type": "object", "properties": {
         "top_n": {"type": "integer"}, "sort_by": {"type": "string"}}},
     "handler": get_percentile_heatmap},
    {"name": "get_asset_treemap",
     "description": "Every bank sized by assets, grouped by behavioral cluster or "
                    "state, with X-Ray risk severity for client-side coloring.",
     "inputSchema": {"type": "object", "properties": {
         "group_by": {"type": "string", "enum": ["peer_cluster_label", "state"]}}},
     "handler": get_asset_treemap},
    {"name": "get_metric_distribution",
     "description": "Histogram, order statistics and disclosed data-quality exclusions "
                    "for one Gold metric across the population.",
     "inputSchema": {"type": "object", "properties": {
         "metric": {"type": "string"}, "bins": {"type": "integer"}},
         "required": ["metric"]},
     "handler": get_metric_distribution},
    {"name": "get_price_candles",
     "description": "Real EOD OHLCV candlestick data for a bank's crosswalk-matched ticker "
                    "(needs scripts/land_market_data.ps1 to have landed it first).",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "limit_days": {"type": "integer"}}, "required": ["cert"]},
     "handler": get_price_candles},
    {"name": "get_market_snapshot",
     "description": "Latest price, 1-day change, 30-day realized volatility, 52-week range.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_market_snapshot},
]

TOOL_BY_NAME = {t["name"]: t for t in TOOLS}
