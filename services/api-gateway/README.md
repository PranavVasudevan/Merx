# api-gateway

Production target: a proper gRPC/REST edge gateway (Go or Rust — one, standardized)
in Phase 5+. Auth, however, is already real — see below.

## Reference implementation (Phase 7)

[`src/bridge_server.py`](src/bridge_server.py) is a dependency-free REST bridge
(stdlib `http.server`) over `banklens_mcp.tools`, built to unblock the quant-terminal
frontend before the real gateway exists. It wraps the exact same tool functions the
MCP server exposes — no duplicated logic — as plain JSON over HTTP, with an explicit
CORS origin allowlist (see `SECURITY.md` — this used to be permissive `*`, fixed in
the Phase 8 security pass).

```powershell
powershell -File scripts/api_bridge.ps1     # http://localhost:8791
```

Endpoints: `/api/health`, `/api/population`, `/api/banks`, `/api/banks/profile`,
`/api/banks/xray`, `/api/banks/peer-cluster`, `/api/banks/ma-fit`,
`/api/banks/stress-test`, `/api/banks/filing-diff`, `/api/banks/risk-score`,
`/api/banks/candles`, `/api/banks/market-snapshot`.

## Observability

`GET /metrics` — real Prometheus metrics (`prometheus-client`, the one real
dependency this file has): `banklens_bridge_requests_total{route,status}` and
`banklens_bridge_request_duration_seconds{route}`. Scraped by
`platform/docker/docker-compose.dev.yml`'s `prometheus` service; a
pre-built Grafana dashboard ("BankLens REST Bridge") is auto-provisioned at
`http://localhost:3000` (see `platform/observability/`) — request rate,
error rate, and p50/p95/p99 latency by route, all verified live against real
traffic before shipping (see `CHANGELOG.md`).

## Auth (OIDC + OPA)

Every route except `/api/health` and `/metrics` requires a real, signed
Keycloak JWT (`src/auth.py::authenticate()` — verified against Keycloak's own
JWKS, not just decoded) and a real OPA authorization decision
(`authorize()` — `platform/auth/opa/policy.rego`: a `viewer` role can read
bank data, `analyst` is additionally required for the stress simulator).
Fails **closed**: if Keycloak or OPA are unreachable, requests get a 503, not
a silent pass-through. Full setup, the realm-import gotcha that was found and
fixed, and how to verify it yourself: see `platform/auth/README.md`.

Set `BANKLENS_AUTH_ENABLED=false` to disable this for a quick local dev loop
without Keycloak/OPA running.

Replace with the real gateway (rate limiting, gRPC) once Phase 5 hardening begins.
