"""Explicit, disclosed data-quality exclusions.

Some FDIC-chartered institutions in the $1B-$250B asset band are not deposit-funded
banks in any meaningful sense: clearing houses (The Depository Trust Company), custody
and trust companies (BlackRock Institutional Trust, Computershare), credit-card
subsidiary charters (Barclays Bank Delaware, Wells Fargo Financial), and digital-asset
custodians (Anchorage Digital). They hold billions in assets against essentially zero
deposits.

They break deposit-based ratios arithmetically — measured on the real landed data,
`loan_to_deposit_pct` reaches **6,759,464%** for BANK OF AMERICA, RHODE ISLAND, N.A.
(2008Q1: $35.8B assets, 0.001% deposit-funded). Pooled into the deposit-flight
training set that produced an imputation mean of **7,846.88%** with a standard
deviation of 194,207 — which, after standardization, collapsed a normal 90%-LTD bank
to z = -0.04 and left one of the model's five features contributing essentially
nothing to any prediction.

But the reason to exclude them is not that the arithmetic is inconvenient. It is that
**a deposit-flight model does not apply to an institution that is not deposit-funded.**
A clearing house cannot suffer a depositor run. Including it teaches the model nothing
and corrupts the scale for every bank that can.

The policy is deliberately a *named, inspectable asset* rather than a silent clip or
winsorization. Quietly clamping an outlier would itself be a fabricated number — the
user would see a plausible chart with no way to know a value had been altered. Every
exclusion here carries the certificate, the institution's real name, the actual
measured figures, and the reason, and is surfaced in the UI.

Threshold: **deposits < 5% of assets**. Chosen from the real distribution, not picked
for convenience — there is a clean gap in the data between the excluded cohort
(0.000%-3.96% deposit-funded) and the next institution up (USAA Savings Bank at 5.9%).
Banks above the line that still carry high loan-to-deposit ratios (Wachovia Mortgage
FSB at 1,221%, Silverton Bank at 734% — which really did fail in 2009) are genuinely
deposit-taking wholesale-funded lenders and are deliberately KEPT: they are real
signal, not noise.
"""

from __future__ import annotations

MIN_DEPOSIT_FUNDED_PCT = 5.0

NOT_DEPOSIT_FUNDED = "not_deposit_funded"
NO_REGULATORY_CAPITAL = "no_standalone_regulatory_capital"
CBLR_FRAMEWORK = "community_bank_leverage_ratio"

_CAPITAL_RATIOS = ("cet1_ratio", "tier1_rbc_ratio", "total_rbc_ratio", "leverage_ratio")

# Capital regimes. Which X-Ray rules apply depends on which of these a bank is under —
# see `capital_basis`.
RISK_BASED = "risk_based"
CBLR = "cblr"
NONE = "none"


def capital_basis(silver: dict) -> str:
    """Which regulatory capital regime this institution reports under.

    Reading a zero as "dangerously thin capital" was producing false alarms on **208 of
    1,049 banks (19.8%)** in the real 2026Q1 population. Two distinct, legitimate
    reasons a bank reports zero, both verified against the landed data:

    `NONE` — **13 banks**: equity not reported and all four ratios exactly 0.0.
    Standard Chartered, Bank of China, BBVA, State Bank of India, Bank Hapoalim and
    peers: US branches/agencies of foreign banks, whose capital is held and reported
    at the foreign parent. No capital rule applies to them at all.

    `CBLR` — **195 banks**: real positive equity and a real leverage ratio, but zero
    risk-weighted assets and zero risk-based ratios. This is the **Community Bank
    Leverage Ratio** framework (EGRRCPA 2018): a qualifying bank under $10B that
    maintains leverage above 9% is *deemed by regulation to satisfy* the risk-based
    capital requirements, and does not report CET1/Tier-1-RBC/Total-RBC or RWA.
    Verified: all 195 are under the $10B eligibility cap, 192 are at or above the 9%
    floor, and the 3 between 8.90% and 8.98% sit inside CBLR's two-percentage-point
    grace band. Flagging these banks "CET1 below the Basel minimum" inverted the
    regulator's actual finding. Their leverage ratio IS the binding measure, so the
    leverage rule still applies — only the risk-based ones are suppressed.

    `RISK_BASED` — everyone else, evaluated normally.

    Genuinely NEGATIVE equity is a real distress signal that `silver.py` preserves on
    purpose; it returns RISK_BASED and is never swept into an exemption.
    """
    equity = silver.get("total_equity")
    if equity in (None, 0) and not any((silver.get(r) or 0) != 0 for r in _CAPITAL_RATIOS):
        return NONE
    if (equity or 0) > 0 and (silver.get("risk_weighted_assets") or 0) == 0 \
            and (silver.get("leverage_ratio") or 0) > 0:
        return CBLR
    return RISK_BASED


def reports_regulatory_capital(silver: dict) -> bool:
    """Whether any capital rule applies (False only for foreign-bank branches)."""
    return capital_basis(silver) != NONE


def deposit_funding_pct(silver: dict) -> float | None:
    """Deposits as a percentage of total assets. None when assets are missing/zero."""
    assets = silver.get("total_assets")
    if not assets:
        return None
    return (silver.get("total_deposits") or 0) / assets * 100


def is_deposit_funded(silver: dict, *, threshold: float = MIN_DEPOSIT_FUNDED_PCT) -> bool:
    """Whether deposit-based analytics meaningfully apply to this institution.

    Unknown funding (missing assets) is treated as NOT excludable — we don't drop a
    bank on the basis of data we don't have.
    """
    pct = deposit_funding_pct(silver)
    return True if pct is None else pct >= threshold


def capital_exclusion_for(silver: dict) -> dict | None:
    """Record explaining why risk-based capital rules don't apply, or None if they do.

    Deliberately scoped to the affected analytic rather than dropping the bank: a
    foreign-bank branch and a CBLR electer are both perfectly valid subjects for
    concentration, funding and deposit analytics. Excluding them wholesale would
    remove 208 real institutions from every other view.
    """
    basis = capital_basis(silver)
    if basis == RISK_BASED:
        return None
    common = {
        "cert": silver.get("cert_number"), "name": silver.get("name"),
        "quarter": silver.get("quarter"), "total_assets": silver.get("total_assets"),
        "total_equity": silver.get("total_equity"),
        "leverage_ratio": silver.get("leverage_ratio"),
    }
    if basis == NONE:
        return {**common, "rule": NO_REGULATORY_CAPITAL,
                "reason": ("Reports no standalone regulatory capital (equity and all four "
                           "ratios are zero) — a US branch or agency of a foreign bank, whose "
                           "capital is held at the parent. No capital rule applies.")}
    return {**common, "rule": CBLR_FRAMEWORK,
            "reason": ("Reports under the Community Bank Leverage Ratio framework: no "
                       "risk-weighted assets and no risk-based ratios, because a qualifying "
                       "bank holding leverage above 9% is deemed by regulation to satisfy the "
                       "risk-based capital requirements. Its leverage ratio is the binding "
                       "measure and is still evaluated.")}


def exclusion_for(silver: dict, *, threshold: float = MIN_DEPOSIT_FUNDED_PCT) -> dict | None:
    """The deposit-analytics exclusion record for one bank, or None if not excluded."""
    if is_deposit_funded(silver, threshold=threshold):
        return None
    pct = deposit_funding_pct(silver)
    return {
        "cert": silver.get("cert_number"),
        "name": silver.get("name"),
        "quarter": silver.get("quarter"),
        "rule": NOT_DEPOSIT_FUNDED,
        "deposits_to_assets_pct": round(pct, 4) if pct is not None else None,
        "total_assets": silver.get("total_assets"),
        "total_deposits": silver.get("total_deposits"),
        "threshold_pct": threshold,
        "reason": ("Deposits are under {:.2f}% of assets — a trust, custody, clearing or "
                   "card-subsidiary charter rather than a deposit-funded bank, so "
                   "deposit-run analytics do not apply.").format(threshold),
    }


def partition(silver_rows: list[dict], *, threshold: float = MIN_DEPOSIT_FUNDED_PCT
              ) -> tuple[list[dict], list[dict]]:
    """Split Silver rows into (kept, exclusion_records). Order is preserved."""
    kept, excluded = [], []
    for s in silver_rows:
        exc = exclusion_for(s, threshold=threshold)
        if exc is None:
            kept.append(s)
        else:
            excluded.append(exc)
    return kept, excluded


def summarize(exclusions: list[dict], total: int) -> dict:
    """A disclosure block a UI can render verbatim."""
    return {
        "threshold_pct": MIN_DEPOSIT_FUNDED_PCT,
        "rule": NOT_DEPOSIT_FUNDED,
        "excluded_count": len(exclusions),
        "total_considered": total,
        "excluded_pct": round(len(exclusions) / total * 100, 2) if total else 0.0,
        "excluded": sorted(exclusions, key=lambda e: e.get("deposits_to_assets_pct") or 0),
    }
