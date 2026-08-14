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
    # Recalibrated against the real population distribution. The old 30/40 thresholds
    # sat BELOW the 25th percentile and fired "high" for 84% of all banks — a constant,
    # not a signal. Both thresholds are now plain-English statements that hold up:
    # above 50% one sector is more than half the loan book; above 65% it is roughly
    # two-thirds. (Ranking against peers is available separately as
    # percentile_rank_max_loan_concentration_pct — a flag should say what IS true, not
    # merely that others are lower.)
    Rule("max_loan_concentration_pct", "Single-sector loan concentration", 50.0, 65.0,
         "higher_worse",
         "One sector dominating the book concentrates credit risk regardless of headline capital."),
    # The 2006 Interagency CRE Concentration Guidance (reaffirmed 2023) screens on CRE
    # against TOTAL RISK-BASED CAPITAL, not book equity — so this rule uses the correct
    # denominator. 300% is the guidance's own criterion and it is a screen meaning
    # "may warrant further supervisory analysis", NOT a limit, so it maps to elevated;
    # "high" is reserved for the far tail (p97.5 of the real population is 533%).
    Rule("cre_to_total_capital_pct", "CRE vs total risk-based capital", 300.0, 500.0,
         "higher_worse",
         "The 2006 interagency guidance screens banks with CRE at or above 300% of total "
         "risk-based capital for further supervisory analysis.",
         family="risk_based_capital"),
    # The guidance's FIRST criterion, a separate and tighter test than the 300% one.
    Rule("construction_to_total_capital_pct", "Construction vs total risk-based capital",
         100.0, 150.0, "higher_worse",
         "Construction & land development at or above 100% of total risk-based capital is "
         "the guidance's first screening criterion — the most cyclical CRE segment.",
         family="risk_based_capital"),
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
    unevaluated: list[str] = []
    evaluated = 0
    for rule in RULES:
        if rule.family in suppressed:
            skipped.append(rule.key)
            continue
        value = gold_row.get(rule.key)
        if value is None:
            # Distinct from `skipped` above: that rule was deliberately suppressed for
            # this bank's capital basis; THIS one simply has no data to test against.
            # Both used to vanish silently, which made an under-covered bank look
            # cleaner than a fully-assessed one — a bank scored on 2 of 9 rules
            # showed "1 flag" exactly like a bank scored on all 9. Reported now so
            # a low flag count can be read against how much was actually checked.
            unevaluated.append(rule.key)
            continue
        evaluated += 1
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
        # Peer context, if percentile ranks were attached (see
        # peers.add_percentile_ranks). C11: defaults to the CLUSTER-
        # conditional percentile (a behaviorally-similar peer group is a more
        # meaningful comparison than the raw global population, which now
        # spans a $1B community bank to a $900B GSIB — see B3), falling back
        # to the population-wide figure only when this bank has no cluster
        # assignment. `peer_percentile_basis` names which one was used so a
        # caller never has to guess.
        pctile = gold_row.get(f"percentile_rank_{rule.key}_within_cluster")
        basis = "within_cluster"
        if pctile is None:
            pctile = gold_row.get(f"percentile_rank_{rule.key}")
            basis = "global"
        if pctile is not None:
            flag["peer_percentile"] = pctile
            flag["peer_percentile_basis"] = basis
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
        # Coverage: how much of the ruleset actually ran. `overall_risk` is only as
        # complete as `rules_evaluated` — a "low" verdict from 2 of 9 rules is a
        # statement about 2 rules, not a clean bill of health.
        "rules_evaluated": evaluated,
        "rules_total": len(RULES),
        "rules_not_evaluated": unevaluated,
        "fully_assessed": not unevaluated and not skipped,
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
