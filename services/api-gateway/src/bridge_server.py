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
import json
import os
import sys
import threading
import time
import traceback
import urllib.parse
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
    "/api/banks/filing-diff": "viewer",
    "/api/banks/risk-score": "viewer",
    "/api/banks/candles": "viewer",
    "/api/banks/market-snapshot": "viewer",
    "/api/market/coverage": "viewer",
    "/api/market/overview": "viewer",
    "/api/macro": "viewer",
    "/api/data-freshness": "viewer",
    "/api/banks/holding-company": "viewer",
    "/api/risk-leaderboard": "viewer",
    "/api/compare": "viewer",
    "/api/watchlist": "viewer",
    "/api/watchlist/note": "viewer",
    "/api/watchlist/rules": "viewer",
    "/api/screens": "viewer",
    "/api/alerts": "viewer",
    "/api/alerts/seen": "viewer",
    "/api/population-metrics": "viewer",
    "/api/metric-distribution": "viewer",
    "/api/percentile-heatmap": "viewer",
    "/api/asset-treemap": "viewer",
    "/api/banks/trends": "viewer",
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
        descending=q.get("descending", "true").lower() != "false", quarter=q.get("quarter"))),
    ("GET", "/api/metric-distribution", lambda q, claims: tools.get_metric_distribution(
        q["metric"], bins=int(q.get("bins", 30)), quarter=q.get("quarter"))),
    ("GET", "/api/percentile-heatmap", lambda q, claims: tools.get_percentile_heatmap(
        top_n=int(q.get("top_n", 40)), sort_by=q.get("sort_by", "total_assets"),
        metrics=q["metrics"].split(",") if q.get("metrics") else None, quarter=q.get("quarter"))),
    ("GET", "/api/asset-treemap", lambda q, claims: tools.get_asset_treemap(
        group_by=q.get("group_by", "peer_cluster_label"), quarter=q.get("quarter"))),
    ("GET", "/api/banks/trends", lambda q, claims: tools.get_bank_trends(_cap(q["cert"]))),
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
    ("POST", "/api/alerts/seen", lambda body, claims: _alert_mark_seen(body, claims)),
    ("POST", "/api/assistant/ask", lambda body, claims: _assistant_ask(body, claims)),
]

DELETE_ROUTES = [
    ("DELETE", "/api/watchlist", lambda q, claims: _watchlist_remove(q, claims)),
    ("DELETE", "/api/watchlist/rules", lambda q, claims: _watchlist_rule_remove(q, claims)),
    ("DELETE", "/api/screens", lambda q, claims: _screen_remove(q, claims)),
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


def _alert_mark_seen(body: dict, claims: dict) -> dict:
    sub = _require_sub(claims)
    common_db.mark_alert_seen(sub, int(body["alert_id"]))
    return {"items": common_db.fetch_alerts(sub)}


def _assistant_ask(body: dict, claims: dict) -> dict:
    """v1 skips supervisor.route() auto-routing on purpose — the frontend has
    the user pick a persona tab directly, saving one whole LLM round-trip and
    making it visible which lens is answering. Always the $0 default provider
    (ollama) — no model/provider override from the client for v1. This can
    legitimately take minutes (Ollama's own client retries with a 120s
    timeout, run_agent loops up to 6 turns) — the caller (do_POST) has no
    special-cased timeout for this route, so the request just blocks."""
    persona_key = body.get("persona")
    persona = PERSONAS.get(persona_key)
    if persona is None:
        raise ValueError(f"unknown persona '{persona_key}' — choose one of {list(PERSONAS)}")
    question = (body.get("question") or "").strip()
    if not question:
        raise ValueError("question must be a non-empty string")

    # G2: this route is already analyst-gated at the REST layer (ROUTE_TIERS
    # above), but the agent can drive ANY tool in the persona's static list
    # through the MCP loop — roles_from_claims(claims) is the same call every
    # other route already makes, threaded through so run_agent additionally
    # intersects the persona's tools against what the CALLER's roles actually
    # permit (G1's OPA policy), not just what the persona nominally allows.
    roles = auth.roles_from_claims(claims)
    result = run_agent(persona, question, roles=roles)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    out = RUNS_DIR / f"{now.strftime('%Y%m%dT%H%M%S%f')}.json"
    payload = to_json(result)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    try:
        model_id = providers.resolve_model(result.provider, None)
        common_db.record_agent_run(
            persona=persona.key, provider=result.provider, model=model_id,
            question=question, answer=result.answer, ok=True,
            transcript_path=str(out.relative_to(REPO)), ts=now,
            user_sub=claims.get("sub"))
    except Exception:
        # Same tradeoff cli.py makes: the transcript on disk is the real
        # content; the Postgres index is queryability, not the record of
        # truth — a DB hiccup shouldn't fail an otherwise-successful answer.
        traceback.print_exc()

    return payload


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
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        # GET/POST are CORS-safelisted methods (exempt from the preflight
        # Access-Control-Allow-Methods check regardless of this header), but
        # DELETE (added for watchlist removal) is not — without this,
        # DELETE's own preflight OPTIONS would pass, then the browser would
        # still block the real request.
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    }
    if origin in _ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


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


def _route_request(method: str, path: str, query: dict, body: dict,
                   auth_header: str | None) -> tuple[int, dict]:
    """THE single place routing + auth + handler-call + error-mapping + metrics
    happen — decoupled from both server transports (the stdlib
    ThreadingHTTPServer `Handler` below, for local dev; `wsgi_app`, for
    gunicorn in production). Every server mode calls through this exact
    function, so which transport served a request can never change what it
    returns. Returns (status, response_body) and never touches a socket
    itself, which is what makes it shareable between the two.
    """
    if not auth.AUTH_ENABLED:
        _warn_auth_disabled()
    arg = body if method == "POST" else query
    for m, route, fn in _ROUTES_BY_METHOD.get(method, []):
        if m == method and path == route:
            start = time.time()
            status = 200
            claims: dict = {}
            try:
                if auth.AUTH_ENABLED and route not in auth.OPEN_ROUTES:
                    claims = auth.authenticate(auth_header)
                    auth.authorize(route, method, auth.roles_from_claims(claims))
                result = fn(arg, claims)
            except auth.AuthError as e:
                status, result = 401, {"error": str(e)}
            except auth.ForbiddenError as e:
                status, result = 403, {"error": str(e)}
            except auth.AuthUnavailable as e:
                status, result = 503, {"error": str(e)}
            except KeyError as e:
                status, result = 400, {"error": f"missing required param: {e}"}
            except Exception as e:
                status, result = 400, {"error": str(e)}
                traceback.print_exc()
            finally:
                REQUEST_COUNT.labels(route=route, status=str(status)).inc()
                REQUEST_LATENCY.labels(route=route).observe(time.time() - start)
            return status, result
    REQUEST_COUNT.labels(route="unmatched", status="404").inc()
    return 404, {"error": f"no route for {path}"}


class Handler(BaseHTTPRequestHandler):
    """Dev-mode transport: stdlib `http.server`, zero installs beyond
    prometheus-client. No request timeout, no body-size cap, no rate limit —
    see `wsgi_app` below for the production transport that adds those."""

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, payload: dict | BinaryResponse):
        if isinstance(payload, BinaryResponse):
            self.send_response(status)
            self.send_header("Content-Type", payload.content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{payload.filename}"')
            self.send_header("Content-Length", str(len(payload.body)))
            for k, v in _cors_headers(self.headers.get("Origin")).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload.body)
            return
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in _cors_headers(self.headers.get("Origin")).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

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

        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        status, result = _route_request("GET", parsed.path, query, {},
                                        self.headers.get("Authorization"))
        self._send(status, result)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send(400, {"error": "malformed JSON body"})
            return
        status, result = _route_request("POST", parsed.path, {}, body,
                                        self.headers.get("Authorization"))
        self._send(status, result)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        status, result = _route_request("DELETE", parsed.path, query, {},
                                        self.headers.get("Authorization"))
        self._send(status, result)


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


def _wsgi_json_response(start_response, status: int, payload: dict | BinaryResponse, origin: str | None):
    status_line = {
        200: "200 OK", 204: "204 No Content", 400: "400 Bad Request",
        401: "401 Unauthorized", 403: "403 Forbidden", 404: "404 Not Found",
        413: "413 Payload Too Large", 429: "429 Too Many Requests",
        503: "503 Service Unavailable",
    }.get(status, f"{status} Error")
    if isinstance(payload, BinaryResponse):
        headers = [
            ("Content-Type", payload.content_type),
            ("Content-Disposition", f'attachment; filename="{payload.filename}"'),
            ("Content-Length", str(len(payload.body))),
        ]
        headers += list(_cors_headers(origin).items())
        start_response(status_line, headers)
        return [payload.body]
    body = json.dumps(payload, default=str).encode("utf-8")
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    headers += list(_cors_headers(origin).items())
    start_response(status_line, headers)
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

    subject = _peek_subject(auth_header) or environ.get("REMOTE_ADDR", "unknown")
    if not _rate_limiter.allow(subject):
        return _wsgi_json_response(start_response, 429, {"error": "rate limit exceeded"}, origin)

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
                {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes"}, origin)
        raw = environ["wsgi.input"].read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return _wsgi_json_response(start_response, 400, {"error": "malformed JSON body"}, origin)

    status, result = _route_request(method, path, query, body, auth_header)
    return _wsgi_json_response(start_response, status, result, origin)


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
            f"--timeout {os.environ.get('BANKLENS_REQUEST_TIMEOUT_S', '30')} "
            f"--bind {host}:{port} bridge_server:wsgi_app"
        ) from e

    class _App(BaseApplication):
        def load_config(self):
            for key, value in {
                "bind": f"{host}:{port}",
                "workers": int(os.environ.get("BANKLENS_WORKERS", "2")),
                "threads": int(os.environ.get("BANKLENS_THREADS", "4")),
                "worker_class": "gthread",
                "timeout": int(os.environ.get("BANKLENS_REQUEST_TIMEOUT_S", "30")),
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
