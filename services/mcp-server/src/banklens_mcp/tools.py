"""MCP tool contracts for BankLens — thin wrappers over the feature logic.

Each tool: read Gold / feature functions, return a JSON-serialisable result. The
same functions power the CLI. See docs/api/mcp-tools.md.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from banklens_common import embeddings
from banklens_common.db import DbUnavailable, filing_coverage_stats, search_filing_chunks
from banklens_transforms import clustering
from banklens_transforms.deposit_flight import (
    EXCLUDED_CANDIDATES, features_from, list_card_versions, load_card, population_percentile,
    score_vector,
)
from banklens_transforms.filing_diff import build_quarters, diff
from banklens_transforms.footprint import county_concentration, county_key, merger_county_impact
from banklens_transforms.gold import quarters_before
from banklens_transforms.ma_fit import pro_forma, rank_partners
from banklens_transforms.market import (
    beta_vs_benchmark, daily_return_series, max_drawdown_pct, pearson_correlation,
    price_snapshot, rebased_series, realized_volatility_annualized, total_return_pct,
)
from banklens_transforms.peers import RANK_METRICS
from banklens_transforms.stress import (
    MINIMUMS, Shock, correlated_scenario, liquidity_survival_horizon, project_multi_period,
    run_stress_test, run_stress_test_quantlib, starting_position,
)
from banklens_transforms.data_quality import capital_basis, exclusion_for, summarize
from banklens_transforms.xray import evaluate_xray

from . import data, licensing


def _need_bank(cert: int, as_of: str | None = None, quarter: str | None = None) -> dict:
    """`quarter` (D3, REPDTE e.g. "20260331"): view this bank as of a DIFFERENT
    landed quarter than the latest, distinct from `as_of` (B9's point-in-time
    Bronze-snapshot reproduction) — the two compose: `quarter` picks WHICH
    quarter's population, `as_of` picks WHICH Bronze landing of that quarter."""
    row = data.population(quarter, as_of=as_of)["by_cert"].get(cert)
    if row is None:
        raise ValueError(
            f"CERT {cert} is not in the landed FDIC population "
            f"({quarter or data.latest_quarter()})"
            + (f" as of {as_of}" if as_of else "") + ".")
    return row


# ---- handlers ------------------------------------------------------------
def list_banks(query: str | None = None, state: str | None = None, country: str | None = None,
               min_assets_b: float | None = None, max_assets_b: float | None = None,
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


_PEER_BASIS_SUFFIX = {"global": "", "size": "_within_size", "cluster": "_within_cluster"}


def get_bank_profile(cert: int, as_of: str | None = None, quarter: str | None = None,
                     peer_basis: str = "global") -> dict:
    """`as_of` (B9, YYYYMMDD): reproduce this profile as it stood on that
    landing date, not today's — see data.population's docstring. Omit for
    today's unchanged behavior. `quarter` (D3, REPDTE): view a DIFFERENT
    landed quarter than the latest — see _need_bank's docstring for how the
    two compose. `peer_basis` (C11): which population every `percentile` field
    below is computed against — 'global' (the whole landed population, the
    default, unchanged from before C11), 'size' (only same-`asset_band`
    peers), or 'cluster' (only same-behavioral-peer-cluster banks). See
    peers.add_percentile_ranks for how all three are computed in one pass."""
    if peer_basis not in _PEER_BASIS_SUFFIX:
        raise ValueError(f"peer_basis must be one of {sorted(_PEER_BASIS_SUFFIX)}, got {peer_basis!r}")
    g = _need_bank(cert, as_of=as_of, quarter=quarter)
    suffix = _PEER_BASIS_SUFFIX[peer_basis]
    def pct(key):
        return {"value": g.get(key), "percentile": g.get(f"percentile_rank_{key}{suffix}")}

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
            # B7 (docs/audit/04-remediation-prompts.md): FDIC publishes SOD only
            # annually, so this branch data can be up to ~18 months stale
            # relative to `quarter`'s quarterly financials — structural on
            # every branch-derived figure, not one hardcoded string on one tool.
            "sod_vintage": data.sod_vintage(),
        }

    return {
        "cert": cert, "name": g["name"], "state": g.get("state"),
        "country": g.get("country"), "quarter": g["quarter"],
        "as_of": as_of,   # B9 — null means "today's latest landed snapshot"
        "peer_basis": peer_basis,  # C11 — which population every "percentile" below is against
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
        # C8 — credit-quality TRAJECTORY (trend/acceleration over this bank's
        # own landed history), not just today's level. See
        # banklens_transforms.gold.credit_trajectory.
        "credit_trajectory": {
            "npl_ratio_pct": pct("npl_ratio_pct"),
            "npl_trend_pp_per_qtr": g.get("npl_trend_pp_per_qtr"),
            "npl_acceleration": g.get("npl_acceleration"),
            "net_charge_off_rate_pct": pct("net_charge_off_rate_pct"),
            "net_charge_off_trend_pp_per_qtr": g.get("net_charge_off_trend_pp_per_qtr"),
            "allowance_coverage_pct": pct("allowance_coverage_pct"),
            "allowance_coverage_trend_pp_per_qtr": g.get("allowance_coverage_trend_pp_per_qtr"),
            "deterioration_flag": g.get("deterioration_flag"),
            "deterioration_signal_count": g.get("deterioration_signal_count"),
            "deterioration_signals_available": g.get("deterioration_signals_available"),
            "trajectory_quarters": g.get("trajectory_quarters"),
        },
        # EU banks only (B2, from EBA's tr_cre.csv credit-risk cube): a
        # supervisory NPL ratio distinct from `npl_ratio_pct` (which for EU
        # banks is an IFRS-9-Stage-3 accounting proxy), and a sector-
        # concentration proxy over the 19 NACE Rev.2 sections. All None for
        # FDIC-sourced banks and for EU banks without a landed credit-risk row.
        "credit_risk_eu": {
            "npl_ratio_pct_supervisory": g.get("npl_ratio_pct_supervisory"),
            "sector_concentration_hhi": g.get("sector_concentration_hhi"),
            "sector_concentration_top_sector": g.get("sector_concentration_top_sector"),
            "sector_concentration_top_pct": g.get("sector_concentration_top_pct"),
        },
    }


def _sibling_charters(rssd: int, exclude_cert: int) -> list[dict]:
    """D4 — every OTHER landed FDIC charter reporting the same holding-company
    RSSD as `exclude_cert`, so a multi-bank holding company renders as one
    group with its member charters listed rather than one bank's page
    silently ignoring that it has siblings."""
    pop = data.population()
    out = []
    for c, silver in pop["silver_by_cert"].items():
        if c == exclude_cert or silver.get("holding_company_rssd") != rssd:
            continue
        g = pop["by_cert"].get(c)
        if g is None:
            continue
        out.append({"cert": c, "name": g["name"], "total_assets": g.get("total_assets")})
    out.sort(key=lambda b: b["total_assets"] or 0, reverse=True)
    return out


def get_holding_company(cert: int) -> dict:
    """B4/D4 — this bank charter's holding company (Fed NIC FR Y-9C, real
    data), with consolidated financials alongside the charter-level ones so a
    caller can see which figures are charter-level versus consolidated at the
    group, plus every sibling FDIC charter that rolls up to the same holding
    company (D4's "multi-charter holding company renders as one entity").
    """
    g = _need_bank(cert)
    silver = data.population()["silver_by_cert"].get(cert) or {}
    rssd = silver.get("holding_company_rssd")
    holdco = data.holding_company_for_cert(cert)
    if rssd is None:
        return {"cert": cert, "name": g["name"], "has_holding_company": False,
               "note": "FDIC reports no separate holding company for this charter — "
                       "it files (or would file) with the SEC at the bank level directly."}
    siblings = _sibling_charters(rssd, cert)
    if holdco is None:
        return {"cert": cert, "name": g["name"], "has_holding_company": True,
               "holding_company_rssd": rssd, "holding_company": None,
               "sibling_charters": siblings,
               "note": "This bank's holding company (RSSD "
                       f"{rssd}) has no landed FR Y-9C filing — not every holding company "
                       "reports Y-9C (e.g. below the reporting-exemption asset threshold), "
                       "or Fed NIC data hasn't been landed (scripts/land_fed_nic.ps1)."}
    return {
        "cert": cert, "name": g["name"], "has_holding_company": True,
        "holding_company_rssd": rssd,
        "sibling_charters": siblings,
        "charter_level": {"total_assets": g.get("total_assets"),
                          "cet1_ratio": g.get("cet1_ratio"),
                          "leverage_ratio": g.get("leverage_ratio")},
        "holding_company": holdco,
    }


def get_bank_xray(cert: int, quarter: str | None = None) -> dict:
    # Gold row carries percentile ranks -> flags get peer context. Which capital rules
    # apply depends on the bank's regulatory capital regime: 195 CBLR electers and 13
    # foreign-bank branches report zeros for reasons that are not thin capital, and
    # were otherwise all flagged "CET1 below the Basel minimum".
    # D3: `quarter` (REPDTE) views a DIFFERENT landed quarter than the latest.
    silver = data.population(quarter)["silver_by_cert"].get(cert) or {}
    return evaluate_xray(_need_bank(cert, quarter=quarter), capital_basis=capital_basis(silver))


def get_peer_cluster(cert: int, quarter: str | None = None) -> dict:
    pop = data.population(quarter)
    g = _need_bank(cert, quarter=quarter)
    cid = g.get("peer_cluster_id")
    mates = [c for c in pop["cluster_members"].get(cid, []) if c != cert]
    names = [pop["by_cert"][c]["name"] for c in mates[:6]]
    return {"cert": cert, "cluster_id": cid, "cluster_label": pop["cluster_labels"].get(cid),
            "cluster_size": len(pop["cluster_members"].get(cid, [])),
            "sample_peers": names}


def find_ma_matches(cert: int, top_n: int = 8, quarter: str | None = None) -> dict:
    pop = data.population(quarter)
    target = _need_bank(cert, quarter=quarter)
    ranked = rank_partners(target, pop["gold"], top_n=top_n, footprints=data.footprints())
    # B7: every candidate's `geo_overlap` component comes from `footprints()`,
    # i.e. the same landed-annually SOD data get_bank_profile/get_branch_map/
    # get_county_concentration disclose a vintage for — see that discussion.
    return {"target": target["name"], "candidates": ranked, "sod_vintage": data.sod_vintage()}


def get_ma_pro_forma(target_cert: int, acquirer_cert: int, *, premium_to_tbv_pct: float = 20.0,
                     cost_synergies_pct_of_target_opex: float = 30.0,
                     tax_rate_pct: float = 21.0) -> dict:
    """C9 — pro-forma calculator for a proposed (target, acquirer) combination:
    combined assets/CET1/goodwill/dilution/earn-back (banklens_transforms.
    ma_fit.pro_forma) plus the combined county-level HHI impact
    (banklens_transforms.footprint.merger_county_impact), flagging every
    county the combination would push over the Fed's 1800 screening
    threshold. `target_cert`/`acquirer_cert` need not be pre-ranked
    candidates from find_ma_matches — any two landed banks can be paired.
    """
    pop = data.population()
    target_silver = pop["silver_by_cert"].get(target_cert)
    acquirer_silver = pop["silver_by_cert"].get(acquirer_cert)
    if target_silver is None:
        raise ValueError(f"CERT {target_cert} (target) not in the population slice.")
    if acquirer_silver is None:
        raise ValueError(f"CERT {acquirer_cert} (acquirer) not in the population slice.")
    result = pro_forma(target_silver, acquirer_silver, premium_to_tbv_pct=premium_to_tbv_pct,
                       cost_synergies_pct_of_target_opex=cost_synergies_pct_of_target_opex,
                       tax_rate_pct=tax_rate_pct)
    names = _full_universe_names()
    county_impact = merger_county_impact(data.county_table(), target_cert, acquirer_cert,
                                         hhi_threshold=BANK_MERGER_HHI_CONCENTRATED)
    for c in county_impact:
        c["name"] = c.get("name") or f"FIPS {c['fips']}"
    result["county_impact"] = {
        "sod_vintage": data.sod_vintage(),
        "hhi_concentrated_threshold": BANK_MERGER_HHI_CONCENTRATED,
        "counties_affected": len(county_impact),
        "counties_crossing_threshold": sum(1 for c in county_impact if c["crosses_threshold"]),
        "counties": county_impact,
    }
    result["target"]["name"] = names.get(target_cert, result["target"]["name"])
    result["acquirer"]["name"] = names.get(acquirer_cert, result["acquirer"]["name"])
    return result


_MA_WEIGHT_VALIDATION_PATH = (
    Path(__file__).resolve().parents[4] / "ml" / "ma_fit" / "weight_validation.json")


def get_ma_weight_validation() -> dict:
    """C9 governance — whether `ma_fit.DEFAULT_WEIGHTS` actually rank real
    acquirers above non-acquirers, validated against real deal history
    (ma_weights_cli.py) rather than left as a hand-set, untested assumption.
    Persisted at validation-run time (a coarse weight-grid refit is real
    compute), not recomputed per request — same pattern as the deposit-flight
    model card.
    """
    if not _MA_WEIGHT_VALIDATION_PATH.exists():
        raise ValueError(
            "M&A weight validation not run yet; run ma_weights_cli "
            "(scripts/ma_weights.ps1).")
    return json.loads(_MA_WEIGHT_VALIDATION_PATH.read_text(encoding="utf-8"))


_XRAY_VALIDATION_PATH = (
    Path(__file__).resolve().parents[4] / "ml" / "xray" / "forward_return_validation.json")


def get_xray_forward_return_validation() -> dict:
    """C10 governance — the cheapest genuine validation available for the
    X-Ray rule engine: do banks it flags high-risk subsequently underperform
    in the market? Persisted by xray_validation_cli.py (needs landed Tiingo
    price data — see scripts/land_market_data.ps1); a zero-observation result
    means no price data is landed yet, not that the validation failed.
    """
    if not _XRAY_VALIDATION_PATH.exists():
        raise ValueError(
            "X-Ray forward-return validation not run yet; run xray_validation_cli "
            "(scripts/xray_validation.ps1).")
    return json.loads(_XRAY_VALIDATION_PATH.read_text(encoding="utf-8"))


def _stress_position(cert: int) -> dict:
    silver = data.population()["silver_by_cert"].get(cert)
    if silver is None:
        raise ValueError(f"CERT {cert} not in the population slice.")
    pos = starting_position(silver)
    if pos.get("tier1_capital") is None or pos.get("rwa") is None:
        raise ValueError(f"CERT {cert} is missing capital-dollar fields; cannot stress test.")
    return pos


def run_stress(cert: int, loan_loss_pct: float = 3.0, deposit_outflow_pct: float = 15.0,
               rate_shock_bps: float = 200.0) -> dict:
    pos = _stress_position(cert)
    return run_stress_test(pos, Shock(loan_loss_pct=loan_loss_pct,
                                      deposit_outflow_pct=deposit_outflow_pct,
                                      rate_shock_bps=rate_shock_bps))


def run_stress_projection(cert: int, loan_loss_pct: float = 3.0, deposit_outflow_pct: float = 15.0,
                          rate_shock_bps: float = 200.0, horizon_quarters: int = 4,
                          phase_in: bool = True, apply_ppnr_offset: bool = True) -> dict:
    """C4 — multi-period stress projection: phases the requested shock in over
    `horizon_quarters` and lets disclosed PPNR earn back part of each period's
    loss, instead of one instantaneous, un-offset hit. See
    banklens_transforms.stress.project_multi_period for the documented
    simplifications."""
    pos = _stress_position(cert)
    return project_multi_period(pos, Shock(
        loan_loss_pct=loan_loss_pct, deposit_outflow_pct=deposit_outflow_pct,
        rate_shock_bps=rate_shock_bps, horizon_quarters=horizon_quarters,
        phase_in=phase_in, apply_ppnr_offset=apply_ppnr_offset))


def get_liquidity_survival(cert: int, quarterly_outflow_pct: float = 15.0) -> dict:
    """C4 — how many quarters of on-balance-sheet liquidity a bank has under a
    SUSTAINED quarterly deposit-outflow rate, not a one-time shock. See
    banklens_transforms.stress.liquidity_survival_horizon."""
    pos = _stress_position(cert)
    return liquidity_survival_horizon(pos, Shock(deposit_outflow_pct=quarterly_outflow_pct))


_LOAN_CATEGORY_LABELS = ("construction", "multifamily", "nonfarm_nonres", "residential_mortgage",
                        "farmland", "agricultural", "c_and_i", "consumer")


def run_segmented_stress_test(cert: int, category_loan_loss_pct: dict[str, float] | None = None,
                              severity_multiplier: float = 3.0, deposit_outflow_pct: float = 15.0,
                              rate_shock_bps: float = 200.0) -> dict:
    """C6 — apply a PER-CATEGORY loan-loss rate instead of one blended
    percentage, so a CRE-concentrated bank and a consumer-lender respond
    differently to the same scenario. When `category_loan_loss_pct` isn't
    given, derives one from this bank's OWN currently-disclosed per-category
    charge-off rate (gold.charge_off_rates_by_category) scaled by
    `severity_multiplier` — "what if your own current loss experience per
    category got severity_multiplier times worse", a real, bank-specific
    starting point rather than an arbitrary flat guess."""
    pos = _stress_position(cert)
    if category_loan_loss_pct is None:
        g = data.population()["by_cert"].get(cert) or {}
        # A category can carry a real, disclosed NEGATIVE charge-off rate (net
        # recoveries exceeded gross charge-offs that quarter) — floor at 0 for
        # the auto-derived STRESS scenario default, since a stress test
        # shouldn't project a category improving; an explicit
        # category_loan_loss_pct override can still pass a negative rate.
        category_loan_loss_pct = {
            label: round(max(0.0, (g.get(f"charge_off_rate_pct_{label}") or 0.0)) * severity_multiplier, 3)
            for label in _LOAN_CATEGORY_LABELS
        }
    return run_stress_test(pos, Shock(category_loan_loss_pct=category_loan_loss_pct,
                                      deposit_outflow_pct=deposit_outflow_pct,
                                      rate_shock_bps=rate_shock_bps))


def get_irrbb(cert: int, parallel_shock_bps: float = 200.0) -> dict:
    """C5 — Economic Value of Equity (EVE) and 12-month Net Interest Income
    (NII) sensitivity under a parallel shift and a non-parallel steepener,
    reusing the same per-bank duration estimate the stress engine's rate-shock
    leg uses. See banklens_transforms.irrbb for the documented single-bucket
    approximation and its bucket-coarseness caveat."""
    from banklens_transforms.irrbb import compute_irrbb
    pos = _stress_position(cert)
    return compute_irrbb(pos, parallel_shock_bps=parallel_shock_bps)


def run_correlated_stress(cert: int, rate_shock_bps: float = 300.0, severity: str = "moderate") -> dict:
    """C4 — a single joint, correlated scenario: a rate shock triggers
    proportional deposit-outflow and loan-loss legs (documented assumptions,
    see banklens_transforms.stress.CORRELATION_ASSUMPTIONS) instead of three
    independently-set sliders."""
    pos = _stress_position(cert)
    shock = correlated_scenario(rate_shock_bps, severity=severity)
    result = run_stress_test(pos, shock)
    result["correlated_severity"] = severity
    result["derived_shock"] = {"loan_loss_pct": shock.loan_loss_pct,
                               "deposit_outflow_pct": shock.deposit_outflow_pct,
                               "rate_shock_bps": shock.rate_shock_bps}
    return result


def diff_filings(cert: int, quarter_a: str | None = None, quarter_b: str | None = None) -> dict:
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


_FILING_DIFF_POPULATION_SUMMARY_PATH = (
    Path(__file__).resolve().parents[4] / "ml" / "filing_diff" / "population_summary.json")


def get_filing_diff_population_summary() -> dict:
    """C13 governance — multiple-testing context for filing_diff's per-bank z
    flags: at the raw z>=2.0 threshold, how many of the flags shown across the
    whole population are expected by chance alone, and the Benjamini-Hochberg
    FDR-controlled alternative flag set. Persisted by
    filing_diff_population_cli.py (diffing 5,000+ banks x 13 items is real
    compute), not recomputed per request — same pattern as the deposit-flight
    model card and the M&A weight validation.
    """
    if not _FILING_DIFF_POPULATION_SUMMARY_PATH.exists():
        raise ValueError(
            "Filing-diff population summary not run yet; run "
            "filing_diff_population_cli (scripts/filing_diff_population.ps1).")
    return json.loads(_FILING_DIFF_POPULATION_SUMMARY_PATH.read_text(encoding="utf-8"))


_BACKTEST_RESULTS_PATH = Path(__file__).resolve().parents[4] / "ml" / "backtest" / "results.json"


def get_backtest_results() -> dict:
    """C14 governance — the backtest harness: for the X-Ray, deposit-flight
    and filing-diff signals, did flagged banks subsequently show deposit
    outflows, capital deterioration, credit deterioration, or failure/exit
    from the population, more often than the rest of the population? Pooled
    across every landed quarter transition and persisted by backtest_cli.py
    (banklens_transforms.backtest) — a null result (lift near 1, CI straddling
    it) is a real, reportable finding here, not an error.
    """
    if not _BACKTEST_RESULTS_PATH.exists():
        raise ValueError(
            "Backtest not run yet; run backtest_cli (scripts/backtest.ps1).")
    return json.loads(_BACKTEST_RESULTS_PATH.read_text(encoding="utf-8"))


def _prior_year_deposits(cert: int, current_quarter: str | None) -> float | None:
    """This bank's total deposits exactly 4 quarters before ``current_quarter``, from
    its own landed population history — the input `deposit_growth_1yr` (the highest-
    weighted deposit-flight feature) needs to compute a real YoY rate instead of being
    imputed. `None` if that quarter isn't landed for this bank, same "disclose, don't
    fabricate" contract as `gold.growth_rate_nyr`.
    """
    if not current_quarter:
        return None
    target = quarters_before(current_quarter, 4)
    row = next((r for r in data.bank_history(cert) if r.get("quarter") == target), None)
    return row.get("total_deposits") if row else None


def _score_full_population(card: dict, quarter: str | None = None) -> tuple[list[dict], int]:
    """Every landed bank's risk_score for `quarter` (D3: defaults to latest) —
    the shared population context both get_risk_score (for a single bank's
    percentile) and get_risk_leaderboard (for the ranking) need. Scoring is a
    handful of multiplications + a sigmoid, cheap enough to redo on every
    request with no caching/precomputation even at the ~4,350-bank widened
    population (docs/audit/04-remediation-prompts.md B3/F8)."""
    pop = data.population(quarter)
    scored = []
    imputed_count = 0
    for g in pop["gold"]:
        cert = g.get("cert_number")
        silver = pop["silver_by_cert"].get(cert)
        if silver is None:
            continue
        prior_dep = _prior_year_deposits(cert, silver.get("quarter"))
        if prior_dep is None:
            imputed_count += 1
        res = score_vector(card, features_from(silver, g, prior_dep))
        scored.append({"cert": cert, "name": g["name"], "state": g.get("state"),
                        "cluster_label": g.get("peer_cluster_label"),
                        "risk_score": res["risk_score"]})
    return scored, imputed_count


def get_risk_score(cert: int, quarter: str | None = None) -> dict:
    card = load_card()
    if card is None:
        raise ValueError("Deposit-flight model not trained yet; run deposit_flight_cli.")
    pop = data.population(quarter)
    silver = pop["silver_by_cert"].get(cert)
    g = pop["by_cert"].get(cert)
    if silver is None:
        raise ValueError(f"CERT {cert} not in the population slice.")
    prior_dep = _prior_year_deposits(cert, silver.get("quarter"))
    res = score_vector(card, features_from(silver, g, prior_dep))
    # C1 — the model's raw sigmoid output is not a calibrated probability of
    # failure (see the model card's calibration_curve); rank it against every
    # other bank scored THIS quarter instead, so what's shown is only ever the
    # thing that's actually true: relative structural resemblance.
    all_scores = [s["risk_score"] for s in _score_full_population(card, quarter)[0]]
    res.update(population_percentile(res["risk_score"], all_scores))
    growth_note = (" growth feature imputed (this bank has fewer than 4 landed quarters "
                    "of history)." if prior_dep is None else "")
    res.update({"cert": cert, "name": g["name"], "model_trained_on": card["trained_on"],
                # G8 — the exact card that produced this score, so it can be
                # reproduced later via load_card(card_hash) however many
                # retrains happen afterward.
                "model_card_hash": card.get("card_hash"),
                "note": "structural resemblance to real bank failures (2023: SVB/Signature/First "
                       "Republic; 2008: IndyMac — though IndyMac's own archetype, subprime-credit-"
                       "driven with a late retail run, is NOT reliably caught by this feature set, "
                       "see risk-score README)." + growth_note})
    return res


def get_risk_leaderboard(top_n: int = 25, state: str | None = None, cluster_label: str | None = None,
                         quarter: str | None = None) -> dict:
    """Feature 13, population-wide: score every landed FDIC bank and rank by
    deposit-flight resemblance. Optional state/cluster_label narrow the
    population BEFORE ranking, so top_n picks the riskiest within that slice
    rather than truncating a global ranking down to whichever of it happens to
    match. Percentile/decile (C1) are always computed against the FULL,
    unfiltered population, so a filtered leaderboard's percentiles still mean
    "resemblance rank among every bank this quarter", not just this slice.
    `quarter` (D3, REPDTE): rank a DIFFERENT landed quarter than the latest.
    """
    card = load_card()
    if card is None:
        raise ValueError("Deposit-flight model not trained yet; run deposit_flight_cli.")
    all_scored, imputed_count = _score_full_population(card, quarter)
    all_scores = [s["risk_score"] for s in all_scored]
    scored = [
        {**s, **population_percentile(s["risk_score"], all_scores)}
        for s in all_scored
        if (not state or (s.get("state") or "").upper() == state.upper())
        and (not cluster_label or s.get("cluster_label") == cluster_label)
    ]
    scored.sort(key=lambda r: r["risk_score"], reverse=True)
    growth_note = (f" growth feature imputed for {imputed_count}/{len(all_scored)} bank(s) "
                    "lacking 4 quarters of landed history." if imputed_count else
                    " growth feature computed for every bank (4+ quarters of landed history).")
    return {
        "count": len(scored),
        "model_trained_on": card["trained_on"],
        # Same honesty caveat get_risk_score carries per-bank — a leaderboard
        # of bare numbers with no caveat would overstate what this model is.
        "note": "structural resemblance to real bank failures (2023: SVB/Signature/First "
               "Republic; 2008: IndyMac — though IndyMac's own archetype, subprime-credit-"
               "driven with a late retail run, is NOT reliably caught by this feature set, "
               "see risk-score README)." + growth_note,
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
    # G3: this tool is one bank per call (entity_count=1) — always a display
    # use, never blocked. The check still runs on every call so it fails loud
    # the moment anyone changes this signature to accept multiple certs
    # without separately remembering the licensing boundary.
    licensing.assert_bulk_allowed("market_ohlc", entity_count=1, tool="get_price_candles")
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
    licensing.assert_bulk_allowed("market_ohlc", entity_count=1, tool="get_market_snapshot")
    snap = price_snapshot(bars)
    snap.update({"cert": cert, "name": g["name"]})
    return snap


def get_market_coverage() -> dict:
    """How many crosswalk-matched tickers are actually landed vs eligible
    right now, and how stale the oldest landed bar is — the honest coverage
    get_price_candles/get_market_snapshot's per-bank errors leave a caller to
    infer one bank at a time. Backed by market_cli.py's persisted cursor +
    hourly-budget landing scheme, not recomputed here (see data.market_coverage).
    """
    return data.market_coverage()


def get_market_overview(certs: list[int] | None = None, top_n: int = 20, window_days: int = 180) -> dict:
    """E2 (docs/audit/04-remediation-prompts.md) — the minimum cross-bank market
    computation /market needs (normally C10's remit): a rebased relative-
    performance series, a returns/volatility scatter, a pairwise return-
    correlation matrix, and a per-bank metrics table (beta, realized volatility
    vs peer median, max drawdown, tangible book value), over a peer set of
    `certs` or, absent one, the `top_n` largest-by-assets banks — all computed
    once here from real landed Tiingo candles (data.price_bars) and real Gold/
    Silver fundamentals, never fabricated.

    Coverage is disclosed, not hidden: EVERY requested bank appears in `banks`
    whether or not it has a crosswalk-matched ticker or landed price data —
    `has_price_data` says which — and only the priced subset feeds the
    performance chart, the scatter, the correlation matrix and the metrics
    table. `coverage_note` states plainly how partial that is.

    Beta benchmark: BankLens lands Tiingo tickers only via the CERT/RSSD
    crosswalk (individual banks — see data.ticker_for_cert), so no dedicated
    regional-bank index/ETF ticker (e.g. KRE) is ever landed; adding one would
    need a new, unbudgeted Tiingo symbol-hour. Beta is therefore computed
    against an EQUAL-WEIGHTED basket of every bank in THIS view with landed
    price data (the simple cross-sectional average of daily returns,
    rebalanced daily) — a peer-basket beta, not a market-index beta. A bank's
    own return is part of the basket it's measured against, so beta on a
    narrow peer set (few priced banks) should be read cautiously; `benchmark`
    in the response names this choice explicitly.

    price_to_tangible_book_value / price_to_earnings are deliberately NOT
    computed. Both need a real PER-SHARE book value / EPS to compare against a
    per-share price, which needs shares-outstanding data BankLens has not
    landed anywhere (SEC XBRL `dei:EntityCommonStockSharesOutstanding` /
    `us-gaap:EarningsPerShareDiluted` — filings_cli.py only extracts 10-K Item
    1A risk-factor text, not XBRL facts). Rather than divide a per-share price
    by an aggregate-dollar equity figure (a fabricated ratio wearing a real
    label), `tangible_book_value_usd` (aggregate total_equity -
    intangible_assets — the same real Gold-derivable components
    gold.texas_ratio_pct already uses) is shown instead, and
    `per_share_metrics_available` is False with a reason.
    """
    pop = data.population()
    by_cert = pop["by_cert"]

    if certs:
        target_certs = [c for c in certs if c in by_cert]
    else:
        rows = [g for g in pop["gold"] if g.get("total_assets") is not None]
        rows.sort(key=lambda g: g["total_assets"], reverse=True)
        target_certs = [g["cert_number"] for g in rows[:top_n]]

    banks = []
    bars_by_cert: dict[int, list[dict]] = {}
    returns_by_cert: dict[int, dict[str, float]] = {}
    for cert in target_certs:
        g = by_cert[cert]
        ticker = data.ticker_for_cert(cert)
        entry = {"cert": cert, "name": g["name"], "ticker": ticker, "has_price_data": False}
        if ticker:
            bars = data.price_bars(ticker)
            windowed = bars[-window_days:] if bars and window_days else bars
            if windowed and len(windowed) >= 2:
                entry["has_price_data"] = True
                bars_by_cert[cert] = windowed
                returns_by_cert[cert] = daily_return_series(windowed)
        banks.append(entry)

    priced_certs = [c for c in target_certs if c in bars_by_cert]

    # G3 (config/sources.yaml: market_ohlc.license.redistributable=false) —
    # `performance_series` below is each priced bank's own daily close rebased
    # to an index, i.e. Tiingo's underlying OHLCV in a linearly-transformed
    # (trivially invertible) shape, for however many banks are in this view.
    # Serving it for more than one bank at once is a bulk/redistribution
    # response, not display, and is blocked below. The scalar analytics
    # (total_return_pct, realized_volatility_pct, max_drawdown_pct,
    # beta_vs_peer_basket, the correlation matrix) are genuinely derived
    # aggregates computed once here — they don't reconstruct Tiingo's feed —
    # and are never blocked.
    market_bulk_blocked = licensing.bulk_blocked("market_ohlc", len(priced_certs))

    # Equal-weighted daily-return basket over the priced set — see docstring's
    # "Beta benchmark" section for why this stands in for a market index.
    basket_returns_by_date: dict[str, list[float]] = defaultdict(list)
    for cert in priced_certs:
        for d, r in returns_by_cert[cert].items():
            basket_returns_by_date[d].append(r)
    benchmark_returns = {d: sum(rs) / len(rs) for d, rs in basket_returns_by_date.items()}

    vol_by_cert = {
        cert: realized_volatility_annualized(bars_by_cert[cert], window=len(bars_by_cert[cert]))
        for cert in priced_certs
    }
    vol_values = [v for v in vol_by_cert.values() if v is not None]
    peer_median_vol = statistics.median(vol_values) if vol_values else None

    metrics = []
    for cert in priced_certs:
        g = by_cert[cert]
        silver = pop["silver_by_cert"].get(cert) or {}
        bars = bars_by_cert[cert]
        vol = vol_by_cert.get(cert)
        equity = silver.get("total_equity")
        tangible_book_value = (equity - (silver.get("intangible_assets") or 0)
                               if equity is not None else None)
        metrics.append({
            "cert": cert, "name": g["name"], "ticker": data.ticker_for_cert(cert),
            "total_return_pct": total_return_pct(bars),
            "realized_volatility_pct": vol,
            "vol_vs_peer_median_pct": (round(vol - peer_median_vol, 2)
                                       if vol is not None and peer_median_vol is not None else None),
            "max_drawdown_pct": max_drawdown_pct(bars),
            "beta_vs_peer_basket": beta_vs_benchmark(returns_by_cert[cert], benchmark_returns),
            "tangible_book_value_usd": tangible_book_value,
            "price_to_tangible_book_value": None,
            "price_to_earnings": None,
            "bars_used": len(bars),
        })

    performance_series = [] if market_bulk_blocked else [{
        "cert": cert, "name": by_cert[cert]["name"], "ticker": data.ticker_for_cert(cert),
        "series": rebased_series(bars_by_cert[cert]),
    } for cert in priced_certs]

    scatter = [{
        "cert": cert, "name": by_cert[cert]["name"],
        "return_pct": total_return_pct(bars_by_cert[cert]),
        "volatility_pct": vol_by_cert.get(cert),
    } for cert in priced_certs]

    correlation = {
        "certs": priced_certs,
        "labels": [by_cert[c]["name"] for c in priced_certs],
        "matrix": [[
            1.0 if a == b else pearson_correlation(returns_by_cert[a], returns_by_cert[b])
            for b in priced_certs
        ] for a in priced_certs],
    }

    return {
        "quarter": pop["quarter"], "window_days": window_days,
        "requested_count": len(target_certs), "priced_count": len(priced_certs),
        "coverage_note": f"{len(priced_certs)} of {len(target_certs)} banks in view "
                        f"have landed price data.",
        "banks": banks,
        "performance_series": performance_series,
        "performance_series_blocked": market_bulk_blocked,
        "performance_series_note": (
            f"Per-bank price series omitted for {len(priced_certs)} priced banks: Tiingo "
            "(config/sources.yaml source 'market_ohlc') is licensed redistributable=false, "
            "and a rebased daily series per bank is a bulk redistribution of that feed, not "
            "single-bank display. Request one cert to see its own series, or use the "
            "aggregate analytics below (return %, volatility, drawdown, beta, correlation), "
            "which are derived summaries, not blocked."
        ) if market_bulk_blocked else None,
        "scatter": scatter,
        "correlation": correlation,
        "metrics": metrics,
        "benchmark": "equal_weighted_peer_basket",
        "per_share_metrics_available": False,
        "per_share_metrics_note": (
            "price_to_tangible_book_value and price_to_earnings are not computed: BankLens "
            "has not landed shares-outstanding or diluted-EPS data (SEC XBRL "
            "dei:EntityCommonStockSharesOutstanding / us-gaap:EarningsPerShareDiluted are not "
            "landed by any ingestion CLI today) needed to put a per-share price on the same "
            "basis as book value/earnings. tangible_book_value_usd (aggregate total_equity - "
            "intangible_assets, real landed data) is shown instead of a fabricated ratio."),
    }


def get_data_freshness() -> dict:
    """B10 — per-source landing vintage: fetch timestamp, source URL, record
    count and (where the source has a fixed cadence) the expected next
    publication, read from the `_provenance.json` every landing already
    writes. A source that shows `landed: false` genuinely hasn't been landed
    in this environment yet — not hidden, not guessed."""
    return {"sources": data.data_freshness()}


# G9 — bounded, representative subset: the FDIC-sourced Silver fields and Gold
# ratios that feed get_risk_score's features_from() (deposit_flight.py), plus
# the raw fields they're built from. NOT the full Gold schema — a metric not
# listed here raises ValueError rather than a guess (see get_metric_lineage).
# Each entry: gold_function (the function that computes it, or None for a
# direct FDIC passthrough), formula, and (silver_field, fdic_code) pairs.
_METRIC_LINEAGE: dict[str, dict] = {
    "total_assets": {"gold_function": None,
                     "formula": "direct FDIC field (silver.to_bank_financials passthrough)",
                     "fields": [("total_assets", "ASSET")]},
    "total_deposits": {"gold_function": None,
                       "formula": "direct FDIC field (silver.to_bank_financials passthrough)",
                       "fields": [("total_deposits", "DEP")]},
    "total_equity": {"gold_function": None,
                     "formula": "direct FDIC field (silver.to_bank_financials passthrough)",
                     "fields": [("total_equity", "EQ")]},
    "securities_total": {"gold_function": None,
                         "formula": "direct FDIC field (silver.to_bank_financials passthrough)",
                         "fields": [("securities_total", "SC")]},
    "securities_htm": {"gold_function": None,
                       "formula": "silver.to_bank_financials: SCHA if FDIC-reported, else "
                                  "securities_total - securities_afs",
                       "fields": [("securities_htm", "SCHA")]},
    "cet1_ratio": {"gold_function": None,
                  "formula": "direct FDIC field (silver.to_bank_financials passthrough, already a %)",
                  "fields": [("cet1_ratio", "IDT1CER")]},
    "uninsured_deposit_pct": {"gold_function": "gold.uninsured_deposit_pct",
                              "formula": "uninsured_deposits / total_deposits * 100",
                              "fields": [("uninsured_deposits", "DEPUNINS"), ("total_deposits", "DEP")]},
    "loan_to_deposit_pct": {"gold_function": "gold.loan_to_deposit_pct",
                            "formula": "total_loans_net / total_deposits * 100",
                            "fields": [("total_loans_net", "LNLSNET"), ("total_deposits", "DEP")]},
    "htm_to_equity": {"gold_function": "deposit_flight.features_from",
                      "formula": "securities_htm / total_equity * 100",
                      "fields": [("securities_htm", "SCHA"), ("total_equity", "EQ")]},
    "securities_to_assets": {"gold_function": "deposit_flight.features_from",
                             "formula": "securities_total / total_assets * 100",
                             "fields": [("securities_total", "SC"), ("total_assets", "ASSET")]},
}


def get_metric_lineage(cert: int, metric: str, quarter: str | None = None) -> dict:
    """G9 — where one metric's number actually came from: the Gold function
    (or formula) that computed it, the exact Silver/FDIC source field(s) and
    their raw values, and the originating Bronze partition's path, checksum
    and fetch timestamp (resolved at query time from that partition's own
    `_provenance.json` — the same file `get_data_freshness` reads, see
    `data.population_provenance`). Covers the bounded set of FDIC-sourced
    capital/financial fields feeding `get_risk_score`, not the full Gold
    schema — an untracked `metric` raises rather than guessing.
    """
    spec = _METRIC_LINEAGE.get(metric)
    if spec is None:
        raise ValueError(
            f"lineage not tracked for metric '{metric}'. Tracked: {sorted(_METRIC_LINEAGE)}")
    pop = data.population(quarter)
    repdte = pop["quarter"]
    silver = pop["silver_by_cert"].get(cert)
    if silver is None:
        raise ValueError(f"CERT {cert} not in the population slice for {repdte}.")
    gold_row = pop["by_cert"].get(cert) or {}
    # Gold-computed ratios (uninsured_deposit_pct, loan_to_deposit_pct) live on the
    # Gold row; direct FDIC passthroughs (total_assets, cet1_ratio, ...) live on
    # Silver instead. Features private to deposit_flight.py (htm_to_equity,
    # securities_to_assets) are on neither — None there is a disclosed gap, not a bug.
    metric_value = gold_row[metric] if metric in gold_row else silver.get(metric)
    prov = data.population_provenance(repdte)
    return {
        "cert": cert, "metric": metric, "quarter": repdte,
        "gold_function": spec["gold_function"] or "silver.to_bank_financials (direct passthrough)",
        "formula": spec["formula"],
        "metric_value": metric_value,
        "source_fields": [{"silver_field": f, "fdic_field": code, "value": silver.get(f)}
                          for f, code in spec["fields"]],
        "provenance_available": prov is not None,
        "bronze_partition": prov.get("partition_path") if prov else None,
        "checksum": prov.get("checksum") if prov else None,
        "fetched_at": prov.get("fetched_at") if prov else None,
        "source_url": prov.get("endpoint") if prov else None,
    }


def get_macro_data() -> dict:
    """B5 — landed FRED macro series (Treasury yield curve, Fed funds,
    unemployment, CRE price index): `{series_id: {latest: {date, value},
    observations: [...]}}`. Empty `series` dict, not an error, if FRED hasn't
    been landed yet (needs the user's own free FRED_API_KEY — see
    scripts/land_fred.ps1) — same "degrade, don't crash" contract every other
    optional source in this module follows.
    """
    all_series = data.macro_series()
    return {
        "series": {
            sid: {"latest": obs[-1] if obs else None, "count": len(obs), "observations": obs}
            for sid, obs in all_series.items()
        },
        "landed": bool(all_series),
    }


def compare_banks(certs: list[int], metrics: list[str] | None = None, quarter: str | None = None) -> dict:
    # Was just the original 4 concentration/funding/capital fields — Wave 0c
    # added real earnings/credit metrics to Gold months after this default was
    # written, and nothing ever updated it, so /compare silently never showed
    # them even though every other page (population-metrics, distributions) did.
    metrics = metrics or ["uninsured_deposit_pct", "loan_to_deposit_pct",
                          "concentration_ratio_cre", "cet1_ratio", "leverage_ratio",
                          "roa_pct", "net_interest_margin_pct", "npl_ratio_pct",
                          "texas_ratio_pct", "brokered_deposit_pct"]
    # G3 — `metrics` is caller-controlled and pulled straight off the Gold row;
    # no Gold field is Tiingo-sourced today, but this is the one tool where a
    # caller picks arbitrary field names for potentially many banks at once, so
    # it gets the same registry check rather than relying on that staying true.
    licensing.assert_fields_bulk_allowed(metrics, entity_count=len(certs), tool="compare_banks")
    by = data.population(quarter)["by_cert"]
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
               "allowance_coverage_pct", "texas_ratio_pct", "noncurrent_assets_ratio_pct",
               # C8 — trajectory, not just a level snapshot: lets the credit page rank
               # by DETERIORATION (trend/acceleration) rather than only by where a
               # bank sits today.
               "npl_trend_pp_per_qtr", "npl_acceleration", "net_charge_off_trend_pp_per_qtr",
               "allowance_coverage_trend_pp_per_qtr", "deterioration_signal_count"],
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


def _percentile_of(value: float, all_values: list[float]) -> float:
    below = sum(1 for v in all_values if v < value)
    return round(below / len(all_values) * 100, 1)


def _apply_peer_set_percentiles(rows: list[dict], metrics: list[str]) -> None:
    """D5 — when a caller restricts a population view to a named peer set
    (`certs`), the Gold layer's `percentile_rank_*` fields still mean "rank
    among the FULL population". Overwrites each row's `percentile_rank_<metric>`
    in place with a rank computed ONLY within this filtered subset, so what's
    displayed is honestly "percentile within your peer set"."""
    for m in metrics:
        values = [r[m] for r in rows if r.get(m) is not None]
        if len(values) < 2:
            continue
        for r in rows:
            if r.get(m) is not None:
                r[f"percentile_rank_{m}"] = _percentile_of(r[m], values)


def get_population_metrics(group: str, limit: int = 2000, sort_by: str | None = None,
                           descending: bool = True, quarter: str | None = None,
                           certs: list[int] | None = None) -> dict:
    """One named metric group across the whole population, with peer percentiles.

    Powers the earnings / credit / funding / capital / concentration views. Returns
    identity columns plus the group's metrics and any `percentile_rank_*` already
    computed for them, so a page never has to re-derive a rank the Gold layer holds.
    `quarter` (D3, REPDTE): a DIFFERENT landed quarter than the latest. `certs`
    (D5): restrict to a named peer set and recompute percentiles WITHIN it.
    """
    metrics = METRIC_GROUPS.get(group)
    if metrics is None:
        raise ValueError(f"unknown metric group '{group}' — choose one of {sorted(METRIC_GROUPS)}")
    pop = data.population(quarter)
    if sort_by is not None and sort_by not in metrics:
        raise ValueError(f"cannot sort '{group}' by '{sort_by}' — not in that group")

    cert_filter = set(certs) if certs else None
    rows = []
    for g in pop["gold"]:
        if cert_filter is not None and g.get("cert_number") not in cert_filter:
            continue
        row = {k: g.get(k) for k in _IDENTITY}
        for m in metrics:
            row[m] = g.get(m)
            pr = g.get(f"percentile_rank_{m}")
            if pr is not None:
                row[f"percentile_rank_{m}"] = pr
        rows.append(row)

    if cert_filter is not None:
        _apply_peer_set_percentiles(rows, metrics)

    if sort_by:
        rows = [r for r in rows if r.get(sort_by) is not None]
        rows.sort(key=lambda r: r[sort_by], reverse=descending)
    else:
        rows.sort(key=lambda r: r.get("total_assets") or 0, reverse=True)
    return {"group": group, "quarter": pop["quarter"], "metrics": metrics,
            "count": len(rows), "banks": rows[:limit],
            "peer_set_size": len(cert_filter) if cert_filter is not None else None}


# A curated cross-group set for the heatmap — one glance across risk, credit, and
# earnings rather than 17 columns nobody can scan. Every one already has a computed
# percentile rank (peers.RANK_METRICS), so this is a projection, not new analysis.
HEATMAP_METRICS = [
    "uninsured_deposit_pct", "loan_to_deposit_pct", "max_loan_concentration_pct",
    "cre_to_total_capital_pct", "cet1_ratio", "leverage_ratio", "roa_pct",
    "net_interest_margin_pct", "npl_ratio_pct", "texas_ratio_pct",
]


def get_percentile_heatmap(
    top_n: int = 40, sort_by: str = "total_assets", metrics: list[str] | None = None,
    quarter: str | None = None, certs: list[int] | None = None,
) -> dict:
    """A bank x metric percentile matrix for `top_n` banks (by `sort_by`, default the
    largest by assets). Powers /heatmap. Cells are `percentile_rank_<metric>`
    (0-100), not the raw value — that is the point of a heatmap like this: it reads
    across metrics on one shared scale instead of mixing percent, ratio, and dollar
    units in the same row.

    `metrics` lets the caller pick a subset/reorder of columns (E6's metric
    picker); it is always filtered down to `peers.RANK_METRICS` — the only fields
    that actually have a computed `percentile_rank_*` — so a typo'd or
    unrecognized metric name silently drops rather than producing an
    all-null column or a KeyError. Falls back to the curated HEATMAP_METRICS
    set (unchanged default behavior) when `metrics` is None or empty after
    filtering. `quarter` (D3, REPDTE): a DIFFERENT landed quarter than the latest.
    `certs` (D5): restrict to a named peer set — cells then show percentile
    WITHIN that set, and `top_n`/`sort_by` narrow within the set.
    """
    pop = data.population(quarter)
    rows = [g for g in pop["gold"] if g.get(sort_by) is not None]
    if certs:
        cert_set = set(certs)
        rows = [g for g in rows if g.get("cert_number") in cert_set]
    rows.sort(key=lambda g: g[sort_by], reverse=True)
    rows = rows[:top_n]
    selected = [m for m in metrics if m in RANK_METRICS] if metrics else []
    selected = selected or HEATMAP_METRICS

    if certs:
        peer_rows = [{**{m: g.get(m) for m in selected}} for g in rows]
        _apply_peer_set_percentiles(peer_rows, selected)
        cells_by_idx = [
            [peer_rows[i].get(f"percentile_rank_{m}") for m in selected]
            for i in range(len(rows))
        ]
    else:
        cells_by_idx = [[g.get(f"percentile_rank_{m}") for m in selected] for g in rows]

    return {
        "quarter": pop["quarter"], "metrics": selected,
        # The full real Gold-computed catalog, so the frontend's metric picker
        # is sourced from what actually has data rather than a hand-duplicated
        # list that can drift from this one.
        "available_metrics": RANK_METRICS,
        "peer_set_size": len(certs) if certs else None,
        "banks": [{
            "cert": g["cert_number"], "name": g["name"], "cells": cells_by_idx[i],
        } for i, g in enumerate(rows)],
    }


# Curated for /trends line charts. Every one is a Gold field already computed by
# gold_features — this is a projection, not new analysis.
TREND_METRICS = [
    "total_assets", "uninsured_deposit_pct", "loan_to_deposit_pct", "cet1_ratio",
    "roa_pct", "net_interest_margin_pct", "npl_ratio_pct", "texas_ratio_pct",
    "brokered_deposit_pct", "max_loan_concentration_pct",
    # C15 — quarter-isolated counterparts of roa_pct/net_interest_margin_pct
    # (and roe/efficiency, tracked even though not separately charted here) —
    # FDIC's YTD-annualized ratios plot a Q1 value and a Q4 value on the same
    # line as if they were comparable, which they aren't. /trends charts these
    # instead of the raw YTD fields for the two metrics selectable there.
    "roa_pct_quarterly", "net_interest_margin_pct_quarterly",
    "roe_pct_quarterly", "efficiency_ratio_pct_quarterly",
    # E11 — deposit-type and loan-category composition, added so /banks/trends
    # (get_bank_trends) carries what BankPage's composition-migration Sankey
    # needs: core_deposit_pct alongside the already-present brokered_deposit_pct,
    # and the 8 DISJOINT loan-category concentration_ratio_* leaves (the same
    # set concentration_ratios()/LOAN_CATEGORIES uses for Feature 11, so these
    # sum to ~100% of gross loans each quarter — no new computation, just a
    # wider projection of existing gold_features fields).
    "core_deposit_pct",
    "concentration_ratio_construction", "concentration_ratio_multifamily",
    "concentration_ratio_nonfarm_nonres", "concentration_ratio_residential_mortgage",
    "concentration_ratio_farmland", "concentration_ratio_agricultural",
    "concentration_ratio_c_and_i", "concentration_ratio_consumer",
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
    cluster_mode = "refit"
    for q in quarters:
        # C3 — fixed-centroid cluster assignment for this multi-quarter view, so
        # a boundary bank with a stable balance sheet doesn't flip peer_cluster_label
        # purely from each quarter's k-means being refit independently. Falls back
        # to refit (data.population's own fallback) if no centroids are persisted.
        pop = data.population(q, cluster_mode="fixed")
        cluster_mode = pop.get("cluster_mode", cluster_mode)
        g = pop["by_cert"].get(cert)
        if g is not None:
            series.append(g)
    if not series:
        raise ValueError(
            f"CERT {cert} has no landed history in any of {', '.join(quarters) or 'no landed quarters'}.")
    return {
        "cert": cert, "name": series[-1]["name"], "metrics": TREND_METRICS,
        "cluster_mode": cluster_mode,
        "quarters": [s["quarter"] for s in series],
        "series": [{**{"quarter": s["quarter"]}, **{m: s.get(m) for m in TREND_METRICS},
                   "peer_cluster_label": s.get("peer_cluster_label")} for s in series],
    }


MAX_BULK_TRENDS_CERTS = 40  # a readable peer-set small-multiples view, not an unbounded scan


def get_bulk_bank_trends(certs: list[int]) -> dict:
    """E10 — the SAME per-quarter trajectory get_bank_trends returns for one bank,
    for an entire named peer set at once, so /trends' small-multiples view (one
    chart per metric, one line per bank in the set, plus a peer-median band) can
    render without N sequential HTTP round trips.

    This is NOT N calls to get_bank_trends glued together: that would reload every
    quarter's data.population() once per bank (N x Q population loads). Here the
    quarter loop is on the OUTSIDE — data.population(q, cluster_mode="fixed") is
    loaded ONCE PER QUARTER and every requested cert's row is pulled out of that
    same call, so an N-bank peer set costs the same Q population loads a single
    bank's get_bank_trends already pays (each cached after its first load), not
    N times as many. Follows compare_banks/run_bulk_stress_test's existing
    "one cross-bank tool, a bounded MAX_* cap, a `skipped` list for certs with
    no landed history" pattern rather than inventing a new shape.
    """
    if not certs:
        raise ValueError("certs must be a non-empty list")
    if len(certs) > MAX_BULK_TRENDS_CERTS:
        raise ValueError(f"at most {MAX_BULK_TRENDS_CERTS} banks per bulk trends request, got {len(certs)}")
    quarters = list(reversed(data.available_quarters()))  # oldest first, for charting
    cluster_mode = "refit"
    series_by_cert: dict[int, list[dict]] = {c: [] for c in certs}
    names: dict[int, str] = {}
    for q in quarters:
        pop = data.population(q, cluster_mode="fixed")
        cluster_mode = pop.get("cluster_mode", cluster_mode)
        by_cert = pop["by_cert"]
        for c in certs:
            g = by_cert.get(c)
            if g is None:
                continue
            names[c] = g["name"]
            series_by_cert[c].append({
                **{"quarter": g["quarter"]}, **{m: g.get(m) for m in TREND_METRICS},
                "peer_cluster_label": g.get("peer_cluster_label"),
            })
    banks, skipped = [], []
    for c in certs:
        series = series_by_cert[c]
        if not series:
            skipped.append({"cert": c, "reason": "no landed history in any of "
                             f"{', '.join(quarters) if quarters else 'no landed quarters'}"})
            continue
        banks.append({
            "cert": c, "name": names[c],
            "quarters": [s["quarter"] for s in series],
            "series": series,
        })
    return {
        "metrics": TREND_METRICS, "quarters": quarters, "cluster_mode": cluster_mode,
        "requested": len(certs), "banks": banks, "skipped": skipped,
    }


MAX_SPARKLINE_CERTS = 2500       # matches get_population_metrics' own page-size
# ceiling (default limit=2000) — this tool exists to batch the trend CELLS a
# population table already renders one row per cert for, not to serve a
# different scale of request than that table itself does.
SPARKLINE_QUARTERS_BACK = 8      # ~2 years — a sparkline a few dozen pixels wide
# doesn't need this bank's entire landed history (22 quarters and growing and
# counting) to show direction; capping the window keeps a multi-thousand-row
# response reasonable regardless of how far back Bronze eventually lands.


def get_population_trend_sparklines(certs: list[int], metrics: list[str]) -> dict:
    """E12 — batched trailing-quarter series for a sparkline column next to an
    already-rendered population table (screener/earnings/credit/funding), so a
    2,000-row table costs ONE extra request instead of one per row.

    Same quarter-loop-outside-bank-loop shape as get_bulk_bank_trends (E10):
    data.population(q) is loaded once per quarter, not once per (quarter, cert)
    pair. Deliberately a SEPARATE tool rather than reusing get_bulk_bank_trends —
    that one is capped at MAX_BULK_TRENDS_CERTS=40 for /trends' small-multiples
    view (a chart per metric, a line per bank, meant to stay readable), while a
    metric-group table can have thousands of rows and only needs the handful of
    metrics that table already shows as columns, not the fixed TREND_METRICS set.

    Every bank's `values[metric]` array is aligned 1:1 to the shared `quarters`
    list (null where that bank has no landed row that quarter) rather than only
    the quarters it happens to have, so a caller (both the Sparkline component
    and ExportCsvButton's trailing per-quarter columns) can index every bank's
    series against the same date grid with no per-bank offset bookkeeping.
    """
    if not certs:
        raise ValueError("certs must be a non-empty list")
    if len(certs) > MAX_SPARKLINE_CERTS:
        raise ValueError(f"at most {MAX_SPARKLINE_CERTS} banks per sparkline request, got {len(certs)}")
    if not metrics:
        raise ValueError("metrics must be a non-empty list")
    # G3 — caller-picked field names for potentially thousands of banks at
    # once, same registry check compare_banks/get_percentile_heatmap apply.
    licensing.assert_fields_bulk_allowed(metrics, entity_count=len(certs), tool="get_population_trend_sparklines")

    quarters = list(reversed(data.available_quarters()[:SPARKLINE_QUARTERS_BACK]))  # oldest first
    cert_list = list(dict.fromkeys(certs))  # de-dupe, preserve caller order
    values_by_cert: dict[int, dict[str, list]] = {c: {m: [] for m in metrics} for c in cert_list}
    seen_by_cert: dict[int, bool] = {c: False for c in cert_list}
    for q in quarters:
        pop = data.population(q)
        by_cert = pop["by_cert"]
        for c in cert_list:
            g = by_cert.get(c)
            for m in metrics:
                values_by_cert[c][m].append(g.get(m) if g is not None else None)
            if g is not None:
                seen_by_cert[c] = True
    banks, skipped = [], []
    for c in cert_list:
        if not seen_by_cert[c]:
            skipped.append({"cert": c, "reason":
                             f"no landed history in the last {len(quarters)} quarters"})
            continue
        banks.append({"cert": c, "values": values_by_cert[c]})
    return {
        "metrics": metrics, "quarters": quarters,
        "requested": len(cert_list), "banks": banks, "skipped": skipped,
    }


# The set of headline metrics /briefing screens for "biggest movers". Each maps to
# whether a HIGHER value is the more concerning direction, purely for how a mover is
# framed in the summary text — both directions are always reported.
_BRIEFING_METRICS = {
    "roa_pct": "Return on assets", "npl_ratio_pct": "NPL ratio",
    "texas_ratio_pct": "Texas Ratio", "cet1_ratio": "CET1 ratio",
    "uninsured_deposit_pct": "Uninsured deposits", "brokered_deposit_pct": "Brokered deposits",
}

# G3 canary: every curated multi-bank field list this module serves fixed
# (population metrics, heatmap, trends, briefing movers) — not caller-picked
# like compare_banks' `metrics`, so nothing checks them per-request. Checked
# once here, at import time, against the same registry compare_banks enforces
# live: a future edit that adds a Tiingo-sourced field to one of these lists
# fails the moment this module is imported, not the first time someone
# actually runs a bulk export against it.
licensing.assert_fields_bulk_allowed(
    _IDENTITY + [m for group in METRIC_GROUPS.values() for m in group]
    + HEATMAP_METRICS + TREND_METRICS + list(_BRIEFING_METRICS),
    entity_count=2, tool="module import canary (curated multi-bank field lists)")


def get_quarterly_briefing(top_n: int = 8) -> dict:
    """Population-wide "what changed this quarter" — real QoQ analysis across the
    latest two landed quarters, not a per-bank drill-down (that's /trends and
    /filing-diff). Four real signals:

      - population churn: certs present in one quarter's landed population but
        not the other (a new charter, a failure/merger, or a data-landing gap)
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

    def _cluster_migrations(cur_pop: dict, prev_pop: dict) -> list[dict]:
        out = []
        for c in cur_certs & prev_certs:
            a = prev_pop["by_cert"].get(c, {}).get("peer_cluster_label")
            b = cur_pop["by_cert"].get(c, {}).get("peer_cluster_label")
            if a and b and a != b:
                out.append({"cert": c, "name": cur_pop["by_cert"][c]["name"], "from": a, "to": b})
        return out

    # C3 — the SERVED migrations use fixed-centroid assignment (falls back to
    # refit if no centroids are persisted yet, same as population() itself), so
    # what's reported here is movement between behavioral groups, not k-means
    # landing in a slightly different place this quarter. `refit_comparison`
    # measures the gap directly rather than assuming fixed centroids matter.
    cur_fixed = data.population(cur_q, cluster_mode="fixed")
    prev_fixed = data.population(prev_q, cluster_mode="fixed")
    migrations = _cluster_migrations(cur_fixed, prev_fixed)
    migration_pairs: dict[str, int] = {}
    for m in migrations:
        key = f"{m['from']} -> {m['to']}"
        migration_pairs[key] = migration_pairs.get(key, 0) + 1

    refit_comparison: dict = {"fixed_centroids_available": cur_fixed.get("cluster_mode") == "fixed"}
    if refit_comparison["fixed_centroids_available"]:
        migrations_refit = _cluster_migrations(cur, prev)
        refit_only = {m["cert"] for m in migrations_refit} - {m["cert"] for m in migrations}
        refit_comparison.update({
            "refit_migration_count": len(migrations_refit),
            "fixed_migration_count": len(migrations),
            "refit_only_count": len(refit_only),
            "note": (f"{len(refit_only)} of {len(migrations_refit)} refit-reported migrations this "
                     "quarter did not occur under fixed centroids — attributable to k-means refit "
                     "noise rather than real behavioral movement." if migrations_refit else
                     "No migrations under either method this quarter."),
        })
    else:
        refit_comparison["note"] = (
            "No fixed centroids persisted yet (run cluster_centroids_cli) — migrations below use "
            "per-quarter refit, the same as every prior release.")

    risk_entrants: list[dict] = []
    card = load_card()
    if card is not None:
        def _all_scores(pop: dict) -> dict[int, float]:
            scored = {}
            for g in pop["gold"]:
                c = g.get("cert_number")
                silver = pop["silver_by_cert"].get(c)
                if silver is None:
                    continue
                scored[c] = score_vector(card, features_from(silver, g, None))["risk_score"]
            return scored
        cur_all, prev_all = _all_scores(cur), _all_scores(prev)
        cur_top = dict(sorted(cur_all.items(), key=lambda t: t[1], reverse=True)[:top_n])
        prev_top_certs = {c for c, _ in sorted(prev_all.items(), key=lambda t: t[1], reverse=True)[:top_n]}
        cur_score_pool = list(cur_all.values())
        for c, score in cur_top.items():
            if c not in prev_top_certs:
                risk_entrants.append({
                    "cert": c, "name": cur["by_cert"][c]["name"],
                    "risk_score": round(score, 4),
                    **population_percentile(score, cur_score_pool),
                })
        risk_entrants.sort(key=lambda r: r["risk_score"], reverse=True)

    return {
        "quarter": cur_q, "prior_quarter": prev_q,
        "population_count": len(cur_certs), "prior_population_count": len(prev_certs),
        "entered": entered, "exited": exited,
        "top_movers": movers[:top_n * 2],
        "cluster_migrations": {
            "count": len(migrations), "by_transition": migration_pairs,
            "sample": migrations[:top_n],
            "method": "fixed_centroids" if refit_comparison["fixed_centroids_available"] else "refit",
            "refit_comparison": refit_comparison,
        },
        "risk_leaderboard_entrants": risk_entrants,
        "risk_model_trained": card is not None,
    }


def get_asset_treemap(group_by: str = "peer_cluster_label", quarter: str | None = None) -> dict:
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
    pop = data.population(quarter)
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


def get_metric_distribution(metric: str, bins: int = 30, quarter: str | None = None,
                            certs: list[int] | None = None) -> dict:
    """Histogram + order statistics for one Gold metric across the population.

    Real analysis rather than data shipping, so it belongs server-side: the binning,
    the percentile cuts, and — importantly — the disclosure of which institutions were
    excluded and why. A distribution rendered without naming its exclusions would be a
    quietly misleading chart, which is the thing `data_quality` exists to prevent.
    `quarter` (D3, REPDTE): a DIFFERENT landed quarter than the latest. `certs`
    (D5): restrict the distribution to a named peer set instead of the full population.
    """
    pop = data.population(quarter)
    cert_filter = set(certs) if certs else None
    values, excluded = [], []
    for g in pop["gold"]:
        if cert_filter is not None and g.get("cert_number") not in cert_filter:
            continue
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
        "peer_set_size": len(cert_filter) if cert_filter is not None else None,
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


# Standard call-report-style asset tiers across the full landed population (B3
# widened this beyond the original $1B-$250B slice — see gold.ASSET_BANDS,
# whose cut points these mirror) — the "conventional" (size-based) peer
# grouping every bank already gets compared against elsewhere (regulatory peer
# groups, most vendor benchmarking tools), as opposed to the BEHAVIORAL
# clustering above. Comparing the two is the actual point of Feature 14: a size
# bucket says nothing about whether a bank funds itself or lends like its
# size-based "peers" do.
_SIZE_BUCKETS = [(1e9, "Community bank (under $1B)"),
                 (10e9, "Community ($1B-$10B)"), (50e9, "Regional ($10B-$50B)"),
                 (250e9, "Super-regional ($50B-$250B)"),
                 (float("inf"), "Global systemically important (over $250B)")]


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
    # Names for `card["positives"]` (cert numbers only) come from the SAME card's
    # own `leave_one_out` entries, not the module's `POSITIVE_CERTS` default —
    # that default is a fallback for callers that never pass `positive_certs`
    # (see deposit_flight.train); the actually-trained-on positives (B6: landed
    # from FDIC's own `failures` endpoint, not hardcoded) are only recoverable
    # from the persisted card itself.
    _lo_names = {r["cert"]: r["name"] for r in card.get("leave_one_out", [])}
    return {
        "features": card["features"], "weights": card["weights"], "bias": card["bias"],
        "auc": card["auc"], "trained_on": card["trained_on"],
        "positives": [{"cert": c, "name": _lo_names.get(c)} for c in card.get("positives", [])],
        "excluded_candidates": [{"cert": c, **info} for c, info in EXCLUDED_CANDIDATES.items()],
        "training_exclusions": card.get("exclusions"),
        "leave_one_out": card.get("leave_one_out", []),
        "scored_quarter": pop["quarter"],
        "driver_points": driver_points,
        # C1 — honest statistics computed once at train time (deposit_flight_cli)
        # and persisted in the card, not recomputed per request: bootstrap CIs are
        # a 200-resample refit and would make /model unusably slow otherwise.
        "imputation_rates": card.get("imputation_rates", {}),
        "bootstrap": card.get("bootstrap"),
        "pr_curve": card.get("pr_curve", []),
        "roc_curve": card.get("roc_curve", []),
        "calibration_curve": card.get("calibration_curve", []),
    }


# The Federal Reserve's own Bank Merger Competitive Review screening threshold — see
# footprint.herfindahl's docstring. This is the bank-specific figure, not the general
# DOJ/FTC 2500 threshold used for the wider economy.
BANK_MERGER_HHI_CONCENTRATED = 1800.0


def _full_universe_names() -> dict[int, str]:
    """Name for ANY landed cert, not just the analytical FDIC financials
    population (B3 widened that to the ~4,350-bank full universe too, but SOD
    and FDIC financials are separately-landed, separately-scoped sources — a
    cert can appear in one and not the other) — county concentration and the
    branch map both span the full ~4,431-cert SOD universe."""
    names = dict(data.bank_name_by_cert())
    names.update({c: g["name"] for c, g in data.population()["by_cert"].items()})
    return names


def get_county_concentration(state: str | None = None, top_n: int = 100) -> dict:
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
    for _fips, entry in data.county_table().items():
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
    vintage = data.sod_vintage()
    return {
        # Kept for existing consumers; `sod_vintage` (B7) is the structural
        # replacement — see get_bank_profile's footprint block for why this
        # can no longer be a single hardcoded string.
        "as_of": f"SOD {vintage['sod_year']}" if vintage else "SOD not landed",
        "sod_vintage": vintage,
        "hhi_concentrated_threshold": BANK_MERGER_HHI_CONCENTRATED,
        "county_count": len(rows), "concentrated_count": sum(1 for r in rows if r["concentrated"]),
        "counties": rows[:top_n],
    }


# A generous lat/lon box spanning the 50 states + DC (CONUS + Alaska + Hawaii),
# each with margin — NOT just CONUS. frontend/apps/web/src/usTopology.ts's
# us-atlas topology ships real Alaska/Hawaii Albers-USA insets (built with the
# same geoAlbersUsa() convention branch points are projected through), so AK/HI
# branches render correctly and are no longer excluded here.
#
# The box still exists to catch a small number of genuinely corrupt SOD rows —
# verified live against the landed 76,120-row dataset: 11 rows tagged with
# Pacific freely-associated-state codes (PW/FM/MH — Palau, Micronesia, Marshall
# Islands; real countries, not covered by NON_CONTIGUOUS_STATES) carry
# impossible latitudes (>90) or stray Pacific-basin coordinates far outside any
# US state, and one row tagged "NJ" carries a UK-area coordinate (50.4, -4.4) —
# an FDIC source data error, not this app's bug. Real state extents in the
# landed data: CONUS+DC lat 24.5-49.0 / lon -124.4 to -67.0; AK lat 53.8-71.3 /
# lon -166.2 to -131.6; HI lat 19.2-22.2 / lon -159.7 to -155.0 — so this box's
# margins (17-72.5 lat, -172 to -65 lon) comfortably contain all real branches
# while still excluding all 12 known-bad rows (confirmed by direct check of the
# landed data, not just the boundary math).
_US_LAT_RANGE = (17.0, 72.5)
_US_LON_RANGE = (-172.0, -65.0)


def get_branch_map(state: str | None = None) -> dict:
    """Feature 15 map data — for a d3-geo Albers-USA canvas projection
    (us-atlas topology, no tiles, no map-provider network calls — see
    usTopology.ts). Covers the 50 states + DC, including Alaska/Hawaii
    (rendered via us-atlas's pre-built Albers-USA insets). Excluded: US
    territories with no landed boundary data (PR/GU/VI/AS/MP, see
    data.NON_CONTIGUOUS_STATES) and a small number of genuinely
    corrupt-coordinate SOD rows (see _US_LAT_RANGE/_US_LON_RANGE) — both
    counted and disclosed (excluded_non_contiguous), not silently dropped.

    F9 — with no `state` filter this used to return every one of the ~75,000
    in-CONUS branch rows individually, which `GeographyPage` requested by
    default on every /geography load. Server-side aggregation now applies at
    that same national scope: instead of raw branches, returns one entry per
    county (FIPS; a coarse lat/lon grid cell as fallback for the small number
    of rows with no county code) — count, total deposits and a centroid,
    mirroring `BranchMapCanvas.tsx`'s own client-side `aggregateBranches()`
    bucketing exactly (same fips-or-grid key, same centroid-of-members
    definition) so the two produce visually identical bubbles; the client
    just no longer has to download ~75k points to compute it. A `state`
    filter still returns individual branches — already a small, per-state
    payload, and the only shape that can drive the client's zoom-to-detail
    dot rendering.
    """
    raw = data.sod_raw()
    names = _full_universe_names()

    def in_scope(r: dict) -> bool:
        if r.get("STALPBR") in data.NON_CONTIGUOUS_STATES:
            return False
        lat, lon = r.get("SIMS_LATITUDE"), r.get("SIMS_LONGITUDE")
        if lat is None or lon is None:
            return False
        return _US_LAT_RANGE[0] <= lat <= _US_LAT_RANGE[1] and _US_LON_RANGE[0] <= lon <= _US_LON_RANGE[1]

    excluded = sum(1 for r in raw if not in_scope(r))
    scoped = []
    for r in raw:
        if not in_scope(r):
            continue
        st = r.get("STALPBR")
        if state and (st or "").upper() != state.upper():
            continue
        scoped.append(r)

    if state:
        branches = [{
            "cert": r.get("CERT"), "lat": round(float(r["SIMS_LATITUDE"]), 3),
            "lon": round(float(r["SIMS_LONGITUDE"]), 3),
            "deposits": round((r.get("DEPSUMBR") or 0) * 1000), "fips": county_key(r),
        } for r in scoped]
        # int(...): `branches` is a plain dict (mixed-type values per key -- cert,
        # lat/lon floats, deposits int, fips str), so mypy can only infer each
        # value's type as the union of all of them; the cast makes this loop's
        # real int-cert assumption explicit instead of silencing the checker.
        certs_present = {int(b["cert"]) for b in branches if b["cert"] is not None}
        return {
            "aggregated": False,
            "branch_count": len(branches), "excluded_non_contiguous": excluded,
            "bank_names": {c: names.get(c, f"CERT {c}") for c in certs_present},
            "branches": branches, "cells": [],
            "sod_vintage": data.sod_vintage(),   # B7 — see get_bank_profile's footprint block
        }

    cells: dict[str, dict] = {}
    for r in scoped:
        lat, lon = float(r["SIMS_LATITUDE"]), float(r["SIMS_LONGITUDE"])
        fips = county_key(r)
        key = fips or f"grid:{round(lat * 2)}:{round(lon * 2)}"
        c = cells.get(key)
        if c is None:
            c = {"fips": fips, "lat_sum": 0.0, "lon_sum": 0.0, "branch_count": 0, "deposits": 0.0}
            cells[key] = c
        c["lat_sum"] += lat; c["lon_sum"] += lon
        c["branch_count"] += 1
        c["deposits"] += (r.get("DEPSUMBR") or 0) * 1000
    cell_list = [{
        "fips": c["fips"],
        "lat": round(c["lat_sum"] / c["branch_count"], 3),
        "lon": round(c["lon_sum"] / c["branch_count"], 3),
        "branch_count": c["branch_count"], "deposits": round(c["deposits"]),
    } for c in cells.values()]
    return {
        "aggregated": True,
        "branch_count": len(scoped), "excluded_non_contiguous": excluded,
        "bank_names": {}, "branches": [], "cells": cell_list,
        "sod_vintage": data.sod_vintage(),
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
            skipped.append({"cert": cert, "name": None, "reason": "not in the landed population"})
            continue
        pos = starting_position(silver)
        if pos.get("tier1_capital") is None or pos.get("rwa") is None:
            skipped.append({"cert": cert, "name": silver.get("name"), "reason": "missing capital-dollar fields"})
            continue
        results.append({"cert": cert, **run_stress_test(pos, shock)})
    # F6 — after["cet1"] can be None (no RWA disclosed to compute it against);
    # sort those to the end (stable, so their relative order is unaffected)
    # rather than crashing on a None/float comparison.
    results.sort(key=lambda r: (r["after"]["cet1"] is None, r["after"]["cet1"] or 0.0))
    return {
        "shock": asdict(shock), "requested": len(certs), "tested": len(results),
        "skipped": skipped,
        # Only a CONFIRMED fail counts — passes_all is None for a bank whose
        # ratios couldn't be computed at all, which is "not assessed", not "failed".
        "fail_count": sum(1 for r in results if r["passes_all"] is False),
        "results": results,
    }


_XRAY_SEVERITY_RANK = {"low": 0, "elevated": 1, "high": 2}
_XRAY_SEVERITY_LABEL = {0: "low", 1: "elevated", 2: "high"}


def summarize_portfolio(exposure_by_cert: dict[int, float]) -> dict:
    """D11 — aggregate a user's counterparty-exposure portfolio (persisted at
    the bridge layer in banklens_common.db.portfolio_positions, passed in here
    as {cert: total_exposure_amount}): exposure-weighted X-Ray severity,
    exposure-weighted deposit-flight resemblance percentile, concentration by
    behavioral cluster and state, and exposure passing/failing a standard
    stress scenario via the existing bulk stress tool.

    This is honestly scoped: the stress result below is "does THIS BANK pass
    its regulatory minimums under the shock", weighted by how much of the
    user's exposure sits with that bank — NOT a loss-given-default calculation
    applied directly to the exposure dollar amount, which would need recovery-
    rate assumptions this repo has no data to support.
    """
    if not exposure_by_cert:
        return {"positions": 0, "total_exposure": 0.0, "banks": []}

    certs = list(exposure_by_cert.keys())
    total_exposure = sum(exposure_by_cert.values())
    pop = data.population()
    by_cert = pop["by_cert"]

    banks = []
    weighted_severity = 0.0
    weighted_risk_pctile = 0.0
    risk_weight_total = 0.0
    by_cluster: dict[str, float] = {}
    by_state: dict[str, float] = {}

    card = load_card()
    all_scores = None
    if card is not None:
        all_scores = [s["risk_score"] for s in _score_full_population(card)[0]]

    for cert in certs:
        exposure = exposure_by_cert[cert]
        g = by_cert.get(cert)
        name = g["name"] if g else f"CERT {cert}"
        severity = None
        risk_pctile = None
        if g is not None:
            silver = pop["silver_by_cert"].get(cert) or {}
            xr = evaluate_xray(g, capital_basis=capital_basis(silver))
            severity = xr["overall_risk"]
            weighted_severity += _XRAY_SEVERITY_RANK[severity] * exposure
            cluster = g.get("peer_cluster_label")
            if cluster:
                by_cluster[cluster] = by_cluster.get(cluster, 0.0) + exposure
            state = g.get("state")
            if state:
                by_state[state] = by_state.get(state, 0.0) + exposure
            if card is not None and all_scores is not None:
                try:
                    prior_dep = _prior_year_deposits(cert, silver.get("quarter"))
                    res = score_vector(card, features_from(silver, g, prior_dep))
                    risk_pctile = population_percentile(res["risk_score"], all_scores)["resemblance_percentile"]
                    if risk_pctile is not None:
                        weighted_risk_pctile += risk_pctile * exposure
                        risk_weight_total += exposure
                except Exception:
                    pass
        banks.append({
            "cert": cert, "name": name, "exposure": exposure,
            "xray_severity": severity, "risk_resemblance_percentile": risk_pctile,
        })

    stress_summary = None
    try:
        bulk = run_bulk_stress_test(certs)
        pass_exposure = fail_exposure = untested_exposure = 0.0
        for r in bulk["results"]:
            exp = exposure_by_cert.get(r["cert"], 0.0)
            if r["passes_all"] is True:
                pass_exposure += exp
            elif r["passes_all"] is False:
                fail_exposure += exp
            else:
                untested_exposure += exp
        for s in bulk["skipped"]:
            untested_exposure += exposure_by_cert.get(s["cert"], 0.0)
        stress_summary = {
            "scenario": bulk["shock"], "exposure_passing": pass_exposure,
            "exposure_failing": fail_exposure, "exposure_untested": untested_exposure,
        }
    except ValueError:
        pass  # e.g. every cert missing capital-dollar fields — leave stress_summary None

    return {
        "positions": len(certs), "total_exposure": total_exposure, "banks": banks,
        "exposure_weighted_xray_severity":
            _XRAY_SEVERITY_LABEL.get(round(weighted_severity / total_exposure)) if total_exposure else None,
        "exposure_weighted_risk_resemblance_percentile":
            round(weighted_risk_pctile / risk_weight_total, 1) if risk_weight_total else None,
        "concentration_by_cluster": by_cluster,
        "concentration_by_state": by_state,
        "stress_summary": stress_summary,
    }


MAX_SURFACE_STEPS = 12  # keeps the grid readable and the per-request cell count bounded


def run_stress_surface(cert: int, loan_loss_pct: float = 3.0,
                       deposit_outflow_max_pct: float = 90.0, rate_shock_max_bps: float = 500.0,
                       steps: int = 7) -> dict:
    """E3 — stressed CET1 across a (deposit_outflow x rate_shock) GRID for ONE bank,
    holding loan_loss_pct fixed at the caller's slider value, for the Stress Lab's
    surface heatmap. `run_bulk_stress_test` above batches the SAME shock over MANY
    banks — the opposite axis from what a surface needs (many shocks, one bank) — so
    it can't be reused here; this does the steps x steps grid server-side in ONE
    request against the SAME already-loaded starting_position, rather than the
    frontend firing steps^2 separate HTTP round trips. Cheap: run_stress_test is pure
    arithmetic over one dict, not a query, so even the max 12x12 grid is instant.

    Every cell is a REAL run_stress_test() result — no interpolation, no fabricated
    values. `cet1_minimum_pct` is the same regulatory minimum (stress.MINIMUMS,
    the Basel III CET1 floor incl. the capital conservation buffer) every other
    stress surface in this app checks against, not an invented threshold.
    """
    if steps < 2 or steps > MAX_SURFACE_STEPS:
        raise ValueError(f"steps must be between 2 and {MAX_SURFACE_STEPS}, got {steps}")
    pos = _stress_position(cert)
    outflow_values = [round(deposit_outflow_max_pct * i / (steps - 1), 2) for i in range(steps)]
    rate_values = [round(rate_shock_max_bps * i / (steps - 1), 1) for i in range(steps)]

    cells = []
    fallback_duration_used = False
    legs_not_applied: list[dict] = []
    seen_legs: set[str] = set()
    for outflow in outflow_values:
        for rate in rate_values:
            shock = Shock(loan_loss_pct=loan_loss_pct, deposit_outflow_pct=outflow, rate_shock_bps=rate)
            res = run_stress_test(pos, shock)
            cells.append({
                "deposit_outflow_pct": outflow, "rate_shock_bps": rate,
                # F6 — "cet1" may be absent from `passes` entirely (no RWA
                # disclosed to compute it against), not just present-and-false.
                "cet1_after": res["after"]["cet1"], "passes_cet1": res["passes"].get("cet1"),
            })
            ds = res["duration_sources"]
            if ds["afs"] == "fallback_default" or ds["htm"] == "fallback_default":
                fallback_duration_used = True
            for leg in res["legs_not_applied"]:
                if leg["leg"] not in seen_legs:
                    seen_legs.add(leg["leg"])
                    legs_not_applied.append(leg)

    return {
        "cert": cert, "name": pos["name"], "quarter": pos["quarter"],
        "loan_loss_pct": loan_loss_pct,
        "deposit_outflow_values": outflow_values, "rate_shock_values": rate_values,
        "steps": steps, "cells": cells,
        "cet1_minimum_pct": MINIMUMS["cet1"],
        # Every grid cell shares this bank's single duration estimate (rate-shock
        # legs only vary bps, not the underlying AFS/HTM duration), so one flag
        # covers the whole surface rather than repeating it per cell.
        "fallback_duration_used": fallback_duration_used,
        # Same disclosure contract as run_stress_test's own `legs_not_applied` —
        # non-empty means part of the requested grid reflects FEWER shocks than
        # asked for (e.g. this bank discloses no deposit total), collected once
        # across the whole grid rather than repeated per cell.
        "legs_not_applied": legs_not_applied,
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
    landed and searchable right now, by extraction confidence, against the
    REAL eligible denominator (B8: docs/audit/04-remediation-prompts.md —
    every population bank with a confident CERT<->CIK crosswalk match, not
    just "however many happen to be landed"). `filings_cli.py` now walks this
    same eligible set with resumable cursor state instead of re-landing the
    same largest-by-assets head every run, so this percentage actually moves
    run over run.
    """
    try:
        stats = filing_coverage_stats()
    except DbUnavailable as exc:
        raise ValueError(f"Filings database unavailable: {exc}") from exc
    eligible = data.filings_eligible_count()
    stats["eligible"] = eligible
    stats["coverage_pct"] = round(stats["filers"] / eligible * 100, 1) if eligible else 0.0
    return stats


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
     "description": "Core Silver/Gold profile for one bank. Optional as_of (YYYYMMDD, B9) "
                    "reproduces the profile as it stood on that landing date, honoring "
                    "later FDIC restatements only if as_of is on or after them.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "as_of": {"type": "string"}}, "required": ["cert"]},
     "handler": get_bank_profile},
    {"name": "get_holding_company",
     "description": "B4 — this bank's holding company (real Fed NIC FR Y-9C data) with "
                    "consolidated financials, or a stated reason it has none / isn't landed.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_holding_company},
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
    {"name": "get_ma_pro_forma",
     "description": "Feature 15 (C9) — pro-forma calculator for a proposed acquisition: combined "
                    "assets/CET1/goodwill/dilution/earn-back, plus combined county HHI impact.",
     "inputSchema": {"type": "object", "properties": {
         "target_cert": _CERT, "acquirer_cert": _CERT,
         "premium_to_tbv_pct": {"type": "number"},
         "cost_synergies_pct_of_target_opex": {"type": "number"},
         "tax_rate_pct": {"type": "number"}},
         "required": ["target_cert", "acquirer_cert"]},
     "handler": get_ma_pro_forma},
    {"name": "get_ma_weight_validation",
     "description": "Feature 15 (C9) governance — whether the M&A fit-score weights actually rank "
                    "real acquirers above non-acquirers, validated against real deal history.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_ma_weight_validation},
    {"name": "get_xray_forward_return_validation",
     "description": "Feature 14 (C10) governance — whether X-Ray-flagged banks subsequently "
                    "underperform in the market, validated against landed Tiingo price history.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_xray_forward_return_validation},
    {"name": "get_filing_diff_population_summary",
     "description": "Feature 12 (C13) governance — expected false positives at the raw filing-diff "
                    "z threshold across the whole population, plus a Benjamini-Hochberg "
                    "FDR-controlled alternative flag set.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_filing_diff_population_summary},
    {"name": "get_backtest_results",
     "description": "Feature 17 (C14) governance — backtest of the X-Ray, deposit-flight and "
                    "filing-diff signals against subsequent deposit/capital/credit "
                    "deterioration and failure/exit, pooled across every landed quarter transition.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_backtest_results},
    {"name": "run_stress_test",
     "description": "Feature 16 — stress capital ratios under loan-loss / deposit-outflow / rate shocks.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "loan_loss_pct": {"type": "number"},
         "deposit_outflow_pct": {"type": "number"}, "rate_shock_bps": {"type": "number"}},
         "required": ["cert"]},
     "handler": run_stress},
    {"name": "run_stress_test_projection",
     "description": "Feature 16 (C4) — multi-period (4-8 quarter) stress projection: phases the "
                    "shock in and lets disclosed PPNR earn back part of each period's loss.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "loan_loss_pct": {"type": "number"},
         "deposit_outflow_pct": {"type": "number"}, "rate_shock_bps": {"type": "number"},
         "horizon_quarters": {"type": "integer"}, "phase_in": {"type": "boolean"},
         "apply_ppnr_offset": {"type": "boolean"}},
         "required": ["cert"]},
     "handler": run_stress_projection},
    {"name": "get_liquidity_survival",
     "description": "Feature 16 (C4) — quarters of on-balance-sheet liquidity survivable under a "
                    "SUSTAINED quarterly deposit-outflow rate.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "quarterly_outflow_pct": {"type": "number"}}, "required": ["cert"]},
     "handler": get_liquidity_survival},
    {"name": "run_segmented_stress_test",
     "description": "Feature 16 (C6) — per-category loan-loss rates (construction, C&I, "
                    "consumer, etc.) instead of one blended percentage, decomposed by category. "
                    "Defaults to this bank's own disclosed charge-off rate per category, scaled up.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT,
         "category_loan_loss_pct": {"type": "object"},
         "severity_multiplier": {"type": "number"},
         "deposit_outflow_pct": {"type": "number"}, "rate_shock_bps": {"type": "number"}},
         "required": ["cert"]},
     "handler": run_segmented_stress_test},
    {"name": "get_irrbb",
     "description": "Feature 16 (C5) — EVE and 12-month NII sensitivity under a parallel rate "
                    "shift and a non-parallel steepener (interest-rate risk in the banking book).",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "parallel_shock_bps": {"type": "number"}}, "required": ["cert"]},
     "handler": get_irrbb},
    {"name": "run_correlated_stress",
     "description": "Feature 16 (C4) — a single joint, correlated scenario: a rate shock triggers "
                    "proportional deposit-outflow and loan-loss legs instead of three independent sliders.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "rate_shock_bps": {"type": "number"},
         "severity": {"type": "string", "enum": ["mild", "moderate", "severe"]}},
         "required": ["cert"]},
     "handler": run_correlated_stress},
    {"name": "get_risk_score",
     "description": "Feature 13 — deposit-flight risk score (model trained on real 2023 + 2008 failures) with drivers.",
     "inputSchema": {"type": "object", "properties": {"cert": _CERT}, "required": ["cert"]},
     "handler": get_risk_score},
    {"name": "get_risk_leaderboard",
     "description": "Feature 13, population-wide — deposit-flight risk score for every landed "
                    "FDIC bank, ranked descending. Optional state/cluster_label filter "
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
    {"name": "get_bulk_bank_trends",
     "description": "E10 — the SAME per-quarter trajectory get_bank_trends returns, for a "
                    f"whole peer set at once (up to {MAX_BULK_TRENDS_CERTS} certs), so "
                    "/trends' small-multiples view can render every bank's line without "
                    "N sequential requests.",
     "inputSchema": {"type": "object", "properties": {
         "certs": {"type": "array", "items": {"type": "integer"}}}, "required": ["certs"]},
     "handler": get_bulk_bank_trends},
    {"name": "get_population_trend_sparklines",
     "description": "E12 — batched trailing-quarter series (last "
                    f"{SPARKLINE_QUARTERS_BACK} quarters, up to {MAX_SPARKLINE_CERTS} certs) "
                    "for a sparkline column next to an already-rendered population table "
                    "(screener/earnings/credit/funding), one request for the whole table.",
     "inputSchema": {"type": "object", "properties": {
         "certs": {"type": "array", "items": {"type": "integer"}},
         "metrics": {"type": "array", "items": {"type": "string"}}},
         "required": ["certs", "metrics"]},
     "handler": get_population_trend_sparklines},
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
         "top_n": {"type": "integer"}, "sort_by": {"type": "string"},
         "metrics": {"type": "array", "items": {"type": "string"},
                     "description": "Subset of peers.RANK_METRICS to include as columns; "
                                    "defaults to the curated HEATMAP_METRICS set."}}},
     "handler": get_percentile_heatmap},
    {"name": "get_asset_treemap",
     "description": "Every bank sized by assets, grouped by behavioral cluster, "
                    "state or country (the only grouping that produces a genuine "
                    "pan-European view), with X-Ray risk severity for client-side "
                    "coloring.",
     "inputSchema": {"type": "object", "properties": {
         "group_by": {"type": "string", "enum": ["peer_cluster_label", "state", "country"]}}},
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
    {"name": "get_market_coverage",
     "description": "How many crosswalk-matched tickers are actually landed vs "
                    "eligible right now, and how stale the oldest landed bar is.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_market_coverage},
    {"name": "get_market_overview",
     "description": "E2 — cross-bank market view for a peer set or the top-N largest "
                    "banks: rebased relative-performance series, a returns/volatility "
                    "scatter, a pairwise return-correlation matrix, and a per-bank "
                    "metrics table (beta vs an equal-weighted peer basket, realized "
                    "volatility vs peer median, max drawdown, tangible book value), "
                    "computed from real landed Tiingo candles + Gold fundamentals. "
                    "Discloses how many of the requested banks actually have landed "
                    "price data rather than silently showing only those that do. "
                    "G3: per-bank price series are omitted (see performance_series_note) "
                    "once more than one bank has landed price data — Tiingo is licensed "
                    "redistributable=false; the aggregate analytics are unaffected.",
     "inputSchema": {"type": "object", "properties": {
         "certs": {"type": "array", "items": {"type": "integer"}},
         "top_n": {"type": "integer"}, "window_days": {"type": "integer"}}},
     "handler": get_market_overview},
    {"name": "get_data_freshness",
     "description": "B10 — per-source landing vintage (fetch timestamp, record count, "
                    "expected next publication) for every registered data source.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_data_freshness},
    {"name": "get_metric_lineage",
     "description": "G9 — provenance for one bank's metric: the Gold function/formula that "
                    "computed it, the Silver/FDIC source field(s) and raw values, and the "
                    "originating Bronze partition path, checksum and fetch timestamp. Covers "
                    "the FDIC capital/financial fields feeding get_risk_score, not the full "
                    "Gold schema.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "metric": {"type": "string"}, "quarter": {"type": "string"}},
         "required": ["cert", "metric"]},
     "handler": get_metric_lineage},
    {"name": "get_macro_data",
     "description": "B5 — landed FRED macro series (Treasury yield curve, Fed funds, "
                    "unemployment, CRE price index).",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": get_macro_data},
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
    {"name": "run_stress_surface",
     "description": "Feature 16 (E3) — stressed CET1 across a (deposit_outflow x "
                    "rate_shock) grid for one bank, loan_loss_pct held fixed. Powers "
                    "the Stress Lab's CET1 surface heatmap, contoured against the "
                    "real regulatory CET1 minimum.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "loan_loss_pct": {"type": "number"},
         "deposit_outflow_max_pct": {"type": "number"}, "rate_shock_max_bps": {"type": "number"},
         "steps": {"type": "integer"}}, "required": ["cert"]},
     "handler": run_stress_surface},
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
