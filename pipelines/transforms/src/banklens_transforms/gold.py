"""Gold layer — derived features every downstream feature/tool/agent reads.

The heart of "build once, reuse everywhere". Each function is a pure, testable
definition, pinned against real figures in the tests. When these move to
dbt/Spark (Phase 2), the reimplementation must reproduce the same numbers.

Phase-1b additions: loan-concentration ratios (feeds Feature 11 X-Ray),
CRE concentration, core-deposit ratio, and pass-through of FDIC capital ratios.
Still TODO (needs the peer population): ``percentile_rank_*``.
"""

from __future__ import annotations

# Loan categories we report concentration for: canonical column -> label.
LOAN_CATEGORIES = {
    "cre_loans": "cre",
    "c_and_i_loans": "c_and_i",
    "residential_mortgage_loans": "residential_mortgage",
    "consumer_loans": "consumer",
    "agricultural_loans": "agricultural",
}


def _pct(numerator, denominator) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100, 4)


def uninsured_deposit_pct(row: dict) -> float | None:
    """Uninsured deposits as % of total deposits — the #1 deposit-flight signal.

    Uses FDIC's reported ``uninsured_deposits`` (DEPUNINS), not DEP - DEPINS.
    """
    return _pct(row.get("uninsured_deposits"), row.get("total_deposits"))


def core_deposit_pct(row: dict) -> float | None:
    """Core (stable, sticky) deposits as % of total. Higher = more stable funding."""
    return _pct(row.get("core_deposits"), row.get("total_deposits"))


def loan_to_deposit_pct(row: dict) -> float | None:
    """Net loans / total deposits. Validated against FDIC's reported LNLSDEPR."""
    return _pct(row.get("total_loans_net"), row.get("total_deposits"))


def equity_to_assets_pct(row: dict) -> float | None:
    """Total equity / total assets. Validated against FDIC's reported EQV."""
    return _pct(row.get("total_equity"), row.get("total_assets"))


def concentration_ratios(row: dict) -> dict:
    """Each loan category as % of gross loans. The core of Feature 11."""
    gross = row.get("total_loans_gross")
    out: dict = {}
    for col, label in LOAN_CATEGORIES.items():
        out[f"concentration_ratio_{label}"] = _pct(row.get(col), gross)
    return out


def max_concentration(concentrations: dict) -> tuple[str | None, float | None]:
    """The single most concentrated loan category and its ratio."""
    best_label, best_val = None, None
    for key, val in concentrations.items():
        if val is not None and (best_val is None or val > best_val):
            best_label, best_val = key.replace("concentration_ratio_", ""), val
    return best_label, best_val


def cre_to_equity_pct(row: dict) -> float | None:
    """CRE loans / total equity. A capital-relative concentration lens.

    NOTE: the precise supervisory 'CRE concentration' guideline uses *total
    risk-based capital* (not book equity) and excludes owner-occupied CRE. This
    equity-based proxy is transparent and directional until we ingest RWA/capital $.
    """
    return _pct(row.get("cre_loans"), row.get("total_equity"))


def qoq_delta(current, previous) -> dict | None:
    if current is None or previous is None:
        return None
    abs_change = current - previous
    pct_change = round(abs_change / previous * 100, 4) if previous else None
    return {"abs": abs_change, "pct": pct_change}


def derive_gold(silver_rows_desc: list[dict]) -> list[dict]:
    """Given Silver rows newest-first, produce Gold feature rows."""
    gold: list[dict] = []
    for i, row in enumerate(silver_rows_desc):
        prev = silver_rows_desc[i + 1] if i + 1 < len(silver_rows_desc) else None
        conc = concentration_ratios(row)
        max_label, max_val = max_concentration(conc)

        g = {
            "cert_number": row.get("cert_number"),
            "name": row.get("name"),
            "quarter": row.get("quarter"),
            # deposits / funding
            "uninsured_deposit_pct": uninsured_deposit_pct(row),
            "core_deposit_pct": core_deposit_pct(row),
            "loan_to_deposit_pct": loan_to_deposit_pct(row),
            "equity_to_assets_pct": equity_to_assets_pct(row),
            # concentration (Feature 11 inputs)
            **conc,
            "max_loan_concentration_category": max_label,
            "max_loan_concentration_pct": max_val,
            "cre_to_equity_pct": cre_to_equity_pct(row),
            # capital adequacy (straight from FDIC)
            "cet1_ratio": row.get("cet1_ratio"),
            "tier1_rbc_ratio": row.get("tier1_rbc_ratio"),
            "total_rbc_ratio": row.get("total_rbc_ratio"),
            "leverage_ratio": row.get("leverage_ratio"),
            # trend
            "qoq_total_deposits": qoq_delta(
                row.get("total_deposits"), prev.get("total_deposits") if prev else None),
            "qoq_uninsured_deposit_pct": qoq_delta(
                uninsured_deposit_pct(row),
                uninsured_deposit_pct(prev) if prev else None),
        }
        gold.append(g)
    return gold
