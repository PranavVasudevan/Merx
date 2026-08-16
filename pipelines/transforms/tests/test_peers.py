"""Feature 11/14 — peer percentile ranking. Pure function, no landed data needed.

Run: ``python pipelines/transforms/tests/test_peers.py``  (no pytest needed)
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.peers import _batch_percentile_ranks, percentile_rank  # noqa: E402


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


# ---- F8: batch (sort + bisect) percentile computation ---------------------

def _naive_batch(population):
    """The pre-F8 approach: percentile_rank() called once per value -- O(n^2)
    over the whole population. Kept here ONLY as the reference implementation
    _batch_percentile_ranks() must match exactly, not as production code."""
    return [percentile_rank(v, population) for v in population]


def test_batch_matches_the_naive_per_value_approach_on_a_small_handcrafted_population():
    population = [10.0, None, 20.0, 20.0, 5.0, None, 30.0, 15.0]
    assert _batch_percentile_ranks(population) == _naive_batch(population)


def test_batch_matches_naive_on_random_populations_of_varying_size_and_density():
    """Bit-identical results is the whole point of F8 -- this is the real
    regression guard, not the handcrafted case above alone."""
    rng = random.Random(20260814)
    for n in (0, 1, 2, 5, 50, 500):
        population = [
            (round(rng.uniform(-100, 100), 2) if rng.random() > 0.15 else None)
            for _ in range(n)
        ]
        assert _batch_percentile_ranks(population) == _naive_batch(population), f"mismatch at n={n}"


def test_batch_on_an_empty_population_returns_all_none_matching_its_length():
    assert _batch_percentile_ranks([]) == []
    assert _batch_percentile_ranks([None, None, None]) == [None, None, None]


def test_batch_is_measurably_faster_than_the_naive_sweep_at_realistic_population_sizes():
    """F8's audit entry: ~23 million comparisons/quarter at the original
    1,049-bank population, growing unworkable at B3's ~4,500-bank universe.
    Report (not just assert) the before/after timing at both sizes."""
    rng = random.Random(20260814)
    for n in (1049, 4500):
        population = [round(rng.uniform(0, 100), 2) for _ in range(n)]

        t0 = time.perf_counter()
        naive = _naive_batch(population)
        naive_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        batch = _batch_percentile_ranks(population)
        batch_s = time.perf_counter() - t0

        assert batch == naive
        print(f"      n={n}: naive={naive_s * 1000:.1f}ms  batch={batch_s * 1000:.1f}ms "
              f"({naive_s / batch_s if batch_s > 0 else float('inf'):.1f}x faster)")
        # A loose bound, not a tight one -- this only needs to catch a real
        # regression back to O(n^2), not chase exact timing on a shared CI
        # runner. The true speedup at n=4500 is two to three orders of
        # magnitude; 3x is a floor far below what either sort+bisect or
        # measurement noise would ever produce by accident.
        assert batch_s * 3 < naive_s, f"batch wasn't meaningfully faster at n={n}"


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
