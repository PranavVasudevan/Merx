"""Feature 11 (X-Ray) rule tests.

Verifies the scorer on a real, well-capitalized bank (Wells Fargo — should be
mostly clean with an elevated uninsured flag) and on a synthetic stressed bank
(should light up multiple HIGH flags). No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
