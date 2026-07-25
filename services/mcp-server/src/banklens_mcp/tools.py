"""MCP tool contracts for BankLens — thin wrappers over the feature logic.

Each tool: read Gold / feature functions, return a JSON-serialisable result. The
same functions power the CLI. See docs/api/mcp-tools.md.
"""

from __future__ import annotations

from banklens_transforms.filing_diff import build_quarters, diff
from banklens_transforms.gold import gold_features
from banklens_transforms.ma_fit import rank_partners
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
    rows = data.population()["gold"]
    def keep(g):
        if query and query.lower() not in (g.get("name") or "").lower():
            return False
        if state and (g.get("state") or "").upper() != state.upper():
            return False
        a = (g.get("total_assets") or 0) / 1e9
        if min_assets_b is not None and a < min_assets_b:
            return False
        if max_assets_b is not None and a > max_assets_b:
            return False
        return True
    hits = sorted((g for g in rows if keep(g)),
                  key=lambda g: g.get("total_assets") or 0, reverse=True)[:limit]
    return {"count": len(hits), "banks": [{
        "cert": g["cert_number"], "name": g["name"], "state": g.get("state"),
        "assets_b": round((g.get("total_assets") or 0) / 1e9, 1),
        "cluster": g.get("peer_cluster_label"),
    } for g in hits]}


def get_bank_profile(cert: int) -> dict:
    g = _need_bank(cert)
    return {
        "cert": cert, "name": g["name"], "state": g.get("state"), "quarter": g["quarter"],
        "assets_b": round((g.get("total_assets") or 0) / 1e9, 1),
        "uninsured_deposit_pct": g.get("uninsured_deposit_pct"),
        "loan_to_deposit_pct": g.get("loan_to_deposit_pct"),
        "cre_concentration_pct": g.get("concentration_ratio_cre"),
        "cet1_ratio": g.get("cet1_ratio"), "leverage_ratio": g.get("leverage_ratio"),
        "peer_cluster": g.get("peer_cluster_label"),
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
    ranked = rank_partners(target, pop["gold"], top_n=top_n, states=pop["states"])
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
]

TOOL_BY_NAME = {t["name"]: t for t in TOOLS}
