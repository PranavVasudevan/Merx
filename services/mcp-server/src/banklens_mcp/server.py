"""MCP server entrypoint — SKELETON (Phase 5).

Declares the tool contracts from docs/api/mcp-tools.md. The real implementation
wires the official MCP SDK and dispatches to the feature services. For now this
documents the surface and lists the tools so the shape is version-controlled.

Install the SDK when this phase starts:  pip install "mcp[cli]"
"""

from __future__ import annotations

# Tool registry — (name, params, feature). Kept as data so it stays in lock-step
# with docs/api/mcp-tools.md and can be schema-generated later.
TOOLS: list[tuple[str, str, str]] = [
    ("list_banks", "query, filters", "search/filter"),
    ("get_bank_profile", "bank_id, quarter", "Silver/Gold core"),
    ("get_bank_xray", "bank_id", "F11 concentration risk"),
    ("diff_filings", "bank_id, quarter_a, quarter_b", "F12 filing diff"),
    ("get_risk_score", "bank_id", "F13 deposit-flight + SHAP"),
    ("get_peer_cluster", "bank_id", "F14 peers"),
    ("find_ma_matches", "bank_id, top_n", "F15 M&A fit"),
    ("run_stress_test", "bank_id, shock_params", "F16 stress sim"),
    ("compare_banks", "bank_id_list, metrics", "side-by-side"),
    ("get_price_candles", "ticker, interval, range", "candlestick OHLCV"),
    ("get_market_snapshot", "bank_id", "market cap, P/B, vol"),
    ("get_macro_series", "series_id, range", "FRED overlays"),
    ("search_filings_text", "query, filters", "RAG over filings"),
]


def main() -> None:
    print("BankLens MCP server — skeleton. Declared tools:")
    for name, params, feature in TOOLS:
        print(f"  {name}({params})  ->  {feature}")
    print("\nPhase 5 wires these to the MCP SDK with auth, audit, and rate limiting.")


if __name__ == "__main__":
    main()
