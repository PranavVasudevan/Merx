"""MCP tool contracts for BankLens — thin wrappers over the feature logic.

Each tool: read Gold / feature functions, return a JSON-serialisable result. The
same functions power the CLI. See docs/api/mcp-tools.md.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict

from banklens_common import embeddings
from banklens_common.db import DbUnavailable, filing_coverage_stats, search_filing_chunks
from banklens_transforms import clustering
from banklens_transforms.deposit_flight import (
    EXCLUDED_CANDIDATES, POSITIVE_CERTS, features_from, load_card, score_vector,
)
from banklens_transforms.filing_diff import build_quarters, diff
from banklens_transforms.footprint import county_concentration, county_key
from banklens_transforms.ma_fit import rank_partners
from banklens_transforms.market import price_snapshot
from banklens_transforms.stress import (
    Shock, run_stress_test, run_stress_test_quantlib, starting_position,
)
from banklens_transforms.data_quality import capital_basis, exclusion_for, summarize
from banklens_transforms.xray import evaluate_xray

from . import data


def _need_bank(cert: int) -> dict:
    row = data.population()["by_cert"].get(cert)
    if row is None:
        raise ValueError(f"CERT {cert} is not in the $1B-$250B population slice (2026Q1).")
    return row


# ---- handlers ------------------------------------------------------------
def list_banks(query: str = None, state: str = None, country: str = None,
               min_assets_b: float = None, max_assets_b: float = None,
               limit: int = 20) -> dict:
    """Search/filter the Gold population — real SQL via data.query_banks()
    (DuckDB), not a hand-rolled Python filter/sort."""
    hits = data.query_banks(query=query, state=state, country=country,
                            min_assets_b=min_assets_b, max_assets_b=max_assets_b, limit=limit)
    # query_banks already SELECT *s every Gold column — these three profitability/
    # credit/capital fields were sitting right there unused because this dict
    # comprehension only ever picked out the original 5. The Screener page never
    # showed anything beyond name/state/assets/cluster as a result.
    return {"count": len(hits), "banks": [{
        "cert": g["cert_number"], "name": g["name"], "state": g.get("state"),
        "country": g.get("country"),
        "assets_b": round((g.get("total_assets") or 0) / 1e9, 1),
        "cluster": g.get("peer_cluster_label"),
        "roa_pct": g.get("roa_pct"), "npl_ratio_pct": g.get("npl_ratio_pct"),
        "cet1_ratio": g.get("cet1_ratio"),
    } for g in hits]}


def get_bank_profile(cert: int) -> dict:
    g = _need_bank(cert)
    def pct(key):
        return {"value": g.get(key), "percentile": g.get(f"percentile_rank_{key}")}

    # Real branch footprint (Feature 15, same landed SOD data /geography and
    # /market-share read) — computed for every bank already, just never reached a
    # per-bank consumer. ~99% of the population has one; sets aren't JSON-
    # serialisable so states/counties are flattened to a sorted list / count.
    fp = data.footprints().get(cert)
    footprint = None
    if fp is not None:
        footprint = {
            "branch_count": fp["branch_count"], "total_deposits": fp["total_deposits"],
            "centroid": list(fp["centroid"]) if fp["centroid"] else None,
            "geo_basis": fp["geo_basis"], "states": sorted(fp["states"]),
            "county_count": len(fp["counties"]),
        }

    return {
        "cert": cert, "name": g["name"], "state": g.get("state"),
        "country": g.get("country"), "quarter": g["quarter"],
        "assets_b": round((g.get("total_assets") or 0) / 1e9, 1),
        "uninsured_deposit_pct": g.get("uninsured_deposit_pct"),
        "loan_to_deposit_pct": g.get("loan_to_deposit_pct"),
        "cre_concentration_pct": g.get("concentration_ratio_cre"),
        "cet1_ratio": g.get("cet1_ratio"), "leverage_ratio": g.get("leverage_ratio"),
        "peer_cluster": g.get("peer_cluster_label"),
        "footprint": footprint,
        "concentration": {
            "cre": pct("concentration_ratio_cre"),
            "c_and_i": pct("concentration_ratio_c_and_i"),
            "residential_mortgage": pct("concentration_ratio_residential_mortgage"),
            "consumer": pct("concentration_ratio_consumer"),
            "agricultural": pct("concentration_ratio_agricultural"),
        },
        "capital": {
            "cet1": pct("cet1_ratio"),
            "tier1_rbc": pct("tier1_rbc_ratio"),
            "total_rbc": pct("total_rbc_ratio"),
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


def get_risk_leaderboard(top_n: int = 25, state: str = None, cluster_label: str = None) -> dict:
    """Feature 13, population-wide: score every bank in the $1B-$250B slice
    and rank by deposit-flight resemblance. Same model as get_risk_score
    (score_vector is a handful of multiplications + a sigmoid — verified
    live that scoring the full ~1,049-bank population takes well under a
    second in pure Python, so this needs no caching/precomputation to be
    viable on every request). Optional state/cluster_label narrow the
    population BEFORE ranking, so top_n picks the riskiest within that slice
    rather than truncating a global ranking down to whichever of it happens
    to match.
    """
    card = load_card()
    if card is None:
        raise ValueError("Deposit-flight model not trained yet; run deposit_flight_cli.")
    pop = data.population()
    scored = []
    for g in pop["gold"]:
        if state and (g.get("state") or "").upper() != state.upper():
            continue
        if cluster_label and g.get("peer_cluster_label") != cluster_label:
            continue
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
    # Was just the original 4 concentration/funding/capital fields — Wave 0c
    # added real earnings/credit metrics to Gold months after this default was
    # written, and nothing ever updated it, so /compare silently never showed
    # them even though every other page (population-metrics, distributions) did.
    metrics = metrics or ["uninsured_deposit_pct", "loan_to_deposit_pct",
                          "concentration_ratio_cre", "cet1_ratio", "leverage_ratio",
                          "roa_pct", "net_interest_margin_pct", "npl_ratio_pct",
                          "texas_ratio_pct", "brokered_deposit_pct"]
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

_IDENTITY = ["cert_number", "name", "state", "country", "total_assets", "peer_cluster_label"]


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
    `group_by` in {"peer_cluster_label", "state", "country"}. Colored client-side by
    whichever risk metric the user picks (X-Ray severity, risk score, a percentile
    rank), since baking one color choice in here would make this three tools
    instead of one. "country" is the one grouping that actually spans the full
    US+EU population — "state" only ever produces boxes for US banks (EU rows
    have `state=None`, landing in the single "Unclassified" box), so pick
    "country" for a genuinely pan-European view.
    """
    if group_by not in ("peer_cluster_label", "state", "country"):
        raise ValueError(f"group_by must be 'peer_cluster_label', 'state' or 'country', got '{group_by}'")
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


# Standard call-report-style asset tiers for the $1B-$250B population band — the
# "conventional" (size-based) peer grouping every bank already gets compared against
# elsewhere (regulatory peer groups, most vendor benchmarking tools), as opposed to
# the BEHAVIORAL clustering above. Comparing the two is the actual point of Feature
# 14: a size bucket says nothing about whether a bank funds itself or lends like its
# size-based "peers" do.
_SIZE_BUCKETS = [(10e9, "Community ($1B-$10B)"), (50e9, "Regional ($10B-$50B)"),
                 (float("inf"), "Super-regional ($50B-$250B)")]


def _size_bucket(assets: float | None) -> str | None:
    if assets is None:
        return None
    for cutoff, label in _SIZE_BUCKETS:
        if assets < cutoff:
            return label
    return _SIZE_BUCKETS[-1][1]


def get_cluster_diagnostics() -> dict:
    """Feature 14 governance — the real k-selection evidence behind the behavioral
    clustering every other page consumes (which always serves k=7, for stable
    cluster ids across quarters), plus where the SIZE-based "conventional" peer
    group a bank would normally get compared against disagrees with how it actually
    behaves.

    silhouette_by_k over k=2..7 is rendered here rather than hidden: k=4 can score
    higher on raw silhouette than the k=7 the app serves — that trade (stability/
    interpretability vs a marginally tighter k) is a real modeling choice a user
    should be able to see and judge, not something to quietly assert.
    """
    pop = data.population()
    diag = data.cluster_diagnostics()
    silhouette_by_k = [{"k": k, **v} for k, v in sorted(diag.items())]

    centroids = []
    for sid, certs in sorted(pop["cluster_members"].items(), key=lambda kv: -len(kv[1])):
        rows = [pop["by_cert"][c] for c in certs]
        centroids.append({
            "cluster_id": sid, "label": pop["cluster_labels"][sid], "size": len(rows),
            "centroid": {f: round(sum((r.get(f) or 0) for r in rows) / len(rows), 2)
                        for f in clustering.FEATURES},
        })

    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for g in pop["gold"]:
        b = _size_bucket(g.get("total_assets"))
        if b and g.get("peer_cluster_label"):
            by_bucket[b].append(g)

    bucket_summary, mismatches = [], []
    for bucket, rows in by_bucket.items():
        counts = Counter(r["peer_cluster_label"] for r in rows)
        modal_label, modal_count = counts.most_common(1)[0]
        mismatched = [r for r in rows if r["peer_cluster_label"] != modal_label]
        bucket_summary.append({
            "bucket": bucket, "size": len(rows), "modal_behavioral_cluster": modal_label,
            "modal_share": round(modal_count / len(rows), 3), "mismatch_count": len(mismatched),
        })
        for r in sorted(mismatched, key=lambda r: r.get("total_assets") or 0, reverse=True)[:8]:
            mismatches.append({
                "cert": r["cert_number"], "name": r["name"], "conventional_bucket": bucket,
                "bucket_modal_cluster": modal_label, "behavioral_cluster": r["peer_cluster_label"],
                "assets_b": round((r.get("total_assets") or 0) / 1e9, 1),
            })

    return {
        "quarter": pop["quarter"], "served_k": 7,
        "silhouette_by_k": silhouette_by_k,
        "centroids": centroids,
        "size_bucket_summary": sorted(bucket_summary, key=lambda b: -b["size"]),
        "sample_mismatches": sorted(mismatches, key=lambda m: -m["assets_b"])[:25],
    }


def get_model_card() -> dict:
    """Feature 13 governance — the deposit-flight model card: coefficients, in-sample
    AUC, the leave-one-out backtest against BOTH real crises it trains on (persisted
    at train time by deposit_flight_cli, not retrained per-request), the documented
    Washington Mutual exclusion (previously visible only in a source docstring, not
    to any UI user), the data-quality exclusions applied before training, and per-
    bank driver contributions for the live population — the beeswarm's raw data.
    """
    card = load_card()
    if card is None:
        raise ValueError("Deposit-flight model not trained yet; run deposit_flight_cli.")
    pop = data.population()
    driver_points = []
    for g in pop["gold"]:
        cert = g.get("cert_number")
        silver = pop["silver_by_cert"].get(cert)
        if silver is None:
            continue
        res = score_vector(card, features_from(silver, g, None))
        for d in res["drivers"]:
            driver_points.append({"cert": cert, "name": g["name"], "feature": d["feature"],
                                  "value": d["value"], "contribution": d["contribution"],
                                  "risk_score": res["risk_score"]})
    return {
        "features": card["features"], "weights": card["weights"], "bias": card["bias"],
        "auc": card["auc"], "trained_on": card["trained_on"],
        "positives": [{"cert": c, "name": n} for c, n in POSITIVE_CERTS.items()],
        "excluded_candidates": [{"cert": c, **info} for c, info in EXCLUDED_CANDIDATES.items()],
        "training_exclusions": card.get("exclusions"),
        "leave_one_out": card.get("leave_one_out", []),
        "scored_quarter": pop["quarter"],
        "driver_points": driver_points,
    }


# The Federal Reserve's own Bank Merger Competitive Review screening threshold — see
# footprint.herfindahl's docstring. This is the bank-specific figure, not the general
# DOJ/FTC 2500 threshold used for the wider economy.
BANK_MERGER_HHI_CONCENTRATED = 1800.0


def _full_universe_names() -> dict[int, str]:
    """Name for ANY landed cert, not just the $1B-$250B population — county
    concentration and the branch map both span the full ~4,431-cert SOD universe,
    most of which never enters the analytical population at all."""
    names = dict(data.bank_name_by_cert())
    names.update({c: g["name"] for c, g in data.population()["by_cert"].items()})
    return names


def get_county_concentration(state: str = None, top_n: int = 100) -> dict:
    """Feature 15 — real county-level deposit HHI computed over the FULL landed SOD
    universe (~4,431 certs, $18.1T in branch deposits), not just the $1B-$250B
    analytical slice — a share computed against the slice alone would overstate every
    number in it. County (FIPS state+county) is the market definition the Federal
    Reserve and DOJ actually use for bank-merger competitive review, so the HHI here
    means something a real regulator would recognize, unlike an invented coordinate
    grid.
    """
    names = _full_universe_names()
    rows = []
    for fips, entry in data.county_table().items():
        if state and (entry.get("state") or "").upper() != state.upper():
            continue
        c = county_concentration(entry)
        if c["hhi"] is None:
            continue
        c["concentrated"] = c["hhi"] >= BANK_MERGER_HHI_CONCENTRATED
        c["shares"] = [{**s, "name": names.get(s["cert"], f"CERT {s['cert']}")}
                       for s in c["shares"][:8]]
        rows.append(c)
    rows.sort(key=lambda r: r["hhi"], reverse=True)
    return {
        "as_of": "SOD 2025", "hhi_concentrated_threshold": BANK_MERGER_HHI_CONCENTRATED,
        "county_count": len(rows), "concentrated_count": sum(1 for r in rows if r["concentrated"]),
        "counties": rows[:top_n],
    }


# A generous contiguous-US bounding box (Census CONUS extent + margin). Needed
# because a handful of SOD rows carry a nominally-domestic STALPBR alongside a
# corrupt or foreign coordinate — verified live: 13 rows tagged with Pacific
# freely-associated-state codes (PW/FM/MH — Palau, Micronesia, Marshall Islands,
# not covered by NON_CONTIGUOUS_STATES) carry latitudes above 90 (impossible) or
# longitudes near 150-160, and one row tagged "NJ" carries a UK-area coordinate
# (50.4, -4.4) — an FDIC source data error, not this app's bug. Rendering these
# on an Albers-fit-to-bounds canvas silently squashed the whole contiguous US into
# a sliver: the fit stretches to whatever the data's extremes are.
_CONUS_LAT_RANGE = (20.0, 50.0)
_CONUS_LON_RANGE = (-130.0, -60.0)


def get_branch_map(state: str = None) -> dict:
    """Feature 15 map data — every landed branch's real coordinates, deposits and
    county, for a hand-rolled canvas projection (no tiles, no map-provider network
    calls). Restricted to the contiguous 48 states + DC: Albers USA's Alaska/Hawaii/
    territory insets need real boundary data this app doesn't have landed, so those
    branches (plus a handful of corrupt-coordinate rows, see _CONUS_LAT_RANGE) are
    counted and disclosed (excluded_non_contiguous), not silently dropped.
    """
    raw = data.sod_raw()
    names = _full_universe_names()

    def in_conus(r: dict) -> bool:
        if r.get("STALPBR") in data.NON_CONTIGUOUS_STATES:
            return False
        lat, lon = r.get("SIMS_LATITUDE"), r.get("SIMS_LONGITUDE")
        if lat is None or lon is None:
            return False
        return _CONUS_LAT_RANGE[0] <= lat <= _CONUS_LAT_RANGE[1] and _CONUS_LON_RANGE[0] <= lon <= _CONUS_LON_RANGE[1]

    excluded = sum(1 for r in raw if not in_conus(r))
    branches = []
    for r in raw:
        if not in_conus(r):
            continue
        st = r.get("STALPBR")
        if state and (st or "").upper() != state.upper():
            continue
        branches.append({
            "cert": r.get("CERT"), "lat": round(float(r["SIMS_LATITUDE"]), 3),
            "lon": round(float(r["SIMS_LONGITUDE"]), 3),
            "deposits": round((r.get("DEPSUMBR") or 0) * 1000), "fips": county_key(r),
        })
    certs_present = {b["cert"] for b in branches if b["cert"] is not None}
    return {
        "branch_count": len(branches), "excluded_non_contiguous": excluded,
        "bank_names": {c: names.get(c, f"CERT {c}") for c in certs_present},
        "branches": branches,
    }


def get_ma_network(top_n: int = 150) -> dict:
    """Feature 15 network view — the `top_n` largest banks by assets, plus every
    bank that appears among their top-3 M&A-fit partners, as a force-graph-ready
    node/edge list. Built from data.network_edges() (precomputed once per quarter,
    NOT scored on this request path — see that function's docstring for why: a
    live full sweep measured at ~17s).
    """
    pop = data.population()
    ranked = sorted(pop["gold"], key=lambda g: g.get("total_assets") or 0, reverse=True)
    seed_certs = [g["cert_number"] for g in ranked[:top_n]]
    edges_by_cert = data.network_edges()

    node_certs = set(seed_certs)
    edges = []
    for cert in seed_certs:
        for e in edges_by_cert.get(cert, []):
            node_certs.add(e["cert_number"])
            edges.append({"source": cert, "target": e["cert_number"], "fit_score": e["fit_score"]})

    nodes = []
    for cert in node_certs:
        g = pop["by_cert"].get(cert)
        if g is None:
            continue
        nodes.append({
            "cert": cert, "name": g["name"], "assets_b": round((g.get("total_assets") or 0) / 1e9, 1),
            "cluster_id": g.get("peer_cluster_id"), "cluster_label": g.get("peer_cluster_label"),
            "is_seed": cert in seed_certs,
        })
    return {"quarter": pop["quarter"], "seed_count": len(seed_certs),
            "nodes": nodes, "edges": edges}


MAX_BULK_STRESS_CERTS = 150   # a readable cross-bank chart, not an unbounded scan


def run_bulk_stress_test(certs: list[int], loan_loss_pct: float = 3.0,
                         deposit_outflow_pct: float = 15.0, rate_shock_bps: float = 200.0) -> dict:
    """Feature 16, cross-bank — the SAME shock applied to every named bank at once,
    so a cluster, a watchlist, or a top-N slice can be compared side by side under
    one scenario instead of clicking through banks individually. Scope resolution
    (which certs make up "this cluster" / "my watchlist" / "top N by assets") is
    the caller's job — the frontend already holds that population/watchlist data,
    so this tool does one thing: stress-test a named list.
    """
    if not certs:
        raise ValueError("certs must be a non-empty list")
    if len(certs) > MAX_BULK_STRESS_CERTS:
        raise ValueError(f"at most {MAX_BULK_STRESS_CERTS} banks per bulk stress test, got {len(certs)}")
    pop = data.population()
    shock = Shock(loan_loss_pct=loan_loss_pct, deposit_outflow_pct=deposit_outflow_pct,
                 rate_shock_bps=rate_shock_bps)
    results, skipped = [], []
    for cert in certs:
        silver = pop["silver_by_cert"].get(cert)
        if silver is None:
            skipped.append({"cert": cert, "name": None, "reason": "not in the $1B-$250B population slice"})
            continue
        pos = starting_position(silver)
        if pos.get("tier1_capital") is None or pos.get("rwa") is None:
            skipped.append({"cert": cert, "name": silver.get("name"), "reason": "missing capital-dollar fields"})
            continue
        results.append({"cert": cert, **run_stress_test(pos, shock)})
    results.sort(key=lambda r: r["after"]["cet1"])
    return {
        "shock": asdict(shock), "requested": len(certs), "tested": len(results),
        "skipped": skipped, "fail_count": sum(1 for r in results if not r["passes_all"]),
        "results": results,
    }


def run_stress_comparison(cert: int, loan_loss_pct: float = 3.0,
                          deposit_outflow_pct: float = 15.0, rate_shock_bps: float = 200.0) -> dict:
    """Feature 16 — the SAME shock priced two ways on the SAME bank: run_stress_test's
    modified-duration approximation vs run_stress_test_quantlib's real QuantLib DCF
    re-price. The DCF version captures bond convexity, so it consistently reports a
    SMALLER loss for the same rate shock (see stress.py's module docstring) — shown
    side by side rather than asserted in prose only.
    """
    silver = data.population()["silver_by_cert"].get(cert)
    if silver is None:
        raise ValueError(f"CERT {cert} not in the population slice.")
    pos = starting_position(silver)
    if pos.get("tier1_capital") is None or pos.get("rwa") is None:
        raise ValueError(f"CERT {cert} is missing capital-dollar fields; cannot stress test.")
    shock = Shock(loan_loss_pct=loan_loss_pct, deposit_outflow_pct=deposit_outflow_pct,
                 rate_shock_bps=rate_shock_bps)
    linear = run_stress_test(pos, shock)
    linear["pricing_engine"] = "linear_duration"
    dcf = run_stress_test_quantlib(pos, shock)
    return {"cert": cert, "name": pos["name"], "linear": linear, "quantlib": dcf}


def search_filings_text(query: str, top_n: int = 8) -> dict:
    """Feature 17 (Tier 6 capstone) — real semantic search over landed SEC 10-K
    Item 1A risk-factor text: the query is embedded with the same nomic-embed-text
    model used at land time, matched by cosine similarity in pgvector. Only
    filers that (a) have a confident CERT<->CIK crosswalk match and (b) had a
    HIGH-confidence Item 1A extraction are searchable — see get_filings_coverage
    for the honest real coverage, and cite the exact returned text, not a
    paraphrase, when answering from a result.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    try:
        vec = embeddings.embed(query)
    except embeddings.EmbeddingError as exc:
        raise ValueError(f"Embedding service unavailable: {exc}") from exc
    try:
        hits = search_filing_chunks(vec, top_n=top_n)
    except DbUnavailable as exc:
        raise ValueError(f"Filings search database unavailable: {exc}") from exc
    return {
        "query": query, "count": len(hits),
        "results": [{**h, "similarity": round(h["similarity"], 4)} for h in hits],
    }


def get_filings_coverage() -> dict:
    """Honest coverage for Feature 17 — how many filers/chunks are actually
    landed and searchable right now, by extraction confidence. Bounded and
    disclosed by design (see filings_cli.py's docstring): only the largest-by-
    assets population banks with a confident crosswalk match are eligible, and
    coverage grows only as far as that CLI has been re-run.
    """
    try:
        return filing_coverage_stats()
    except DbUnavailable as exc:
        raise ValueError(f"Filings database unavailable: {exc}") from exc


# ---- registry ------------------------------------------------------------
_CERT = {"type": "integer",
        "description": "FDIC certificate number (US banks), or the synthetic "
                       "cert_number BankLens assigns EU banks (see silver_eba.py) "
                       "— both are ordinary ints returned by list_banks/get_bank_profile."}

TOOLS = [
    {"name": "list_banks",
     "description": "Search/filter banks (US + EU) by name, state, country, or asset range.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "state": {"type": "string"},
         "country": {"type": "string", "description": "ISO-2 country code, e.g. 'US', 'DE', 'FR'"},
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
                    "the $1B-$250B slice, ranked descending. Optional state/cluster_label filter "
                    "the population before ranking.",
     "inputSchema": {"type": "object", "properties": {
         "top_n": {"type": "integer"}, "state": {"type": "string"},
         "cluster_label": {"type": "string"}}},
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
    {"name": "get_cluster_diagnostics",
     "description": "Feature 14 governance — silhouette-by-k evidence for the behavioral "
                    "clustering, cluster centroids, and where size-based 'conventional' "
                    "peer groups disagree with actual balance-sheet behavior.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_cluster_diagnostics},
    {"name": "get_model_card",
     "description": "Feature 13 governance — deposit-flight model coefficients, AUC, "
                    "leave-one-out backtest against both real crises, documented "
                    "exclusions (incl. Washington Mutual), and per-bank driver "
                    "contributions for the live population.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_model_card},
    {"name": "get_county_concentration",
     "description": "Feature 15 — real county-level deposit HHI over the full "
                    "~4,431-cert SOD universe, against the Fed's bank-merger "
                    "screening threshold (HHI >= 1800).",
     "inputSchema": {"type": "object", "properties": {
         "state": {"type": "string"}, "top_n": {"type": "integer"}}},
     "handler": get_county_concentration},
    {"name": "get_branch_map",
     "description": "Feature 15 — every landed branch's real lat/lon, deposits and "
                    "county, for a hand-rolled US branch map (contiguous states only).",
     "inputSchema": {"type": "object", "properties": {"state": {"type": "string"}}},
     "handler": get_branch_map},
    {"name": "get_ma_network",
     "description": "Feature 15 — force-graph nodes/edges of the largest banks and "
                    "their top M&A-fit partners, colored by behavioral cluster.",
     "inputSchema": {"type": "object", "properties": {"top_n": {"type": "integer"}}},
     "handler": get_ma_network},
    {"name": "run_bulk_stress_test",
     "description": "Feature 16, cross-bank — the same shock applied to a named "
                    "list of banks (a cluster, watchlist, or top-N slice) at once.",
     "inputSchema": {"type": "object", "properties": {
         "certs": {"type": "array", "items": {"type": "integer"}},
         "loan_loss_pct": {"type": "number"}, "deposit_outflow_pct": {"type": "number"},
         "rate_shock_bps": {"type": "number"}}, "required": ["certs"]},
     "handler": run_bulk_stress_test},
    {"name": "run_stress_comparison",
     "description": "Feature 16 — the same shock priced two ways on one bank: "
                    "linear-duration approximation vs a real QuantLib DCF re-price.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "loan_loss_pct": {"type": "number"},
         "deposit_outflow_pct": {"type": "number"}, "rate_shock_bps": {"type": "number"}},
         "required": ["cert"]},
     "handler": run_stress_comparison},
    {"name": "search_filings_text",
     "description": "Feature 17 — semantic search over landed SEC 10-K Item 1A "
                    "risk-factor text (pgvector cosine similarity). Cite the "
                    "returned text exactly, not a paraphrase.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "top_n": {"type": "integer"}}, "required": ["query"]},
     "handler": search_filings_text},
    {"name": "get_filings_coverage",
     "description": "Feature 17 — how many filers/chunks are actually landed and "
                    "searchable right now, by extraction confidence.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_filings_coverage},
]

TOOL_BY_NAME = {t["name"]: t for t in TOOLS}
