"""Pin the Silver/Gold definitions against real Wells Fargo (CERT 3511) figures.

Fixtures are actual FDIC values probed live from the API. When these transforms are
reimplemented (dbt/PySpark/Rust), they must reproduce these numbers exactly. A key
test also checks that our independently COMPUTED ratios match FDIC's own REPORTED
ratios (LNLSDEPR, EQV) — proof the math is right rather than merely self-consistent.

Run: ``python pipelines/transforms/tests/test_gold_metrics.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.gold import (  # noqa: E402
    concentration_ratios, cre_to_equity_pct, derive_gold, equity_to_assets_pct,
    gold_features, growth_rate_nyr, loan_to_deposit_pct, max_concentration,
    uninsured_deposit_pct,
)
from banklens_transforms.silver import to_bank_financials  # noqa: E402

WF_2026Q1 = {
    "CERT": 3511, "REPDTE": 20260331, "NAMEFULL": "WELLS FARGO BANK, NATIONAL ASSOCIATION", "STALP": "SD",
    "ASSET": 1852239000, "DEP": 1516982000, "DEPDOM": 1510143000, "DEPINS": 839527000,
    "DEPUNINS": 723812000, "COREDEP": 1367054000,
    "LNLSGR": 985437000, "LNLSNET": 971566000, "EQ": 173016000,
    "LNRE": 361336000, "LNRECONS": 13459000, "LNREMULT": 26383000, "LNRENRES": 83180000,
    "LNRELOC": 10018000, "LNRERES": 233117000, "LNREAG": 793000, "LNAG": 3285000,
    "LNCI": 198483000, "LNCON": 116977000, "LNCRCD": 57277000, "LNAUTO": 53794000, "LNCONOTH": 4508000,
    "SC": 420321000, "SCAF": 216209000,
    "IDT1CER": 12.583643423831154, "IDT1RWAJR": 12.583643423831154,
    "RBCRWAJ": 14.055044819622672, "RBC1AAJ": 8.40035032428292,
    "EQV": 9.340911189106805, "LNLSDEPR": 64.0459807697125,
}
WF_2025Q4 = {
    "CERT": 3511, "REPDTE": 20251231, "NAMEFULL": "WELLS FARGO BANK, NATIONAL ASSOCIATION",
    "STALP": "SD", "ASSET": 1822693000, "DEP": 1483390000, "DEPUNINS": 705000000,
}


def approx(a, b, tol=0.05):
    return a is not None and abs(a - b) <= tol


def test_silver_units_ratios_and_derivations():
    row = to_bank_financials(WF_2026Q1)
    assert row["total_assets"] == 1_852_239_000 * 1000        # thousands -> USD
    assert row["quarter"] == "2026Q1" and row["filing_date"] == "2026-03-31"
    assert row["uninsured_deposits"] == 723_812_000 * 1000    # reported DEPUNINS, not DEP-DEPINS
    assert approx(row["cet1_ratio"], 12.5836, 0.001)          # ratio fields unscaled
    assert row["cre_loans"] == (13_459_000 + 26_383_000 + 83_180_000) * 1000
    assert row["securities_htm"] == (420_321_000 - 216_209_000) * 1000


def test_us_rows_are_tagged_us_and_usd():
    """The country/currency tags EU support depends on — a US row must never be
    left untagged, or it can't be told apart from an EBA-sourced row downstream."""
    row = to_bank_financials(WF_2026Q1)
    assert row["country"] == "US"
    assert row["currency"] == "USD"


def test_computed_ratios_match_fdic_reported():
    """Our independent math must agree with FDIC's own reported ratios."""
    s = to_bank_financials(WF_2026Q1)
    assert approx(loan_to_deposit_pct(s), s["loan_to_deposit_ratio_reported"], 0.1)
    assert approx(equity_to_assets_pct(s), s["equity_to_assets_ratio_reported"], 0.01)
    assert approx(uninsured_deposit_pct(s), 47.71)


def test_concentration_ratios_are_the_disjoint_leaf_set():
    """`concentration_ratios` returns only MUTUALLY DISJOINT categories, so the
    ratios describe one loan book and `max_concentration` can't rank a parent
    against its own child."""
    c = concentration_ratios(to_bank_financials(WF_2026Q1))
    assert approx(c["concentration_ratio_c_and_i"], 20.14)
    assert "concentration_ratio_cre" not in c          # roll-up, reported elsewhere
    assert "concentration_ratio_heloc" not in c        # subset of residential_mortgage
    label, val = max_concentration(c)
    assert label == "residential_mortgage" and approx(val, 23.66)


def test_disjoint_leaves_do_not_exceed_the_loan_book():
    """Guard against the defect this taxonomy exists to fix: an earlier 12-category
    draft double-counted parents and children and summed to 129.9% on this bank."""
    s = to_bank_financials(WF_2026Q1)
    total = sum(v for v in concentration_ratios(s).values() if v is not None)
    assert total <= 101.0, f"disjoint leaves sum to {total:.1f}% — categories overlap"


def test_rollups_reported_but_never_ranked():
    g = gold_features(to_bank_financials(WF_2026Q1))
    assert approx(g["concentration_ratio_cre"], 12.48)
    assert g["max_loan_concentration_category"] == "residential_mortgage"
    assert approx(cre_to_equity_pct(to_bank_financials(WF_2026Q1)), 71.10, 0.1)


def test_qoq_delta_direction():
    gold = derive_gold([to_bank_financials(WF_2026Q1), to_bank_financials(WF_2025Q4)])
    assert gold[0]["qoq_total_deposits"]["abs"] > 0    # deposits grew Q4'25 -> Q1'26
    assert gold[1]["qoq_total_deposits"] is None       # no older quarter


def test_growth_rate_needs_an_exact_anchor_quarter():
    """No row landed exactly 12 quarters back -> None, never an interpolated guess."""
    rows = [to_bank_financials(WF_2026Q1), to_bank_financials(WF_2025Q4)]
    assert growth_rate_nyr(rows, 3, "total_assets") is None


def test_growth_rate_computes_cagr_when_anchor_present():
    anchor = dict(WF_2026Q1)
    anchor["REPDTE"] = 20230331          # exactly 12 quarters before 2026Q1
    anchor["ASSET"] = 1_000_000_000       # -> $1.0T vs current $1.852239T
    rate = growth_rate_nyr([to_bank_financials(WF_2026Q1), to_bank_financials(anchor)],
                           3, "total_assets")
    assert approx(rate, 22.85, 0.05)      # (1.852239)^(1/3) - 1


def test_growth_rate_none_on_nonpositive_anchor():
    anchor = dict(WF_2026Q1); anchor["REPDTE"] = 20230331; anchor["ASSET"] = 0
    rows = [to_bank_financials(WF_2026Q1), to_bank_financials(anchor)]
    assert growth_rate_nyr(rows, 3, "total_assets") is None


def test_minus_one_sentinel_treated_as_missing_not_minus_1000():
    """Regression for a REAL data quirk found live in pre-2008 FDIC data (IndyMac,
    CERT 29730): SCHA reported as -1, FDIC's 'not reported' sentinel, not -$1,000."""
    raw = dict(WF_2026Q1); raw["SCHA"] = -1
    assert to_bank_financials(raw)["securities_htm_reported"] is None
    # ...but a genuinely negative equity (an insolvent bank) must NOT be discarded —
    # catching failing banks is this platform's whole point.
    raw2 = dict(WF_2026Q1); raw2["EQ"] = -500
    assert to_bank_financials(raw2)["total_equity"] == -500_000


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
