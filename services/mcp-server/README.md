# services/mcp-server — the governed tool surface (Phase 5)

One audited API shared by UI, CLI/SDK, and AI agents. Tools are thin: validate →
authorise (OIDC + OPA, incl. data-license enforcement) → **audit** → dispatch to
the feature services. Contracts: [`docs/api/mcp-tools.md`](../../docs/api/mcp-tools.md).

```powershell
python src/banklens_mcp/server.py     # prints the declared tool surface (skeleton)
```

Phase 5 wires the official MCP SDK (`pip install "mcp[cli]"`).
