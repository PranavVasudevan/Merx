"""Feature 11/14 — peer percentile ranking. Pure function, no landed data needed.

Run: ``python pipelines/transforms/tests/test_peers.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.peers import percentile_rank  # noqa: E402


def test_value_none_is_none():
    assert percentile_rank(None, [1.0, 2.0, 3.0]) is None


def test_population_all_none_is_none():
    assert percentile_rank(5.0, [None, None, None]) is None


def test_empty_population_is_none():
    assert percentile_rank(5.0, []) is None


def test_none_values_in_population_are_ignored_not_counted():
    """A None in the population must not silently count as <= value (nor be dropped
    from the denominator inconsistently) — it should simply be excluded entirely."""
    assert percentile_rank(5.0, [1.0, None, 9.0]) == percentile_rank(5.0, [1.0, 9.0])


def test_value_below_everyone_is_the_0th_percentile():
    assert percentile_rank(0.0, [1.0, 2.0, 3.0, 4.0]) == 0.0


def test_value_above_everyone_is_the_100th_percentile():
    assert percentile_rank(10.0, [1.0, 2.0, 3.0, 4.0]) == 100.0


def test_ties_count_as_less_than_or_equal():
    """Definition is explicitly '<=' — a value tied with the whole population ranks
    at the 100th percentile, not excluded from its own comparison."""
    assert percentile_rank(1.0, [1.0, 1.0, 1.0]) == 100.0


def test_single_value_population_matching_the_value_is_100th_percentile():
    assert percentile_rank(5.0, [5.0]) == 100.0


def test_single_value_population_below_the_value_is_still_100th_percentile():
    assert percentile_rank(5.0, [1.0]) == 100.0


def test_single_value_population_above_the_value_is_0th_percentile():
    assert percentile_rank(1.0, [5.0]) == 0.0


def test_midpoint_of_population_ranks_proportionally():
    # 2 of 4 values <= 2.0 -> 50.0
    assert percentile_rank(2.0, [1.0, 2.0, 3.0, 4.0]) == 50.0


def test_result_is_rounded_to_one_decimal():
    # 1 of 3 <= value -> 33.333... -> rounds to 33.3
    assert percentile_rank(1.0, [1.0, 2.0, 3.0]) == 33.3


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
