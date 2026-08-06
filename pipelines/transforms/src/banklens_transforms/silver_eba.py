"""Silver layer — normalise one raw EBA Transparency Exercise record into the SAME
canonical schema `silver.to_bank_financials` produces for FDIC, so every Gold
derivation, MCP tool and frontend panel that reads a Silver row can treat a German
or Austrian bank identically to a US one wherever the underlying data actually
supports it.

Two real corrections applied here, not left to the caller:

  1. **Currency.** EBA reports in EUR (millions); FDIC reports in USD. Comparing
     `total_assets` across the two without conversion would silently corrupt every
     percentile rank, leaderboard and cross-bank comparison in the app — a German
     bank's €95bn would out-rank a US bank's genuinely larger $150bn balance
     sheet. Every dollar amount is converted to USD at Silver time using the ECB
     reference rate landed by `sources/fx.py`, and the original EUR figure plus
     the exact rate/date used are kept alongside (`*_eur`, `fx_rate`, `fx_date`)
     so the conversion is auditable, not just applied.
  2. **Identity.** EBA banks have no FDIC CERT. `cert_number` — the app's
     pervasive int primary key (MCP tool params, frontend `cert` type, watchlist
     rows) — is a deterministic CRC32 of the bank's LEI, offset into a disjoint
     namespace (900,000,000+) so it can never collide with a real FDIC CERT
     (FDIC's own CERT numbers top out in the low hundred-thousands). The real
     LEI is preserved in a `lei` field for anyone who needs the actual identifier.

What does NOT carry over, honestly: no loan-category concentration (no
`concentration_ratio_*` — the X-Ray feature will show blanks for these banks, not
fabricated zeros), no uninsured-deposit split, no branch-level geography. EBA's
public disclosure is coarser than FDIC's Call Reports at this granularity — see
`config/sources.yaml`'s `eba_transparency.data_quality_note`.
"""

from __future__ import annotations

import zlib

_MILLIONS = 1_000_000
_CERT_OFFSET = 900_000_000
_CERT_RANGE = 90_000_000       # 900,000,000-989,999,999, disjoint from real FDIC CERTs


def synthetic_cert_number(lei: str) -> int:
    """A deterministic, collision-checked-at-land-time stand-in for `cert_number`.
    Same LEI always maps to the same int (stable across re-lands); the ~120-bank
    population makes a CRC32 collision in a 90M-wide range astronomically
    unlikely, and `eba_land_cli.py` asserts uniqueness on every run rather than
    trusting that assumption silently."""
    return _CERT_OFFSET + (zlib.crc32(lei.encode("utf-8")) % _CERT_RANGE)


_QUARTER_END_MONTH = {"03": 1, "06": 2, "09": 3, "12": 4}
_MONTH_LAST_DAY = {"03": "31", "06": "30", "09": "30", "12": "31"}


def _parse_period(period: str) -> tuple[str | None, str | None]:
    """"202506" -> ("2025-06-30", "2025Q2"). EBA's Period is YYYYMM of the
    quarter-end month, same convention as FDIC's REPDTE."""
    if not period or len(period) != 6:
        return None, None
    year, month = period[:4], period[4:6]
    q = _QUARTER_END_MONTH.get(month)
    if q is None:
        return None, None
    return f"{year}-{month}-{_MONTH_LAST_DAY[month]}", f"{year}Q{q}"


# EUR-denominated (millions) fields from eba.py's FINANCIAL_ITEMS that need
# both the millions->units scaling AND the EUR->USD conversion. Ratio fields
# (cet1_ratio, tier1_rbc_ratio, total_rbc_ratio, leverage_ratio) are percentages
# — already scaled to percent in eba.py, currency-agnostic, no conversion here.
_EUR_MILLIONS_FIELDS = {
    "total_assets": "total_assets",
    "total_liabilities": "total_liabilities",
    "total_equity": "total_equity",
    "total_risk_exposure_amount": "risk_weighted_assets",
    "interest_income": "interest_income",
    "interest_expense": "interest_expense",
    "net_fee_income": "noninterest_income",
    "net_income": "net_income",
}

_RATIO_PASSTHROUGH = ("cet1_ratio", "tier1_rbc_ratio", "total_rbc_ratio", "leverage_ratio")


def to_bank_financials_eba(raw: dict, institution: dict, *, fx_rate: float,
                           fx_date: str) -> dict:
    """`raw`: one pivoted (LEI, Period) row from `EbaSource.fetch_financials`.
    `institution`: the matching entry from `EbaSource.fetch_institutions` (name +
    country). `fx_rate`/`fx_date`: the EUR->USD rate to convert with and its
    as-of date, from `sources/fx.py` — passed in rather than fetched here so this
    stays a pure function like `silver.to_bank_financials`, no network in Silver.
    """
    lei = raw["lei"]
    filing_date, quarter = _parse_period(raw.get("period"))

    row: dict = {
        "cert_number": synthetic_cert_number(lei),
        "lei": lei,
        "name": institution.get("name"),
        "state": None,
        "country": raw.get("country") or institution.get("country"),
        "currency": "USD",
        "quarter": quarter,
        "filing_date": filing_date,
        "restated_flag": False,
        "_source": "eba.transparency",
        "fx_rate_eur_usd": fx_rate,
        "fx_rate_date": fx_date,
    }

    for src_field, canonical in _EUR_MILLIONS_FIELDS.items():
        eur_value = raw.get(src_field)
        if eur_value is None:
            row[canonical] = None
            row[f"{canonical}_eur"] = None
            continue
        eur_units = eur_value * _MILLIONS
        row[canonical] = round(eur_units * fx_rate, 2)
        row[f"{canonical}_eur"] = round(eur_units, 2)

    for field in _RATIO_PASSTHROUGH:
        row[field] = raw.get(field)

    # Fields FDIC-derived Silver rows have that EBA genuinely has no equivalent
    # for — explicit None, not omitted, so Gold/xray treat "not disclosed" the
    # same way they already treat any other missing FDIC field.
    for absent in ("total_deposits", "uninsured_deposits", "core_deposits",
                   "total_loans_gross", "total_loans_net", "cre_loans",
                   "construction_loans", "multifamily_loans", "nonfarm_nonres_loans",
                   "residential_mortgage_loans", "farmland_loans", "agricultural_loans",
                   "c_and_i_loans", "consumer_loans", "brokered_deposits",
                   "noncurrent_loans", "allowance_for_credit_losses"):
        row.setdefault(absent, None)

    return row
