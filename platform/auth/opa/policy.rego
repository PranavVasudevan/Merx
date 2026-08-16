package banklens

import future.keywords.if
import future.keywords.in

# Real authorization policy, not just "is the token valid" duplicated —
# that's authentication, already handled by the bridge's own JWT signature
# check (see services/api-gateway/src/bridge_server.py's _verify_token()).
# OPA answers a DIFFERENT question: given a validated identity's roles, is
# THIS action allowed? Two roles: "viewer" (read bank data) and "analyst"
# (viewer + can run the compute-heavier what-if simulators).
#
# Input shape (see bridge_server.py's _opa_authorize()) for a REST route:
#   {"path": "/api/banks/stress-test", "method": "GET", "roles": ["viewer"]}
# ...or, for an MCP tools/call (see banklens_mcp/authz.py's authorize_tool()),
# keyed by tool name instead of path/method — see mcp_viewer_tools below:
#   {"tool": "run_stress_test", "roles": ["viewer"]}

default allow := false

# Always open, no token required — health checks and metrics scraping
# shouldn't need a login (see bridge_server.py, these routes skip auth
# entirely and never call OPA — listed here too for documentation, this
# rule is never actually evaluated for them).
open_routes := {"/api/health", "/metrics", "/api/openapi.json"}

# Any authenticated viewer or analyst can read core bank data. `ma-fit`
# belongs here, not in analyst_routes below: the frontend's App.tsx loads it
# in the SAME Promise.all() as profile/xray/peer-cluster/risk-score for every
# bank view — found live in a real browser session that putting it behind
# "analyst" broke the entire profile view for a viewer-role user (Promise.all
# rejects all-or-nothing on one 403), not just the M&A panel. It's a read/
# lookup (peer-matching), not a deliberately-triggered simulation, so viewer
# access is the correct fix, not a frontend workaround.
viewer_routes := {
    "/api/population",
    "/api/quarters",
    "/api/banks",
    "/api/banks/profile",
    "/api/banks/xray",
    "/api/banks/peer-cluster",
    "/api/banks/ma-fit",
    "/api/banks/ma-pro-forma",
    "/api/ma-weight-validation",
    "/api/xray-forward-return-validation",
    "/api/filing-diff-population-summary",
    "/api/backtest",
    "/api/banks/filing-diff",
    "/api/banks/risk-score",
    "/api/banks/candles",
    "/api/banks/market-snapshot",
    "/api/market/coverage",
    "/api/market/overview",
    "/api/macro",
    "/api/data-freshness",
    "/api/metric-lineage",
    "/api/banks/holding-company",
    "/api/risk-leaderboard",
    "/api/compare",
    "/api/population-metrics",
    "/api/metric-distribution",
    "/api/percentile-heatmap",
    "/api/asset-treemap",
    "/api/banks/trends",
    # E10 — batched per-bank trends for a peer-set small-multiples view, same
    # read-only tier as the single-bank /api/banks/trends it sits alongside.
    "/api/banks/trends-bulk",
    # E12 — batched trailing-quarter series for a table's sparkline column
    # (screener/earnings/credit/funding), same read-only tier as
    # /api/population-metrics and /api/banks/trends it sits alongside.
    "/api/population-trends",
    "/api/briefing",
    "/api/cluster-diagnostics",
    "/api/model-card",
    "/api/county-concentration",
    "/api/branch-map",
    "/api/network",
    "/api/filings/search",
    "/api/filings/coverage",
    "/api/banks/tearsheet",
    # C5 — EVE/NII sensitivity read, same tier as its MCP counterpart
    # (get_irrbb is in mcp_viewer_tools below) — a disclosed-bucket-based
    # analysis, not a user-triggered simulation.
    "/api/banks/irrbb",
    # GET/POST/DELETE all need the same role (managing your own watchlist
    # isn't analyst-gated) — this set format can't express per-method rules
    # on the same path, but the bridge only ever calls authorize() with the
    # request's actual method, so one entry here covers all three verbs.
    "/api/watchlist",
    # D2 — saved screens, watchlist notes/rules, alerts: all scoped to the
    # caller's own user_sub server-side, so viewer access is correct (same
    # reasoning as /api/watchlist itself).
    "/api/watchlist/note",
    "/api/watchlist/rules",
    "/api/screens",
    "/api/peer-sets",
    "/api/annotations",
    "/api/scenarios",
    "/api/custom-scenarios",
    "/api/portfolio",
    "/api/portfolio/summary",
    "/api/alerts",
    "/api/alerts/seen",
    # G4 — export/delete the caller's own stored data (watchlist, agent-run
    # transcripts, audit-log entries), same own-user_sub scoping as the routes
    # just above — not an ops/analyst capability.
    "/api/privacy/export",
    "/api/privacy/data",
}

# Compute-heavier "what-if" actions: require the analyst role specifically.
# stress-test is a good fit here BECAUSE it's a standalone panel with its own
# user-triggered sliders/API call, not bundled into the core profile load.
analyst_routes := {
    "/api/banks/stress-test",
    "/api/banks/stress-test-bulk",
    "/api/banks/stress-test-compare",
    "/api/banks/stress-test-surface",
    # C4/C6 — multi-period projection, sustained-outflow liquidity horizon,
    # correlated joint scenario, and per-category segmented loss rates: the
    # same user-triggered what-if class as stress-test above, same tier as
    # their MCP counterparts in mcp_analyst_tools below.
    "/api/banks/stress-test-projection",
    "/api/banks/liquidity-survival",
    "/api/banks/correlated-stress",
    "/api/banks/segmented-stress-test",
    # /api/assistant/ask stays analyst-only in its own right (it can drive ANY
    # tool through the agent loop, including the analyst-tier ones below) —
    # no longer the sole enforcement point for the agent fleet now that
    # mcp_viewer_tools/mcp_analyst_tools give the MCP server its own per-tool
    # check (services/mcp-server/src/banklens_mcp/authz.py), but keeping this
    # route analyst-gated too is real defense in depth, not redundant: a
    # viewer asking the assistant a question that never touches an
    # analyst-tier tool still shouldn't reach this endpoint at all.
    "/api/assistant/ask",
    # Activity feeds can reveal OTHER users' questions/tool activity, not
    # just the caller's own — treat as an ops capability, not a plain read.
    "/api/activity/agent-runs",
    "/api/activity/audit-log",
}

allow if {
    input.path in open_routes
}

allow if {
    input.path in viewer_routes
    some role in input.roles
    role in {"viewer", "analyst"}
}

allow if {
    input.path in analyst_routes
    "analyst" in input.roles
}

# ---------------------------------------------------------------------------
# MCP tool tiers — the fix for the gap analyst_routes used to describe above:
# every tools/call the MCP server (services/mcp-server/src/banklens_mcp/server.py)
# receives is evaluated against these sets too, via the exact same OPA HTTP
# call the REST bridge makes (banklens_common.authz.opa_query, used by both
# services/api-gateway/src/auth.py and services/mcp-server/src/banklens_mcp/
# authz.py) — one policy file, not two authorization systems. Tiers mirror
# viewer_routes/analyst_routes' split for the same underlying operation
# (e.g. run_stress_test here == /api/banks/stress-test above).
#
# Input shape for a tool call: {"tool": "run_stress_test", "roles": ["analyst"]}
mcp_viewer_tools := {
    "list_banks", "get_bank_profile", "get_holding_company", "get_bank_xray",
    "get_peer_cluster", "find_ma_matches", "get_ma_pro_forma", "get_ma_weight_validation",
    "get_xray_forward_return_validation",
    "get_irrbb", "get_risk_score",
    "get_risk_leaderboard", "diff_filings", "get_bank_trends", "get_quarterly_briefing",
    "compare_banks", "get_population_metrics", "get_percentile_heatmap", "get_asset_treemap",
    "get_metric_distribution", "get_price_candles", "get_market_snapshot", "get_market_coverage",
    "get_market_overview",
    "get_data_freshness", "get_metric_lineage", "get_macro_data", "get_cluster_diagnostics", "get_model_card",
    "get_county_concentration", "get_branch_map", "get_ma_network", "search_filings_text",
    "get_filings_coverage", "get_population_trend_sparklines",
    "get_filing_diff_population_summary", "get_backtest_results",
}

mcp_analyst_tools := {
    "run_stress_test", "run_stress_test_projection", "get_liquidity_survival",
    "run_segmented_stress_test", "run_correlated_stress", "run_bulk_stress_test",
    "run_stress_surface", "run_stress_comparison",
}

allow if {
    input.tool in mcp_viewer_tools
    some role in input.roles
    role in {"viewer", "analyst"}
}

allow if {
    input.tool in mcp_analyst_tools
    "analyst" in input.roles
}
