"""BankLens REST bridge — dependency-free HTTP wrapper over banklens_mcp.tools.

The MCP server speaks JSON-RPC over stdio, which a browser can't call directly.
This bridge exposes the SAME tool functions (no duplicated logic) as plain REST/JSON
over HTTP, for the quant-terminal frontend. Every route's actual behavior — routing,
auth, error mapping, metrics — lives in ONE place, `_route_request()`, so the two
server transports below can never drift into serving different responses for the
same request; only the process/concurrency model differs between them:

  - Dev (default): stdlib `http.server.ThreadingHTTPServer` + `Handler`. Zero
    installs beyond prometheus-client (for /metrics). No request timeout, no body
    cap, no rate limit — fine for a trusted local loop, not for the open internet.
  - Prod (`BANKLENS_SERVER=prod`): a WSGI app (`wsgi_app`) served by gunicorn's
    real prefork worker model — a bounded worker/thread pool, a request timeout
    (gunicorn kills a worker that exceeds it), a 1MB request-body cap, and a
    per-subject token-bucket rate limit. Requires `pip install gunicorn`; the
    bridge Dockerfile installs it. Can also be run directly as
    `gunicorn bridge_server:wsgi_app` without going through `main()` at all.

Run (dev):
    $env:PYTHONPATH = "services/mcp-server/src;pipelines/transforms/src"
    python services/api-gateway/src/bridge_server.py

Run (prod):
    $env:BANKLENS_SERVER = "prod"
    python services/api-gateway/src/bridge_server.py
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import queue
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

import auth
from banklens_common import db as common_db

REPO = Path(__file__).resolve().parents[3]
for rel in ("services/mcp-server/src", "pipelines/transforms/src", "services/agents/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from banklens_mcp import data, tearsheet, tools  # noqa: E402

# The bridge's first-ever dependency on the agents package — surfaces the
# fleet (supervisor + 4 personas, real MCP tool-calling loop) that was
# previously CLI-only. Deliberate new coupling, not accidental.
from banklens_agents import providers  # noqa: E402
from banklens_agents.agent import run_agent, to_json  # noqa: E402
from banklens_agents.personas import PERSONAS  # noqa: E402

import openapi_spec  # noqa: E402  — F19, same directory as this file

RUNS_DIR = REPO / "data" / "agent_runs"

PORT = 8791

# Real metrics (platform/docker/docker-compose.dev.yml's prometheus service
# scrapes GET /metrics), not a stub — see CHANGELOG.md for the live
# Prometheus+Grafana verification. `route` is always one of the fixed
# ROUTES[].route strings below (query-string params, no path params), so this
# label can't blow up in cardinality the way per-ID path segments would.
REQUEST_COUNT = Counter(
    "banklens_bridge_requests_total", "Total HTTP requests handled by the REST bridge",
    ["route", "status"])
REQUEST_LATENCY = Histogram(
    "banklens_bridge_request_duration_seconds", "Request latency in seconds",
    ["route"])


def _cap(cert: int) -> int:
    return int(cert)


class BinaryResponse:
    """D1 — a route can return this instead of a JSON-serialisable dict (so
    far only the PDF tearsheet). `_send`/`_wsgi_response` special-case it the
    same way both transports already special-case /metrics — everything else
    about routing/auth/error-mapping/metrics in `_route_request` is unchanged."""
    __slots__ = ("body", "content_type", "filename")

    def __init__(self, body: bytes, content_type: str, filename: str):
        self.body = body
        self.content_type = content_type
        self.filename = filename


# The authorization tier every non-open route must be declared under. This is the
# single source of truth the OPA policy is checked against — see
# services/api-gateway/tests/test_route_policy.py, which fails if a route here is
# missing from platform/auth/opa/policy.rego or sits in the wrong tier.
#
# That test exists because these were four hand-maintained parallel lists (this table,
# policy.rego, api.ts, NavShell.tsx) and a missing policy entry already broke an entire
# page once: OPA denies by default, and the frontend's Promise.all rejects
# all-or-nothing on a single 403, so one absent line took down a whole view rather than
# one panel. Adding a dozen more routes by hand without a check would guarantee a repeat.
ROUTE_TIERS: dict[str, str] = {
    "/api/population": "viewer",
    "/api/quarters": "viewer",
    "/api/banks": "viewer",
    "/api/banks/profile": "viewer",
    "/api/banks/xray": "viewer",
    "/api/banks/peer-cluster": "viewer",
    "/api/banks/ma-fit": "viewer",
    "/api/banks/ma-pro-forma": "viewer",
    "/api/ma-weight-validation": "viewer",
    "/api/xray-forward-return-validation": "viewer",
    "/api/filing-diff-population-summary": "viewer",
    "/api/backtest": "viewer",
    "/api/banks/filing-diff": "viewer",
    "/api/banks/risk-score": "viewer",
    "/api/banks/candles": "viewer",
    "/api/banks/market-snapshot": "viewer",
    "/api/market/coverage": "viewer",
    "/api/market/overview": "viewer",
    "/api/macro": "viewer",
    "/api/data-freshness": "viewer",
    "/api/metric-lineage": "viewer",
    "/api/banks/holding-company": "viewer",
    "/api/risk-leaderboard": "viewer",
    "/api/compare": "viewer",
    "/api/watchlist": "viewer",
    "/api/watchlist/note": "viewer",
    "/api/watchlist/rules": "viewer",
    "/api/screens": "viewer",
    "/api/peer-sets": "viewer",
    "/api/annotations": "viewer",
    "/api/scenarios": "viewer",
    "/api/custom-scenarios": "viewer",
    "/api/portfolio": "viewer",
    "/api/portfolio/summary": "viewer",
    "/api/alerts": "viewer",
    "/api/alerts/seen": "viewer",
    "/api/population-metrics": "viewer",
    "/api/metric-distribution": "viewer",
    "/api/percentile-heatmap": "viewer",
    "/api/asset-treemap": "viewer",
    "/api/banks/trends": "viewer",
    "/api/banks/trends-bulk": "viewer",
    # E12 — batched sparkline-column trend series for a population table.
    "/api/population-trends": "viewer",
    "/api/briefing": "viewer",
    "/api/cluster-diagnostics": "viewer",
    "/api/model-card": "viewer",
    "/api/county-concentration": "viewer",
    "/api/branch-map": "viewer",
    "/api/network": "viewer",
    "/api/filings/search": "viewer",
    "/api/filings/coverage": "viewer",
    "/api/banks/tearsheet": "viewer",
    "/api/banks/stress-test": "analyst",
    "/api/banks/stress-test-bulk": "analyst",
    "/api/banks/stress-test-compare": "analyst",
    "/api/banks/stress-test-surface": "analyst",
    "/api/banks/stress-test-projection": "analyst",
    "/api/banks/liquidity-survival": "analyst",
    "/api/banks/correlated-stress": "analyst",
    "/api/banks/irrbb": "viewer",
    "/api/banks/segmented-stress-test": "analyst",
    "/api/assistant/ask": "analyst",
    "/api/activity/agent-runs": "analyst",
    "/api/activity/audit-log": "analyst",
    # G4 — self-service export/delete, scoped server-side to the caller's own
    "/api/privacy/export": "viewer",
    "/api/privacy/data": "viewer",
}

ROUTES = [
    ("GET", "/api/health", lambda q, claims: {"status": "ok"}),
    # F19 — served through the normal dict-returning dispatch (unlike
    # /metrics, which returns Prometheus text format and is special-cased in
    # both transports) so it gets the same ETag/Cache-Control treatment every
    # other successful GET does. References ROUTES/POST_ROUTES/DELETE_ROUTES
    # by NAME inside the lambda (not by value) — safe: the lambda body only
    # runs once a real request arrives, long after module load has finished
    # building these tables, even though this entry sits inside ROUTES itself.
    ("GET", "/api/openapi.json", lambda q, claims: openapi_spec.build_openapi_spec(
        get_routes=ROUTES, post_routes=POST_ROUTES, delete_routes=DELETE_ROUTES,
        route_tiers=ROUTE_TIERS, open_routes=auth.OPEN_ROUTES)),
    ("GET", "/api/population", lambda q, claims: _population_summary()),
    # D3 — every landed quarter (newest first) + which one is "latest", for the
    # global quarter selector. Not itself quarter-scoped by a `quarter` param.
    ("GET", "/api/quarters", lambda q, claims: {
        "quarters": data.available_quarters(), "latest": data.latest_quarter()}),
    ("GET", "/api/banks", lambda q, claims: tools.list_banks(
        query=q.get("query"), state=q.get("state"), country=q.get("country"),
        min_assets_b=_f(q.get("min_assets_b")), max_assets_b=_f(q.get("max_assets_b")),
        limit=int(q.get("limit", 20)))),
    ("GET", "/api/banks/profile", lambda q, claims: tools.get_bank_profile(
        _cap(q["cert"]), as_of=q.get("as_of"), quarter=q.get("quarter"),
        peer_basis=q.get("peer_basis", "global"))),
    ("GET", "/api/banks/xray", lambda q, claims: tools.get_bank_xray(
        _cap(q["cert"]), quarter=q.get("quarter"))),
    ("GET", "/api/banks/peer-cluster", lambda q, claims: tools.get_peer_cluster(
        _cap(q["cert"]), quarter=q.get("quarter"))),
    ("GET", "/api/banks/ma-fit", lambda q, claims: tools.find_ma_matches(
        _cap(q["cert"]), top_n=int(q.get("top_n", 8)), quarter=q.get("quarter"))),
    ("GET", "/api/banks/ma-pro-forma", lambda q, claims: tools.get_ma_pro_forma(
        _cap(q["target_cert"]), _cap(q["acquirer_cert"]),
        premium_to_tbv_pct=_f(q.get("premium_to_tbv_pct"), 20.0),
        cost_synergies_pct_of_target_opex=_f(q.get("cost_synergies_pct_of_target_opex"), 30.0),
        tax_rate_pct=_f(q.get("tax_rate_pct"), 21.0))),
    ("GET", "/api/ma-weight-validation", lambda q, claims: tools.get_ma_weight_validation()),
    ("GET", "/api/xray-forward-return-validation",
     lambda q, claims: tools.get_xray_forward_return_validation()),
    ("GET", "/api/filing-diff-population-summary",
     lambda q, claims: tools.get_filing_diff_population_summary()),
    ("GET", "/api/backtest", lambda q, claims: tools.get_backtest_results()),
    ("GET", "/api/banks/stress-test", lambda q, claims: tools.run_stress(
        _cap(q["cert"]), loan_loss_pct=_f(q.get("loan_loss_pct"), 3.0),
        deposit_outflow_pct=_f(q.get("deposit_outflow_pct"), 15.0),
        rate_shock_bps=_f(q.get("rate_shock_bps"), 200.0))),
    ("GET", "/api/banks/filing-diff", lambda q, claims: tools.diff_filings(
        _cap(q["cert"]), quarter_a=q.get("quarter_a"), quarter_b=q.get("quarter_b"))),
    ("GET", "/api/banks/risk-score", lambda q, claims: tools.get_risk_score(
        _cap(q["cert"]), quarter=q.get("quarter"))),
    ("GET", "/api/banks/candles", lambda q, claims: tools.get_price_candles(
        _cap(q["cert"]), limit_days=int(q.get("limit_days", 180)))),
    ("GET", "/api/banks/market-snapshot", lambda q, claims: tools.get_market_snapshot(_cap(q["cert"]))),
    ("GET", "/api/market/coverage", lambda q, claims: tools.get_market_coverage()),
    ("GET", "/api/market/overview", lambda q, claims: tools.get_market_overview(
        certs=_certs(q["certs"]) if q.get("certs") else None,
        top_n=int(q.get("top_n", 20)), window_days=int(q.get("window_days", 180)))),
    ("GET", "/api/macro", lambda q, claims: tools.get_macro_data()),
    ("GET", "/api/data-freshness", lambda q, claims: tools.get_data_freshness()),
    ("GET", "/api/metric-lineage", lambda q, claims: tools.get_metric_lineage(
        _cap(q["cert"]), q["metric"], quarter=q.get("quarter"))),
    ("GET", "/api/banks/holding-company", lambda q, claims: tools.get_holding_company(_cap(q["cert"]))),
    ("GET", "/api/risk-leaderboard", lambda q, claims: tools.get_risk_leaderboard(
        top_n=int(q.get("top_n", 25)), state=q.get("state"), cluster_label=q.get("cluster_label"),
        quarter=q.get("quarter"))),
    ("GET", "/api/compare", lambda q, claims: tools.compare_banks(
        _certs(q["certs"]), metrics=q["metrics"].split(",") if q.get("metrics") else None,
        quarter=q.get("quarter"))),
    ("GET", "/api/watchlist", lambda q, claims: {
        "items": common_db.fetch_watchlist(_require_sub(claims))}),
    ("GET", "/api/population-metrics", lambda q, claims: tools.get_population_metrics(
        q["group"], limit=int(q.get("limit", 2000)), sort_by=q.get("sort_by"),
        descending=q.get("descending", "true").lower() != "false", quarter=q.get("quarter"),
        certs=_certs(q["certs"]) if q.get("certs") else None)),
    ("GET", "/api/metric-distribution", lambda q, claims: tools.get_metric_distribution(
        q["metric"], bins=int(q.get("bins", 30)), quarter=q.get("quarter"),
        certs=_certs(q["certs"]) if q.get("certs") else None)),
    ("GET", "/api/percentile-heatmap", lambda q, claims: tools.get_percentile_heatmap(
        top_n=int(q.get("top_n", 40)), sort_by=q.get("sort_by", "total_assets"),
        metrics=q["metrics"].split(",") if q.get("metrics") else None, quarter=q.get("quarter"),
        certs=_certs(q["certs"]) if q.get("certs") else None)),
    ("GET", "/api/asset-treemap", lambda q, claims: tools.get_asset_treemap(
        group_by=q.get("group_by", "peer_cluster_label"), quarter=q.get("quarter"))),
    ("GET", "/api/banks/trends", lambda q, claims: tools.get_bank_trends(_cap(q["cert"]))),
    # E10 — same trajectory as /api/banks/trends, for a whole peer set in one
    # request (certs travels comma-separated, same reason /api/compare does).
    ("GET", "/api/banks/trends-bulk", lambda q, claims: tools.get_bulk_bank_trends(_certs(q["certs"]))),
    # E12 — batched trailing-quarter series for a table's sparkline column:
    # certs + metrics travel comma-separated, same convention as
    # /api/compare and /api/banks/trends-bulk above.
    ("GET", "/api/population-trends", lambda q, claims: tools.get_population_trend_sparklines(
        _certs(q["certs"]), q["metrics"].split(","))),
    ("GET", "/api/briefing", lambda q, claims: tools.get_quarterly_briefing(
        top_n=int(q.get("top_n", 8)))),
    ("GET", "/api/cluster-diagnostics", lambda q, claims: tools.get_cluster_diagnostics()),
    ("GET", "/api/model-card", lambda q, claims: tools.get_model_card()),
    ("GET", "/api/county-concentration", lambda q, claims: tools.get_county_concentration(
        state=q.get("state"), top_n=int(q.get("top_n", 100)))),
    ("GET", "/api/branch-map", lambda q, claims: tools.get_branch_map(state=q.get("state"))),
    ("GET", "/api/network", lambda q, claims: tools.get_ma_network(top_n=int(q.get("top_n", 150)))),
    ("GET", "/api/filings/search", lambda q, claims: tools.search_filings_text(
        q["query"], top_n=int(q.get("top_n", 8)))),
    ("GET", "/api/filings/coverage", lambda q, claims: tools.get_filings_coverage()),
    ("GET", "/api/banks/tearsheet", lambda q, claims: BinaryResponse(
        tearsheet.build_tearsheet_pdf(_cap(q["cert"])), "application/pdf",
        f"banklens-tearsheet-{q['cert']}.pdf")),
    ("GET", "/api/banks/stress-test-bulk", lambda q, claims: tools.run_bulk_stress_test(
        _certs(q["certs"]), loan_loss_pct=_f(q.get("loan_loss_pct"), 3.0),
        deposit_outflow_pct=_f(q.get("deposit_outflow_pct"), 15.0),
        rate_shock_bps=_f(q.get("rate_shock_bps"), 200.0))),
    ("GET", "/api/banks/stress-test-compare", lambda q, claims: tools.run_stress_comparison(
        _cap(q["cert"]), loan_loss_pct=_f(q.get("loan_loss_pct"), 3.0),
        deposit_outflow_pct=_f(q.get("deposit_outflow_pct"), 15.0),
        rate_shock_bps=_f(q.get("rate_shock_bps"), 200.0))),
    # E3 — (deposit_outflow x rate_shock) grid for one bank, for the Stress Lab's
    # CET1 surface heatmap. Computed server-side in one request (see
    # tools.run_stress_surface's docstring for why run_bulk_stress_test's cross-BANK
    # batching can't be reused for a cross-SCENARIO grid on one bank).
    ("GET", "/api/banks/stress-test-surface", lambda q, claims: tools.run_stress_surface(
        _cap(q["cert"]), loan_loss_pct=_f(q.get("loan_loss_pct"), 3.0),
        deposit_outflow_max_pct=_f(q.get("deposit_outflow_max_pct"), 90.0),
        rate_shock_max_bps=_f(q.get("rate_shock_max_bps"), 500.0),
        steps=int(q.get("steps", 7)))),
    ("GET", "/api/banks/stress-test-projection", lambda q, claims: tools.run_stress_projection(
        _cap(q["cert"]), loan_loss_pct=_f(q.get("loan_loss_pct"), 3.0),
        deposit_outflow_pct=_f(q.get("deposit_outflow_pct"), 15.0),
        rate_shock_bps=_f(q.get("rate_shock_bps"), 200.0),
        horizon_quarters=int(q.get("horizon_quarters", 4)),
        phase_in=q.get("phase_in", "true").lower() != "false",
        apply_ppnr_offset=q.get("apply_ppnr_offset", "true").lower() != "false")),
    ("GET", "/api/banks/liquidity-survival", lambda q, claims: tools.get_liquidity_survival(
        _cap(q["cert"]), quarterly_outflow_pct=_f(q.get("quarterly_outflow_pct"), 15.0))),
    ("GET", "/api/banks/correlated-stress", lambda q, claims: tools.run_correlated_stress(
        _cap(q["cert"]), rate_shock_bps=_f(q.get("rate_shock_bps"), 300.0),
        severity=q.get("severity", "moderate"))),
    ("GET", "/api/banks/irrbb", lambda q, claims: tools.get_irrbb(
        _cap(q["cert"]), parallel_shock_bps=_f(q.get("parallel_shock_bps"), 200.0))),
    ("GET", "/api/banks/segmented-stress-test", lambda q, claims: tools.run_segmented_stress_test(
        _cap(q["cert"]), severity_multiplier=_f(q.get("severity_multiplier"), 3.0),
        deposit_outflow_pct=_f(q.get("deposit_outflow_pct"), 15.0),
        rate_shock_bps=_f(q.get("rate_shock_bps"), 200.0))),
    ("GET", "/api/activity/agent-runs", lambda q, claims: {
        "items": common_db.fetch_recent_agent_runs(int(q.get("limit", 50)))}),
    ("GET", "/api/activity/audit-log", lambda q, claims: {
        "items": common_db.fetch_recent_audit(int(q.get("limit", 50)))}),
    # D2 — saved screens, watchlist notes/rules, alerts.
    ("GET", "/api/watchlist/rules", lambda q, claims: {
        "items": common_db.fetch_watchlist_rules(_require_sub(claims))}),
    ("GET", "/api/screens", lambda q, claims: {
        "items": common_db.fetch_saved_screens(_require_sub(claims))}),
    # D5 — named, persisted peer sets.
    ("GET", "/api/peer-sets", lambda q, claims: {
        "items": common_db.fetch_peer_sets(_require_sub(claims))}),
    # D7 — analyst annotations for one bank, shared across users (not
    # per-caller like watchlist/peer-sets/screens above).
    ("GET", "/api/annotations", lambda q, claims: {
        "items": common_db.fetch_annotations(_cap(q["cert"]))}),
    # D10 — named scenario registry (config/scenarios.json) + user-saved ones.
    ("GET", "/api/scenarios", lambda q, claims: _scenario_library()),
    ("GET", "/api/custom-scenarios", lambda q, claims: {
        "items": common_db.fetch_custom_scenarios(_require_sub(claims))}),
    # D11 — exposure/portfolio positions + aggregate view.
    ("GET", "/api/portfolio", lambda q, claims: {
        "items": common_db.fetch_portfolio_positions(_require_sub(claims))}),
    ("GET", "/api/portfolio/summary", lambda q, claims: _portfolio_summary(claims)),
    ("GET", "/api/alerts", lambda q, claims: {
        "items": common_db.fetch_alerts(
            _require_sub(claims), limit=int(q.get("limit", 50)),
            unseen_only=q.get("unseen_only", "false").lower() == "true")}),
    # G4 — self-service export of everything stored against the caller's own
    # user_sub (watchlist, agent-run transcripts, audit-log entries where
    # scopable — see common_db.export_user_data's docstring for the audit-log
    # caveat). No new handler function needed: the query is entirely in db.py.
    ("GET", "/api/privacy/export", lambda q, claims: common_db.export_user_data(_require_sub(claims))),
]

POST_ROUTES = [
    ("POST", "/api/watchlist", lambda body, claims: _watchlist_add(body, claims)),
    ("POST", "/api/watchlist/note", lambda body, claims: _watchlist_note(body, claims)),
    ("POST", "/api/watchlist/rules", lambda body, claims: _watchlist_rule_add(body, claims)),
    ("POST", "/api/screens", lambda body, claims: _screen_save(body, claims)),
    ("POST", "/api/peer-sets", lambda body, claims: _peer_set_save(body, claims)),
    ("POST", "/api/annotations", lambda body, claims: _annotation_save(body, claims)),
    ("POST", "/api/custom-scenarios", lambda body, claims: _custom_scenario_save(body, claims)),
    ("POST", "/api/portfolio", lambda body, claims: _portfolio_add(body, claims)),
    ("POST", "/api/alerts/seen", lambda body, claims: _alert_mark_seen(body, claims)),
    # F16 — NOT here: /api/assistant/ask streams Server-Sent Events instead of
    # returning one JSON dict, so it can't go through this dict-returning
    # dispatch table. Both transports (Handler.do_POST / wsgi_app) special-case
    # the path directly, still authorizing against the SAME "analyst" tier
    # (ROUTE_TIERS below still carries the entry — see
    # _authenticate_and_authorize) and test_route_policy.py's drift check,
    # which reads ROUTE_TIERS/policy.rego, not this table.
]

DELETE_ROUTES = [
    ("DELETE", "/api/watchlist", lambda q, claims: _watchlist_remove(q, claims)),
    ("DELETE", "/api/watchlist/rules", lambda q, claims: _watchlist_rule_remove(q, claims)),
    ("DELETE", "/api/screens", lambda q, claims: _screen_remove(q, claims)),
    ("DELETE", "/api/peer-sets", lambda q, claims: _peer_set_remove(q, claims)),
    ("DELETE", "/api/annotations", lambda q, claims: _annotation_remove(q, claims)),
    ("DELETE", "/api/custom-scenarios", lambda q, claims: _custom_scenario_remove(q, claims)),
    ("DELETE", "/api/portfolio", lambda q, claims: _portfolio_remove(q, claims)),
    # G4 — deletes every row stored against the caller's own user_sub across
    # every table listed in export_user_data (see docs/privacy.md).
    ("DELETE", "/api/privacy/data", lambda q, claims: common_db.delete_user_data(_require_sub(claims))),
]


def _f(v, default=None):
    return float(v) if v not in (None, "") else default


def _certs(v: str) -> list[int]:
    # do_GET's query parser collapses repeated keys (parse_qs -> first value
    # only), so a list param has to travel as one comma-separated string —
    # no existing precedent for a list query param elsewhere in this file.
    return [int(c) for c in v.split(",") if c.strip()]


def _require_sub(claims: dict) -> str:
    # Real Keycloak tokens always carry "sub" — this only trips in the
    # documented BANKLENS_AUTH_ENABLED=false local dev escape hatch, which
    # has no real user to scope a watchlist to.
    sub = claims.get("sub")
    if not sub:
        raise ValueError("watchlist requires an authenticated user (no 'sub' claim on "
                         "the token) — set BANKLENS_AUTH_ENABLED=true")
    return sub


def _watchlist_add(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.add_watchlist_item(sub, _cap(body["cert"]))
    return {"items": common_db.fetch_watchlist(sub)}


def _watchlist_remove(query: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.remove_watchlist_item(sub, _cap(query["cert"]))
    return {"items": common_db.fetch_watchlist(sub)}


def _watchlist_note(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.update_watchlist_note(sub, _cap(body["cert"]), body.get("note") or "")
    return {"items": common_db.fetch_watchlist(sub)}


_RULE_TYPES = {"metric_threshold", "metric_delta", "xray_severity_increase", "risk_leaderboard_entry"}


def _watchlist_rule_add(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    rule_type = body.get("rule_type")
    if rule_type not in _RULE_TYPES:
        raise ValueError(f"rule_type must be one of {sorted(_RULE_TYPES)}")
    common_db.add_watchlist_rule(
        sub, _cap(body["cert"]), rule_type,
        metric=body.get("metric"), operator=body.get("operator"),
        threshold=_f(body.get("threshold")), top_n=int(body["top_n"]) if body.get("top_n") else None)
    return {"items": common_db.fetch_watchlist_rules(sub)}


def _watchlist_rule_remove(query: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.remove_watchlist_rule(sub, int(query["rule_id"]))
    return {"items": common_db.fetch_watchlist_rules(sub)}


def _screen_save(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("a saved screen needs a non-empty name")
    common_db.save_screen(sub, name, body.get("filters") or {})
    return {"items": common_db.fetch_saved_screens(sub)}


def _screen_remove(query: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.delete_saved_screen(sub, int(query["screen_id"]))
    return {"items": common_db.fetch_saved_screens(sub)}


def _peer_set_save(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("a peer set needs a non-empty name")
    certs = [int(c) for c in (body.get("certs") or [])]
    if len(certs) < 2:
        raise ValueError("a peer set needs at least 2 banks")
    common_db.save_peer_set(sub, name, certs)
    return {"items": common_db.fetch_peer_sets(sub)}


def _peer_set_remove(query: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.delete_peer_set(sub, int(query["peer_set_id"]))
    return {"items": common_db.fetch_peer_sets(sub)}


def _annotation_save(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    note_md = (body.get("note_md") or "").strip()
    if not note_md:
        raise ValueError("an annotation needs non-empty text")
    cert = _cap(body["cert"])
    common_db.add_annotation(sub, cert, note_md, quarter=body.get("quarter"))
    return {"items": common_db.fetch_annotations(cert)}


def _annotation_remove(query: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    cert = _cap(query["cert"])
    common_db.delete_annotation(sub, int(query["annotation_id"]))
    return {"items": common_db.fetch_annotations(cert)}


_SCENARIOS_PATH = REPO / "config" / "scenarios.json"


def _scenario_library() -> dict:
    """D10 — named stress scenarios (config/scenarios.json). Read fresh each
    call: this is a small, human-edited config file, not worth a cache-
    invalidation story for."""
    if not _SCENARIOS_PATH.exists():
        return {"version": 0, "scenarios": []}
    return json.loads(_SCENARIOS_PATH.read_text(encoding="utf-8"))


def _custom_scenario_save(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("a scenario needs a non-empty name")
    common_db.save_custom_scenario(
        sub, name, _f(body.get("loan_loss_pct"), 3.0),
        _f(body.get("deposit_outflow_pct"), 15.0), _f(body.get("rate_shock_bps"), 200.0))
    return {"items": common_db.fetch_custom_scenarios(sub)}


def _custom_scenario_remove(query: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.delete_custom_scenario(sub, int(query["scenario_id"]))
    return {"items": common_db.fetch_custom_scenarios(sub)}


def _portfolio_add(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    exposure_type = (body.get("exposure_type") or "").strip()
    if not exposure_type:
        raise ValueError("a position needs a non-empty exposure_type")
    common_db.add_portfolio_position(
        sub, _cap(body["cert"]), _f(body.get("exposure_amount"), 0.0), exposure_type)
    return {"items": common_db.fetch_portfolio_positions(sub)}


def _portfolio_remove(query: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.delete_portfolio_position(sub, int(query["position_id"]))
    return {"items": common_db.fetch_portfolio_positions(sub)}


def _portfolio_summary(claims: dict) -> dict:
    sub = _require_sub(claims)
    positions = common_db.fetch_portfolio_positions(sub)
    exposure_by_cert: dict[int, float] = {}
    for p in positions:
        exposure_by_cert[p["cert"]] = exposure_by_cert.get(p["cert"], 0.0) + p["exposure_amount"]
    return tools.summarize_portfolio(exposure_by_cert)


def _alert_mark_seen(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.mark_alert_seen(sub, int(body["alert_id"]))
    return {"items": common_db.fetch_alerts(sub)}


# F16 — configurable deadline for POST /api/assistant/ask (was previously
# unbounded: "Ollama's own client retries with a 120s timeout, run_agent
# loops up to 6 turns... the request just blocks", per this route's old
# docstring). 120s default matches that pre-existing Ollama-client timeout,
# so the common case (a slow but eventually-responding local model) is
# unaffected; it's the genuinely-hung-provider case this now bounds.
_ASSISTANT_DEADLINE_S = float(os.environ.get("BANKLENS_ASSISTANT_DEADLINE_S", "120"))
# Extra time given to a cancelled run_agent loop to notice `cancel_event` at
# its next turn boundary and return (see agent.py's cooperative-cancellation
# docstring) before this route gives up on it outright.
_ASSISTANT_CANCEL_GRACE_S = 10.0


def _sse_line(event: str, data) -> bytes:
    # SSE wire format: an `event:` line naming the type, a `data:` line
    # carrying one JSON value (SSE itself has no structured-payload concept),
    # a blank line terminating the event. `data` must not itself contain a
    # literal newline — json.dumps default output never does.
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode("utf-8")


def _stream_assistant_answer(persona, question: str, roles: list[str] | None,
                             history: list[dict] | None = None):
    """Runs `run_agent` on a background thread and yields (event, payload)
    pairs as they happen: "tool_call"/"tool_result"/"final" (run_agent's own
    on_event kinds, forwarded live — not batched until the end, which is the
    whole point of F16's move to streaming), then exactly one terminal event,
    either ("result", AgentResult) on success or ("error", {"error": str}).

    Deadline (F16): `_ASSISTANT_DEADLINE_S` after this generator starts, a
    still-running loop is asked to stop cooperatively (agent.py's
    `cancel_event`, checked between turns) and given `_ASSISTANT_CANCEL_GRACE_S`
    to do so and return a real (partial) AgentResult. A provider call that's
    outright HUNG — never returns at all, the exact case this route's old
    docstring warned about — can't be preempted mid-call with the stdlib
    alone; past the grace period this generator stops waiting and yields
    "error" so the HTTP response completes within a bounded time regardless.
    The abandoned worker thread is a daemon thread: harmless once nothing is
    listening for its result, and it exits on its own whenever the hung call
    eventually returns or errors.
    """
    events: "queue.Queue[tuple[str, object]]" = queue.Queue()
    cancel_event = threading.Event()
    outcome: dict = {}

    def _on_event(kind, payload):
        events.put((kind, payload))

    def _worker():
        try:
            outcome["result"] = run_agent(persona, question, roles=roles, history=history,
                                          on_event=_on_event, cancel_event=cancel_event)
        except Exception as e:
            outcome["error"] = str(e)
        finally:
            events.put(("__done__", None))

    threading.Thread(target=_worker, daemon=True, name="assistant-ask-worker").start()

    deadline_at = time.monotonic() + _ASSISTANT_DEADLINE_S
    grace_at: float | None = None  # set once the deadline actually fires
    while True:
        now = time.monotonic()
        if grace_at is None:
            wait = deadline_at - now
            if wait <= 0:
                cancel_event.set()
                grace_at = now + _ASSISTANT_CANCEL_GRACE_S
                yield ("timeout", {
                    "message": f"exceeded the {_ASSISTANT_DEADLINE_S:.0f}s deadline; asking "
                              "the model to stop at its next turn boundary"})
                continue
        else:
            wait = grace_at - now
            if wait <= 0:
                yield ("error", {"error": "provider did not respond to cancellation within "
                                          f"{_ASSISTANT_CANCEL_GRACE_S:.0f}s; abandoning this request"})
                return

        try:
            kind, payload = events.get(timeout=wait)
        except queue.Empty:
            continue  # re-loop: recompute which phase (pre/post-deadline) we're in

        if kind == "__done__":
            break
        yield (kind, payload)

    if "result" in outcome:
        yield ("result", outcome["result"])
    else:
        yield ("error", {"error": outcome.get("error", "unknown error")})


def _assistant_ask_sse(body: dict, claims: dict, request_id: str | None = None):
    """Generator of raw SSE wire bytes for POST /api/assistant/ask (F16) —
    the persona/question validation, roles resolution and run-persistence
    side effects `_assistant_ask` used to do around one blocking `run_agent`
    call, now wrapping `_stream_assistant_answer`'s live event stream instead.
    Shared verbatim by both transports (Handler.do_POST / wsgi_app) so this
    logic exists in exactly one place, same as `_route_request` for every
    other route. Caller is responsible for auth (via
    `_authenticate_and_authorize`) and SSE response headers BEFORE iterating
    this — by the time the first byte here is written, the response is
    already committed to 200 and streaming.

    `request_id` (F17): embedded in every "error" event's payload — an SSE
    stream has no response body separate from its events, so this is the
    equivalent of `_route_request`'s "embed request_id in every error
    response body" for a route that can't use that dict-returning path.
    Optional (auto-generated if omitted) purely so direct unit tests of this
    function (see test_bridge.py) don't need to care about it.
    """
    request_id = request_id or _new_request_id()
    persona_key = body.get("persona")
    persona = PERSONAS.get(persona_key)
    if persona is None:
        yield _sse_line("error", {"error": f"unknown persona '{persona_key}' — choose one of {list(PERSONAS)}",
                                  "request_id": request_id})
        return
    question = (body.get("question") or "").strip()
    if not question:
        yield _sse_line("error", {"error": "question must be a non-empty string", "request_id": request_id})
        return

    # D12 — multi-turn conversation state. The client resends the prior
    # question/answer transcript on every request (this route, like every
    # other one here, is otherwise stateless — no server-side session store to
    # invalidate or leak across users); we just validate its shape defensively
    # since it's caller-supplied JSON, same as any other request field.
    raw_history = body.get("history")
    history: list[dict] = []
    if isinstance(raw_history, list):
        for turn in raw_history:
            if (isinstance(turn, dict) and turn.get("role") in ("user", "assistant")
                    and isinstance(turn.get("content"), str)):
                history.append({"role": turn["role"], "content": turn["content"]})

    # G2: this route is already analyst-gated at the REST layer (ROUTE_TIERS
    # above), but the agent can drive ANY tool in the persona's static list
    # through the MCP loop — roles_from_claims(claims) is the same call every
    # other route already makes, threaded through so run_agent additionally
    # intersects the persona's tools against what the CALLER's roles actually
    # permit (G1's OPA policy), not just what the persona nominally allows.
    roles = auth.roles_from_claims(claims)

    final_result = None
    for kind, payload in _stream_assistant_answer(persona, question, roles, history):
        if kind == "result":
            final_result = payload
            out = to_json(payload)
            # Handed back so the client's NEXT request can resend it as
            # `history` — this turn's question plus the (possibly partial)
            # answer, appended to what was already sent in.
            out["history"] = [*history, {"role": "user", "content": question},
                              {"role": "assistant", "content": payload.answer}]
            yield _sse_line("result", out)
        elif kind == "error":
            yield _sse_line(kind, {**payload, "request_id": request_id})
        else:
            yield _sse_line(kind, payload)

    if final_result is None:
        return  # errored, or the hard grace period expired — nothing to persist

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    out = RUNS_DIR / f"{now.strftime('%Y%m%dT%H%M%S%f')}.json"
    payload = to_json(final_result)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    try:
        model_id = providers.resolve_model(final_result.provider, None)
        common_db.record_agent_run(
            persona=persona.key, provider=final_result.provider, model=model_id,
            question=question, answer=final_result.answer, ok=not final_result.partial,
            transcript_path=str(out.relative_to(REPO)), ts=now,
            user_sub=claims.get("sub"))
    except Exception:
        # Same tradeoff cli.py makes: the transcript on disk is the real
        # content; the Postgres index is queryability, not the record of
        # truth — a DB hiccup shouldn't fail an otherwise-successful answer.
        traceback.print_exc()


def _population_summary() -> dict:
    """Trimmed population for the peer-position scatter (avoid shipping the full Gold)."""
    pop = data.population()["gold"]
    return {"banks": [{
        "cert": g["cert_number"], "name": g["name"], "state": g.get("state"),
        "assets_b": round((g.get("total_assets") or 0) / 1e9, 2),
        "cre_pct": g.get("concentration_ratio_cre"),
        "uninsured_pct": g.get("uninsured_deposit_pct"),
        "cet1": g.get("cet1_ratio"),
        "cluster_id": g.get("peer_cluster_id"),
        "cluster_label": g.get("peer_cluster_label"),
    } for g in pop if g.get("concentration_ratio_cre") is not None
       and g.get("uninsured_deposit_pct") is not None]}


# Origins allowed to call this bridge. `Access-Control-Allow-Origin: *` would let
# ANY webpage a user has open in their browser query this service while it's
# running (a real local attack surface, not theoretical — it's what made the
# path-traversal bug found in banklens_mcp.data browser-reachable rather than
# merely local-process-reachable). An explicit allowlist, echoed back only on
# match, closes that off.
#
# BANKLENS_ALLOWED_ORIGINS (comma-separated) adds/overrides for a deployed
# frontend; the three localhost defaults below (Vite dev server, Docker Compose
# container, K8s dev overlay's NodePort) always remain allowed so local dev is
# never broken by a missing env var.
_ALLOWED_ORIGINS = {
    "http://localhost:5173", "http://localhost:8080", "http://localhost:30080",
} | {o.strip() for o in os.environ.get("BANKLENS_ALLOWED_ORIGINS", "").split(",") if o.strip()}


def _cors_headers(origin: str | None) -> dict[str, str]:
    headers = {
        # Narrowed from "*": the frontend (api.ts) only ever sends these two —
        # Authorization (Bearer token) and Content-Type (JSON POST bodies). A
        # wildcard here buys nothing for this app and widens what a malicious
        # page could try to smuggle through a preflight.
        "Access-Control-Allow-Headers": "Authorization, Content-Type, If-None-Match",
        # GET/POST are CORS-safelisted methods (exempt from the preflight
        # Access-Control-Allow-Methods check regardless of this header), but
        # DELETE (added for watchlist removal) is not — without this,
        # DELETE's own preflight OPTIONS would pass, then the browser would
        # still block the real request.
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        # F10/F17 — ETag and X-Request-ID aren't CORS-safelisted RESPONSE
        # headers (unlike Cache-Control/Content-Length/etc, which browsers
        # always expose to JS); without this, api.ts could never read either
        # one — ETag for its conditional-GET logic, X-Request-ID so a caught
        # error can surface the id a user quotes back for support.
        "Access-Control-Expose-Headers": "ETag, X-Request-ID",
    }
    if origin in _ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


# F10 — GET routes that must never be shared/long-lived-cached: per-user state
# (watchlist, saved screens, alerts, privacy export/delete) that changes on
# THIS user's own write actions, activity feeds that can reveal other users'
# actions, and anything meant to reflect "right now" rather than "as of the
# last quarterly refresh". Every other GET route serves data that only
# changes when a new quarter lands (see quarterly_refresh.py's
# invalidate_cache() call) or a landing script runs, so a real ETag +
# long max-age is safe and, for /api/population's ~hundreds-of-KB payload
# in particular, the whole point of this change.
_NON_CACHEABLE_PATHS = {
    "/api/health", "/api/data-freshness",
    "/api/watchlist", "/api/watchlist/note", "/api/watchlist/rules",
    "/api/screens", "/api/alerts", "/api/alerts/seen",
    "/api/activity/agent-runs", "/api/activity/audit-log",
    "/api/privacy/export", "/api/privacy/data",
}

_CACHE_MAX_AGE_SECONDS = int(os.environ.get("BANKLENS_CACHE_MAX_AGE_SECONDS", str(24 * 3600)))
_MIN_GZIP_BYTES = 512  # compressing a tiny body just adds gzip's own framing overhead


def _etag_for(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:20] + '"'


def _prepare_json_body(payload: dict, *, cacheable: bool, accept_encoding: str | None,
                       if_none_match: str | None) -> tuple[int | None, bytes, dict[str, str]]:
    """Serializes `payload`, and for a cacheable GET response: computes a
    content-addressed ETag, honors a matching If-None-Match with a real 304
    (empty body — the whole point, no re-shipping the payload the client
    already has), and gzip-compresses whatever body IS sent when the client
    advertises support. `/api/population` and friends are immutable once a
    quarter lands, so a repeat visit now costs a 304 or a compressed body
    instead of re-transferring the full JSON every time.

    Returns (status_override, body_bytes, extra_headers); status_override is
    only set to 304 to signal the caller to send an empty body at that status
    instead of the normal one.
    """
    body = json.dumps(payload, default=str).encode("utf-8")
    headers: dict[str, str] = {}
    status_override: int | None = None

    if cacheable:
        etag = _etag_for(body)
        headers["ETag"] = etag
        headers["Cache-Control"] = f"public, max-age={_CACHE_MAX_AGE_SECONDS}, must-revalidate"
        headers["Vary"] = "Accept-Encoding"
        if if_none_match and if_none_match == etag:
            return 304, b"", headers

    if accept_encoding and "gzip" in accept_encoding and len(body) >= _MIN_GZIP_BYTES:
        body = gzip.compress(body, compresslevel=6)
        headers["Content-Encoding"] = "gzip"

    return status_override, body, headers


_ROUTES_BY_METHOD = {"GET": ROUTES, "POST": POST_ROUTES, "DELETE": DELETE_ROUTES}


def _warn_auth_disabled() -> None:
    # Loud on purpose (stderr, not logging.debug): if the loopback bind check
    # in main() is somehow bypassed (e.g. someone proxies loopback traffic out
    # to a real network), this is the last line of defense that makes an
    # unauthenticated request impossible to miss in any log tail/aggregator.
    sys.stderr.write(
        "\n" + "!" * 78 + "\n"
        "! BANKLENS_AUTH_ENABLED=false — this request was served with NO auth check.\n"
        "! Every route is open. This must never be reachable from outside localhost.\n"
        + "!" * 78 + "\n\n"
    )


def _authenticate_and_authorize(route: str, method: str, auth_header: str | None) -> dict:
    """The exact authenticate+authorize sequence `_route_request` runs for
    every dict-returning route, factored out (F16) so the assistant SSE path
    — which bypasses `_route_request` entirely to stream instead of returning
    one JSON blob — still goes through the identical check rather than a
    second, maintained-by-hand copy of it. Raises the same `auth.AuthError` /
    `auth.ForbiddenError` / `auth.AuthUnavailable` `_route_request` catches."""
    if not auth.AUTH_ENABLED:
        _warn_auth_disabled()
    claims: dict = {}
    if auth.AUTH_ENABLED and route not in auth.OPEN_ROUTES:
        claims = auth.authenticate(auth_header)
        auth.authorize(route, method, auth.roles_from_claims(claims))
    return claims


def _new_request_id() -> str:
    # 16 hex chars (64 bits) — short enough a user can plausibly read it back
    # over a support ticket, long enough collisions don't matter in practice.
    return uuid.uuid4().hex[:16]


def _log_request(*, request_id: str, method: str, route: str, status: int,
                 latency_s: float, subject: str | None, error_class: str | None) -> None:
    """F17 — one JSON line per request to STDOUT (stderr stays reserved for
    the loud auth-disabled banner and raw tracebacks — see `_warn_auth_disabled`
    and the `except Exception` branch below, which now also tags its
    traceback with this same `request_id` so the two streams correlate).
    `request_id` is echoed as the X-Request-ID response header on every
    response (both transports) and embedded in every ERROR response body, so
    a request ID copied from a browser's network tab — or quoted by a user
    reporting a bug — locates this exact line. Structured (one JSON object,
    not a free-text format) so a log aggregator can index `route`/`status`/
    `latency_ms` without a regex. Complementary to, not a replacement for,
    the existing Prometheus counters/histogram above, which answer "how is
    the service doing in aggregate" — this answers "what happened on THIS
    one request."
    """
    print(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(), "request_id": request_id,
        "method": method, "route": route, "status": status,
        "latency_ms": round(latency_s * 1000, 2), "subject": subject,
        "error_class": error_class,
    }, default=str))


def _route_request(method: str, path: str, query: dict, body: dict,
                   auth_header: str | None, request_id: str | None = None) -> tuple[int, dict]:
    """THE single place routing + auth + handler-call + error-mapping + metrics
    happen — decoupled from both server transports (the stdlib
    ThreadingHTTPServer `Handler` below, for local dev; `wsgi_app`, for
    gunicorn in production). Every server mode calls through this exact
    function, so which transport served a request can never change what it
    returns. Returns (status, response_body) and never touches a socket
    itself, which is what makes it shareable between the two.

    `request_id` (F17): both transports generate one per real HTTP request
    and pass it through, so it can be echoed as an X-Request-ID response
    header AND logged here. Optional (auto-generated if omitted) purely so
    direct unit tests of this function (see test_bridge.py) don't need to
    care about it.
    """
    request_id = request_id or _new_request_id()
    arg = body if method == "POST" else query
    for m, route, fn in _ROUTES_BY_METHOD.get(method, []):
        if m == method and path == route:
            start = time.time()
            status = 200
            claims: dict = {}
            error_class: str | None = None
            try:
                claims = _authenticate_and_authorize(route, method, auth_header)
                result = fn(arg, claims)
            except auth.AuthError as e:
                status, result = 401, {"error": str(e)}
                error_class = type(e).__name__
            except auth.ForbiddenError as e:
                status, result = 403, {"error": str(e)}
                error_class = type(e).__name__
            except auth.AuthUnavailable as e:
                status, result = 503, {"error": str(e)}
                error_class = type(e).__name__
            except KeyError as e:
                status, result = 400, {"error": f"missing required param: {e}"}
                error_class = "KeyError"
            except ValueError as e:
                # F18 — every deliberate validation guard in the handler layer
                # (tools.py, the D-series watchlist/screens/etc. handlers)
                # raises ValueError on purpose for "the caller did something
                # wrong" — an unknown persona, a cert not in the population, a
                # peer set with fewer than 2 banks, and so on. str(e) is safe
                # to show back: it's OUR OWN message, not something leaked
                # from a lower layer, so 400 + the real text stays.
                status, result = 400, {"error": str(e)}
                error_class = "ValueError"
            except Exception as e:
                # Everything else is a genuine server fault — a missing data
                # file, an unhandled None deep in a transform, a real bug —
                # not the caller's fault, so 500 (not 400), so 5xx-based
                # alerting actually fires on it (F18's whole point). No
                # internal detail (str(e) could be a file path, a DB error, a
                # stack fragment) goes in the body; request_id is what a user
                # quotes, and the full exception is still in the traceback
                # below AND the structured log line, both tagged with the
                # same request_id, for whoever's on call to actually debug it.
                status, result = 500, {"error": "internal server error"}
                error_class = type(e).__name__
                sys.stderr.write(f"[{request_id}] ")
                traceback.print_exc()
            finally:
                REQUEST_COUNT.labels(route=route, status=str(status)).inc()
                REQUEST_LATENCY.labels(route=route).observe(time.time() - start)
                _log_request(request_id=request_id, method=method, route=route, status=status,
                            latency_s=time.time() - start, subject=claims.get("sub"),
                            error_class=error_class)
            if status >= 400 and isinstance(result, dict):
                result = {**result, "request_id": request_id}
            return status, result
    REQUEST_COUNT.labels(route="unmatched", status="404").inc()
    _log_request(request_id=request_id, method=method, route=path, status=404,
                latency_s=0.0, subject=None, error_class=None)
    return 404, {"error": f"no route for {path}", "request_id": request_id}


class Handler(BaseHTTPRequestHandler):
    """Dev-mode transport: stdlib `http.server`, zero installs beyond
    prometheus-client. No request timeout, no body-size cap, no rate limit —
    see `wsgi_app` below for the production transport that adds those."""

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, payload: dict | BinaryResponse, *, route: str | None = None,
             request_id: str | None = None):
        if isinstance(payload, BinaryResponse):
            self.send_response(status)
            self.send_header("Content-Type", payload.content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{payload.filename}"')
            self.send_header("Content-Length", str(len(payload.body)))
            if request_id:
                self.send_header("X-Request-ID", request_id)
            for k, v in _cors_headers(self.headers.get("Origin")).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload.body)
            return

        # F10 — cacheable only for a successful GET on a route that isn't
        # per-user/dynamic (see _NON_CACHEABLE_PATHS); a POST/DELETE result or
        # an error response is never a candidate regardless of route.
        cacheable = (status == 200 and self.command == "GET"
                    and route is not None and route not in _NON_CACHEABLE_PATHS)
        status_override, body, extra_headers = _prepare_json_body(
            payload, cacheable=cacheable,
            accept_encoding=self.headers.get("Accept-Encoding"),
            if_none_match=self.headers.get("If-None-Match"))
        send_status = status_override if status_override is not None else status

        self.send_response(send_status)
        if send_status != 304:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if request_id:
            self.send_header("X-Request-ID", request_id)
        for k, v in extra_headers.items():
            self.send_header(k, v)
        for k, v in _cors_headers(self.headers.get("Origin")).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _send_sse(self, body: dict, claims: dict, request_id: str):
        """F16 — the streaming counterpart to `_send`: writes each chunk
        `_assistant_ask_sse` yields to the socket as it's produced instead of
        buffering a full response. `send_response`/`end_headers` commit this
        response to 200 immediately (no HTTP status can change mid-stream —
        the same reason SSE never carries a non-200 status; a mid-stream
        failure is instead an "error" event, see `_stream_assistant_answer`),
        so this is only reached after auth has already succeeded."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")  # disable nginx response buffering, if fronted by one
        self.send_header("X-Request-ID", request_id)  # F17
        for k, v in _cors_headers(self.headers.get("Origin")).items():
            self.send_header(k, v)
        self.end_headers()
        for chunk in _assistant_ask_sse(body, claims, request_id):
            self.wfile.write(chunk)
            self.wfile.flush()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/metrics":
            body = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        request_id = _new_request_id()
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        status, result = _route_request("GET", parsed.path, query, {},
                                        self.headers.get("Authorization"), request_id)
        self._send(status, result, route=parsed.path, request_id=request_id)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        request_id = _new_request_id()
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send(400, {"error": "malformed JSON body", "request_id": request_id},
                      request_id=request_id)
            return

        # F16 — special-cased ahead of the generic dict-returning dispatch:
        # this route streams SSE, so it can't go through `_route_request`/
        # `_send`. Auth still happens first and errors still come back as a
        # normal JSON error response with a real status code (401/403/503) —
        # only a request that's actually authorized ever gets switched to
        # `Content-Type: text/event-stream`, at which point the status is
        # committed to 200 and any later failure becomes an "error" SSE event
        # instead (see `_stream_assistant_answer`).
        if parsed.path == "/api/assistant/ask":
            start = time.time()
            error_class: str | None = None
            claims: dict = {}
            try:
                claims = _authenticate_and_authorize(parsed.path, "POST",
                                                     self.headers.get("Authorization"))
            except auth.AuthError as e:
                self._send(401, {"error": str(e), "request_id": request_id}, request_id=request_id)
                status, error_class = 401, type(e).__name__
            except auth.ForbiddenError as e:
                self._send(403, {"error": str(e), "request_id": request_id}, request_id=request_id)
                status, error_class = 403, type(e).__name__
            except auth.AuthUnavailable as e:
                self._send(503, {"error": str(e), "request_id": request_id}, request_id=request_id)
                status, error_class = 503, type(e).__name__
            else:
                self._send_sse(body, claims, request_id)
                status = 200
            REQUEST_COUNT.labels(route=parsed.path, status=str(status)).inc()
            latency_s = time.time() - start
            REQUEST_LATENCY.labels(route=parsed.path).observe(latency_s)
            _log_request(request_id=request_id, method="POST", route=parsed.path, status=status,
                        latency_s=latency_s, subject=claims.get("sub"), error_class=error_class)
            return

        status, result = _route_request("POST", parsed.path, {}, body,
                                        self.headers.get("Authorization"), request_id)
        self._send(status, result, request_id=request_id)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        request_id = _new_request_id()
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        status, result = _route_request("DELETE", parsed.path, query, {},
                                        self.headers.get("Authorization"), request_id)
        self._send(status, result, request_id=request_id)


# ---- production (WSGI/gunicorn) transport ---------------------------------

_MAX_BODY_BYTES = int(os.environ.get("BANKLENS_MAX_BODY_BYTES", str(1_000_000)))  # 1 MB


class _TokenBucket:
    """A simple per-key token bucket — good enough to blunt an accidental
    client-side retry storm or one misbehaving caller; not a substitute for a
    real edge rate limiter (Cloudflare/API-gateway level) in front of a real
    deployment. Thread-safe: gunicorn's default worker class here is
    threaded (see `_run_gunicorn`), so multiple requests can hit `allow()`
    concurrently within one worker process."""

    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.burst = float(burst)
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True


# Per-process bucket (gunicorn's prefork model means each worker enforces its
# own limit — with N workers the effective ceiling is N times these numbers,
# which is the right tradeoff for a stateless per-process limiter over adding
# a shared-state dependency like Redis just to make the ceiling exact).
_rate_limiter = _TokenBucket(
    rate_per_sec=float(os.environ.get("BANKLENS_RATE_LIMIT_PER_SEC", "5")),
    burst=int(os.environ.get("BANKLENS_RATE_LIMIT_BURST", "20")))


def _peek_subject(auth_header: str | None) -> str | None:
    """Best-effort subject for rate-limit keying, read WITHOUT verifying the
    token's signature — real verification happens later, inside
    `_route_request` -> `auth.authenticate`, and doing it twice per request
    just to pick a rate-limit bucket key would double the JWKS-backed auth
    cost for no benefit (a forged token still can't pass the real check
    downstream; it only ever affects which bucket a request counts against).
    A missing/garbage token degrades to per-IP limiting in the caller, which
    is still a real limit, just a coarser one."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):]
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        sub = claims.get("sub")
        return sub if isinstance(sub, str) else None
    except Exception:
        return None


_STATUS_LINES = {
    200: "200 OK", 204: "204 No Content", 304: "304 Not Modified", 400: "400 Bad Request",
    401: "401 Unauthorized", 403: "403 Forbidden", 404: "404 Not Found",
    413: "413 Payload Too Large", 429: "429 Too Many Requests",
    500: "500 Internal Server Error",  # F18
    503: "503 Service Unavailable",
}


def _wsgi_json_response(start_response, status: int, payload: dict | BinaryResponse, origin: str | None,
                        *, method: str | None = None, route: str | None = None,
                        accept_encoding: str | None = None, if_none_match: str | None = None,
                        request_id: str | None = None):
    if isinstance(payload, BinaryResponse):
        headers = [
            ("Content-Type", payload.content_type),
            ("Content-Disposition", f'attachment; filename="{payload.filename}"'),
            ("Content-Length", str(len(payload.body))),
        ]
        if request_id:
            headers.append(("X-Request-ID", request_id))
        headers += list(_cors_headers(origin).items())
        start_response(_STATUS_LINES.get(status, f"{status} Error"), headers)
        return [payload.body]

    # F10 — same cacheability rule the dev transport (Handler._send) applies:
    # a successful GET on a route that isn't per-user/dynamic.
    cacheable = status == 200 and method == "GET" and route is not None and route not in _NON_CACHEABLE_PATHS
    status_override, body, extra_headers = _prepare_json_body(
        payload, cacheable=cacheable, accept_encoding=accept_encoding, if_none_match=if_none_match)
    send_status = status_override if status_override is not None else status

    headers = [] if send_status == 304 else [("Content-Type", "application/json")]
    headers.append(("Content-Length", str(len(body))))
    if request_id:
        headers.append(("X-Request-ID", request_id))
    headers += list(extra_headers.items())
    headers += list(_cors_headers(origin).items())
    start_response(_STATUS_LINES.get(send_status, f"{send_status} Error"), headers)
    return [body]


def wsgi_app(environ, start_response):
    """Production transport: a plain WSGI callable served by gunicorn (see
    `_run_gunicorn` / `main`, or run it directly as
    `gunicorn bridge_server:wsgi_app`). Adds, on top of what dev mode gives
    you: a 1MB request-body cap (413 over that), and a per-subject-claim
    token-bucket rate limit (429 over that) — gunicorn itself supplies the
    bounded worker/thread pool and the request timeout (`--timeout`, default
    30s here), so neither is reimplemented here. Every matched route still
    goes through the exact same `_route_request()` the dev transport uses.
    """
    method = environ["REQUEST_METHOD"]
    path = environ.get("PATH_INFO", "")
    origin = environ.get("HTTP_ORIGIN")
    auth_header = environ.get("HTTP_AUTHORIZATION")

    if method == "OPTIONS":
        start_response("204 No Content", list(_cors_headers(origin).items()))
        return [b""]

    if method == "GET" and path == "/metrics":
        body = generate_latest()
        start_response("200 OK", [("Content-Type", CONTENT_TYPE_LATEST),
                                  ("Content-Length", str(len(body)))])
        return [body]

    request_id = _new_request_id()  # F17

    subject = _peek_subject(auth_header) or environ.get("REMOTE_ADDR", "unknown")
    if not _rate_limiter.allow(subject):
        return _wsgi_json_response(start_response, 429, {"error": "rate limit exceeded", "request_id": request_id},
                                   origin, request_id=request_id)

    query = {k: v[0] for k, v in urllib.parse.parse_qs(environ.get("QUERY_STRING", "")).items()}
    body: dict = {}
    if method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > _MAX_BODY_BYTES:
            return _wsgi_json_response(
                start_response, 413,
                {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes", "request_id": request_id},
                origin, request_id=request_id)
        raw = environ["wsgi.input"].read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return _wsgi_json_response(start_response, 400,
                                       {"error": "malformed JSON body", "request_id": request_id},
                                       origin, request_id=request_id)

    # F16 — same special-case Handler.do_POST makes: this route streams SSE
    # instead of one JSON dict, so it can't go through `_route_request` /
    # `_wsgi_json_response`. Auth still happens first, with normal JSON error
    # responses for a failure — see that method's docstring for the full
    # rationale (identical here, just the WSGI-side mechanics).
    if method == "POST" and path == "/api/assistant/ask":
        start = time.time()
        try:
            claims = _authenticate_and_authorize(path, method, auth_header)
        except auth.AuthError as e:
            REQUEST_COUNT.labels(route=path, status="401").inc()
            REQUEST_LATENCY.labels(route=path).observe(time.time() - start)
            _log_request(request_id=request_id, method=method, route=path, status=401,
                        latency_s=time.time() - start, subject=None, error_class=type(e).__name__)
            return _wsgi_json_response(start_response, 401, {"error": str(e), "request_id": request_id},
                                       origin, request_id=request_id)
        except auth.ForbiddenError as e:
            REQUEST_COUNT.labels(route=path, status="403").inc()
            REQUEST_LATENCY.labels(route=path).observe(time.time() - start)
            _log_request(request_id=request_id, method=method, route=path, status=403,
                        latency_s=time.time() - start, subject=None, error_class=type(e).__name__)
            return _wsgi_json_response(start_response, 403, {"error": str(e), "request_id": request_id},
                                       origin, request_id=request_id)
        except auth.AuthUnavailable as e:
            REQUEST_COUNT.labels(route=path, status="503").inc()
            REQUEST_LATENCY.labels(route=path).observe(time.time() - start)
            _log_request(request_id=request_id, method=method, route=path, status=503,
                        latency_s=time.time() - start, subject=None, error_class=type(e).__name__)
            return _wsgi_json_response(start_response, 503, {"error": str(e), "request_id": request_id},
                                       origin, request_id=request_id)

        headers = [
            ("Content-Type", "text/event-stream"),
            ("Cache-Control", "no-cache"),
            ("Connection", "keep-alive"),
            ("X-Accel-Buffering", "no"),  # disable nginx response buffering, if fronted by one
            ("X-Request-ID", request_id),
        ]
        headers += list(_cors_headers(origin).items())
        start_response("200 OK", headers)

        def _sse_body():
            try:
                yield from _assistant_ask_sse(body, claims, request_id)
            finally:
                REQUEST_COUNT.labels(route=path, status="200").inc()
                latency_s = time.time() - start
                REQUEST_LATENCY.labels(route=path).observe(latency_s)
                _log_request(request_id=request_id, method=method, route=path, status=200,
                            latency_s=latency_s, subject=claims.get("sub"), error_class=None)

        return _sse_body()

    status, result = _route_request(method, path, query, body, auth_header, request_id)
    return _wsgi_json_response(
        start_response, status, result, origin, method=method, route=path,
        accept_encoding=environ.get("HTTP_ACCEPT_ENCODING"),
        if_none_match=environ.get("HTTP_IF_NONE_MATCH"), request_id=request_id)


# F16 — gunicorn's `--timeout` kills and restarts a worker that hasn't
# notified the master within that many seconds; a gthread worker (this repo's
# worker_class) can be mid-request that whole time. Since POST /api/
# assistant/ask now legitimately runs up to `_ASSISTANT_DEADLINE_S +
# _ASSISTANT_CANCEL_GRACE_S`, the worker timeout MUST exceed that or gunicorn
# would kill the worker (and every other in-flight request sharing it) before
# this route's own graceful deadline ever gets a chance to fire — silently
# reintroducing the exact "hangs the whole request thread" failure mode F16
# set out to fix, just moved one layer down. +20s of headroom over the
# graceful path's own worst case.
_MIN_SAFE_WORKER_TIMEOUT_S = int(_ASSISTANT_DEADLINE_S + _ASSISTANT_CANCEL_GRACE_S + 20)


def _run_gunicorn(host: str, port: int) -> None:
    """Launch gunicorn's own prefork/threaded worker model around `wsgi_app`
    — a crashed or hung worker is restarted by gunicorn's master process, not
    something hand-rolled here. Lazy import: dev mode (the default) has no
    reason to require gunicorn installed; only BANKLENS_SERVER=prod does."""
    try:
        from gunicorn.app.base import BaseApplication
    except ImportError as e:
        raise SystemExit(
            "BANKLENS_SERVER=prod requires gunicorn (pip install gunicorn), or run it "
            f"directly without this wrapper: gunicorn --workers 2 --threads 4 "
            f"--timeout {os.environ.get('BANKLENS_REQUEST_TIMEOUT_S', str(_MIN_SAFE_WORKER_TIMEOUT_S))} "
            f"--bind {host}:{port} bridge_server:wsgi_app"
        ) from e

    timeout = int(os.environ.get("BANKLENS_REQUEST_TIMEOUT_S", str(_MIN_SAFE_WORKER_TIMEOUT_S)))
    if timeout < _MIN_SAFE_WORKER_TIMEOUT_S:
        # Loud, not fatal: an operator who deliberately wants a shorter worker
        # timeout and accepts that assistant requests may get killed mid-
        # stream instead of completing gracefully can still set it — but they
        # should not discover that tradeoff via a silent, unexplained 502.
        sys.stderr.write(
            f"WARNING: BANKLENS_REQUEST_TIMEOUT_S={timeout} is below "
            f"{_MIN_SAFE_WORKER_TIMEOUT_S}s (BANKLENS_ASSISTANT_DEADLINE_S="
            f"{_ASSISTANT_DEADLINE_S:.0f} + its cancellation grace period). gunicorn may "
            "kill a worker mid-stream on POST /api/assistant/ask before that route's own "
            "deadline gets a chance to return cleanly.\n")

    class _App(BaseApplication):
        def load_config(self):
            for key, value in {
                "bind": f"{host}:{port}",
                "workers": int(os.environ.get("BANKLENS_WORKERS", "2")),
                "threads": int(os.environ.get("BANKLENS_THREADS", "4")),
                "worker_class": "gthread",
                "timeout": timeout,
            }.items():
                self.cfg.set(key, value)

        def load(self):
            return wsgi_app

    _App().run()


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _require_safe_bind(host: str) -> None:
    """BANKLENS_AUTH_ENABLED=false is a documented local-dev escape hatch, not
    a supported deployment mode — every route becomes unauthenticated and
    unauthorized. Bound to loopback that's a trusted single-machine loop;
    bound to anything else it's an open service. Refuse to start rather than
    let that combination reach a socket that's actually listening."""
    if auth.AUTH_ENABLED:
        return
    if host.strip().lower() in _LOOPBACK_HOSTS:
        return
    raise SystemExit(
        f"Refusing to start: BANKLENS_AUTH_ENABLED=false with "
        f"BANKLENS_BRIDGE_HOST={host!r} would serve every route with no "
        "authentication or authorization to anything that can reach that "
        "address. Fix by either:\n"
        "  - unsetting BANKLENS_AUTH_ENABLED (or setting it to true) to run "
        "with real OIDC/OPA auth, or\n"
        "  - binding to loopback only: BANKLENS_BRIDGE_HOST=localhost "
        "(the auth-disabled escape hatch is local-dev-only by design)."
    )


def main() -> None:
    # Default to localhost (safe for bare local dev — doesn't expose the port to
    # the LAN). Containers set BANKLENS_BRIDGE_HOST=0.0.0.0 — a container's own
    # network namespace makes that safe; Docker's `-p`/K8s Service control real
    # external exposure, not this bind address. That reasoning assumes real
    # auth is on, though — see _require_safe_bind for the auth-disabled case.
    host = os.environ.get("BANKLENS_BRIDGE_HOST", "localhost")
    _require_safe_bind(host)
    print("Warming population cache...")
    data.population()
    if os.environ.get("BANKLENS_SERVER", "dev").strip().lower() == "prod":
        print(f"BankLens REST bridge (prod/gunicorn) on http://{host}:{PORT}")
        _run_gunicorn(host, PORT)
    else:
        print(f"BankLens REST bridge on http://{host}:{PORT}  (Ctrl+C to stop)")
        ThreadingHTTPServer((host, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
