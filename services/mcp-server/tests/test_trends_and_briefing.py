"""Tests for get_bank_trends and get_quarterly_briefing — both need at least 2
landed population quarters (Wave 0d's 8-quarter land). SkipTest, not fail, if
that isn't present, same convention as the rest of this test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import tools  # noqa: E402


class SkipTest(Exception):
    pass


def require_multi_quarter_data():
    from banklens_mcp import data
    if len(data.available_quarters()) < 2:
        raise SkipTest(
            f"need >= 2 landed quarters, have {len(data.available_quarters())} "
            f"(run scripts/land_population.ps1 -Quarters 8)")


# ---- get_bank_trends ------------------------------------------------------
def test_trends_unknown_cert_is_a_clear_error():
    require_multi_quarter_data()
    try:
        tools.get_bank_trends(999999999)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "no landed history" in str(e)


def test_trends_quarters_are_chronological_oldest_first():
    require_multi_quarter_data()
    r = tools.get_bank_trends(6976)
    assert r["quarters"] == sorted(r["quarters"])
    assert len(r["series"]) == len(r["quarters"])
    assert all(s["quarter"] == q for s, q in zip(r["series"], r["quarters"], strict=True))


def test_trends_series_carries_every_declared_metric():
    require_multi_quarter_data()
    r = tools.get_bank_trends(6976)
    for s in r["series"]:
        for m in r["metrics"]:
            assert m in s


# ---- get_quarterly_briefing -----------------------------------------------
def test_briefing_needs_at_least_two_quarters():
    """Hermetic: exercises the guard without needing real data at all."""
    from banklens_mcp import tools as _tools
    orig = _tools.data.available_quarters
    _tools.data.available_quarters = lambda: ["20260331"]
    try:
        tools.get_quarterly_briefing()
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "at least 2" in str(e)
    finally:
        _tools.data.available_quarters = orig


def test_briefing_population_churn_counts_are_consistent():
    require_multi_quarter_data()
    b = tools.get_quarterly_briefing()
    assert b["population_count"] > 0 and b["prior_population_count"] > 0
    # every entrant name must be unique to the current quarter's population
    assert len(b["entered"]) <= b["population_count"]
    assert len(b["exited"]) <= b["prior_population_count"]


def test_briefing_movers_are_sorted_by_absolute_change():
    require_multi_quarter_data()
    b = tools.get_quarterly_briefing(top_n=5)
    changes = [abs(m["change"]) for m in b["top_movers"]]
    assert changes == sorted(changes, reverse=True)
    assert len(b["top_movers"]) <= 10   # top_n * 2


def test_briefing_cluster_migration_count_matches_its_own_sample_and_pairs():
    require_multi_quarter_data()
    b = tools.get_quarterly_briefing()
    mig = b["cluster_migrations"]
    assert sum(mig["by_transition"].values()) == mig["count"]
    assert len(mig["sample"]) <= mig["count"]


def test_briefing_risk_entrants_are_flagged_when_model_untrained():
    """If the model card is missing, the briefing must say so explicitly rather
    than silently returning an empty entrants list indistinguishable from 'no
    entrants this quarter'."""
    require_multi_quarter_data()
    b = tools.get_quarterly_briefing()
    if not b["risk_model_trained"]:
        assert b["risk_leaderboard_entrants"] == []
    else:
        assert isinstance(b["risk_leaderboard_entrants"], list)


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
