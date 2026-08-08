"""EU (EBA) ingestion + Silver mapping. Covers the two real bugs found building this:
IFRS-9 stage-dimensioned items being silently overwritten instead of summed, and
capital ratios arriving as raw fractions rather than percentages.

Run: ``python pipelines/transforms/tests/test_silver_eba.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pipelines" / "transforms" / "src"))
sys.path.insert(0, str(ROOT / "pipelines" / "ingestion" / "src"))

from banklens_ingestion.sources.eba import EbaSource  # noqa: E402
from banklens_transforms.silver_eba import (  # noqa: E402
    synthetic_cert_number, to_bank_financials_eba,
)

# Shaped exactly like a real pivoted row from EbaSource.fetch_financials().
DEKA_RAW = {
    "lei": "0W2PZJM8XOY22M4GG883", "period": "202506", "country": "DE",
    "total_assets": 94984.87649245, "total_liabilities": 87461.74377662,
    "total_equity": 7523.13271583, "total_risk_exposure_amount": 30769.68617154,
    "cet1_ratio": 18.418734934683, "tier1_rbc_ratio": 20.364156141331,
    "total_rbc_ratio": 22.925928027679, "leverage_ratio": 7.591355060250,
    "interest_income": 2081.65271325, "interest_expense": 1892.84812659,
    "net_fee_income": 1242.90099423, "net_income": 568.51583746,
    "cash_and_balances": 5000.0,
    "loans_amortised_cost": 40000.0, "loans_fvoci": 1000.0,
    "npl_loans_amortised_cost": 900.0, "npl_loans_fvoci": 100.0,
    "allowance_loans_amortised_cost": -400.0, "allowance_loans_fvoci": -100.0,
    "securities_afs": 3000.0, "securities_htm": 4000.0,
}
DEKA_INST = {"lei": "0W2PZJM8XOY22M4GG883", "name": "DekaBank Deutsche Girozentrale",
             "country": "DE", "country_desc": "Germany"}
FX, FX_DATE = 1.1554, "2026-08-05"


def approx(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def _row():
    return to_bank_financials_eba(DEKA_RAW, DEKA_INST, fx_rate=FX, fx_date=FX_DATE)


_CSV_HEADER = ('"LEI_Code","NSA","Period","Item","Label","ASSETS_FV","ASSETS_Stages",'
               '"Exposure","Financial_instruments","Amount","Sheet"\n')


def _csv_row(item, amount, stage="0"):
    return (f'"LEI1","DE","202506","{item}","Label","0","{stage}","0","0",'
            f'"{amount}","Assets"\n')


def test_stage_dimensioned_items_are_summed_not_overwritten():
    """THE bug this file exists for. Items 2521016-2521019 arrive as three rows per
    bank (IFRS 9 stages 1/2/3). A last-write-wins pivot keeps whichever stage the CSV
    ends on — verified live, that made Deutsche Bank's EUR 614bn loan book read as
    EUR 14bn (its stage-3 slice alone), an absurd figure for a EUR 1.4tn bank."""
    text = _CSV_HEADER + "".join([
        _csv_row("2521019", 542048.99, stage="1"),
        _csv_row("2521019", 58211.30, stage="2"),
        _csv_row("2521019", 14125.21, stage="3"),
    ])
    rows = EbaSource._pivot_financials_csv(text)
    assert len(rows) == 1
    assert approx(rows[0]["loans_amortised_cost"], 614385.50, tol=0.1)


def test_stage_3_is_captured_separately_as_non_performing():
    """Stage 3 == credit-impaired under IFRS 9 — the only route to a real NPL ratio
    for EU banks, since EBA publishes no direct non-performing figure."""
    text = _CSV_HEADER + "".join([
        _csv_row("2521019", 900.0, stage="1"),
        _csv_row("2521019", 50.0, stage="2"),
        _csv_row("2521019", 50.0, stage="3"),
    ])
    row = EbaSource._pivot_financials_csv(text)[0]
    assert approx(row["loans_amortised_cost"], 1000.0)   # all stages
    assert approx(row["npl_loans_amortised_cost"], 50.0)  # stage 3 only


def test_scalar_item_appearing_twice_raises_rather_than_silently_dropping():
    """If a future EBA release adds a dimension to a currently-scalar item, silently
    keeping one slice would under-report a balance sheet. Fail the landing instead."""
    text = _CSV_HEADER + _csv_row("2521010", 100.0) + _csv_row("2521010", 200.0)
    try:
        EbaSource._pivot_financials_csv(text)
        raise AssertionError("expected ValueError on a duplicated scalar item")
    except ValueError as e:
        assert "2521010" in str(e)


def test_capital_ratios_scaled_from_fractions_to_percent():
    """EBA reports ratios as raw fractions (0.1841 = 18.41%), unlike FDIC's
    already-percentage IDT1CER. Unscaled, an 18% CET1 would read as 0.18%."""
    text = _CSV_HEADER + _csv_row("2520140", 0.184187)
    assert approx(EbaSource._pivot_financials_csv(text)[0]["cet1_ratio"], 18.4187, 1e-6)


def test_eur_millions_converted_to_usd_units():
    row = _row()
    assert approx(row["total_assets"], 94984.87649245 * 1_000_000 * FX, tol=1.0)
    assert approx(row["total_assets_eur"], 94984.87649245 * 1_000_000, tol=1.0)
    assert row["fx_rate_eur_usd"] == FX and row["fx_rate_date"] == FX_DATE


def test_ratios_pass_through_without_fx_conversion():
    row = _row()
    assert approx(row["cet1_ratio"], 18.418734934683, tol=1e-6)
    assert approx(row["leverage_ratio"], 7.591355060250, tol=1e-6)


def test_capital_dollars_derived_from_ratio_times_rwa():
    """EBA gives ratios but not capital dollars; ratio x RWA recovers them exactly.
    Without this there is no starting capital for the stress test to erode."""
    row = _row()
    rwa = row["risk_weighted_assets"]
    assert approx(row["tier1_capital"], 20.364156141331 / 100 * rwa, tol=1.0)
    assert approx(row["total_capital"], 22.925928027679 / 100 * rwa, tol=1.0)


def test_loans_npl_and_allowance_combined_with_sign_normalised():
    """EBA reports accumulated impairment NEGATIVE (verified live: DB -5,736), while
    FDIC's LNATRES is positive and every downstream consumer assumes positive."""
    row = _row()
    assert approx(row["total_loans_gross"], 41000.0 * 1_000_000 * FX, tol=1.0)
    assert approx(row["noncurrent_loans"], 1000.0 * 1_000_000 * FX, tol=1.0)
    assert row["allowance_for_credit_losses"] > 0          # sign normalised
    assert approx(row["allowance_for_credit_losses"], 500.0 * 1_000_000 * FX, tol=1.0)
    assert row["total_loans_net"] < row["total_loans_gross"]


def test_synthetic_cert_is_deterministic_and_cannot_collide_with_fdic():
    a = synthetic_cert_number("0W2PZJM8XOY22M4GG883")
    b = synthetic_cert_number("0W2PZJM8XOY22M4GG883")
    c = synthetic_cert_number("7LTWFZYICNSX8D621K86")
    assert a == b and a != c
    # FDIC CERTs top out in the low hundred-thousands; this namespace starts at 900M.
    assert 900_000_000 <= a < 990_000_000 and 900_000_000 <= c < 990_000_000


def test_deposits_stay_absent_rather_than_being_faked():
    """EBA discloses no clean deposit total. Inventing one would silently corrupt
    every liquidity/run calculation downstream."""
    row = _row()
    assert "total_deposits" in row and row["total_deposits"] is None
    assert row["uninsured_deposits"] is None
    assert row["country"] == "DE" and row["state"] is None and row["currency"] == "USD"


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
