"""Feature 11 — Balance-Sheet X-Ray (concentration & structural risk).

Surfaces hidden risk that headline ratios hide: a bank with "healthy" capital but
40% of loans in one sector, heavy reliance on uninsured deposits, thin liquidity,
or a shrinking capital buffer.

Logic: transparent rule-based scoring over Gold features. Each rule compares a
metric to supervisory-informed thresholds and, if breached, emits a flag with the
value, the threshold, a severity, and a plain-English reason. The overall risk is
the worst severity among the flags.

This is deliberately auditable (no ML). The peer-percentile dimension from the
product spec (``percentile_rank_*``) needs the peer population and lands in Phase 2;
the pure single-bank rules are implemented here now. The gRPC service in
``services/feature-services/xray`` will wrap this exact logic.
"""

from __future__ import annotations

from dataclasses import dataclass

# severity ordering for rollup
_ORDER = {"low": 0, "elevated": 1, "high": 2}


@dataclass(frozen=True)
class Rule:
    key: str                 # Gold field to read
    label: str               # human name
    elevated: float          # threshold for "elevated"
    high: float              # threshold for "high"
    direction: str           # "higher_worse" or "lower_worse"
    why: str                 # plain-English rationale
    # "risk_based_capital" rules are skipped for CBLR electers and foreign-bank
    # branches; "leverage" is skipped only for the latter. See evaluate_xray.
    family: str = "general"


# Thresholds are supervisory-informed starting points, tunable per the peer study.
RULES: list[Rule] = [
    Rule("uninsured_deposit_pct", "Uninsured deposit reliance", 40.0, 55.0,
         "higher_worse",
         "Uninsured depositors (>$250k) run first; high reliance = structurally run-prone (cf. SVB ~94%)."),
    Rule("loan_to_deposit_pct", "Loan-to-deposit (liquidity)", 90.0, 100.0,
         "higher_worse",
         "Loans funded beyond the deposit base lean on wholesale/volatile funding."),
    Rule("max_loan_concentration_pct", "Single-sector loan concentration", 30.0, 40.0,
         "higher_worse",
         "One sector dominating the book concentrates credit risk regardless of headline capital."),
    Rule("cre_to_equity_pct", "CRE vs capital", 250.0, 300.0,
         "higher_worse",
         "CRE above ~300% of capital is the classic supervisory concentration flag."),
    Rule("core_deposit_pct", "Core-deposit stability", 55.0, 40.0,
         "lower_worse",
         "Low core (sticky) deposits mean funding can evaporate under stress."),
    Rule("cet1_ratio", "CET1 capital buffer", 10.5, 7.0,
         "lower_worse",
         "CET1 below the Basel minimum-plus-buffer (~10.5%) leaves little loss absorption.",
         family="risk_based_capital"),
    Rule("leverage_ratio", "Tier 1 leverage", 5.0, 4.0,
         "lower_worse",
         "Leverage ratio under 5% (well-capitalized threshold) signals a thin equity base.",
         family="leverage"),
]


def _severity(rule: Rule, value: float) -> str:
    if rule.direction == "higher_worse":
        if value >= rule.high:
            return "high"
        if value >= rule.elevated:
            return "elevated"
        return "low"
    else:  # lower_worse
        if value <= rule.high:
            return "high"
        if value <= rule.elevated:
            return "elevated"
        return "low"


def evaluate_xray(gold_row: dict, *, capital_basis: str = "risk_based") -> dict:
    """Score one Gold row, returning an interpretable risk breakdown.

    `capital_basis` selects which capital rules legitimately apply — see
    `banklens_transforms.data_quality.capital_basis`, which derives it from Silver:

      "risk_based" — the normal case; every rule applies.
      "cblr"       — a Community Bank Leverage Ratio electer. Reports no RWA and no
                     risk-based ratios *because the regulation deems it to satisfy
                     them*, so the CET1 rule is suppressed. Its leverage ratio is the
                     binding measure and IS still evaluated.
      "none"       — a US branch/agency of a foreign bank, capital held at the parent.
                     No capital rule applies.

    Measured on the real 2026Q1 population, reading those zeros as thin capital was
    producing a false "CET1 below the Basel minimum" flag on 208 of 1,049 banks (19.8%)
    — for the 195 CBLR electers it inverted the regulator's actual finding.
    """
    suppressed = {
        "risk_based": set(),
        "cblr": {"risk_based_capital"},
        "none": {"risk_based_capital", "leverage"},
    }.get(capital_basis, set())

    flags: list[dict] = []
    skipped: list[str] = []
    for rule in RULES:
        if rule.family in suppressed:
            skipped.append(rule.key)
            continue
        value = gold_row.get(rule.key)
        if value is None:
            continue
        sev = _severity(rule, value)
        if sev == "low":
            continue
        threshold = rule.high if sev == "high" else rule.elevated
        flag = {
            "factor": rule.label,
            "metric": rule.key,
            "value": round(value, 2),
            "threshold": threshold,
            "severity": sev,
            "note": rule.why,
        }
        # Peer context, if percentile ranks were attached (see peers.add_percentile_ranks).
        pctile = gold_row.get(f"percentile_rank_{rule.key}")
        if pctile is not None:
            flag["peer_percentile"] = pctile
        flags.append(flag)

    flags.sort(key=lambda f: _ORDER[f["severity"]], reverse=True)
    overall = "low"
    if flags:
        overall = max(flags, key=lambda f: _ORDER[f["severity"]])["severity"]

    return {
        "cert_number": gold_row.get("cert_number"),
        "name": gold_row.get("name"),
        "quarter": gold_row.get("quarter"),
        "overall_risk": overall,
        "flag_count": len(flags),
        "flags": flags,
        # Named, not silent: a consumer must be able to tell "no capital flag" from
        # "capital not assessed", and see why.
        "capital_basis": capital_basis,
        "rules_not_applicable": skipped,
        "key_metrics": {
            "uninsured_deposit_pct": gold_row.get("uninsured_deposit_pct"),
            "loan_to_deposit_pct": gold_row.get("loan_to_deposit_pct"),
            "max_loan_concentration": {
                "category": gold_row.get("max_loan_concentration_category"),
                "pct": gold_row.get("max_loan_concentration_pct"),
            },
            "cet1_ratio": gold_row.get("cet1_ratio"),
            "leverage_ratio": gold_row.get("leverage_ratio"),
        },
    }
