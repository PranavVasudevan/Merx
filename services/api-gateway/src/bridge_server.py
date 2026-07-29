"""BankLens REST bridge — dependency-free HTTP wrapper over banklens_mcp.tools.

The MCP server speaks JSON-RPC over stdio, which a browser can't call directly.
This bridge exposes the SAME tool functions (no duplicated logic) as plain REST/JSON
over HTTP, for the quant-terminal frontend (Phase 7). Production (Phase 5+) will
likely front the official MCP server with a proper gRPC/REST gateway; this reference
keeps things runnable with zero installs (stdlib `http.server` only).

Run:
    $env:PYTHONPATH = "services/mcp-server/src;pipelines/transforms/src"
    python services/api-gateway/src/bridge_server.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for rel in ("services/mcp-server/src", "pipelines/transforms/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from banklens_mcp import data, tools  # noqa: E402

PORT = 8791


def _cap(cert: int) -> int:
    return int(cert)


ROUTES = [
    ("GET", "/api/health", lambda q: {"status": "ok"}),
    ("GET", "/api/population", lambda q: _population_summary()),
    ("GET", "/api/banks", lambda q: tools.list_banks(
        query=q.get("query"), state=q.get("state"),
        min_assets_b=_f(q.get("min_assets_b")), max_assets_b=_f(q.get("max_assets_b")),
        limit=int(q.get("limit", 20)))),
    ("GET", "/api/banks/profile", lambda q: tools.get_bank_profile(_cap(q["cert"]))),
    ("GET", "/api/banks/xray", lambda q: tools.get_bank_xray(_cap(q["cert"]))),
    ("GET", "/api/banks/peer-cluster", lambda q: tools.get_peer_cluster(_cap(q["cert"]))),
    ("GET", "/api/banks/ma-fit", lambda q: tools.find_ma_matches(
        _cap(q["cert"]), top_n=int(q.get("top_n", 8)))),
    ("GET", "/api/banks/stress-test", lambda q: tools.run_stress(
        _cap(q["cert"]), loan_loss_pct=_f(q.get("loan_loss_pct"), 3.0),
        deposit_outflow_pct=_f(q.get("deposit_outflow_pct"), 15.0),
        rate_shock_bps=_f(q.get("rate_shock_bps"), 200.0))),
    ("GET", "/api/banks/filing-diff", lambda q: tools.diff_filings(
        _cap(q["cert"]), quarter_a=q.get("quarter_a"), quarter_b=q.get("quarter_b"))),
    ("GET", "/api/banks/risk-score", lambda q: tools.get_risk_score(_cap(q["cert"]))),
    ("GET", "/api/banks/candles", lambda q: tools.get_price_candles(
        _cap(q["cert"]), limit_days=int(q.get("limit_days", 180)))),
    ("GET", "/api/banks/market-snapshot", lambda q: tools.get_market_snapshot(_cap(q["cert"]))),
]


def _f(v, default=None):
    return float(v) if v not in (None, "") else default


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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        for method, route, fn in ROUTES:
            if method == "GET" and parsed.path == route:
                try:
                    self._send(200, fn(query))
                except KeyError as e:
                    self._send(400, {"error": f"missing required param: {e}"})
                except Exception as e:
                    traceback.print_exc()
                    self._send(400, {"error": str(e)})
                return
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
