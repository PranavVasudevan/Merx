# MCP tool contracts

The MCP server (Phase 5) exposes one governed, audited surface shared by the UI,
the CLI/SDK, and the AI agents. Tools are thin — heavy compute lives in the Rust
engines, ClickHouse, DuckDB, and ML services behind them.

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

| Tool | Signature | Notes |
|---|---|---|
| `get_price_candles` | `(ticker, interval, range)` | OHLCV for candlestick charts |
| `get_market_snapshot` | `(bank_id)` | market cap, P/B, 30d vol |
| `get_macro_series` | `(series_id, range)` | FRED overlays |
| `search_filings_text` | `(query, filters)` | RAG over 10-K/10-Q narrative |

## Cross-cutting
Every call is OIDC-authenticated, OPA-authorised (incl. data-license enforcement),
schema-validated, versioned, rate-limited, and **audit-logged** (tool, args hash,
requester, bank_id, timestamp, latency, result hash).
