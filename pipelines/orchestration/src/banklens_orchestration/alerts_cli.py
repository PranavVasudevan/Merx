"""D2 (docs/audit/04-remediation-prompts.md): evaluate every user's saved
watchlist threshold rules against the just-refreshed data and record any that
trip as a new alert (GET /api/alerts surfaces them in-app). Wired as its own
DAG stage in quarterly_refresh.build_dag() — depends on land_population,
clustering and deposit_flight_retrain so cluster- and risk-leaderboard-based
rules see the freshly retrained state, not last quarter's.

Supported rule_type values (set via POST /api/watchlist/rules):
  metric_threshold       — {metric} {operator: 'gt'|'lt'} {threshold}, against
                            the LATEST landed quarter only.
  metric_delta           — |latest {metric} - prior-quarter {metric}| >
                            {threshold} (absolute percentage-point change).
  xray_severity_increase — this bank's X-Ray overall_risk moved up a level
                            (low -> elevated -> high) since the prior quarter.
  risk_leaderboard_entry — this bank is in the top {top_n} of the deposit-
                            flight risk leaderboard this quarter.

Dedup: `db.alert_already_recorded(rule_id, quarter)` keeps a rerun of the SAME
quarter from writing a duplicate alert for a persistently-tripped rule (e.g. a
bank that stays in the top 25 for several quarters legitimately re-alerts once
per NEW quarter, not once per DAG rerun).

Email delivery is explicitly out of scope: the product runs on a documented
$0 budget with no transactional-email provider configured anywhere else in
this repo. D2's acceptance criterion — "a user can save a screen, set a
threshold on a watched bank, and see a triggered alert after a data refresh"
— only requires the alert be visible in-app, which GET /api/alerts satisfies.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
for rel in ("services/mcp-server/src", "pipelines/transforms/src",
           "libs/python/banklens_common/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from banklens_common import db  # noqa: E402
from banklens_mcp import data, tools  # noqa: E402
from banklens_transforms.data_quality import capital_basis  # noqa: E402
from banklens_transforms.xray import evaluate_xray  # noqa: E402

_SEVERITY_RANK = {"low": 0, "elevated": 1, "high": 2}


def _severity_for_quarter(cert: int, quarter: str) -> str | None:
    pop = data.population(quarter)
    g = pop["by_cert"].get(cert)
    if g is None:
        return None
    silver = pop["silver_by_cert"].get(cert) or {}
    return evaluate_xray(g, capital_basis=capital_basis(silver))["overall_risk"]


def _evaluate_one(rule: dict, quarters: list[str], leaderboard_cache: dict[int, set[int]]) -> str | None:
    """Returns an alert message if `rule` trips against the current state, else None."""
    cert, latest, rule_type = rule["cert"], quarters[0], rule["rule_type"]

    if rule_type == "metric_threshold":
        g = data.population(latest)["by_cert"].get(cert)
        value = g.get(rule["metric"]) if g else None
        if value is None or rule["threshold"] is None:
            return None
        op = rule["operator"]
        tripped = value > rule["threshold"] if op == "gt" else value < rule["threshold"]
        if not tripped:
            return None
        return (f"{rule['metric']} is {value:.2f} "
                f"({'above' if op == 'gt' else 'below'} your {rule['threshold']:.2f} threshold) "
                f"as of {latest}")

    if rule_type == "metric_delta":
        if len(quarters) < 2 or rule["threshold"] is None:
            return None
        cur = data.population(latest)["by_cert"].get(cert)
        prior = data.population(quarters[1])["by_cert"].get(cert)
        cv = cur.get(rule["metric"]) if cur else None
        pv = prior.get(rule["metric"]) if prior else None
        if cv is None or pv is None:
            return None
        delta = cv - pv
        if abs(delta) <= rule["threshold"]:
            return None
        return (f"{rule['metric']} moved {delta:+.2f}pp ({pv:.2f} -> {cv:.2f}) since "
                f"{quarters[1]} — exceeds your {rule['threshold']:.2f}pp threshold")

    if rule_type == "xray_severity_increase":
        if len(quarters) < 2:
            return None
        cur_sev = _severity_for_quarter(cert, latest)
        prior_sev = _severity_for_quarter(cert, quarters[1])
        if cur_sev is None or prior_sev is None:
            return None
        if _SEVERITY_RANK.get(cur_sev, 0) <= _SEVERITY_RANK.get(prior_sev, 0):
            return None
        return f"X-Ray severity increased from {prior_sev} to {cur_sev} as of {latest}"

    if rule_type == "risk_leaderboard_entry":
        top_n = rule.get("top_n") or 25
        if top_n not in leaderboard_cache:
            try:
                leaderboard_cache[top_n] = {
                    r["cert"] for r in tools.get_risk_leaderboard(top_n=top_n)["top"]}
            except ValueError:
                leaderboard_cache[top_n] = set()  # model not trained yet
        if cert not in leaderboard_cache[top_n]:
            return None
        return f"entered the top {top_n} of the deposit-flight risk leaderboard as of {latest}"

    return None


def run() -> dict:
    """Evaluate every saved rule once and record newly-tripped alerts. Returns
    a small summary dict (also useful for the DAG run log / a manual check)."""
    quarters = data.available_quarters()
    if not quarters:
        return {"rules_evaluated": 0, "alerts_created": 0}
    try:
        rules = db.fetch_watchlist_rules()
    except db.DbUnavailable as exc:
        # Same fail-open posture as every other Postgres-backed feature in this
        # repo (A8) — an unconfigured/unreachable DB in a given environment
        # must not fail the whole quarterly refresh over an optional feature.
        return {"rules_evaluated": 0, "alerts_created": 0, "skipped": str(exc)}
    leaderboard_cache: dict[int, set[int]] = {}
    created = 0
    for rule in rules:
        if db.alert_already_recorded(rule["id"], quarters[0]):
            continue
        try:
            message = _evaluate_one(rule, quarters, leaderboard_cache)
        except Exception:
            # One malformed rule (e.g. a typo'd metric name) must not sink the
            # whole evaluation pass for every other user's rules.
            continue
        if message:
            db.record_alert(rule["user_sub"], rule["cert"], message,
                            rule_id=rule["id"], quarter=quarters[0])
            created += 1
    return {"rules_evaluated": len(rules), "alerts_created": created}


if __name__ == "__main__":
    print(run())
