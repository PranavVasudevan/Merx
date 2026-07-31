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
    return evaluate_xray(_need_bank(cert))     # gold row carries percentile ranks -> peer context


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
    rows = data.bank_quarters(cert)
    if not rows:
        raise ValueError(f"Multi-quarter data not landed for CERT {cert}. "
                         f"Available: {data.landed_bank_certs()}.")
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
    {"name": "diff_filings",
     "description": "Feature 12 — flag line-item moves that are unusual vs the bank's own history.",
     "inputSchema": {"type": "object", "properties": {
         "cert": _CERT, "quarter_a": {"type": "string"}, "quarter_b": {"type": "string"}},
         "required": ["cert"]},
     "handler": diff_filings},
    {"name": "compare_banks",
     "description": "Side-by-side comparison of banks across chosen metrics.",
     "inputSchema": {"type": "object", "properties": {
         "certs": {"type": "array", "items": {"type": "integer"}},
         "metrics": {"type": "array", "items": {"type": "string"}}}, "required": ["certs"]},
     "handler": compare_banks},
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
