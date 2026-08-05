"""BankLens REST bridge — dependency-free HTTP wrapper over banklens_mcp.tools.

The MCP server speaks JSON-RPC over stdio, which a browser can't call directly.
This bridge exposes the SAME tool functions (no duplicated logic) as plain REST/JSON
over HTTP, for the quant-terminal frontend (Phase 7). Production (Phase 5+) will
likely front the official MCP server with a proper gRPC/REST gateway; this reference
keeps things runnable with zero installs (stdlib `http.server` only) plus one real
dependency for observability (prometheus-client — see /metrics below).

Run:
    $env:PYTHONPATH = "services/mcp-server/src;pipelines/transforms/src"
    python services/api-gateway/src/bridge_server.py
"""

from __future__ import annotations

import json
import os
import sys
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

from banklens_mcp import data, tools  # noqa: E402

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
    "/api/banks": "viewer",
    "/api/banks/profile": "viewer",
    "/api/banks/xray": "viewer",
    "/api/banks/peer-cluster": "viewer",
    "/api/banks/ma-fit": "viewer",
    "/api/banks/filing-diff": "viewer",
    "/api/banks/risk-score": "viewer",
    "/api/banks/candles": "viewer",
    "/api/banks/market-snapshot": "viewer",
    "/api/risk-leaderboard": "viewer",
    "/api/compare": "viewer",
    "/api/watchlist": "viewer",
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
    "/api/banks/stress-test": "analyst",
    "/api/assistant/ask": "analyst",
    "/api/activity/agent-runs": "analyst",
    "/api/activity/audit-log": "analyst",
}

ROUTES = [
    ("GET", "/api/health", lambda q, claims: {"status": "ok"}),
    ("GET", "/api/population", lambda q, claims: _population_summary()),
    ("GET", "/api/banks", lambda q, claims: tools.list_banks(
        query=q.get("query"), state=q.get("state"),
        min_assets_b=_f(q.get("min_assets_b")), max_assets_b=_f(q.get("max_assets_b")),
        limit=int(q.get("limit", 20)))),
    ("GET", "/api/banks/profile", lambda q, claims: tools.get_bank_profile(_cap(q["cert"]))),
    ("GET", "/api/banks/xray", lambda q, claims: tools.get_bank_xray(_cap(q["cert"]))),
    ("GET", "/api/banks/peer-cluster", lambda q, claims: tools.get_peer_cluster(_cap(q["cert"]))),
    ("GET", "/api/banks/ma-fit", lambda q, claims: tools.find_ma_matches(
        _cap(q["cert"]), top_n=int(q.get("top_n", 8)))),
    ("GET", "/api/banks/stress-test", lambda q, claims: tools.run_stress(
        _cap(q["cert"]), loan_loss_pct=_f(q.get("loan_loss_pct"), 3.0),
        deposit_outflow_pct=_f(q.get("deposit_outflow_pct"), 15.0),
        rate_shock_bps=_f(q.get("rate_shock_bps"), 200.0))),
    ("GET", "/api/banks/filing-diff", lambda q, claims: tools.diff_filings(
        _cap(q["cert"]), quarter_a=q.get("quarter_a"), quarter_b=q.get("quarter_b"))),
    ("GET", "/api/banks/risk-score", lambda q, claims: tools.get_risk_score(_cap(q["cert"]))),
    ("GET", "/api/banks/candles", lambda q, claims: tools.get_price_candles(
        _cap(q["cert"]), limit_days=int(q.get("limit_days", 180)))),
    ("GET", "/api/banks/market-snapshot", lambda q, claims: tools.get_market_snapshot(_cap(q["cert"]))),
    ("GET", "/api/risk-leaderboard", lambda q, claims: tools.get_risk_leaderboard(
        top_n=int(q.get("top_n", 25)))),
    ("GET", "/api/compare", lambda q, claims: tools.compare_banks(
        _certs(q["certs"]), metrics=q["metrics"].split(",") if q.get("metrics") else None)),
    ("GET", "/api/watchlist", lambda q, claims: {
        "items": common_db.fetch_watchlist(_require_sub(claims))}),
    ("GET", "/api/population-metrics", lambda q, claims: tools.get_population_metrics(
        q["group"], limit=int(q.get("limit", 2000)), sort_by=q.get("sort_by"),
        descending=q.get("descending", "true").lower() != "false")),
    ("GET", "/api/metric-distribution", lambda q, claims: tools.get_metric_distribution(
        q["metric"], bins=int(q.get("bins", 30)))),
    ("GET", "/api/percentile-heatmap", lambda q, claims: tools.get_percentile_heatmap(
        top_n=int(q.get("top_n", 40)), sort_by=q.get("sort_by", "total_assets"))),
    ("GET", "/api/asset-treemap", lambda q, claims: tools.get_asset_treemap(
        group_by=q.get("group_by", "peer_cluster_label"))),
    ("GET", "/api/banks/trends", lambda q, claims: tools.get_bank_trends(_cap(q["cert"]))),
    ("GET", "/api/briefing", lambda q, claims: tools.get_quarterly_briefing(
        top_n=int(q.get("top_n", 8)))),
    ("GET", "/api/cluster-diagnostics", lambda q, claims: tools.get_cluster_diagnostics()),
    ("GET", "/api/model-card", lambda q, claims: tools.get_model_card()),
    ("GET", "/api/county-concentration", lambda q, claims: tools.get_county_concentration(
        state=q.get("state"), top_n=int(q.get("top_n", 100)))),
    ("GET", "/api/branch-map", lambda q, claims: tools.get_branch_map(state=q.get("state"))),
    ("GET", "/api/activity/agent-runs", lambda q, claims: {
        "items": common_db.fetch_recent_agent_runs(int(q.get("limit", 50)))}),
    ("GET", "/api/activity/audit-log", lambda q, claims: {
        "items": common_db.fetch_recent_audit(int(q.get("limit", 50)))}),
]

POST_ROUTES = [
    ("POST", "/api/watchlist", lambda body, claims: _watchlist_add(body, claims)),
    ("POST", "/api/assistant/ask", lambda body, claims: _assistant_ask(body, claims)),
]

DELETE_ROUTES = [
    ("DELETE", "/api/watchlist", lambda q, claims: _watchlist_remove(q, claims)),
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

    result = run_agent(persona, question)

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
            transcript_path=str(out.relative_to(REPO)), ts=now)
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


# Origins the real quant-terminal frontend runs on in this reference setup: the
# Vite dev server, the Docker Compose container, and the K8s dev overlay's
# NodePort. `Access-Control-Allow-Origin: *` would let ANY webpage a user has open
# in their browser query this service while it's running (a real local attack
# surface, not theoretical — it's what made the path-traversal bug found in
# banklens_mcp.data browser-reachable rather than merely local-process-reachable).
# An explicit allowlist, echoed back only on match, closes that off.
_ALLOWED_ORIGINS = {
    "http://localhost:5173", "http://localhost:8080", "http://localhost:30080",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin")
        if origin in _ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "*")
        # GET/POST are CORS-safelisted methods (exempt from the preflight
        # Access-Control-Allow-Methods check regardless of this header), but
        # DELETE (added for watchlist removal) is not — without this,
        # DELETE's own preflight OPTIONS would pass, then the browser would
        # still block the real request.
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _dispatch(self, method: str, path: str, routes: list, arg) -> bool:
        """Shared auth + call + error-mapping + metrics for GET/POST/DELETE —
        do_GET used to inline this; do_POST/do_DELETE need the exact same
        shape, so it's factored here rather than tripled. Returns whether a
        route matched (the caller sends 404 itself if not, since the 404
        response/metric label is identical across all three verbs)."""
        for m, route, fn in routes:
            if m == method and path == route:
                start = time.time()
                status = 200
                claims: dict = {}
                try:
                    if auth.AUTH_ENABLED and route not in auth.OPEN_ROUTES:
                        claims = auth.authenticate(self.headers.get("Authorization"))
                        auth.authorize(route, method, auth.roles_from_claims(claims))
                    self._send(200, fn(arg, claims))
                except auth.AuthError as e:
                    status = 401
                    self._send(401, {"error": str(e)})
                except auth.ForbiddenError as e:
                    status = 403
                    self._send(403, {"error": str(e)})
                except auth.AuthUnavailable as e:
                    status = 503
                    self._send(503, {"error": str(e)})
                except KeyError as e:
                    status = 400
                    self._send(400, {"error": f"missing required param: {e}"})
                except Exception as e:
                    status = 400
                    traceback.print_exc()
                    self._send(400, {"error": str(e)})
                finally:
                    REQUEST_COUNT.labels(route=route, status=str(status)).inc()
                    REQUEST_LATENCY.labels(route=route).observe(time.time() - start)
                return True
        return False

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
        if self._dispatch("GET", parsed.path, ROUTES, query):
            return
        REQUEST_COUNT.labels(route="unmatched", status="404").inc()
        self._send(404, {"error": f"no route for {parsed.path}"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send(400, {"error": "malformed JSON body"})
            return
        if self._dispatch("POST", parsed.path, POST_ROUTES, body):
            return
        REQUEST_COUNT.labels(route="unmatched", status="404").inc()
        self._send(404, {"error": f"no route for {parsed.path}"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if self._dispatch("DELETE", parsed.path, DELETE_ROUTES, query):
            return
        REQUEST_COUNT.labels(route="unmatched", status="404").inc()
        self._send(404, {"error": f"no route for {parsed.path}"})


def main() -> None:
    # Default to localhost (safe for bare local dev — doesn't expose the port to
    # the LAN). Containers set BANKLENS_BRIDGE_HOST=0.0.0.0 — a container's own
    # network namespace makes that safe; Docker's `-p`/K8s Service control real
    # external exposure, not this bind address.
    host = os.environ.get("BANKLENS_BRIDGE_HOST", "localhost")
    print("Warming population cache...")
    data.population()
    print(f"BankLens REST bridge on http://{host}:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer((host, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
