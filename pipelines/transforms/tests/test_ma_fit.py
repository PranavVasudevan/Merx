"""Feature 15 (M&A fit) tests — synthetic banks, no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.ma_fit import (  # noqa: E402
    business_similarity, funding_complementarity, geo_overlap, rank_partners, size_fit,
)


def test_funding_complementarity_rewards_opposite_positions():
    loan_heavy = {"loan_to_deposit_pct": 130}     # needs funding
    deposit_rich = {"loan_to_deposit_pct": 55}    # excess deposits
    similar = {"loan_to_deposit_pct": 128}
    assert funding_complementarity(loan_heavy, deposit_rich) > 0.5
    assert funding_complementarity(loan_heavy, similar) < 0.5


def test_business_similarity_cosine():
    a = {"concentration_ratio_cre": 70, "concentration_ratio_c_and_i": 10}
    b = {"concentration_ratio_cre": 72, "concentration_ratio_c_and_i": 9}
    c = {"concentration_ratio_cre": 5, "concentration_ratio_c_and_i": 60}
    assert business_similarity(a, b) > 0.98        # near-identical mix
    assert business_similarity(a, c) < business_similarity(a, b)


def test_size_fit_prefers_larger_acquirer():
    t = {"total_assets": 10e9}
    assert size_fit(t, {"total_assets": 30e9}) == 1.0     # 3x — plausible acquirer
    assert size_fit(t, {"total_assets": 5e9}) < 0.3       # smaller than target
    assert size_fit(t, {"total_assets": 500e9}) < 0.5     # target is a rounding error


def test_geo_overlap_jaccard():
    # geo_overlap now takes real branch-footprint dicts (grid cells), not state sets —
    # see banklens_transforms.footprint for why (FDIC's STALP/CITY are unreliable
    # at branch level, verified live).
    fp_same = {"cells": {(1, 1), (2, 2)}}
    fp_disjoint = {"cells": {(9, 9)}}
    assert geo_overlap(fp_same, fp_same) == 1.0
    assert geo_overlap(fp_same, fp_disjoint) == 0.0
    assert geo_overlap(fp_same, None) is None


def test_rank_excludes_self_and_sorts():
    target = {"cert_number": 1, "loan_to_deposit_pct": 130, "total_assets": 10e9,
              "concentration_ratio_cre": 60}
    pop = [
        target,
        {"cert_number": 2, "loan_to_deposit_pct": 55, "total_assets": 30e9,
         "concentration_ratio_cre": 58},   # deposit-rich, similar, bigger -> best
        {"cert_number": 3, "loan_to_deposit_pct": 135, "total_assets": 4e9,
         "concentration_ratio_cre": 10},   # loan-heavy, smaller, different -> worse
    ]
    ranked = rank_partners(target, pop, top_n=5)
    assert all(r["cert_number"] != 1 for r in ranked)      # self excluded
    assert ranked[0]["cert_number"] == 2                   # best fit first


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
