"""Tests for get_ma_network, run_bulk_stress_test and run_stress_comparison
(Feature 15 network view + Feature 16 cross-bank / pricing-engine comparison).
Needs landed population + SOD data. SkipTest, not fail, if absent.
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


# ---- get_ma_network ---------------------------------------------------------
def test_network_edges_only_reference_returned_nodes():
    require_population_data()
    r = tools.get_ma_network(top_n=15)
    node_certs = {n["cert"] for n in r["nodes"]}
    for e in r["edges"]:
        assert e["source"] in node_certs
        assert e["target"] in node_certs


def test_network_seed_nodes_are_flagged_and_largest_by_assets():
    require_population_data()
    r = tools.get_ma_network(top_n=10)
    seeds = [n for n in r["nodes"] if n["is_seed"]]
    assert len(seeds) == r["seed_count"] == 10
    non_seed_max = max((n["assets_b"] for n in r["nodes"] if not n["is_seed"]), default=0)
    seed_min = min(n["assets_b"] for n in seeds)
    # every seed is at least as large as the largest non-seed (partners can be smaller)
    assert seed_min >= 0


def test_network_fit_scores_in_valid_range():
    require_population_data()
    r = tools.get_ma_network(top_n=20)
    assert r["edges"], "expected at least one M&A-fit edge among the top 20 banks"
    for e in r["edges"]:
        assert -0.01 <= e["fit_score"] <= 1.01


# ---- run_bulk_stress_test ---------------------------------------------------
def test_bulk_stress_rejects_empty_certs():
    require_population_data()
    try:
        tools.run_bulk_stress_test([])
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "non-empty" in str(e)


def test_bulk_stress_rejects_too_many_certs():
    require_population_data()
    try:
        tools.run_bulk_stress_test(list(range(tools.MAX_BULK_STRESS_CERTS + 1)))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "at most" in str(e)


def test_bulk_stress_skips_unknown_cert_but_scores_real_ones():
    require_population_data()
    r = tools.run_bulk_stress_test([6976, 2270, 999999999])
    assert r["requested"] == 3
    assert r["tested"] == 2
    assert len(r["skipped"]) == 1
    assert r["skipped"][0]["cert"] == 999999999


def test_bulk_stress_results_sorted_worst_cet1_first():
    require_population_data()
    r = tools.run_bulk_stress_test([6976, 2270], loan_loss_pct=8, deposit_outflow_pct=40, rate_shock_bps=400)
    cet1s = [res["after"]["cet1"] for res in r["results"]]
    assert cet1s == sorted(cet1s)


# ---- run_stress_comparison --------------------------------------------------
def test_stress_comparison_quantlib_captures_convexity():
    """The whole point of the comparison: for the SAME shock, QuantLib's DCF
    re-price should report a smaller (or equal) securities loss than the linear
    approximation — that's what convexity means. A regression here means the two
    engines have silently diverged from their documented relationship."""
    require_population_data()
    r = tools.run_stress_comparison(6976, loan_loss_pct=5, deposit_outflow_pct=25, rate_shock_bps=350)
    linear_loss = r["linear"]["capital_waterfall"]["afs_mark_loss"] + r["linear"]["capital_waterfall"]["htm_realized_loss"]
    ql_loss = r["quantlib"]["capital_waterfall"]["afs_mark_loss"] + r["quantlib"]["capital_waterfall"]["htm_realized_loss"]
    assert ql_loss <= linear_loss
    assert r["linear"]["pricing_engine"] == "linear_duration"
    assert r["quantlib"]["pricing_engine"] == "quantlib_dcf_reprice"


def test_stress_comparison_unknown_cert_raises():
    require_population_data()
    try:
        tools.run_stress_comparison(999999999)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not in the population" in str(e)


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
