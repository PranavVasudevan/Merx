"""Silver layer — normalise one raw FDIC record into the canonical schema.

Cleaning steps:
  * map FDIC codes -> human canonical column names
  * convert DOLLAR fields from **thousands of USD** to actual USD
  * pass RATIO fields (already percentages) through unchanged  <-- do NOT rescale
  * parse REPDTE (YYYYMMDD int) -> ISO date + quarter label
  * flag missing values explicitly (None), never silently zero-fill
  * aggregate CRE (commercial real estate) from its RC-C components

Two important corrections learned from the live FDIC data:
  1. Uninsured deposits are taken from FDIC's reported ``DEPUNINS`` (an official
     estimate) rather than derived as ``DEP - DEPINS``. The insured/uninsured
     estimates use a different base, so the reported figure is authoritative.
  2. Capital ratios (CET1/Tier1/Total/Leverage) come straight from FDIC — they are
     already percentages and must not be multiplied by 1000.
"""

from __future__ import annotations

from typing import TypedDict

_THOUSANDS = 1000

# raw FDIC code -> canonical column, for DOLLAR amounts (reported in thousands)
_DOLLAR_FIELDS = {
    "ASSET": "total_assets",
    "DEP": "total_deposits",
    "DEPDOM": "domestic_deposits",
    "DEPINS": "insured_deposits",
    "DEPUNINS": "uninsured_deposits",       # FDIC's reported estimate
    "COREDEP": "core_deposits",
    "LNLSGR": "total_loans_gross",
    "LNLSNET": "total_loans_net",
    "EQ": "total_equity",
    # loan composition
    "LNRE": "real_estate_loans",
    "LNRECONS": "construction_loans",
    "LNREMULT": "multifamily_loans",
    "LNRENRES": "nonfarm_nonres_loans",     # nonfarm nonresidential = CRE core
    "LNRELOC": "heloc_loans",
    "LNRERES": "residential_mortgage_loans",
    "LNREAG": "farmland_loans",
    "LNAG": "agricultural_loans",
    "LNCI": "c_and_i_loans",
    "LNCON": "consumer_loans",
    "LNCRCD": "credit_card_loans",
    "LNAUTO": "auto_loans",
    "LNCONOTH": "consumer_other_loans",
    # securities
    "SC": "securities_total",
    "SCAF": "securities_afs",
    "SCHA": "securities_htm_reported",   # HTM amortized cost (direct)
    # balance-sheet dollars for the stress simulator (Feature 16)
    "RBCT1J": "tier1_capital",
    "RBC": "total_capital",
    "RWAJT": "risk_weighted_assets",
    "ASSET5": "average_assets",
    "CHBAL": "cash_and_balances",
    # income statement
    "NETINC": "net_income",
    "INTINC": "interest_income",
    "EINTEXP": "interest_expense",
    "NONII": "noninterest_income",
    "NONIX": "noninterest_expense",
    "ELNATR": "provision_for_credit_losses",
    # asset quality. NOTE P3ASSET/P9ASSET are ASSET-level past-due, not loan-level —
    # named accordingly so nobody divides them by a loan denominator by accident.
    "NCLNLS": "noncurrent_loans",
    "NTLNLS": "net_charge_offs",
    # C6 — net charge-offs by the same 8-leaf disjoint category set
    # gold.LOAN_CATEGORIES uses for concentration ratios.
    "NTRECONS": "net_charge_offs_construction",
    "NTREMULT": "net_charge_offs_multifamily",
    "NTRENRES": "net_charge_offs_nonfarm_nonres",
    "NTRERES": "net_charge_offs_residential_mortgage",
    "NTREAG": "net_charge_offs_farmland",
    "NTAG": "net_charge_offs_agricultural",
    "NTCI": "net_charge_offs_c_and_i",
    "NTCON": "net_charge_offs_consumer",
    "LNATRES": "allowance_for_credit_losses",
    "P3ASSET": "assets_past_due_30_89",
    "P9ASSET": "assets_past_due_90_plus",
    "ORE": "other_real_estate_owned",
    "INTAN": "intangible_assets",
    # funding composition
    "BRO": "brokered_deposits",
    "VOLIAB": "volatile_liabilities",
    "DEPLGAMT": "large_denomination_deposits",
    "NTRTIME": "time_deposits",
}

# raw FDIC code -> canonical column, for RATIO fields (already %, pass through)
_RATIO_FIELDS = {
    "IDT1CER": "cet1_ratio",
    "IDT1RWAJR": "tier1_rbc_ratio",
    "RBCRWAJ": "total_rbc_ratio",
    "RBC1AAJ": "leverage_ratio",
    "EQV": "equity_to_assets_ratio_reported",
    "LNLSDEPR": "loan_to_deposit_ratio_reported",
    # FDIC's own computed performance ratios. These are **year-to-date annualized**,
    # so Q1 and Q4 are not like-for-like — anything comparing them across quarters
    # must de-annualize from net_income/average_assets instead of differencing these.
    "NIMY": "net_interest_margin_reported",
    "ROA": "roa_reported",
    "ROE": "roe_reported",
    "EEFFR": "efficiency_ratio_reported",
    "NPERFV": "noncurrent_assets_ratio_reported",
    "IDLNCORR": "loans_to_core_deposits_reported",
}


class SilverRow(TypedDict):
    """The real, complete shape `to_bank_financials()` returns — documented here
    so a typo in a consumer's key access (``row["toatl_assets"]``) is a mypy
    error instead of a silent `None`/`KeyError` at runtime. `to_bank_financials`
    builds this dynamically (looping over `_DOLLAR_FIELDS`/`_RATIO_FIELDS`), so
    the dict literal there is `cast` to this at the return point rather than
    constructed field-by-field."""

    cert_number: int | None
    name: str | None
    state: str | None
    country: str
    currency: str
    quarter: str | None
    filing_date: str | None
    restated_flag: bool
    _source: str
    rssd_id: int | None
    holding_company_name: str | None
    holding_company_rssd: int | None

    total_assets: float | None
    total_deposits: float | None
    domestic_deposits: float | None
    insured_deposits: float | None
    uninsured_deposits: float | None
    core_deposits: float | None
    total_loans_gross: float | None
    total_loans_net: float | None
    total_equity: float | None
    real_estate_loans: float | None
    construction_loans: float | None
    multifamily_loans: float | None
    nonfarm_nonres_loans: float | None
    heloc_loans: float | None
    residential_mortgage_loans: float | None
    farmland_loans: float | None
    agricultural_loans: float | None
    c_and_i_loans: float | None
    consumer_loans: float | None
    credit_card_loans: float | None
    auto_loans: float | None
    consumer_other_loans: float | None
    securities_total: float | None
    securities_afs: float | None
    securities_htm_reported: float | None
    tier1_capital: float | None
    total_capital: float | None
    risk_weighted_assets: float | None
    average_assets: float | None
    cash_and_balances: float | None
    net_income: float | None
    interest_income: float | None
    interest_expense: float | None
    noninterest_income: float | None
    noninterest_expense: float | None
    provision_for_credit_losses: float | None
    noncurrent_loans: float | None
    net_charge_offs: float | None
    net_charge_offs_construction: float | None
    net_charge_offs_multifamily: float | None
    net_charge_offs_nonfarm_nonres: float | None
    net_charge_offs_residential_mortgage: float | None
    net_charge_offs_farmland: float | None
    net_charge_offs_agricultural: float | None
    net_charge_offs_c_and_i: float | None
    net_charge_offs_consumer: float | None
    allowance_for_credit_losses: float | None
    assets_past_due_30_89: float | None
    assets_past_due_90_plus: float | None
    other_real_estate_owned: float | None
    intangible_assets: float | None
    brokered_deposits: float | None
    volatile_liabilities: float | None
    large_denomination_deposits: float | None
    time_deposits: float | None
    securities_htm: float | None
    cre_loans: float | None

    cet1_ratio: float | None
    tier1_rbc_ratio: float | None
    total_rbc_ratio: float | None
    leverage_ratio: float | None
    equity_to_assets_ratio_reported: float | None
    loan_to_deposit_ratio_reported: float | None
    net_interest_margin_reported: float | None
    roa_reported: float | None
    roe_reported: float | None
    efficiency_ratio_reported: float | None
    noncurrent_assets_ratio_reported: float | None
    loans_to_core_deposits_reported: float | None


def _to_usd(value) -> float | None:
    if value is None or value == "":
        return None
    v = float(value)
    # FDIC uses -1 as a "not reported" sentinel in some older dollar fields (found
    # live in pre-2008 SCHA/HTM-securities data for IndyMac) — NOT a real -$1,000.
    # Only -1 exactly is treated this way; a genuinely negative EQ (insolvent bank)
    # is real data and must NOT be discarded — this platform's whole point is
    # catching failing banks, so a legitimately negative equity value matters.
    if v == -1:
        return None
    return v * _THOUSANDS


def _to_ratio(value) -> float | None:
    if value is None or value == "":
        return None
    return round(float(value), 4)


def _parse_repdte(repdte) -> tuple[str | None, str | None]:
    """20260331 -> ("2026-03-31", "2026Q1")."""
    if repdte is None:
        return None, None
    s = str(int(repdte))
    year, month, day = s[0:4], s[4:6], s[6:8]
    quarter = {"03": 1, "06": 2, "09": 3, "12": 4}.get(month)
    return f"{year}-{month}-{day}", (f"{year}Q{quarter}" if quarter else None)


def to_bank_financials(raw: dict) -> dict:
    """Map one raw FDIC financials record to a canonical Silver row."""
    iso_date, quarter = _parse_repdte(raw.get("REPDTE"))

    row: dict = {
        "cert_number": int(raw["CERT"]) if raw.get("CERT") is not None else None,
        "name": raw.get("NAMEFULL"),
        "state": raw.get("STALP"),
        "country": "US",
        "currency": "USD",
        "quarter": quarter,
        "filing_date": iso_date,
        "restated_flag": False,
        "_source": "fdic.bankfind",
        # holding-company identity — the crosswalk to SEC filers joins on these
        "rssd_id": int(raw["RSSDID"]) if raw.get("RSSDID") not in (None, "") else None,
        "holding_company_name": raw.get("NAMEHCR"),
        "holding_company_rssd": int(raw["RSSDHCR"]) if raw.get("RSSDHCR") not in (None, "", 0) else None,
    }
    for code, col in _DOLLAR_FIELDS.items():
        row[col] = _to_usd(raw.get(code))
    for code, col in _RATIO_FIELDS.items():
        row[col] = _to_ratio(raw.get(code))

    # HTM securities: prefer FDIC's reported amortized cost (SCHA); else derive SC - AFS.
    if row.get("securities_htm_reported") is not None:
        row["securities_htm"] = row["securities_htm_reported"]
    elif row.get("securities_total") is not None and row.get("securities_afs") is not None:
        row["securities_htm"] = row["securities_total"] - row["securities_afs"]
    else:
        row["securities_htm"] = None

    # CRE (commercial real estate) aggregate, incl. owner-occupied:
    # construction + multifamily + nonfarm-nonresidential.
    cre_parts = [row.get("construction_loans"), row.get("multifamily_loans"),
                 row.get("nonfarm_nonres_loans")]
    row["cre_loans"] = sum(p for p in cre_parts if p is not None) if any(
        p is not None for p in cre_parts) else None

    return row
