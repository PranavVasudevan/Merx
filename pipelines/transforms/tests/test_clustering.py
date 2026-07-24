"""K-Means / silhouette tests on synthetic, clearly-separable data. No network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.clustering import (  # noqa: E402
    build_matrix, choose_k, kmeans, label_cluster, silhouette,
)


def _blob(cx, cy, n, spread=0.2, seed=0):
    import random
    rng = random.Random(seed)
    return [[cx + rng.uniform(-spread, spread), cy + rng.uniform(-spread, spread)] for _ in range(n)]


def test_kmeans_recovers_two_blobs():
    X = _blob(0, 0, 40, seed=1) + _blob(10, 10, 40, seed=2)
    labels, centroids, inertia = kmeans(X, 2, seed=1)
    # the first 40 and last 40 should each be internally consistent
    assert len(set(labels[:40])) == 1
    assert len(set(labels[40:])) == 1
    assert labels[0] != labels[-1]


def test_silhouette_high_for_separated():
    X = _blob(0, 0, 30, seed=1) + _blob(20, 20, 30, seed=2)
    labels, _, _ = kmeans(X, 2, seed=1)
    assert silhouette(X, labels) > 0.7           # well-separated -> high silhouette


def test_choose_k_prefers_true_k():
    X = _blob(0, 0, 30, seed=1) + _blob(15, 0, 30, seed=2) + _blob(0, 15, 30, seed=3)
    k, labels, _, scores = choose_k(X, k_range=range(2, 6))
    assert k == 3


def test_build_matrix_imputes_and_standardizes():
    gold = [
        {"concentration_ratio_cre": 70, "uninsured_deposit_pct": None, "core_deposit_pct": 90,
         "concentration_ratio_c_and_i": 5, "concentration_ratio_residential_mortgage": 5,
         "concentration_ratio_consumer": 1, "loan_to_deposit_pct": 80},
        {"concentration_ratio_cre": 10, "uninsured_deposit_pct": 40, "core_deposit_pct": 60,
         "concentration_ratio_c_and_i": 30, "concentration_ratio_residential_mortgage": 20,
         "concentration_ratio_consumer": 10, "loan_to_deposit_pct": 95},
    ]
    kept, X = build_matrix(gold)
    assert len(kept) == 2 and len(X) == 2 and len(X[0]) == 7   # None imputed, not dropped


def test_label_cluster():
    assert "CRE-concentrated" in label_cluster(
        {"concentration_ratio_cre": 70, "uninsured_deposit_pct": 50})


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
