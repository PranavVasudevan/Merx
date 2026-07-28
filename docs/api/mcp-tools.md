# MCP tool contracts

The MCP server exposes one governed, audited surface shared by the UI, the CLI/SDK,
and the AI agents. Tools are thin — heavy compute lives in the feature logic behind
them (today `banklens_transforms`; later the Rust engines, ClickHouse, DuckDB, ML).

**Status:** a dependency-free reference server is **implemented** in
`services/mcp-server` (JSON-RPC 2.0 over stdio, per-call audit to `data/mcp_audit.jsonl`),
exposing **11 tools** — the 9 core feature tools plus `get_price_candles` and
`get_market_snapshot` (real Tiingo EOD data via the CERT↔CIK↔RSSD crosswalk).
Drive it with `scripts/mcp_demo.ps1`; use it in Claude Code via the repo's `.mcp.json`.

## Core tools (from the product spec)

| Tool | Signature | Feature |
|---|---|---|
| `list_banks` | `(query, filters)` | search/filter by name, state, size, cluster |
| `get_bank_profile` | `(bank_id, quarter)` | Silver/Gold core data for one bank |
| `get_bank_xray` | `(bank_id)` | F11 concentration risk |
| `diff_filings` | `(bank_id, quarter_a, quarter_b)` | F12 filing diff |
| `get_risk_score` | `(bank_id)` | F13 deposit-flight + SHAP drivers |
| `get_peer_cluster` | `(bank_id)` | F14 behavioural peers |
| `find_ma_matches` | `(bank_id, top_n)` | F15 M&A fit |
| `run_stress_test` | `(bank_id, shock_params)` | F16 capital-buffer sim |
| `compare_banks` | `(bank_id_list, metrics)` | side-by-side |

## Quant / market additions

| Tool | Signature | Status |
|---|---|---|
| `get_price_candles` | `(cert, limit_days)` | ✅ implemented — real Tiingo EOD OHLCV, needs the bank's crosswalk ticker AND landed price data (`scripts/land_market_data.ps1`, needs a free `TIINGO_API_KEY`) |
| `get_market_snapshot` | `(cert)` | ✅ implemented — latest close, 1d change, 30d realized vol, 52w range |
| `get_macro_series` | `(series_id, range)` | planned — FRED overlays |
| `search_filings_text` | `(query, filters)` | planned — RAG over 10-K/10-Q narrative, needs pgvector/Qdrant |

## Cross-cutting
Every call is OIDC-authenticated, OPA-authorised (incl. data-license enforcement),
schema-validated, versioned, rate-limited, and **audit-logged** (tool, args hash,
requester, bank_id, timestamp, latency, result hash).
