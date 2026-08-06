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
