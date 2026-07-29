"""Data access for the MCP tools — loads the landed Bronze, builds the Gold
feature layer + peer percentiles + behavioral clusters once, and caches it.

The MCP server is thin: it reads the SAME Gold/feature logic the CLI and (later)
the UI use. No business logic lives here that isn't already in banklens_transforms.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from banklens_transforms import clustering
from banklens_transforms.footprint import build_footprints
from banklens_transforms.gold import gold_features
from banklens_transforms.market import to_price_bar
from banklens_transforms.peers import add_percentile_ranks
from banklens_transforms.silver import to_bank_financials

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "data"
_POP = DATA / "bronze" / "source=fdic" / "population" / "repdte=20260331" / "records.json"
_CROSSWALK = DATA / "silver" / "crosswalk.json"
_SOD = DATA / "bronze" / "source=fdic" / "sod" / "year=2025" / "records.json"

_CLUSTER_METRICS = ["concentration_ratio_cre", "concentration_ratio_c_and_i",
                    "concentration_ratio_residential_mortgage", "uninsured_deposit_pct",
                    "core_deposit_pct"]
_cache: dict = {}


def population() -> dict:
    """Return {gold, by_cert, silver_by_cert, cluster_members, cluster_labels}.
    Real branch footprints (for Feature 15's geo-overlap) are a separate cached
    accessor — see footprints() below."""
    if "pop" in _cache:
        return _cache["pop"]

    raw = json.loads(_POP.read_text(encoding="utf-8-sig"))
    silver = [to_bank_financials(r) for r in raw]
    gold = [gold_features(s) for s in silver]
    add_percentile_ranks(gold)

    silver_by_cert = {}
    for s, g in zip(silver, gold):
        g["state"] = s.get("state")
        cert = s.get("cert_number")
        if cert is not None:
            silver_by_cert[cert] = s

    # behavioral clusters (k=7, deterministic seed)
    kept, X = clustering.build_matrix(gold)
    labels, _, _ = clustering.kmeans(X, 7)
    members = defaultdict(list)
    for g, lab in zip(kept, labels):
        g["peer_cluster_id"] = lab
        members[lab].append(g)
    cluster_labels = {}
    for lab, ms in members.items():
        means = {m: _avg(ms, m) for m in _CLUSTER_METRICS}
        cluster_labels[lab] = clustering.label_cluster(means)
    for g in kept:
        g["peer_cluster_label"] = cluster_labels[g["peer_cluster_id"]]

    _cache["pop"] = {
        "gold": gold,
        "by_cert": {g["cert_number"]: g for g in gold},
        "silver_by_cert": silver_by_cert,
        "cluster_members": {lab: [g["cert_number"] for g in ms] for lab, ms in members.items()},
        "cluster_labels": cluster_labels,
    }
    return _cache["pop"]


def footprints() -> dict[int, dict]:
    """Real branch-level footprints keyed by CERT (bank-level, not holding-company —
    SOD branch data is per FDIC-insured bank, so no crosswalk needed here). Empty
    dict if SOD hasn't been landed (see scripts/land_sod.ps1)."""
    if "footprints" in _cache:
        return _cache["footprints"]
    if not _SOD.exists():
        _cache["footprints"] = {}
    else:
        raw = json.loads(_SOD.read_text(encoding="utf-8-sig"))
        _cache["footprints"] = build_footprints(raw)
    return _cache["footprints"]


def bank_quarters(cert: int) -> list[dict] | None:
    """Per-bank multi-quarter Silver rows (newest-first), or None if not landed."""
    p = DATA / "bronze" / "source=fdic" / f"cert={cert}" / "records.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8-sig"))
    return [to_bank_financials(r) for r in raw]


def landed_bank_certs() -> list[int]:
    d = DATA / "bronze" / "source=fdic"
    return sorted(int(p.name.split("=")[1]) for p in d.glob("cert=*") if p.is_dir())


def ticker_for_cert(cert: int) -> str | None:
    """The real, crosswalk-matched ticker for a bank's holding company (or its own
    ticker, for the banks with no separate holding company — see crosswalk.md),
    restricted to exact/high_confidence matches only (never a low-confidence guess)."""
    if "crosswalk_by_rssd" not in _cache:
        if not _CROSSWALK.exists():
            _cache["crosswalk_by_rssd"] = {}
        else:
            rows = json.loads(_CROSSWALK.read_text(encoding="utf-8"))
            _cache["crosswalk_by_rssd"] = {
                r["rssd"]: r for r in rows if r["match_type"] in ("exact", "high_confidence")
            }
    silver = population()["silver_by_cert"].get(cert)
    if not silver:
        return None
    rssd = silver.get("holding_company_rssd") or silver.get("rssd_id")
    row = _cache["crosswalk_by_rssd"].get(rssd)
    return row["ticker"] if row else None


def price_bars(ticker: str) -> list[dict] | None:
    """Landed EOD price bars for a ticker (ascending by date), or None if not landed
    (see scripts/land_market_data.ps1 — needs the user's own free Tiingo key)."""
    cache_key = f"bars:{ticker}"
    if cache_key in _cache:
        return _cache[cache_key]
    p = DATA / "bronze" / "source=tiingo" / "daily" / f"ticker={ticker}" / "records.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    bars = sorted((to_price_bar(r) for r in raw), key=lambda b: b["date"])
    _cache[cache_key] = bars
    return bars


def _avg(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0
