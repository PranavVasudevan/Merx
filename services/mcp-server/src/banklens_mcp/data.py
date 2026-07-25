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
from banklens_transforms.gold import gold_features
from banklens_transforms.peers import add_percentile_ranks
from banklens_transforms.silver import to_bank_financials

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "data"
_POP = DATA / "bronze" / "source=fdic" / "population" / "repdte=20260331" / "records.json"

_CLUSTER_METRICS = ["concentration_ratio_cre", "concentration_ratio_c_and_i",
                    "concentration_ratio_residential_mortgage", "uninsured_deposit_pct",
                    "core_deposit_pct"]
_cache: dict = {}


def population() -> dict:
    """Return {gold, by_cert, silver_by_cert, states, cluster_members, cluster_labels}."""
    if "pop" in _cache:
        return _cache["pop"]

    raw = json.loads(_POP.read_text(encoding="utf-8-sig"))
    silver = [to_bank_financials(r) for r in raw]
    gold = [gold_features(s) for s in silver]
    add_percentile_ranks(gold)

    states, silver_by_cert = {}, {}
    for s, g in zip(silver, gold):
        g["state"] = s.get("state")
        cert = s.get("cert_number")
        if cert is not None:
            silver_by_cert[cert] = s
            if s.get("state"):
                states[cert] = {s["state"]}

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
        "states": states,
        "cluster_members": {lab: [g["cert_number"] for g in ms] for lab, ms in members.items()},
        "cluster_labels": cluster_labels,
    }
    return _cache["pop"]


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


def _avg(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0
