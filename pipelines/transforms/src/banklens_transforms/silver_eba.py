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

What does NOT carry over, honestly: no US-style loan-CATEGORY concentration (no
`concentration_ratio_*` by CRE/C&I/consumer/etc — the X-Ray feature will show
blanks for these banks, not fabricated zeros), no uninsured-deposit split, no
branch-level geography. EBA's public disclosure is coarser than FDIC's Call
Reports at this granularity — see `config/sources.yaml`'s
`eba_transparency.data_quality_note`.

What DOES carry over as of the `tr_cre.csv` credit-risk cube being parsed
(`banklens_ingestion.sources.eba.EbaSource.fetch_credit_risk`): a supervisory
performing/non-performing split (`npl_ratio_pct_supervisory`) and a
sector-concentration proxy (`sector_concentration_hhi`,
`sector_concentration_top_sector`/`_top_pct`) — see the credit-risk block below.
"""

from __future__ import annotations

import zlib

from .footprint import herfindahl

# NACE Rev.2 section labels for codes 1-19, in the exact order the EBA's own
# "NACE" mapped-template sheet lists them (its rows 11-29) — this IS the EBA's
# published mapping for `tr_cre.csv`'s NACE_codes dimension, not an external
# NACE table (see `banklens_ingestion.sources.eba`'s module docstring for how
# it was verified; the raw numeric codes are decoded there, the human-readable
# labels live here at the Silver/decode layer).
NACE_SECTORS: dict[int, str] = {
    1: "A Agriculture, forestry and fishing",
    2: "B Mining and quarrying",
    3: "C Manufacturing",
    4: "D Electricity, gas, steam and air conditioning supply",
    5: "E Water supply",
    6: "F Construction",
    7: "G Wholesale and retail trade",
    8: "H Transport and storage",
    9: "I Accommodation and food service activities",
    10: "J Information and communication",
    11: "K Financial and insurance activities",
    12: "L Real estate activities",
    13: "M Professional, scientific and technical activities",
    14: "N Administrative and support service activities",
    15: "O Public administration and defence, compulsory social security",
    16: "P Education",
    17: "Q Human health services and social work activities",
    18: "R Arts, entertainment and recreation",
    19: "S Other services",
}

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
    "cash_and_balances": "cash_and_balances",
    # IFRS -> US-GAAP analogues, an approximation stated plainly rather than implied:
    # "fair value through OCI" is the closest IFRS category to US AFS, and
    # "amortised cost" to US HTM. Not identical accounting definitions, but the same
    # economic distinction (marked-to-market vs. carried at cost), which is exactly
    # what the rate-shock leg of the stress test keys off.
    "securities_afs": "securities_afs",
    "securities_htm": "securities_htm",
}

# Summed from their IFRS-9 stage components in the connector, then combined here.
_LOAN_PARTS = ("loans_amortised_cost", "loans_fvoci")
_NPL_PARTS = ("npl_loans_amortised_cost", "npl_loans_fvoci")
_ALLOWANCE_PARTS = ("allowance_loans_amortised_cost", "allowance_loans_fvoci")


def _sum_parts(raw: dict, parts) -> float | None:
    """Sum present components; None only when every component is missing (so a bank
    reporting only one of the two loan categories still gets a real total)."""
    vals = [raw.get(p) for p in parts]
    present = [v for v in vals if v is not None]
    return sum(present) if present else None

_RATIO_PASSTHROUGH = ("cet1_ratio", "tier1_rbc_ratio", "total_rbc_ratio", "leverage_ratio")


def to_bank_financials_eba(raw: dict, institution: dict, *, fx_rate: float,
                           fx_date: str, credit_risk: dict | None = None) -> dict:
    """`raw`: one pivoted (LEI, Period) row from `EbaSource.fetch_financials`.
    `institution`: the matching entry from `EbaSource.fetch_institutions` (name +
    country). `fx_rate`/`fx_date`: the EUR->USD rate to convert with and its
    as-of date, from `sources/fx.py` — passed in rather than fetched here so this
    stays a pure function like `silver.to_bank_financials`, no network in Silver.
    `credit_risk`: the matching (LEI, Period) row from
    `EbaSource.fetch_credit_risk`, or None if the credit-risk cube hasn't been
    landed (or has no row for this bank-period) — every field it would set stays
    explicitly None, same "disclose, don't fabricate" contract as the deposit
    fields below.
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

    # ---- loans, non-performing, allowance (summed from IFRS-9 stage components) ----
    def _usd(eur_millions):
        return None if eur_millions is None else round(eur_millions * _MILLIONS * fx_rate, 2)

    gross_loans = _sum_parts(raw, _LOAN_PARTS)
    npl = _sum_parts(raw, _NPL_PARTS)
    # EBA reports accumulated impairment as a NEGATIVE number (verified live:
    # Deutsche Bank -5,736). FDIC's LNATRES is positive, and every downstream
    # consumer (allowance_coverage_pct, texas_ratio_pct) assumes positive — so
    # normalise the sign here rather than making each consumer special-case it.
    allowance = _sum_parts(raw, _ALLOWANCE_PARTS)
    allowance = abs(allowance) if allowance is not None else None

    row["total_loans_gross"] = _usd(gross_loans)
    row["noncurrent_loans"] = _usd(npl)
    row["allowance_for_credit_losses"] = _usd(allowance)
    row["total_loans_net"] = _usd(
        gross_loans - allowance if gross_loans is not None and allowance is not None else None)

    # ---- capital DOLLARS, derived from the reported ratios ----
    # EBA publishes capital ratios but not the capital dollar amounts FDIC gives
    # directly (RBCT1J/RBC). Since ratio = capital / RWA by definition, and RWA is
    # reported, the dollars are recoverable exactly: capital = ratio x RWA. This is
    # what makes the capital-shock leg of the stress test possible for EU banks at
    # all — without it there is no starting capital to erode.
    rwa = row.get("risk_weighted_assets")
    for ratio_field, capital_field in (("tier1_rbc_ratio", "tier1_capital"),
                                       ("total_rbc_ratio", "total_capital")):
        ratio = row.get(ratio_field)
        row[capital_field] = (round(ratio / 100.0 * rwa, 2)
                              if ratio is not None and rwa else None)

    # ---- credit risk, from tr_cre.csv (B2: the two Item codes sources/eba.py
    # decodes — see its module docstring for how they were verified) ----
    # `npl_ratio_pct` (below) already exists via IFRS-9 Stage 3 loans from
    # tr_oth.csv — an accounting-impairment-based proxy. This is a SEPARATE,
    # additional figure from the credit-risk cube's own supervisory
    # performing/non-performing split, which is the closer analogue to FDIC's
    # delinquency-based "noncurrent loans" definition. Both are kept, distinctly
    # named, rather than one silently overwriting the other.
    row["npl_ratio_pct_supervisory"] = None
    row["sector_concentration_hhi"] = None
    row["sector_concentration_top_sector"] = None
    row["sector_concentration_top_pct"] = None
    if credit_risk is not None:
        total = credit_risk.get("npl_gross_carrying_eur_m")
        nonperforming = credit_risk.get("npl_nonperforming_eur_m")
        if total and nonperforming is not None:
            row["npl_ratio_pct_supervisory"] = round(nonperforming / total * 100, 4)

        nace = credit_risk.get("nace_gross_carrying_eur_m")
        if nace:
            sector_total = sum(nace.values())
            if sector_total > 0:
                shares_pct = [v / sector_total * 100 for v in nace.values()]
                row["sector_concentration_hhi"] = herfindahl(shares_pct)
                top_code, top_amount = max(nace.items(), key=lambda kv: kv[1])
                row["sector_concentration_top_sector"] = NACE_SECTORS.get(int(top_code))
                row["sector_concentration_top_pct"] = round(top_amount / sector_total * 100, 2)

    # Fields FDIC-derived Silver rows have that EBA genuinely has no equivalent
    # for — explicit None, not omitted, so Gold/xray treat "not disclosed" the
    # same way they already treat any other missing FDIC field. Deposits are the
    # consequential absence: EBA discloses no clean deposit total (only a combined
    # amortised-cost liabilities figure that also contains issued debt), so the
    # deposit-outflow leg of the stress test cannot run for these banks.
    for absent in ("total_deposits", "uninsured_deposits", "core_deposits",
                   "cre_loans", "construction_loans", "multifamily_loans",
                   "nonfarm_nonres_loans", "residential_mortgage_loans",
                   "farmland_loans", "agricultural_loans", "c_and_i_loans",
                   "consumer_loans", "brokered_deposits", "average_assets"):
        row.setdefault(absent, None)

    return row
