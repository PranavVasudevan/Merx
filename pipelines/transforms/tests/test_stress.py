"""Feature 16 — capital-buffer simulator. Deterministic math, so every expected
value here is hand-derivable rather than a recorded snapshot.

Includes the regression for a real false-reassurance bug: a bank with no disclosed
deposits, asked to survive a 25% deposit run, returned completely unchanged ratios —
reading as "immune" when the truth was "not measured".

Run: ``python pipelines/transforms/tests/test_stress.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.stress import (  # noqa: E402
    MINIMUMS, Shock, run_stress_test, starting_position,
)

# A deliberately round synthetic bank so every expected number is checkable by hand:
# CET1 = 10% of RWA, leverage = 10%, no securities marks unless a rate shock is asked.
FULL = {
    "name": "Testbank", "quarter": "2026Q1",
    "tier1_capital": 10_000.0, "total_capital": 12_000.0,
    "risk_weighted_assets": 100_000.0,
    "cet1_ratio": 10.0, "leverage_ratio": 10.0,
    "total_loans_gross": 50_000.0, "total_deposits": 80_000.0,
    "cash_and_balances": 10_000.0,
    "securities_afs": 5_000.0, "securities_htm": 5_000.0,
}
# Same bank with deposits undisclosed — the EU/EBA shape.
NO_DEPOSITS = {**FULL, "total_deposits": None}


def approx(a, b, tol=0.02):
    return a is not None and abs(a - b) <= tol


def test_zero_shock_reproduces_the_reported_ratios():
    """The baseline must be a no-op: if a zero shock moves the ratios, the starting
    position is wrong and every stressed number built on it is wrong too."""
    res = run_stress_test(starting_position(FULL), Shock())
    assert approx(res["before"]["cet1"], 10.0)
    assert approx(res["after"]["cet1"], 10.0)
    assert approx(res["after"]["leverage"], 10.0)
    assert res["passes_all"] is True


def test_loan_loss_erodes_capital_by_the_expected_amount():
    """10% loss on a 50,000 loan book = 5,000 of capital gone (no tax shield).
    CET1 10,000 -> 5,000; RWA shrinks by the written-off loans: 100,000 -> 95,000.
    So CET1 ratio = 5,000/95,000 = 5.26%."""
    res = run_stress_test(starting_position(FULL), Shock(loan_loss_pct=10.0))
    assert approx(res["capital_waterfall"]["loan_loss"], 5_000.0, tol=1.0)
    assert approx(res["after"]["cet1"], 5.26, tol=0.05)
    assert res["passes"]["cet1"] is False      # below the 7.0 minimum
    assert res["passes_all"] is False


def test_ratios_never_go_negative_under_an_extreme_shock():
    res = run_stress_test(starting_position(FULL), Shock(loan_loss_pct=100.0,
                                                        deposit_outflow_pct=100.0,
                                                        rate_shock_bps=1000))
    for k, v in res["after"].items():
        assert v >= 0.0, f"{k} went negative: {v}"


def test_severity_is_monotonic():
    """A strictly worse shock can never produce a strictly better capital ratio."""
    mild = run_stress_test(starting_position(FULL), Shock(loan_loss_pct=2.0))
    harsh = run_stress_test(starting_position(FULL), Shock(loan_loss_pct=8.0))
    assert harsh["after"]["cet1"] < mild["after"]["cet1"]


def test_deposit_run_forces_htm_sales_once_liquidity_is_exhausted():
    """The SVB chain: outflow beyond cash+AFS forces HTM sales, realizing the loss
    that was previously only on paper. Liquidity here is 10,000 cash + 5,000 AFS;
    a 25% run on 80,000 deposits = 20,000, so 5,000 must come from HTM."""
    res = run_stress_test(starting_position(FULL),
                          Shock(deposit_outflow_pct=25.0, rate_shock_bps=200))
    liq = res["liquidity"]
    assert approx(liq["deposit_outflow"], 20_000.0, tol=1.0)
    assert liq["shortfall_forcing_htm_sales"] > 0
    assert 0 < liq["htm_sold_fraction"] <= 1.0
    assert res["capital_waterfall"]["htm_realized_loss"] > 0


def test_small_run_is_absorbed_without_touching_htm():
    res = run_stress_test(starting_position(FULL),
                          Shock(deposit_outflow_pct=5.0, rate_shock_bps=200))
    assert res["liquidity"]["shortfall_forcing_htm_sales"] == 0
    assert res["liquidity"]["htm_sold_fraction"] == 0
    assert res["capital_waterfall"]["htm_realized_loss"] == 0


def test_fully_covered_bank_reports_no_missing_legs():
    res = run_stress_test(starting_position(FULL),
                          Shock(loan_loss_pct=3.0, deposit_outflow_pct=25.0,
                                rate_shock_bps=200))
    assert res["fully_covered"] is True
    assert res["legs_not_applied"] == []


def test_undisclosed_deposits_are_reported_not_silently_treated_as_zero():
    """THE regression. Found live on EU banks: `pos["total_deposits"] or 0.0` turned
    "not disclosed" into "zero deposits", so a 25% run produced a 0 outflow and
    untouched ratios — indistinguishable from a bank that genuinely shrugged it off.
    The arithmetic still runs, but the skipped leg must be named."""
    res = run_stress_test(starting_position(NO_DEPOSITS),
                          Shock(loan_loss_pct=3.0, deposit_outflow_pct=25.0,
                                rate_shock_bps=200))
    assert res["fully_covered"] is False
    legs = {l["leg"] for l in res["legs_not_applied"]}
    assert "deposit_outflow" in legs
    assert legs == {"deposit_outflow"}          # the other two legs DID run
    missing = next(l for l in res["legs_not_applied"] if l["leg"] == "deposit_outflow")
    assert missing["requested_pct"] == 25.0     # what the caller actually asked for
    assert missing["reason"]


def test_a_leg_that_was_not_requested_is_not_reported_as_missing():
    """Only shocks the caller actually asked for count as skipped — a bank with no
    deposits that was never asked about deposits is fully covered for that request."""
    res = run_stress_test(starting_position(NO_DEPOSITS), Shock(loan_loss_pct=3.0))
    assert res["fully_covered"] is True
    assert res["legs_not_applied"] == []


def test_minimums_are_the_real_regulatory_floors():
    assert MINIMUMS == {"cet1": 7.0, "tier1": 8.5, "total": 10.5, "leverage": 4.0}


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
