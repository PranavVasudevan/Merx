"""BankLens MCP server (Phase 5) — the governed tool surface.

Thin orchestration: tools validate + authorise + audit, then call the feature
services / DuckDB / ClickHouse / ML behind them. See docs/api/mcp-tools.md.
"""

__version__ = "0.0.1"
