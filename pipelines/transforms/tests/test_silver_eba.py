"""Pin the EBA Silver mapping: currency conversion (EUR millions -> USD units)
and the synthetic cert_number namespace, against a realistic fixture shaped like
`EbaSource.fetch_financials()`'s real output (see sources/eba.py's live
verification for where these numbers came from).

Run: ``python pipelines/transforms/tests/test_silver_eba.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.silver_eba import (  # noqa: E402
    synthetic_cert_number, to_bank_financials_eba,
)

DEKABANK_RAW = {
    "lei": "0W2PZJM8XOY22M4GG883", "period": "202506", "country": "DE",
    "total_assets": 94984.87649245, "total_liabilities": 87461.74377662,
    "total_equity": 7523.13271583, "total_risk_exposure_amount": 30769.68617154,
    "cet1_ratio": 18.418734934683, "tier1_rbc_ratio": 20.364156141331,
    "total_rbc_ratio": 22.925928027679, "leverage_ratio": 7.591355060250,
    "interest_income": 2081.65271325, "interest_expense": 1892.84812659,
    "net_fee_income": 1242.90099423, "net_income": 568.51583746,
}
DEKABANK_INSTITUTION = {"lei": "0W2PZJM8XOY22M4GG883", "name": "DekaBank Deutsche Girozentrale",
                        "country": "DE", "country_desc": "Germany"}


def approx(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def test_synthetic_cert_number_is_deterministic_and_namespaced():
    a = synthetic_cert_number("0W2PZJM8XOY22M4GG883")
    b = synthetic_cert_number("0W2PZJM8XOY22M4GG883")
    c = synthetic_cert_number("7LTWFZYICNSX8D621K86")   # Deutsche Bank's LEI
    assert a == b
    assert a != c
    assert 900_000_000 <= a < 990_000_000
    assert 900_000_000 <= c < 990_000_000


def test_eur_to_usd_conversion_uses_millions_then_rate():
    row = to_bank_financials_eba(DEKABANK_RAW, DEKABANK_INSTITUTION,
                                 fx_rate=1.1554, fx_date="2026-08-05")
    # 94984.87649245 million EUR * 1e6 * 1.1554 = 109,758,275,... USD
    expected_usd = 94984.87649245 * 1_000_000 * 1.1554
    assert approx(row["total_assets"], expected_usd, tol=1.0)
    assert approx(row["total_assets_eur"], 94984.87649245 * 1_000_000, tol=1.0)
    assert row["fx_rate_eur_usd"] == 1.1554
    assert row["fx_rate_date"] == "2026-08-05"


def test_ratio_fields_pass_through_without_fx_conversion():
    row = to_bank_financials_eba(DEKABANK_RAW, DEKABANK_INSTITUTION,
                                 fx_rate=1.1554, fx_date="2026-08-05")
    assert approx(row["cet1_ratio"], 18.418734934683, tol=1e-6)
    assert approx(row["leverage_ratio"], 7.591355060250, tol=1e-6)


def test_period_parses_to_quarter_end_date():
    row = to_bank_financials_eba(DEKABANK_RAW, DEKABANK_INSTITUTION,
                                 fx_rate=1.1554, fx_date="2026-08-05")
    assert row["quarter"] == "2025Q2"
    assert row["filing_date"] == "2025-06-30"


def test_identity_and_currency_fields():
    row = to_bank_financials_eba(DEKABANK_RAW, DEKABANK_INSTITUTION,
                                 fx_rate=1.1554, fx_date="2026-08-05")
    assert row["lei"] == "0W2PZJM8XOY22M4GG883"
    assert row["name"] == "DekaBank Deutsche Girozentrale"
    assert row["country"] == "DE"
    assert row["state"] is None
    assert row["currency"] == "USD"           # converted, not left in EUR
    assert row["_source"] == "eba.transparency"


def test_fdic_only_fields_are_explicit_none_not_omitted():
    row = to_bank_financials_eba(DEKABANK_RAW, DEKABANK_INSTITUTION,
                                 fx_rate=1.1554, fx_date="2026-08-05")
    assert "total_deposits" in row and row["total_deposits"] is None
    assert "cre_loans" in row and row["cre_loans"] is None


def test_missing_source_field_yields_none_not_a_crash():
    partial = dict(DEKABANK_RAW)
    del partial["net_income"]
    row = to_bank_financials_eba(partial, DEKABANK_INSTITUTION,
                                 fx_rate=1.1554, fx_date="2026-08-05")
    assert row["net_income"] is None
    assert row["net_income_eur"] is None


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
