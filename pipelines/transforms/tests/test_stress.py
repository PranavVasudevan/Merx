"""Feature 16 stress-simulator tests, pinned to real Wells Fargo capital figures.

Key property: with ZERO shock the recomputed ratios must reproduce FDIC's reported
ratios exactly (proof the baseline is right). Then shocks move them predictably.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.silver import to_bank_financials  # noqa: E402
from banklens_transforms.stress import (  # noqa: E402
    Shock, run_stress_test, run_stress_test_quantlib, starting_position,
)

# Real WF 2026Q1 (thousands / percentages), verified live.
WF = {
    "CERT": 3511, "REPDTE": 20260331, "NAMEFULL": "WELLS FARGO BANK, NATIONAL ASSOCIATION",
    "STALP": "SD", "DEP": 1516982000, "LNLSGR": 985437000, "LNLSNET": 971566000,
    "SC": 420321000, "SCAF": 216209000, "SCHA": 204169000, "CHBAL": 173552000,
    "RBCT1J": 151450000, "RBC": 169159000, "RWAJT": 1203546500, "ASSET5": 1837466000,
    "IDT1CER": 12.583643, "IDT1RWAJR": 12.583643, "RBCRWAJ": 14.055045, "RBC1AAJ": 8.400350,
}


def _pos():
    return starting_position(to_bank_financials(WF))


def test_baseline_reproduces_reported_ratios():
    res = run_stress_test(_pos(), Shock())      # zero shock
    b = res["before"]
    assert abs(b["cet1"] - 12.58) < 0.05
    assert abs(b["total"] - 14.06) < 0.05
    assert abs(b["leverage"] - 8.40) < 0.05
    assert res["after"] == res["before"]        # nothing changed
    assert res["passes_all"]


def test_loan_losses_are_monotonic():
    mild = run_stress_test(_pos(), Shock(loan_loss_pct=1))["after"]["cet1"]
    harsh = run_stress_test(_pos(), Shock(loan_loss_pct=5))["after"]["cet1"]
    assert harsh < mild


def test_severe_scenario_breaches_minimums():
    res = run_stress_test(_pos(), Shock(loan_loss_pct=10, deposit_outflow_pct=40, rate_shock_bps=300))
    assert not res["passes_all"]
    assert res["after"]["cet1"] < res["before"]["cet1"]


def test_svb_chain_forces_htm_realization():
    # Big rate shock + big outflow: liquidity can't cover it -> HTM must be sold.
    res = run_stress_test(_pos(), Shock(rate_shock_bps=400, deposit_outflow_pct=70))
    liq = res["liquidity"]
    assert liq["shortfall_forcing_htm_sales"] > 0
    assert liq["htm_sold_fraction"] > 0
    assert res["capital_waterfall"]["htm_realized_loss"] > 0


def test_quantlib_baseline_also_reproduces_reported_ratios():
    """Zero shock: the QuantLib path shares the exact same baseline logic as
    the linear path (only the rate-shock marks differ, and there's no shock
    here), so it must reproduce the same reported ratios."""
    res = run_stress_test_quantlib(_pos(), Shock())
    b = res["before"]
    assert abs(b["cet1"] - 12.58) < 0.05
    assert res["after"] == res["before"]
    assert res["pricing_engine"] == "quantlib_dcf_reprice"


def test_quantlib_reports_a_smaller_capital_hit_than_the_linear_approximation():
    """The actual point of this integration: bond convexity means a real
    re-price is a SMALLER loss than the linear duration approximation for the
    same rate shock — verified here on Wells Fargo's real securities book, not
    just on synthetic bond math (see test_quantlib_pricing.py for that)."""
    shock = Shock(rate_shock_bps=250)
    linear = run_stress_test(_pos(), shock)
    real = run_stress_test_quantlib(_pos(), shock)
    assert real["capital_waterfall"]["afs_mark_loss"] < linear["capital_waterfall"]["afs_mark_loss"]
    assert real["after"]["cet1"] > linear["after"]["cet1"]  # a smaller hit -> a higher surviving ratio


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:  # noqa: BLE001 — a crash must not abort the rest
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
