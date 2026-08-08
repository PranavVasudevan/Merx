"""Feature 11 — Balance-Sheet X-Ray. Rule-based, so each expected verdict is
traceable to one named supervisory threshold.

Includes the regression for a real reporting bug: rules that couldn't run for lack
of disclosed data vanished silently, so a bank assessed on 2 of 8 rules displayed
"1 flag, elevated" identically to one assessed on all 8.

Run: ``python pipelines/transforms/tests/test_xray.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.xray import RULES, evaluate_xray  # noqa: E402

# A clean bank: every rule has data, none breach.
HEALTHY = {
    "cert_number": 1, "name": "Healthy Bank", "quarter": "2026Q1",
    "uninsured_deposit_pct": 20.0, "loan_to_deposit_pct": 70.0,
    "max_loan_concentration_pct": 30.0, "cre_to_total_capital_pct": 100.0,
    "construction_to_total_capital_pct": 40.0, "core_deposit_pct": 80.0,
    "cet1_ratio": 14.0, "leverage_ratio": 9.0,
}
# The EU/EBA shape: only capital metrics disclosed.
SPARSE = {
    "cert_number": 2, "name": "EU Bank", "quarter": "2025Q2",
    "cet1_ratio": 14.0, "leverage_ratio": 4.7,
}


def test_healthy_bank_is_fully_assessed_and_clean():
    r = evaluate_xray(HEALTHY)
    assert r["overall_risk"] == "low"
    assert r["flag_count"] == 0
    assert r["fully_assessed"] is True
    assert r["rules_evaluated"] == r["rules_total"] == len(RULES)
    assert r["rules_not_evaluated"] == []


def test_breach_raises_severity_and_names_the_threshold():
    """A bank over the uninsured-deposit threshold must flag, and the flag must
    carry the value and threshold that produced it — an unexplained score is
    unusable to an examiner."""
    bank = {**HEALTHY, "uninsured_deposit_pct": 80.0}
    r = evaluate_xray(bank)
    assert r["overall_risk"] in ("elevated", "high")
    flag = next(f for f in r["flags"] if f["metric"] == "uninsured_deposit_pct")
    assert flag["value"] == 80.0
    assert flag["threshold"] is not None
    assert flag["note"]


def test_overall_risk_is_the_worst_severity_present():
    bank = {**HEALTHY, "uninsured_deposit_pct": 80.0, "cet1_ratio": 6.0}
    r = evaluate_xray(bank)
    assert r["overall_risk"] == "high"
    assert r["flag_count"] >= 2


def test_flags_are_sorted_worst_first():
    bank = {**HEALTHY, "uninsured_deposit_pct": 80.0, "cet1_ratio": 6.0}
    sev = [f["severity"] for f in evaluate_xray(bank)["flags"]]
    order = {"high": 2, "elevated": 1, "low": 0}
    assert sev == sorted(sev, key=lambda s: order[s], reverse=True)


def test_undisclosed_rules_are_reported_not_silently_dropped():
    """THE regression. A bank with only capital data must say so, or its low flag
    count reads as a clean bill of health rather than a thin assessment."""
    r = evaluate_xray(SPARSE)
    assert r["fully_assessed"] is False
    assert r["rules_evaluated"] == 2                    # cet1 + leverage only
    assert r["rules_evaluated"] < r["rules_total"]
    assert "uninsured_deposit_pct" in r["rules_not_evaluated"]
    assert "max_loan_concentration_pct" in r["rules_not_evaluated"]


def test_sparse_bank_still_flags_on_the_rules_that_can_run():
    """Partial coverage must not mean partial function — a thin leverage ratio is
    still catchable from the two metrics EBA does disclose."""
    r = evaluate_xray(SPARSE)
    assert r["flag_count"] >= 1
    assert any(f["metric"] == "leverage_ratio" for f in r["flags"])


def test_capital_basis_suppression_is_distinct_from_missing_data():
    """A CBLR electer reports no risk-based capital by design — that's a deliberate
    suppression, not a data gap, and the two must not be conflated."""
    r = evaluate_xray(HEALTHY, capital_basis="cblr")
    assert "risk_based_capital" not in [f["metric"] for f in r["flags"]]
    assert r["rules_not_applicable"]                    # suppressed by basis
    assert r["fully_assessed"] is False


def test_peer_percentile_attached_when_available():
    bank = {**HEALTHY, "uninsured_deposit_pct": 80.0,
            "percentile_rank_uninsured_deposit_pct": 97.5}
    flag = next(f for f in evaluate_xray(bank)["flags"]
                if f["metric"] == "uninsured_deposit_pct")
    assert flag["peer_percentile"] == 97.5


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
