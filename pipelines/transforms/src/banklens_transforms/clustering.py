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

import math
import random
from collections import Counter

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
def build_matrix(gold_rows: list[dict], features: list[str] = FEATURES):
    """Return (kept_rows, X) where X is standardized; missing values imputed to mean."""
    # column means over present values
    means = {}
    for f in features:
        vals = [g[f] for g in gold_rows if g.get(f) is not None]
        means[f] = sum(vals) / len(vals) if vals else 0.0

    kept, raw = [], []
    for g in gold_rows:
        vec = [g[f] if g.get(f) is not None else means[f] for f in features]
        kept.append(g)
        raw.append(vec)

    # standardize (z-score) per column
    n = len(raw)
    cols = list(zip(*raw)) if raw else []
    mu = [sum(c) / n for c in cols]
    sd = [math.sqrt(sum((v - mu[j]) ** 2 for v in c) / n) or 1.0 for j, c in enumerate(cols)]
    X = [[(raw[i][j] - mu[j]) / sd[j] for j in range(len(features))] for i in range(n)]
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
                    centroids[c] = [sum(col) / len(members) for col in zip(*members)]
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
