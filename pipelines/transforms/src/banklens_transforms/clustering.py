"""Feature 14 — Peer Group Redefiner (behavioral clustering).

Reclusters banks by how their balance sheet actually *behaves* — loan mix and
funding profile — instead of lazy asset-size buckets, and flags banks whose
conventional label doesn't match their behavioral cluster. Output: a
``peer_cluster_id`` per bank (a Gold field, per the plan) plus a human label.

Transparent, dependency-free K-Means (k-means++ init, standardized features) with
silhouette-based k selection. At this scale (~1k banks, ~7 features) pure Python is
instant and fully auditable; the ML-platform phase swaps in scikit-learn + MLflow
for scale, robustness, and experiment tracking.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path

# Behavioral features (loan concentration + funding mix). Deliberately NOT asset
# size — the whole point is to cluster by behavior, then compare to size labels.
FEATURES = [
    "concentration_ratio_cre",
    "concentration_ratio_c_and_i",
    "concentration_ratio_residential_mortgage",
    "concentration_ratio_consumer",
    "uninsured_deposit_pct",
    "core_deposit_pct",
    "loan_to_deposit_pct",
]


# ---- feature matrix ------------------------------------------------------
def build_raw_matrix(gold_rows: list[dict], features: list[str] = FEATURES):
    """Return (kept_rows, raw) — mean-imputed but NOT standardized. Split out of
    `build_matrix` (C3) so fixed-centroid assignment can standardize a quarter's
    raw values against a PERSISTED reference mu/sd instead of that quarter's
    own (which is exactly the behavior that makes "fixed" centroids not
    actually fixed)."""
    means = {}
    for f in features:
        vals = [g[f] for g in gold_rows if g.get(f) is not None]
        means[f] = sum(vals) / len(vals) if vals else 0.0

    kept, raw = [], []
    for g in gold_rows:
        vec = [g[f] if g.get(f) is not None else means[f] for f in features]
        kept.append(g)
        raw.append(vec)
    return kept, raw


def standardize_with(raw: list[list[float]], mu: list[float], sd: list[float]) -> list[list[float]]:
    """Standardize a raw feature matrix against an EXTERNAL mu/sd (e.g. a
    persisted reference-quarter fit), not its own column statistics."""
    return [[(row[j] - mu[j]) / sd[j] for j in range(len(mu))] for row in raw]


def build_matrix(gold_rows: list[dict], features: list[str] = FEATURES):
    """Return (kept_rows, X) where X is standardized against THIS OWN matrix's
    column stats (per-quarter refit — the pre-C3 behavior); see
    `build_raw_matrix`/`standardize_with` for the fixed-centroid path."""
    kept, raw = build_raw_matrix(gold_rows, features)
    n = len(raw)
    cols = list(zip(*raw, strict=True)) if raw else []
    mu = [sum(c) / n for c in cols]
    sd = [math.sqrt(sum((v - mu[j]) ** 2 for v in c) / n) or 1.0 for j, c in enumerate(cols)]
    X = standardize_with(raw, mu, sd)
    return kept, X


def _sqdist(a, b) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(len(a)))


def _kpp_init(X, k, rng):
    centroids = [X[rng.randrange(len(X))]]
    while len(centroids) < k:
        d2 = [min(_sqdist(x, c) for c in centroids) for x in X]
        total = sum(d2) or 1.0
        r = rng.random() * total
        acc = 0.0
        pick = len(X) - 1
        for i, dd in enumerate(d2):
            acc += dd
            if acc >= r:
                pick = i
                break
        centroids.append(X[pick])
    return [list(c) for c in centroids]


def kmeans(X, k, *, seed=42, restarts=6, max_iter=100):
    """Return (labels, centroids, inertia) for the best of several restarts."""
    best = None
    for r in range(restarts):
        rng = random.Random(seed + r)
        centroids = _kpp_init(X, k, rng)
        labels = [0] * len(X)
        for _ in range(max_iter):
            changed = False
            for i, x in enumerate(X):
                lab = min(range(k), key=lambda c: _sqdist(x, centroids[c]))
                if lab != labels[i]:
                    labels[i] = lab
                    changed = True
            for c in range(k):
                members = [X[i] for i in range(len(X)) if labels[i] == c]
                if members:
                    centroids[c] = [sum(col) / len(members) for col in zip(*members, strict=True)]
            if not changed:
                break
        inertia = sum(_sqdist(X[i], centroids[labels[i]]) for i in range(len(X)))
        if best is None or inertia < best[2]:
            best = (labels[:], [c[:] for c in centroids], inertia)
    return best


def silhouette(X, labels, *, sample=350, seed=7) -> float:
    """Mean silhouette on a random subsample (full n^2 is wasteful at scale)."""
    idx = list(range(len(X)))
    if len(idx) > sample:
        idx = random.Random(seed).sample(idx, sample)
    by_label: dict[int, list[int]] = {}
    for i in range(len(X)):
        by_label.setdefault(labels[i], []).append(i)
    if len(by_label) < 2:
        return -1.0

    total, count = 0.0, 0
    for i in idx:
        same = [j for j in by_label[labels[i]] if j != i]
        if not same:
            continue
        a = sum(math.sqrt(_sqdist(X[i], X[j])) for j in same) / len(same)
        b = min(
            sum(math.sqrt(_sqdist(X[i], X[j])) for j in members) / len(members)
            for lab, members in by_label.items() if lab != labels[i]
        )
        total += (b - a) / max(a, b) if max(a, b) > 0 else 0.0
        count += 1
    return total / count if count else -1.0


def choose_k(X, k_range=range(2, 8), **kw):
    """Pick k maximizing silhouette. Returns (best_k, labels, centroids, scores)."""
    scores = {}
    best = None
    for k in k_range:
        labels, centroids, _ = kmeans(X, k, **kw)
        s = silhouette(X, labels)
        scores[k] = round(s, 4)
        if best is None or s > best[0]:
            best = (s, k, labels, centroids)
    return best[1], best[2], best[3], scores


def silhouette_by_k(X, k_range=range(2, 8), **kw) -> dict:
    """Diagnostic: silhouette and largest-cluster share for each k (with cached labels).

    The largest-cluster share exposes *degenerate* solutions — a high silhouette that
    is really just one tight outlier group plus a giant catch-all blob (typical at k=2).
    """
    out = {}
    for k in k_range:
        labels, _, _ = kmeans(X, k, **kw)
        share = max(Counter(labels).values()) / len(X)
        out[k] = {"silhouette": round(silhouette(X, labels), 4),
                  "max_share": round(share, 3), "labels": labels}
    return out


def select_k(diag: dict, *, max_share: float = 0.55, fallback: int = 6) -> int:
    """Best silhouette among non-degenerate k (largest cluster <= max_share); else fallback."""
    ok = [k for k, v in diag.items() if v["max_share"] <= max_share]
    if not ok:
        return fallback
    return max(ok, key=lambda k: diag[k]["silhouette"])


# ---- interpretation ------------------------------------------------------
_BASES = ("CRE-concentrated", "C&I / commercial", "Residential-mortgage", "Diversified")
_FUNDING = ("high-uninsured", "core-funded", "mixed-funded")

# Every label `label_cluster` can emit, in a fixed order. k-means assigns cluster
# INTEGERS arbitrarily, so the same behavioral group gets a different integer in every
# quarter — which would render as fake "cluster migration" on any multi-quarter view.
# Deriving the id from the label instead makes cluster identity stable over time and
# semantically meaningful, at the cost that two k-means clusters landing on the same
# label in one quarter collapse to one id (which is arguably the right answer: they
# are behaviorally the same group).
CANONICAL_CLUSTER_LABELS = [f"{b}, {f}" for b in _BASES for f in _FUNDING]
STABLE_CLUSTER_ID = {label: i for i, label in enumerate(CANONICAL_CLUSTER_LABELS)}


def stable_cluster_id(label: str) -> int:
    """Time-stable id for a behavioral cluster label (see CANONICAL_CLUSTER_LABELS)."""
    return STABLE_CLUSTER_ID[label]


FIXED_CENTROIDS_PATH = Path(__file__).resolve().parents[4] / "ml" / "clustering" / "fixed_centroids.json"


def assign_fixed(X: list[list[float]], centroids: list[list[float]]) -> list[int]:
    """C3 — nearest-centroid assignment against ALREADY-FITTED, persisted
    centroids: no iteration, no refit. A bank near a decision boundary with a
    stable balance sheet should get the SAME cluster label quarter to quarter;
    `population()`'s per-quarter `kmeans()` refit can flip it purely because
    that quarter's centroids landed in slightly different positions, even with
    stable-cluster-id label matching (label_cluster/stable_cluster_id) papering
    over the INTEGER but not the actual reassignment."""
    return [min(range(len(centroids)), key=lambda c: _sqdist(x, centroids[c])) for x in X]


def fit_fixed_centroids(gold_rows: list[dict], *, k: int = 7, features: list[str] = FEATURES,
                        seed: int = 42) -> dict:
    """Fit centroids ONCE on a reference quarter's population, in the SAME
    standardized space `population()` normally refits per quarter — the
    payload `save_fixed_centroids` persists and every other quarter's
    `assign_fixed` call reuses unchanged."""
    kept, X = build_matrix(gold_rows, features)
    _, raw = build_raw_matrix(gold_rows, features)
    n = len(raw)
    cols = list(zip(*raw, strict=True)) if raw else []
    mu = [sum(c) / n for c in cols]
    sd = [math.sqrt(sum((v - mu[j]) ** 2 for v in c) / n) or 1.0 for j, c in enumerate(cols)]
    labels, centroids, _ = kmeans(X, k, seed=seed)
    raw_members: dict[int, list[dict]] = {}
    for g, lab in zip(kept, labels, strict=True):
        raw_members.setdefault(lab, []).append(g)
    # Reorder centroids by STABLE id (not k-means' arbitrary integer), same
    # scheme population() already uses, so a centroid's position in the
    # persisted list is meaningful on its own.
    ordered: dict[int, list[float]] = {}
    stable_labels: dict[int, str] = {}
    for lab, members in raw_members.items():
        means = {f: sum((m.get(f) or 0) for m in members) / len(members) for f in features}
        text = label_cluster(means)
        sid = stable_cluster_id(text)
        ordered[sid] = centroids[lab]
        stable_labels[sid] = text
    sids = sorted(ordered)
    return {
        "features": features, "mu": mu, "sd": sd, "k": k,
        "stable_ids": sids,
        "centroids": [ordered[s] for s in sids],
        "cluster_labels": {s: stable_labels[s] for s in sids},
    }


def save_fixed_centroids(fit: dict, *, reference_quarter: str) -> None:
    FIXED_CENTROIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**fit, "reference_quarter": reference_quarter}
    FIXED_CENTROIDS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_fixed_centroids() -> dict | None:
    if not FIXED_CENTROIDS_PATH.exists():
        return None
    return json.loads(FIXED_CENTROIDS_PATH.read_text(encoding="utf-8"))


def label_cluster(centroid_means: dict) -> str:
    """A short human label from a cluster's average behavior."""
    cre = centroid_means.get("concentration_ratio_cre", 0)
    ci = centroid_means.get("concentration_ratio_c_and_i", 0)
    res = centroid_means.get("concentration_ratio_residential_mortgage", 0)
    unins = centroid_means.get("uninsured_deposit_pct", 0)
    core = centroid_means.get("core_deposit_pct", 0)

    if cre >= 55:
        base = "CRE-concentrated"
    elif ci >= 25:
        base = "C&I / commercial"
    elif res >= 30:
        base = "Residential-mortgage"
    else:
        base = "Diversified"
    if unins >= 45:
        funding = "high-uninsured"
    elif core >= 80:
        funding = "core-funded"
    else:
        funding = "mixed-funded"
    return f"{base}, {funding}"
