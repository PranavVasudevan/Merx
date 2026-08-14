"""Feature X-Ray data-quality exclusions — capital regime detection and the
deposit-funded exclusion. Pure functions, no landed data needed.

Covers the two false-flag shapes that produced 208 real false alarms on the
2026Q1 population (see banklens_transforms.data_quality's module docstring):
foreign-bank branches reporting no standalone capital (NONE) and Community
Bank Leverage Ratio electers reporting no risk-based ratios (CBLR).

Run: ``python pipelines/transforms/tests/test_data_quality.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.data_quality import (  # noqa: E402
    CBLR, CBLR_FRAMEWORK, MIN_DEPOSIT_FUNDED_PCT, NONE, NOT_DEPOSIT_FUNDED,
    NO_REGULATORY_CAPITAL, RISK_BASED, capital_basis, capital_exclusion_for,
    deposit_funding_pct, exclusion_for, is_deposit_funded,
)


# ---- capital_basis ---------------------------------------------------------

def test_normal_bank_is_risk_based():
    """Everyday case: positive equity, real RWA, real ratios."""
    silver = {
        "total_equity": 500.0, "risk_weighted_assets": 4_000.0,
        "cet1_ratio": 12.0, "tier1_rbc_ratio": 12.0, "total_rbc_ratio": 13.0,
        "leverage_ratio": 9.0,
    }
    assert capital_basis(silver) == RISK_BASED


def test_cblr_bank_real_equity_and_leverage_zero_risk_based_ratios():
    """The 195-bank CBLR shape: real positive equity, a real leverage ratio,
    but zero RWA and zero risk-based ratios (EGRRCPA 2018 exemption)."""
    silver = {
        "total_equity": 900.0, "risk_weighted_assets": 0,
        "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0, "total_rbc_ratio": 0.0,
        "leverage_ratio": 9.5,
    }
    assert capital_basis(silver) == CBLR


def test_foreign_branch_equity_unreported_all_ratios_zero_is_none():
    """The 13-bank foreign-branch shape: no standalone capital reported at all."""
    silver = {
        "total_equity": None, "risk_weighted_assets": 0,
        "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0, "total_rbc_ratio": 0.0,
        "leverage_ratio": 0.0,
    }
    assert capital_basis(silver) == NONE


def test_equity_exactly_zero_with_all_ratios_zero_is_also_none():
    """Equity reported as literal 0 (not just missing) with every ratio at 0
    is the same foreign-branch shape, not a distress signal."""
    silver = {
        "total_equity": 0, "risk_weighted_assets": 0,
        "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0, "total_rbc_ratio": 0.0,
        "leverage_ratio": 0.0,
    }
    assert capital_basis(silver) == NONE


def test_negative_equity_is_real_distress_not_swept_into_none():
    """Genuinely negative equity must stay RISK_BASED — it's a real distress
    signal `silver.py` preserves on purpose, per the module's own docstring."""
    silver = {
        "total_equity": -50.0, "risk_weighted_assets": 1_000.0,
        "cet1_ratio": -2.0, "tier1_rbc_ratio": -2.0, "total_rbc_ratio": -1.0,
        "leverage_ratio": -1.0,
    }
    assert capital_basis(silver) == RISK_BASED


def test_cblr_requires_positive_leverage_ratio_not_just_zero_rwa():
    """Zero RWA with a non-positive leverage ratio isn't the CBLR shape —
    falls through to RISK_BASED (and would legitimately look distressed)."""
    silver = {
        "total_equity": 900.0, "risk_weighted_assets": 0,
        "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0, "total_rbc_ratio": 0.0,
        "leverage_ratio": 0.0,
    }
    assert capital_basis(silver) == RISK_BASED


# ---- capital_exclusion_for --------------------------------------------------

def test_capital_exclusion_for_risk_based_is_none():
    silver = {"total_equity": 500.0, "risk_weighted_assets": 4_000.0,
              "cet1_ratio": 12.0, "leverage_ratio": 9.0}
    assert capital_exclusion_for(silver) is None


def test_capital_exclusion_for_cblr_names_the_framework():
    silver = {"cert_number": 111, "name": "Small Community Bank",
              "total_equity": 900.0, "risk_weighted_assets": 0,
              "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0, "total_rbc_ratio": 0.0,
              "leverage_ratio": 9.5}
    exc = capital_exclusion_for(silver)
    assert exc is not None
    assert exc["rule"] == CBLR_FRAMEWORK
    assert exc["cert"] == 111 and exc["leverage_ratio"] == 9.5
    assert "Community Bank Leverage Ratio" in exc["reason"]


def test_capital_exclusion_for_none_names_no_regulatory_capital():
    silver = {"cert_number": 222, "name": "Foreign Branch USA",
              "total_equity": None, "risk_weighted_assets": 0,
              "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0, "total_rbc_ratio": 0.0,
              "leverage_ratio": 0.0}
    exc = capital_exclusion_for(silver)
    assert exc is not None
    assert exc["rule"] == NO_REGULATORY_CAPITAL
    assert exc["cert"] == 222


# ---- deposit-funded exclusion, threshold boundary at 5% --------------------

def test_min_deposit_funded_pct_constant_is_5():
    assert MIN_DEPOSIT_FUNDED_PCT == 5.0


def test_deposit_funding_pct_computes_correctly():
    silver = {"total_assets": 1_000.0, "total_deposits": 250.0}
    assert deposit_funding_pct(silver) == 25.0


def test_deposit_funding_pct_none_when_assets_missing_or_zero():
    assert deposit_funding_pct({"total_assets": None, "total_deposits": 100.0}) is None
    assert deposit_funding_pct({"total_assets": 0, "total_deposits": 100.0}) is None


def test_exactly_at_threshold_is_deposit_funded_not_excluded():
    """Boundary is '>=' — a bank exactly at 5.0% is kept, not excluded."""
    silver = {"total_assets": 1_000.0, "total_deposits": 50.0}  # exactly 5.0%
    assert deposit_funding_pct(silver) == 5.0
    assert is_deposit_funded(silver) is True
    assert exclusion_for(silver) is None


def test_just_below_threshold_is_excluded():
    silver = {"cert_number": 333, "name": "Clearing House Trust",
              "quarter": "2026Q1", "total_assets": 1_000.0, "total_deposits": 49.0}
    assert deposit_funding_pct(silver) == 4.9
    assert is_deposit_funded(silver) is False
    exc = exclusion_for(silver)
    assert exc is not None
    assert exc["rule"] == NOT_DEPOSIT_FUNDED
    assert exc["cert"] == 333
    assert exc["deposits_to_assets_pct"] == 4.9
    assert exc["threshold_pct"] == 5.0


def test_well_below_threshold_the_bank_of_america_rhode_island_shape():
    """A near-zero deposit-funded institution — real numbers from the module
    docstring's cited example, scaled down."""
    silver = {"cert_number": 444, "name": "BANK OF AMERICA, RHODE ISLAND, N.A.",
              "total_assets": 35_800_000.0, "total_deposits": 358.0}  # 0.001%
    exc = exclusion_for(silver)
    assert exc is not None
    assert exc["deposits_to_assets_pct"] < 0.01


def test_unknown_funding_missing_assets_is_not_excluded():
    """Unknown funding (missing assets) must not be treated as excludable —
    we don't drop a bank on the basis of data we don't have."""
    silver = {"total_assets": None, "total_deposits": None}
    assert is_deposit_funded(silver) is True
    assert exclusion_for(silver) is None


def test_custom_threshold_is_respected():
    silver = {"total_assets": 1_000.0, "total_deposits": 80.0}  # 8%
    assert exclusion_for(silver, threshold=5.0) is None
    exc = exclusion_for(silver, threshold=10.0)
    assert exc is not None and exc["threshold_pct"] == 10.0


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
