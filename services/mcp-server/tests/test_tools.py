"""Direct tests of banklens_mcp.tools functions that aren't already covered via
test_mcp.py's JSON-RPC round trip — get_population_metrics and get_metric_distribution,
the two tools backing the earnings/credit/funding/capital/concentration/distribution
pages. All need landed Bronze; SkipTest (not fail) if it isn't present, same
convention as test_mcp.py / test_data.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import tools  # noqa: E402


class SkipTest(Exception):
    pass


def require_landed_data():
    from banklens_mcp import data
    if not data.available_quarters():
        raise SkipTest(f"no landed population under {data._POP_DIR} "
                       f"(run scripts/land_population.ps1)")


def test_unknown_metric_group_is_a_clear_error():
    require_landed_data()
    try:
        tools.get_population_metrics("not_a_real_group")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unknown metric group" in str(e)


def test_get_population_metrics_returns_identity_plus_group_metrics():
    require_landed_data()
    r = tools.get_population_metrics("earnings", limit=5)
    assert r["group"] == "earnings"
    assert r["count"] > 0
    assert len(r["banks"]) == 5
    row = r["banks"][0]
    for m in r["metrics"]:
        assert m in row


def test_get_population_metrics_sort_is_respected():
    require_landed_data()
    r = tools.get_population_metrics("credit", limit=20, sort_by="npl_ratio_pct",
                                     descending=True)
    vals = [b["npl_ratio_pct"] for b in r["banks"]]
    assert vals == sorted(vals, reverse=True)
    assert all(v is not None for v in vals)     # sorting drops nulls, doesn't crash on them


def test_sort_by_metric_outside_the_group_is_rejected():
    require_landed_data()
    try:
        tools.get_population_metrics("earnings", sort_by="npl_ratio_pct")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not in that group" in str(e)


def test_distribution_order_statistics_are_internally_consistent():
    require_landed_data()
    d = tools.get_metric_distribution("cet1_ratio", bins=10)
    assert d["min"] <= d["p10"] <= d["p25"] <= d["median"] <= d["p75"] <= d["p90"] <= d["max"]
    assert d["count"] > 0


def test_distribution_histogram_accounts_for_every_value():
    """Regression guard: equal-width binning on a heavy-tailed metric used to collapse
    to one bin (measured on texas_ratio_pct: 991 of 1,035 banks in a single bin) unless
    the tails are folded into the first/last bin rather than spread across dozens of
    empty ones. Whatever the binning strategy, the counts must always sum to n — no
    value may be silently dropped."""
    require_landed_data()
    d = tools.get_metric_distribution("texas_ratio_pct", bins=12)
    total = sum(h["count"] for h in d["histogram"])
    assert total == d["count"], f"histogram counts sum to {total}, expected {d['count']}"
    max_bin_share = max(h["count"] for h in d["histogram"]) / d["count"]
    assert max_bin_share < 0.8, (
        f"one bin holds {max_bin_share:.0%} of all values — binning is not useful")


def test_distribution_discloses_exclusions_even_when_the_metric_is_null():
    """Regression guard for a REAL bug: exclusion status used to be checked AFTER the
    null-value check, so an excluded bank whose deposit-sensitive metric came out None
    (division by ~zero deposits) vanished from the distribution with NO record in
    'exclusions' — the exact quietly-misleading outcome data_quality exists to
    prevent. Measured on loan_to_deposit_pct: fixing the order took disclosed
    exclusions from 1 to 8."""
    require_landed_data()
    d = tools.get_metric_distribution("loan_to_deposit_pct", bins=10)
    assert d["exclusions"]["excluded_count"] >= 1
    assert d["count"] + d["exclusions"]["excluded_count"] == d["exclusions"]["total_considered"]


def test_heatmap_cells_align_with_declared_metrics():
    require_landed_data()
    h = tools.get_percentile_heatmap(top_n=10)
    assert len(h["banks"]) == 10
    for b in h["banks"]:
        assert len(b["cells"]) == len(h["metrics"])
        # cells are percentiles (0-100) or None, never a raw ratio/dollar value
        assert all(c is None or 0 <= c <= 100 for c in b["cells"])


def test_heatmap_respects_sort_by():
    require_landed_data()
    h = tools.get_percentile_heatmap(top_n=5, sort_by="total_assets")
    from banklens_mcp import data
    by_cert = data.population()["by_cert"]
    assets = [by_cert[b["cert"]]["total_assets"] for b in h["banks"]]
    assert assets == sorted(assets, reverse=True)


def test_treemap_groups_cover_the_full_population_once_each():
    require_landed_data()
    from banklens_mcp import data
    t = tools.get_asset_treemap(group_by="peer_cluster_label")
    counted = sum(len(g["children"]) for g in t["groups"])
    with_assets = sum(1 for g in data.population()["gold"] if g.get("total_assets"))
    assert counted == with_assets, "every bank with assets must appear in exactly one group"


def test_treemap_rejects_unknown_group_by():
    require_landed_data()
    try:
        tools.get_asset_treemap(group_by="not_a_real_field")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_treemap_carries_real_xray_risk_not_a_placeholder():
    """Regression guard: an early draft left overall_risk hardcoded to None on every
    node. Every bank in a treemap group must carry a real X-Ray severity."""
    require_landed_data()
    t = tools.get_asset_treemap(group_by="state")
    sample = t["groups"][0]["children"]
    assert all(c["overall_risk"] in ("low", "elevated", "high") for c in sample)


def test_distribution_unknown_metric_is_a_clear_error():
    require_landed_data()
    try:
        tools.get_metric_distribution("not_a_real_metric")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "no values for metric" in str(e)


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
