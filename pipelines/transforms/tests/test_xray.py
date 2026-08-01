"""Feature 11 (X-Ray) rule tests.

Verifies the scorer on a real, well-capitalized bank (Wells Fargo — should be
mostly clean with an elevated uninsured flag) and on a synthetic stressed bank
(should light up multiple HIGH flags). No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.data_quality import capital_basis  # noqa: E402
from banklens_transforms.gold import derive_gold  # noqa: E402
from banklens_transforms.silver import to_bank_financials  # noqa: E402
from banklens_transforms.xray import evaluate_xray  # noqa: E402

# Reuse the real Wells Fargo fixture.
from test_gold_metrics import WF_2026Q1  # noqa: E402


def test_wells_fargo_is_well_capitalized_but_elevated_uninsured():
    g = derive_gold([to_bank_financials(WF_2026Q1)])[0]
    x = evaluate_xray(g)
    # Diversified + well-capitalized => no HIGH flags...
    assert all(f["severity"] != "high" for f in x["flags"])
    # ...but uninsured reliance (~48%) trips the elevated threshold.
    assert x["overall_risk"] == "elevated"
    assert any(f["metric"] == "uninsured_deposit_pct" for f in x["flags"])


def test_stressed_bank_lights_up_high():
    """A synthetic bank: SVB-like uninsured, CRE-heavy, thin capital."""
    stressed = {
        "cert_number": 99999, "name": "STRESSED COMMUNITY BANK", "quarter": "2026Q1",
        "uninsured_deposit_pct": 88.0,          # SVB territory
        "loan_to_deposit_pct": 105.0,           # over-lent
        "max_loan_concentration_category": "cre",
        "max_loan_concentration_pct": 55.0,     # dangerously concentrated
        "cre_to_equity_pct": 420.0,             # way past the 300% flag
        "core_deposit_pct": 35.0,               # unstable funding
        "cet1_ratio": 6.5,                      # below buffer
        "leverage_ratio": 3.8,                  # below well-capitalized
    }
    x = evaluate_xray(stressed)
    assert x["overall_risk"] == "high"
    assert x["flag_count"] >= 5
    # highest-severity flags sort first
    assert x["flags"][0]["severity"] == "high"


def test_none_metrics_are_skipped():
    x = evaluate_xray({"cert_number": 1, "name": "SPARSE", "quarter": "2026Q1"})
    assert x["overall_risk"] == "low" and x["flag_count"] == 0


def test_capital_basis_detects_the_three_regimes():
    """Regression guard for a REAL defect: reading a reported zero as "thin capital"
    produced a false 'CET1 below the Basel minimum' flag on 208 of 1,049 real banks."""
    normal = {"total_equity": 1.6e9, "cet1_ratio": 14.6, "tier1_rbc_ratio": 14.6,
              "total_rbc_ratio": 15.6, "leverage_ratio": 10.4,
              "risk_weighted_assets": 1.1e10}
    # Capitol Federal's real shape: positive equity, real leverage, zero RWA/CET1.
    cblr = {"total_equity": 9.8e8, "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0,
            "total_rbc_ratio": 0.0, "leverage_ratio": 9.512, "risk_weighted_assets": 0.0}
    # Standard Chartered's real shape: nothing reported at all.
    branch = {"total_equity": None, "cet1_ratio": 0.0, "tier1_rbc_ratio": 0.0,
              "total_rbc_ratio": 0.0, "leverage_ratio": 0.0, "risk_weighted_assets": 0.0}
    assert capital_basis(normal) == "risk_based"
    assert capital_basis(cblr) == "cblr"
    assert capital_basis(branch) == "none"


def test_negative_equity_is_never_treated_as_an_exemption():
    """A genuinely distressed bank must stay fully evaluated — silver.py preserves
    negative equity on purpose and it must not be swept into a capital exemption."""
    distressed = {"total_equity": -5.0e8, "cet1_ratio": -2.0, "tier1_rbc_ratio": -2.0,
                  "total_rbc_ratio": -1.0, "leverage_ratio": -1.5,
                  "risk_weighted_assets": 2.0e9}
    assert capital_basis(distressed) == "risk_based"
    x = evaluate_xray({"cert_number": 1, "name": "D", "cet1_ratio": -2.0, "leverage_ratio": -1.5},
                      capital_basis=capital_basis(distressed))
    assert x["rules_not_applicable"] == []
    assert any(f["metric"] == "cet1_ratio" and f["severity"] == "high" for f in x["flags"])


def test_cblr_suppresses_cet1_but_keeps_leverage():
    """CBLR electers are DEEMED to satisfy risk-based requirements, so flagging CET1
    inverts the regulator's finding — but leverage is their binding measure and must
    still be evaluated."""
    row = {"cert_number": 1, "name": "CBLR BANK", "cet1_ratio": 0.0, "leverage_ratio": 3.5}
    x = evaluate_xray(row, capital_basis="cblr")
    assert x["rules_not_applicable"] == ["cet1_ratio"]
    assert not any(f["metric"] == "cet1_ratio" for f in x["flags"])
    assert any(f["metric"] == "leverage_ratio" and f["severity"] == "high" for f in x["flags"])


def test_foreign_branch_suppresses_all_capital_rules():
    row = {"cert_number": 1, "name": "FOREIGN BRANCH", "cet1_ratio": 0.0,
           "leverage_ratio": 0.0, "uninsured_deposit_pct": 60.0}
    x = evaluate_xray(row, capital_basis="none")
    assert set(x["rules_not_applicable"]) == {"cet1_ratio", "leverage_ratio"}
    # non-capital analytics still apply to these banks — they're not dropped wholesale
    assert any(f["metric"] == "uninsured_deposit_pct" for f in x["flags"])


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
