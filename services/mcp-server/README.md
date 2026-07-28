# services/mcp-server — the governed tool surface (Phase 5)

One MCP surface shared by UI, CLI/SDK, and AI agents. Tools are thin: they call the
**same** `banklens_transforms` feature logic the CLIs use, then audit every call.
This is the project thesis — *one backend, three consumers* — made real.

## Reference implementation (dependency-free)

Speaks the Model Context Protocol directly (JSON-RPC 2.0 over stdio, newline-delimited)
so it runs with **zero installs**. Production swaps in the official `mcp` SDK; the tool
contracts in `tools.py` stay identical. Handles `initialize`, `tools/list`, `tools/call`,
`ping`, and notifications. Every call is appended to `data/mcp_audit.jsonl`.

## Tools (11)
`list_banks` · `get_bank_profile` · `get_bank_xray` (F11) · `diff_filings` (F12) ·
`get_risk_score` (F13) · `get_peer_cluster` (F14) · `find_ma_matches` (F15) ·
`run_stress_test` (F16) · `compare_banks` · `get_price_candles` · `get_market_snapshot`

Cross-sectional tools read the 1,049-bank population (2026Q1); `diff_filings` needs
per-bank multi-quarter Bronze (WF 3511, Dime 6976 landed). `get_price_candles` /
`get_market_snapshot` need (a) an exact/high-confidence crosswalk ticker match and
(b) landed Tiingo price data (`scripts/land_market_data.ps1`, needs the user's own
free `TIINGO_API_KEY` — see [`docs/data-contracts/market_prices.md`](../../docs/data-contracts/market_prices.md)).

## Try it
```powershell
powershell -File scripts/mcp_demo.ps1        # drives the server over real stdio
python services/mcp-server/tests/test_mcp.py # hermetic protocol tests
```

## Use it inside Claude Code
The repo ships a project-scoped [`.mcp.json`](../../.mcp.json). Open this repo in
Claude Code and approve the `banklens` server when prompted — then ask things like
*"run a 60% deposit-run stress test on cert 6976"* or *"which banks are most CRE-
concentrated vs peers?"* and the agent will chain these tools. (Config is read at
startup, so restart Claude Code after first checkout.)

## Next (Phase 5/6)
Official `mcp` SDK; OIDC + OPA authz (+ data-license enforcement); JSON-schema output
validation; tool versioning; then the agent fleet (Phase 6) on top.
