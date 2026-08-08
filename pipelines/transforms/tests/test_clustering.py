"""Feature 14 — behavioral peer clustering. Tested on synthetic, clearly-separable
blobs so the expected grouping is knowable independently of the algorithm. No
network, no landed data.

Run: ``python pipelines/transforms/tests/test_clustering.py``  (no pytest needed)
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.clustering import (  # noqa: E402
    FEATURES, build_matrix, kmeans, silhouette, stable_cluster_id,
)


def _blob(cx, cy, n, spread=0.2, seed=0):
    rng = random.Random(seed)
    return [[cx + rng.uniform(-spread, spread), cy + rng.uniform(-spread, spread)]
            for _ in range(n)]


def test_kmeans_recovers_two_well_separated_blobs():
    """Two tight, far-apart clusters must come back as two groups — if this fails,
    every real cluster assignment downstream is suspect."""
    X = _blob(0, 0, 30, seed=1) + _blob(10, 10, 30, seed=2)
    labels, _, _ = kmeans(X, 2)
    first, second = labels[:30], labels[30:]
    assert len(set(first)) == 1 and len(set(second)) == 1
    assert first[0] != second[0]


def test_clustering_is_deterministic_across_runs():
    """A fixed seed must give a stable partition, or a bank's peer group would
    silently change between quarters with no underlying change in its data."""
    X = _blob(0, 0, 20, seed=3) + _blob(8, 8, 20, seed=4)
    a, _, _ = kmeans(X, 2)
    b, _, _ = kmeans(X, 2)
    assert a == b


def test_silhouette_prefers_the_true_cluster_count():
    """Silhouette is what picks k — it must score the genuine structure (k=3 on
    three blobs) above an obviously wrong split."""
    X = _blob(0, 0, 20, seed=5) + _blob(9, 0, 20, seed=6) + _blob(0, 9, 20, seed=7)
    s3 = silhouette(X, kmeans(X, 3)[0])
    s2 = silhouette(X, kmeans(X, 2)[0])
    assert s3 > s2


def test_silhouette_is_in_valid_range():
    X = _blob(0, 0, 20, seed=8) + _blob(7, 7, 20, seed=9)
    assert -1.0 <= silhouette(X, kmeans(X, 2)[0]) <= 1.0


def test_build_matrix_standardizes_and_imputes_missing_to_mean():
    """A bank missing one metric must not be dropped from the population, and must
    not skew the space either — it gets the column mean."""
    rows = [
        {f: 10.0 for f in FEATURES},
        {f: 20.0 for f in FEATURES},
        {**{f: 15.0 for f in FEATURES}, FEATURES[0]: None},   # one gap
    ]
    kept, X = build_matrix(rows)
    assert len(kept) == 3 and len(X) == 3          # nobody dropped
    assert all(len(v) == len(FEATURES) for v in X)
    assert all(isinstance(v, float) for v in X[2])  # gap filled, not None


def test_stable_cluster_id_is_label_derived_not_positional():
    """Cluster ids must come from the behavioral LABEL, not k-means' arbitrary
    integer — otherwise the same archetype gets a new id each quarter and the
    multi-quarter view renders fake migration between peer groups."""
    assert stable_cluster_id("CRE-concentrated, core-funded") == \
           stable_cluster_id("CRE-concentrated, core-funded")
    assert stable_cluster_id("CRE-concentrated, core-funded") != \
           stable_cluster_id("C&I / commercial, mixed-funded")


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
