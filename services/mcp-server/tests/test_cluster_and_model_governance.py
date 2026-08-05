"""Tests for get_cluster_diagnostics (Feature 14 governance) and get_model_card
(Feature 13 governance). Both need real landed data — SkipTest, not fail, if it
isn't present, same convention as the rest of this test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import tools  # noqa: E402


class SkipTest(Exception):
    pass


def require_population_data():
    from banklens_mcp import data
    if not data.available_quarters():
        raise SkipTest("no landed population quarters (run scripts/land_population.ps1)")


def require_trained_model():
    from banklens_transforms.deposit_flight import load_card
    require_population_data()
    if load_card() is None:
        raise SkipTest("deposit-flight model not trained (run deposit_flight_cli)")


# ---- get_cluster_diagnostics ----------------------------------------------
def test_cluster_diagnostics_covers_every_k_in_range():
    require_population_data()
    d = tools.get_cluster_diagnostics()
    assert {row["k"] for row in d["silhouette_by_k"]} == set(range(2, 8))
    assert d["served_k"] == 7


def test_cluster_diagnostics_silhouette_scores_are_valid_range():
    require_population_data()
    d = tools.get_cluster_diagnostics()
    for row in d["silhouette_by_k"]:
        assert -1.0 <= row["silhouette"] <= 1.0
        assert 0.0 < row["max_share"] <= 1.0


def test_cluster_diagnostics_centroids_match_served_clustering():
    require_population_data()
    d = tools.get_cluster_diagnostics()
    assert len(d["centroids"]) == 7
    assert sum(c["size"] for c in d["centroids"]) > 0
    # every centroid has every behavioral feature
    from banklens_transforms import clustering
    for c in d["centroids"]:
        assert set(c["centroid"]) == set(clustering.FEATURES)


def test_cluster_diagnostics_bucket_sizes_sum_to_classified_population():
    require_population_data()
    d = tools.get_cluster_diagnostics()
    total_bucketed = sum(b["size"] for b in d["size_bucket_summary"])
    assert total_bucketed > 0
    # every mismatch must reference a real bucket present in the summary
    buckets = {b["bucket"] for b in d["size_bucket_summary"]}
    for m in d["sample_mismatches"]:
        assert m["conventional_bucket"] in buckets
        assert m["behavioral_cluster"] != m["bucket_modal_cluster"]


# ---- get_model_card ---------------------------------------------------------
def test_model_card_missing_model_is_a_clear_error():
    """Hermetic: exercises the guard without needing a trained model at all."""
    from banklens_mcp import tools as _tools
    orig = _tools.load_card
    _tools.load_card = lambda: None
    try:
        tools.get_model_card()
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not trained" in str(e)
    finally:
        _tools.load_card = orig


def test_model_card_carries_the_real_backtest_and_exclusion():
    require_trained_model()
    c = tools.get_model_card()
    assert 0.5 < c["auc"] <= 1.0
    assert len(c["weights"]) == len(c["features"])
    loo_certs = {r["cert"] for r in c["leave_one_out"]}
    assert {24735, 57053, 59017, 29730} <= loo_certs   # SVB, Signature, First Republic, IndyMac
    for r in c["leave_one_out"]:
        assert 0.0 <= r["percentile"] <= 100.0
        assert 1 <= r["rank"] <= r["n"]
    assert any(e["cert"] == 32633 for e in c["excluded_candidates"])   # Washington Mutual


def test_model_card_driver_points_cover_every_feature_for_scored_banks():
    require_trained_model()
    c = tools.get_model_card()
    assert c["driver_points"]
    certs = {p["cert"] for p in c["driver_points"]}
    features_per_cert = {cert: {p["feature"] for p in c["driver_points"] if p["cert"] == cert}
                         for cert in list(certs)[:5]}
    for feats in features_per_cert.values():
        assert feats == set(c["features"])


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except SkipTest as e:
                skipped += 1; print(f"SKIP  {name}: {e}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
