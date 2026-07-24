"""Pin the Silver/Gold definitions against real Wells Fargo (CERT 3511) figures.

Fixtures are actual FDIC values for 2026-03-31 (thousands of USD / percentages),
probed live from the API. When the transforms are reimplemented in dbt/PySpark,
they must reproduce these exactly. A key test also checks that our independently
COMPUTED ratios match FDIC's own REPORTED ratios (LNLSDEPR, EQV) — proof the math
is right.

Run: ``python pipelines/transforms/tests/test_gold_metrics.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.gold import (  # noqa: E402
    concentration_ratios, cre_to_equity_pct, derive_gold, equity_to_assets_pct,
    loan_to_deposit_pct, max_concentration, uninsured_deposit_pct,
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
WF_2025Q4 = {  # partial — only fields needed for the QoQ baseline
    "CERT": 3511, "REPDTE": 20251231, "NAMEFULL": "WELLS FARGO BANK, NATIONAL ASSOCIATION",
    "STALP": "SD", "ASSET": 1822693000, "DEP": 1483390000, "DEPUNINS": 705000000,
}


def approx(a, b, tol=0.05):
    return a is not None and abs(a - b) <= tol


def test_silver_units_ratios_and_derivations():
    row = to_bank_financials(WF_2026Q1)
    assert row["total_assets"] == 1_852_239_000 * 1000        # thousands -> USD
    assert row["quarter"] == "2026Q1" and row["filing_date"] == "2026-03-31"
    # uninsured now uses reported DEPUNINS (not DEP - DEPINS)
    assert row["uninsured_deposits"] == 723_812_000 * 1000
    # ratio fields passed through unscaled
    assert approx(row["cet1_ratio"], 12.5836, 0.001)
    assert approx(row["leverage_ratio"], 8.4004, 0.001)
    # CRE aggregate = construction + multifamily + nonfarm-nonres
    assert row["cre_loans"] == (13_459_000 + 26_383_000 + 83_180_000) * 1000
    # HTM derived = total - AFS
    assert row["securities_htm"] == (420_321_000 - 216_209_000) * 1000


def test_uninsured_pct_uses_reported():
    # 723,812 / 1,516,982 = 47.71%
    assert approx(uninsured_deposit_pct(to_bank_financials(WF_2026Q1)), 47.71)


def test_computed_ratios_match_fdic_reported():
    """Our independent math must agree with FDIC's own reported ratios."""
    s = to_bank_financials(WF_2026Q1)
    assert approx(loan_to_deposit_pct(s), s["loan_to_deposit_ratio_reported"], 0.1)   # vs LNLSDEPR
    assert approx(equity_to_assets_pct(s), s["equity_to_assets_ratio_reported"], 0.01)  # vs EQV


def test_concentration_ratios():
    s = to_bank_financials(WF_2026Q1)
    c = concentration_ratios(s)
    assert approx(c["concentration_ratio_cre"], 12.48)
    assert approx(c["concentration_ratio_c_and_i"], 20.14)
    assert approx(c["concentration_ratio_residential_mortgage"], 23.66)
    # residential mortgage is Wells Fargo's most concentrated category
    label, val = max_concentration(c)
    assert label == "residential_mortgage" and approx(val, 23.66)


def test_cre_to_equity():
    # 123,022 / 173,016 = 71.10%
    assert approx(cre_to_equity_pct(to_bank_financials(WF_2026Q1)), 71.10, 0.1)


def test_qoq_delta_direction():
    rows = [to_bank_financials(WF_2026Q1), to_bank_financials(WF_2025Q4)]
    gold = derive_gold(rows)
    assert gold[0]["qoq_total_deposits"]["abs"] > 0     # deposits grew Q4'25 -> Q1'26
    assert gold[1]["qoq_total_deposits"] is None        # no older quarter


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
