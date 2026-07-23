"""Pin the Gold metric definitions against real Wells Fargo (CERT 3511) figures.

These fixtures are actual FDIC values (2026-03-31, in thousands of USD). When the
transforms are reimplemented in dbt/PySpark, they must reproduce these exactly.
Run: ``python -m pytest pipelines/transforms/tests`` (or the stdlib runner below).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.gold import (  # noqa: E402
    derive_gold, equity_to_assets_pct, loan_to_deposit_pct, uninsured_deposit_pct,
)
from banklens_transforms.silver import to_bank_financials  # noqa: E402

# Raw FDIC record shape (thousands of USD), verified live.
WF_2026Q1 = {
    "CERT": 3511, "REPDTE": 20260331, "NAMEFULL": "WELLS FARGO BANK, NATIONAL ASSOCIATION",
    "STALP": "SD", "ASSET": 1852239000, "DEP": 1516982000, "DEPDOM": 1510143000,
    "DEPINS": 839527000, "LNLSGR": 985437000, "LNLSNET": 971566000, "EQ": 173016000,
}
WF_2025Q4 = {
    "CERT": 3511, "REPDTE": 20251231, "NAMEFULL": "WELLS FARGO BANK, NATIONAL ASSOCIATION",
    "STALP": "SD", "ASSET": 1822693000, "DEP": 1483390000, "DEPDOM": 1476890000,
    "DEPINS": 821222000, "LNLSGR": 953077000, "LNLSNET": 939271000, "EQ": 173751000,
}


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


def test_silver_units_and_dates():
    row = to_bank_financials(WF_2026Q1)
    # thousands -> actual USD
    assert row["total_assets"] == 1_852_239_000 * 1000
    assert row["quarter"] == "2026Q1"
    assert row["filing_date"] == "2026-03-31"
    # uninsured = total - insured
    assert row["uninsured_deposits"] == (1_516_982_000 - 839_527_000) * 1000


def test_uninsured_pct():
    row = to_bank_financials(WF_2026Q1)
    # (1,516,982 - 839,527) / 1,516,982 = 44.66%
    assert approx(uninsured_deposit_pct(row), 44.66, tol=0.05)


def test_loan_to_deposit_pct():
    row = to_bank_financials(WF_2026Q1)
    # 971,566 / 1,516,982 = 64.04%
    assert approx(loan_to_deposit_pct(row), 64.04, tol=0.05)


def test_equity_to_assets_pct():
    row = to_bank_financials(WF_2026Q1)
    # 173,016 / 1,852,239 = 9.34%
    assert approx(equity_to_assets_pct(row), 9.34, tol=0.05)


def test_qoq_delta_direction():
    rows = [to_bank_financials(WF_2026Q1), to_bank_financials(WF_2025Q4)]
    gold = derive_gold(rows)
    # deposits grew Q4'25 -> Q1'26
    assert gold[0]["qoq_total_deposits"]["abs"] > 0
    assert gold[1]["qoq_total_deposits"] is None  # no older quarter to compare


# --- zero-dependency runner (works without pytest) -----------------------
if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}: {e}")
    print(f"\n{'OK' if failures == 0 else failures} " +
          ("- all tests passed" if failures == 0 else "test(s) failed"))
    sys.exit(1 if failures else 0)
