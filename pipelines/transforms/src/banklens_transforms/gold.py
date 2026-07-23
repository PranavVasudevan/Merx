"""Gold layer — derived features every downstream feature/tool/agent reads.

This is the heart of the platform's "build once, reuse everywhere" principle.
Phase 1 implements the ratios the vertical-slice fields support and documents
(honestly) what still needs richer inputs.

Each function is a pure, testable definition. Tests in
``pipelines/transforms/tests/test_gold_metrics.py`` pin these against real
Wells Fargo numbers so the dbt/Spark reimplementation can be validated to match.
"""

from __future__ import annotations


def _pct(numerator, denominator) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100, 4)


def uninsured_deposit_pct(row: dict) -> float | None:
    """Uninsured deposits as % of total deposits. The #1 deposit-flight signal.

    Rationale: insured depositors (<$250k) have no reason to run; uninsured ones
    (corporations, VCs) flee first. High uninsured % => structurally run-prone.
    """
    return _pct(row.get("uninsured_deposits"), row.get("total_deposits"))


def loan_to_deposit_pct(row: dict) -> float | None:
    """Net loans / total deposits. A crude liquidity/funding-intensity gauge."""
    return _pct(row.get("total_loans_net"), row.get("total_deposits"))


def equity_to_assets_pct(row: dict) -> float | None:
    """Total equity / total assets — a simple leverage proxy.

    NOTE: this is *not* the regulatory Tier-1 leverage ratio (which uses Tier-1
    capital over *average* assets). It is a transparent stand-in until we ingest
    the FDIC/Call-Report capital fields. Labelled as a proxy on purpose.
    """
    return _pct(row.get("total_equity"), row.get("total_assets"))


def qoq_delta(current, previous) -> dict | None:
    """Quarter-over-quarter absolute and percentage change for a metric."""
    if current is None or previous is None:
        return None
    abs_change = current - previous
    pct_change = round(abs_change / previous * 100, 4) if previous else None
    return {"abs": abs_change, "pct": pct_change}


def derive_gold(silver_rows_desc: list[dict]) -> list[dict]:
    """Given Silver rows sorted newest-first, produce Gold feature rows.

    QoQ deltas use the immediately older quarter as the baseline.
    """
    gold: list[dict] = []
    for i, row in enumerate(silver_rows_desc):
        prev = silver_rows_desc[i + 1] if i + 1 < len(silver_rows_desc) else None
        gold.append({
            "cert_number": row.get("cert_number"),
            "name": row.get("name"),
            "quarter": row.get("quarter"),
            "uninsured_deposit_pct": uninsured_deposit_pct(row),
            "loan_to_deposit_pct": loan_to_deposit_pct(row),
            "equity_to_assets_pct": equity_to_assets_pct(row),
            "qoq_total_deposits": qoq_delta(
                row.get("total_deposits"), prev.get("total_deposits") if prev else None),
            "qoq_total_assets": qoq_delta(
                row.get("total_assets"), prev.get("total_assets") if prev else None),
            # TODO(phase-2): concentration_ratio_* needs loan-composition fields
            #   (CRE, C&I, consumer, resi, ag); percentile_rank_* needs the peer set.
        })
    return gold
