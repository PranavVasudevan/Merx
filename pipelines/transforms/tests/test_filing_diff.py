"""Feature 12 — Filing Diff statistical change detection. Pure function over
hand-built quarter dicts (bypasses `build_quarters`/`gold_features`, which need a
full Silver row — `diff()` itself only ever reads the keys named in `TRACKED`).

Run: ``python pipelines/transforms/tests/test_filing_diff.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.filing_diff import diff  # noqa: E402


def q(quarter: str, total_assets: float, **extra) -> dict:
    """A quarter dict with everything else in TRACKED left unset (None)."""
    return {"name": "Testbank", "quarter": quarter, "total_assets": total_assets, **extra}


def flag_for(result: dict, metric: str) -> dict | None:
    return next((f for f in result["flags"] if f["metric"] == metric), None)


def line_for(result: dict, metric: str) -> dict:
    return next(li for li in result["line_items"] if li["metric"] == metric)


# ---- small-sample z behaviour --------------------------------------------

def test_two_quarters_has_no_z_and_falls_back_to_the_big_absolute_threshold():
    """With only two quarters there's no history at all to build a baseline from
    (hist is always empty once the transition itself is excluded), so z must be
    None — flagging then falls back to the coarse _BIG floor (8% for a dollar
    item), not the z-score path."""
    quarters = [q("2026Q2", 110.0), q("2026Q1", 100.0)]  # +10% -- above _BIG (8%)
    result = diff(quarters)
    li = line_for(result, "total_assets")
    assert li["z"] is None
    assert li["flagged"] is True
    assert flag_for(result, "total_assets") is not None


def test_two_quarters_small_move_is_not_flagged_even_with_no_z():
    quarters = [q("2026Q2", 103.0), q("2026Q1", 100.0)]  # +3% -- below _BIG (8%)
    result = diff(quarters)
    li = line_for(result, "total_assets")
    assert li["z"] is None
    assert li["flagged"] is False


def test_three_quarters_still_has_no_z_one_historical_sample_cant_form_a_std():
    """Variance needs >= 2 historical observations (`len(hist) > 1`); a single
    leftover sample after excluding the evaluated transition still yields std=0
    -> z=None, same fallback-threshold behaviour as the two-quarter case."""
    quarters = [q("2026Q3", 110.0), q("2026Q2", 100.0), q("2026Q1", 90.0)]
    result = diff(quarters)  # diffs Q2->Q3 by default (two most recent)
    li = line_for(result, "total_assets")
    assert li["z"] is None


def test_four_quarters_is_enough_history_to_compute_a_real_z():
    quarters = [
        q("2026Q4", 100.0), q("2026Q3", 100.0), q("2026Q2", 101.0), q("2026Q1", 100.0),
    ]
    result = diff(quarters)  # Q3->Q4: 0% change vs a real (if degenerate) baseline
    li = line_for(result, "total_assets")
    # Two historical samples now exist (Q2->Q3 flat except one), so a std --
    # and therefore a real z, not None -- becomes computable.
    assert li["z"] is not None


# ---- materiality floor + z-threshold gating -------------------------------

def test_high_z_alone_does_not_flag_a_sub_floor_move():
    """A tiny move can still be a statistical outlier for a very stable bank --
    the _FLOOR gate exists precisely so that doesn't get flagged as material."""
    quarters = [
        q("2026Q5", 100.5),  # +0.5% -- real but trivial move, below the 2.0% floor
        q("2026Q4", 100.0), q("2026Q3", 100.0), q("2026Q2", 100.0), q("2026Q1", 100.0),
    ]
    result = diff(quarters)
    li = line_for(result, "total_assets")
    assert abs(li["change"]) < 2.0
    assert li["flagged"] is False


def test_material_move_below_z_threshold_does_not_flag():
    """A move that clears the materiality floor but isn't a statistical outlier
    for THIS bank (it moves by a similar amount every quarter) shouldn't flag."""
    quarters = [
        q("2026Q5", 106.0), q("2026Q4", 103.0), q("2026Q3", 106.0),
        q("2026Q2", 103.0), q("2026Q1", 100.0),
    ]
    result = diff(quarters, z_threshold=2.0)
    li = line_for(result, "total_assets")
    assert abs(li["change"]) >= 2.0          # clears the materiality floor
    assert li["z"] is not None
    assert abs(li["z"]) < 2.0                # but isn't a real outlier for this bank
    assert li["flagged"] is False


def test_material_and_statistically_outlying_move_flags():
    quarters = [
        q("2026Q5", 150.0),  # +50% -- wildly outside this bank's normal +/-1% wobble
        q("2026Q4", 100.0), q("2026Q3", 101.0), q("2026Q2", 100.0), q("2026Q1", 101.0),
    ]
    result = diff(quarters)
    li = line_for(result, "total_assets")
    assert li["flagged"] is True
    assert flag_for(result, "total_assets")["z"] is not None
    assert abs(flag_for(result, "total_assets")["z"]) >= 2.0


# ---- the evaluated transition is excluded from its own baseline ----------

def test_evaluated_transition_is_excluded_from_its_own_baseline_stats():
    """If the evaluated Q5->Q6 jump (+100%) were allowed to count toward its own
    mean/std, a huge one-off move would drag the baseline toward itself and
    SUPPRESS its own z: hand-computed, folding it in gives mean=20.2, std=40.0,
    z=(100-20.2)/40.0 = 1.99 -- BELOW the 2.0 flagging threshold. Excluding it (the
    real behaviour), the baseline is just the four steady +/-2% oscillations, giving
    z ~= 50 -- an unmistakable outlier. Assert the real result lands nowhere near
    the polluted-baseline value, which is what would happen if exclusion regressed."""
    quarters = [
        q("2026Q6", 200.0),  # the transition under test: Q5->Q6 = +100%
        q("2026Q5", 100.0),
        q("2026Q4", 102.0),
        q("2026Q3", 100.0),
        q("2026Q2", 102.0),
        q("2026Q1", 100.0),
    ]
    result = diff(quarters)  # defaults to most-recent transition, Q5->Q6
    li = line_for(result, "total_assets")

    assert li["change"] == 100.0
    assert li["z"] is not None
    assert li["z"] > 10.0        # nowhere near the ~1.99 a polluted baseline would give
    assert li["flagged"] is True


# ---- unreported values --------------------------------------------------

def test_missing_value_on_either_side_is_listed_but_never_flagged():
    quarters = [q("2026Q2", 110.0, total_deposits=None), q("2026Q1", 100.0, total_deposits=50.0)]
    result = diff(quarters)
    li = line_for(result, "total_deposits")
    assert li["change"] is None
    assert li["z"] is None
    assert li["flagged"] is False
    assert flag_for(result, "total_deposits") is None
    # Still present in the side-by-side view even though nothing could be diffed.
    assert li["quarter_a_value"] == 50.0
    assert li["quarter_b_value"] is None


def test_zero_baseline_denominator_is_treated_as_unreported_not_infinite_growth():
    quarters = [q("2026Q2", 100.0, total_deposits=50.0), q("2026Q1", 100.0, total_deposits=0.0)]
    result = diff(quarters)
    li = line_for(result, "total_deposits")
    assert li["change"] is None
    assert li["flagged"] is False


# ---- ratio (percentage-point) items use the pp floor, not the dollar floor --

def test_ratio_item_uses_the_pp_floor_not_the_dollar_pct_floor():
    quarters = [
        q("2026Q5", 100.0, cet1_ratio=10.5),  # +0.5pp -- clears the 0.3pp ratio floor
        q("2026Q4", 100.0, cet1_ratio=10.0), q("2026Q3", 100.0, cet1_ratio=10.0),
        q("2026Q2", 100.0, cet1_ratio=10.0), q("2026Q1", 100.0, cet1_ratio=10.0),
    ]
    result = diff(quarters)
    li = line_for(result, "cet1_ratio")
    assert li["unit"] == "pp"
    assert li["change"] == 0.5
    assert abs(li["change"]) >= 0.3   # clears the 0.3pp ratio floor


# ---- selection / ordering --------------------------------------------------

def test_defaults_to_the_two_most_recent_quarters():
    quarters = [q("2026Q3", 130.0), q("2026Q2", 120.0), q("2026Q1", 100.0)]
    result = diff(quarters)
    assert result["from_quarter"] == "2026Q2"
    assert result["to_quarter"] == "2026Q3"


def test_explicit_quarter_selection_is_order_independent():
    quarters = [q("2026Q3", 130.0), q("2026Q2", 120.0), q("2026Q1", 100.0)]
    forward = diff(quarters, quarter_a="2026Q1", quarter_b="2026Q3")
    backward = diff(quarters, quarter_a="2026Q3", quarter_b="2026Q1")
    assert forward["from_quarter"] == backward["from_quarter"] == "2026Q1"
    assert forward["to_quarter"] == backward["to_quarter"] == "2026Q3"


def test_flags_are_sorted_by_absolute_z_descending():
    quarters = [
        q("2026Q5", 200.0, total_deposits=140.0),
        q("2026Q4", 100.0, total_deposits=100.0),
        q("2026Q3", 101.0, total_deposits=105.0),
        q("2026Q2", 100.0, total_deposits=95.0),
        q("2026Q1", 101.0, total_deposits=104.0),
    ]
    result = diff(quarters)
    zs = [abs(f["z"]) for f in result["flags"] if f["z"] is not None]
    assert zs == sorted(zs, reverse=True)


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
