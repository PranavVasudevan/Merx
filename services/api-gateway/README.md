# api-gateway

Production target: a proper gRPC/REST edge gateway (Go or Rust — one, standardized),
with auth, in Phase 5+.

## Reference implementation (Phase 7)

[`src/bridge_server.py`](src/bridge_server.py) is a dependency-free REST bridge
(stdlib `http.server`) over `banklens_mcp.tools`, built to unblock the quant-terminal
frontend before the real gateway exists. It wraps the exact same tool functions the
MCP server exposes — no duplicated logic — as plain JSON over HTTP with permissive
dev-mode CORS.

```powershell
powershell -File scripts/api_bridge.ps1     # http://localhost:8791
```

Endpoints: `/api/health`, `/api/population`, `/api/banks`, `/api/banks/profile`,
`/api/banks/xray`, `/api/banks/peer-cluster`, `/api/banks/ma-fit`,
`/api/banks/stress-test`, `/api/banks/filing-diff`, `/api/banks/risk-score`.

Replace with the real gateway (auth, rate limiting, gRPC) once Phase 5 hardening begins.
