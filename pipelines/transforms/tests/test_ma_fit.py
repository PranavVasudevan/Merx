"""Feature 15 — M&A Fit Finder scoring. Pure functions, no landed data needed.

Covers normal scoring (all four weighted components present, including a real
geo-overlap from synthetic branch footprints) and the no-geo-footprint
renormalization branch — the case exercised whenever a candidate has no
footprint on file. That branch's internal implementation may later change
(a separate backlog item may simplify it); this test checks OBSERVABLE OUTPUT
against a manually-computed proportional renormalization, so it stays valid
either way.

Run: ``python pipelines/transforms/tests/test_ma_fit.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.ma_fit import (  # noqa: E402
    DEFAULT_WEIGHTS, business_similarity, fit_score, funding_complementarity,
    geo_overlap, size_fit,
)

# A deposit-rich, loan-heavy pair with an identical loan mix (so business
# similarity is a clean 1.0) and a candidate a plausible 3x the target's size.
TARGET = {
    "cert_number": 1, "name": "Target Bank", "total_assets": 1_000.0,
    "loan_to_deposit_pct": 120.0,
    "concentration_ratio_cre": 0.4, "concentration_ratio_c_and_i": 0.3,
    "concentration_ratio_residential_mortgage": 0.2,
    "concentration_ratio_consumer": 0.1, "concentration_ratio_agricultural": 0.0,
}
CAND = {
    "cert_number": 2, "name": "Cand Bank", "total_assets": 3_000.0,
    "loan_to_deposit_pct": 60.0,
    "concentration_ratio_cre": 0.4, "concentration_ratio_c_and_i": 0.3,
    "concentration_ratio_residential_mortgage": 0.2,
    "concentration_ratio_consumer": 0.1, "concentration_ratio_agricultural": 0.0,
}

# Synthetic branch footprints (grid-cell based, matching what the unit tests
# in footprint.py exercise) — target and cand share exactly one of three cells.
TARGET_FP = {"cells": {"06073", "06075"}, "deposits_by_cell": {}}
CAND_FP = {"cells": {"06075", "06077"}, "deposits_by_cell": {}}


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_funding_complementarity_opposite_positions_score_above_half():
    comp = funding_complementarity(TARGET, CAND)
    assert comp > 0.5


def test_business_similarity_identical_mix_is_1():
    assert business_similarity(TARGET, CAND) == 1.0


def test_size_fit_plausible_acquirer_range_is_1():
    assert size_fit(TARGET, CAND) == 1.0


def test_geo_overlap_real_footprints_is_jaccard():
    # shared = {06075} -> 1/3
    assert geo_overlap(TARGET_FP, CAND_FP) == round(1 / 3, 4)


def test_geo_overlap_missing_footprint_is_none():
    assert geo_overlap(None, CAND_FP) is None
    assert geo_overlap(TARGET_FP, None) is None


def test_normal_scoring_combines_all_four_weighted_components():
    """With real footprints supplied, geo participates at its full DEFAULT_WEIGHTS
    share alongside funding/business/size — verify the combined score is the
    weighted sum of the four independently-computed components."""
    comp = funding_complementarity(TARGET, CAND)
    sim = business_similarity(TARGET, CAND)
    szf = size_fit(TARGET, CAND)
    geo = geo_overlap(TARGET_FP, CAND_FP)
    w = DEFAULT_WEIGHTS
    expected = comp * w["funding"] + sim * w["business"] + szf * w["size"] + geo * w["geo"]

    result = fit_score(TARGET, CAND, target_footprint=TARGET_FP, cand_footprint=CAND_FP)
    assert result["cert_number"] == 2
    assert result["funding_complementarity"] == comp
    assert result["business_similarity"] == sim
    assert result["size_fit"] == szf
    assert result["geo_overlap"] == geo
    assert approx(result["fit_score"], round(expected, 4), tol=1e-3)


def test_normal_scoring_rationale_mentions_size_multiple():
    result = fit_score(TARGET, CAND, target_footprint=TARGET_FP, cand_footprint=CAND_FP)
    assert "3.0x the target's size" in result["rationale"]


def test_no_geo_footprint_renormalizes_proportionally_over_remaining_weights():
    """THE renormalization branch: a candidate with no footprint data on either
    side. `geo_overlap` degrades to None, so the funding/business/size weights
    must be renormalized to sum to 1 (each scaled by its own share of the
    weight that would otherwise sum without geo) rather than silently
    zero-filling geo's slice of the score."""
    comp = funding_complementarity(TARGET, CAND)
    sim = business_similarity(TARGET, CAND)
    szf = size_fit(TARGET, CAND)

    w = DEFAULT_WEIGHTS
    remaining = w["funding"] + w["business"] + w["size"]
    expected = (comp * (w["funding"] / remaining) + sim * (w["business"] / remaining)
                + szf * (w["size"] / remaining))

    result = fit_score(TARGET, CAND)  # no footprints passed at all
    assert result["geo_overlap"] is None
    assert approx(result["fit_score"], round(expected, 4), tol=1e-3)


def test_no_geo_footprint_score_differs_from_with_geo_score():
    """Sanity check that the renormalization branch actually engages (not a
    no-op that happens to match by coincidence) — with these fixtures the
    real geo overlap (1/3) is below what full weighted renormalization implies,
    so the two scores must differ."""
    with_geo = fit_score(TARGET, CAND, target_footprint=TARGET_FP, cand_footprint=CAND_FP)
    without_geo = fit_score(TARGET, CAND)
    assert with_geo["fit_score"] != without_geo["fit_score"]


def test_no_geo_footprint_rationale_has_no_shared_market_mention():
    result = fit_score(TARGET, CAND)
    assert "local market" not in result["rationale"]


def test_default_weights_sum_to_1():
    assert approx(sum(DEFAULT_WEIGHTS.values()), 1.0)


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
