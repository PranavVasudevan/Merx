"""Silver layer — normalise one raw FDIC record into the canonical schema.

Cleaning steps (Phase 1 subset of the full contract):
  * map FDIC MDRM-style codes -> human canonical column names
  * convert amounts from **thousands of USD** to actual USD
  * parse REPDTE (YYYYMMDD int) -> ISO date + quarter label
  * flag missing values explicitly (None), never silently zero-fill

The full Silver contract (loan composition, capital ratios, restated-filing
dedupe, CERT<->CIK<->RSSD crosswalk) is documented in
``docs/data-contracts/bank_financials.silver.md``.
"""

from __future__ import annotations

# FDIC financial amounts are reported in thousands of dollars.
_THOUSANDS = 1000

# raw FDIC code -> canonical Silver column
_FIELD_MAP = {
    "ASSET": "total_assets",
    "DEP": "total_deposits",
    "DEPDOM": "domestic_deposits",
    "DEPINS": "insured_deposits",
    "LNLSGR": "total_loans_gross",
    "LNLSNET": "total_loans_net",
    "EQ": "total_equity",
}


def _to_usd(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value) * _THOUSANDS


def _parse_repdte(repdte) -> tuple[str | None, str | None]:
    """20260331 -> ("2026-03-31", "2026Q1")."""
    if repdte is None:
        return None, None
    s = str(int(repdte))
    year, month, day = s[0:4], s[4:6], s[6:8]
    quarter = {"03": 1, "06": 2, "09": 3, "12": 4}.get(month)
    q_label = f"{year}Q{quarter}" if quarter else None
    return f"{year}-{month}-{day}", q_label


def to_bank_financials(raw: dict) -> dict:
    """Map one raw FDIC financials record to a canonical Silver row."""
    iso_date, quarter = _parse_repdte(raw.get("REPDTE"))

    row: dict = {
        "cert_number": int(raw["CERT"]) if raw.get("CERT") is not None else None,
        "name": raw.get("NAMEFULL"),
        "state": raw.get("STALP"),
        "quarter": quarter,
        "filing_date": iso_date,
        "restated_flag": False,  # dedupe of restatements handled in the full build
        "_source": "fdic.bankfind",
    }
    for code, col in _FIELD_MAP.items():
        row[col] = _to_usd(raw.get(code))

    # derived-but-still-Silver: uninsured deposits = total - insured (estimate)
    if row["total_deposits"] is not None and row["insured_deposits"] is not None:
        row["uninsured_deposits"] = row["total_deposits"] - row["insured_deposits"]
    else:
        row["uninsured_deposits"] = None

    return row
