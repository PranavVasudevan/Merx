"""Percentile-rank (peer) tests. No network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.peers import (  # noqa: E402
    add_percentile_ranks, percentile_rank, summary_stats,
)


def test_percentile_rank_basic():
    pop = [10, 20, 30, 40, 50]
    assert percentile_rank(50, pop) == 100.0     # highest -> 100th
    assert percentile_rank(10, pop) == 20.0      # lowest of 5 -> 20th
    assert percentile_rank(30, pop) == 60.0      # 3 of 5 <= 30


def test_percentile_rank_handles_none():
    assert percentile_rank(None, [1, 2, 3]) is None
    assert percentile_rank(5, [None, None]) is None
    # None values in the population are ignored
    assert percentile_rank(2, [1, None, 3]) == 50.0


def test_add_percentile_ranks_attaches_fields():
    gold = [
        {"cert_number": 1, "concentration_ratio_cre": 70.0, "cet1_ratio": 8.0},
        {"cert_number": 2, "concentration_ratio_cre": 10.0, "cet1_ratio": 15.0},
        {"cert_number": 3, "concentration_ratio_cre": 40.0, "cet1_ratio": 12.0},
    ]
    add_percentile_ranks(gold, metrics=["concentration_ratio_cre", "cet1_ratio"])
    top = next(g for g in gold if g["cert_number"] == 1)
    assert top["percentile_rank_concentration_ratio_cre"] == 100.0   # most concentrated
    assert top["percentile_rank_cet1_ratio"] == 33.3                 # thinnest capital


def test_summary_stats():
    gold = [{"m": v} for v in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]
    s = summary_stats(gold, "m")
    assert s["n"] == 10 and s["max"] == 10


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
