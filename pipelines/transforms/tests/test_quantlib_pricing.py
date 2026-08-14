"""C7 — real QuantLib DCF re-pricing for the AFS/HTM securities book. Needs the
compiled `QuantLib` Python bindings (`pip install QuantLib`); SKIPs rather than
fails when that optional dependency isn't installed, same convention as every
other test here that depends on something not guaranteed present.

Run: ``python pipelines/transforms/tests/test_quantlib_pricing.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import QuantLib  # noqa: F401
    _HAS_QUANTLIB = True
except ImportError:
    _HAS_QUANTLIB = False

if _HAS_QUANTLIB:
    from banklens_transforms.quantlib_pricing import loss_from_reprice, reprice_under_shock


def approx(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


def test_zero_shock_is_a_price_no_op():
    r = reprice_under_shock(maturity_years=5, base_yield=0.04, rate_shock_bps=0)
    assert approx(r["price_change_pct"], 0.0, tol=1e-9)
    assert approx(r["base_price"], r["shocked_price"], tol=1e-6)


def test_rate_rise_produces_a_price_loss():
    r = reprice_under_shock(maturity_years=5, base_yield=0.04, rate_shock_bps=200)
    assert r["price_change_pct"] < 0
    loss = loss_from_reprice(book_value=1_000_000.0, maturity_years=5, base_yield=0.04, rate_shock_bps=200)
    assert loss > 0        # positive == a loss, matching stress.py's afs_loss/htm_unrealized sign convention


def test_rate_fall_produces_a_price_gain():
    r = reprice_under_shock(maturity_years=5, base_yield=0.04, rate_shock_bps=-200)
    assert r["price_change_pct"] > 0
    loss = loss_from_reprice(book_value=1_000_000.0, maturity_years=5, base_yield=0.04, rate_shock_bps=-200)
    assert loss < 0        # a negative "loss" is a real gain


def test_larger_shock_produces_a_larger_absolute_loss():
    small = loss_from_reprice(1_000_000.0, maturity_years=5, base_yield=0.04, rate_shock_bps=100)
    large = loss_from_reprice(1_000_000.0, maturity_years=5, base_yield=0.04, rate_shock_bps=400)
    assert large > small > 0


def test_longer_maturity_is_more_rate_sensitive_than_shorter_for_the_same_shock():
    short = loss_from_reprice(1_000_000.0, maturity_years=2, base_yield=0.04, rate_shock_bps=200)
    long_ = loss_from_reprice(1_000_000.0, maturity_years=10, base_yield=0.04, rate_shock_bps=200)
    assert long_ > short > 0


def test_modified_duration_is_below_maturity_for_a_coupon_bond():
    """Per the module docstring: a coupon bond's duration is always less than
    its maturity (cash flows arrive before the final one) — genuinely distinct
    from the caller's plain 'assumed duration in years' input, not a rounding
    artifact."""
    r = reprice_under_shock(maturity_years=10, base_yield=0.04, rate_shock_bps=100)
    assert 0 < r["modified_duration"] < 10


def test_convexity_is_positive_for_a_plain_fixed_rate_bond():
    r = reprice_under_shock(maturity_years=10, base_yield=0.04, rate_shock_bps=100)
    assert r["convexity"] > 0


def test_convexity_means_a_real_reprice_beats_a_pure_linear_duration_estimate():
    """The whole point of C7/C4's upgrade: convexity means the ACTUAL price drop
    under a rate rise is smaller than a linear (duration-only) approximation
    would predict, and the actual price gain under a rate fall is larger. Assert
    the real DCF loss for a rise is strictly less than the naive linear estimate
    (book_value * duration * shock)."""
    maturity, base_yield, shock_bps = 10, 0.04, 300
    r = reprice_under_shock(maturity, base_yield, shock_bps)
    book_value = 1_000_000.0
    linear_estimate = book_value * r["modified_duration"] * (shock_bps / 10_000.0)
    real_loss = loss_from_reprice(book_value, maturity, base_yield, shock_bps)
    assert 0 < real_loss < linear_estimate


def test_zero_or_negative_maturity_is_a_documented_no_op_not_a_crash():
    r = reprice_under_shock(maturity_years=0, base_yield=0.04, rate_shock_bps=200)
    assert r == {"modified_duration": 0.0, "convexity": 0.0, "price_change_pct": 0.0,
                 "base_price": 100.0, "shocked_price": 100.0}


def test_zero_or_negative_base_yield_is_a_documented_no_op_not_a_crash():
    r = reprice_under_shock(maturity_years=5, base_yield=0.0, rate_shock_bps=200)
    assert r["price_change_pct"] == 0.0


def test_non_positive_book_value_never_produces_a_loss():
    assert loss_from_reprice(0.0, maturity_years=5, base_yield=0.04, rate_shock_bps=200) == 0.0
    assert loss_from_reprice(-100.0, maturity_years=5, base_yield=0.04, rate_shock_bps=200) == 0.0


def test_repeated_calls_are_order_independent_despite_global_evaluation_date_state():
    """ql.Settings.instance().evaluationDate is process-global — the module docs
    say reprice_under_shock() sets it unconditionally every call specifically so
    call order can't leak state between banks. Interleave two different bonds and
    confirm neither call's result depends on which ran first."""
    a1 = reprice_under_shock(5, 0.04, 200)
    b1 = reprice_under_shock(10, 0.06, -100)
    b2 = reprice_under_shock(10, 0.06, -100)
    a2 = reprice_under_shock(5, 0.04, 200)
    assert a1 == a2
    assert b1 == b2


if __name__ == "__main__":
    if not _HAS_QUANTLIB:
        print("SKIP  QuantLib not installed (pip install QuantLib) — skipping quantlib_pricing tests")
        sys.exit(0)
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
