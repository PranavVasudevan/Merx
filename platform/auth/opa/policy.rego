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
# Input shape (see bridge_server.py's _opa_authorize()):
#   {"path": "/api/banks/stress-test", "method": "GET", "roles": ["viewer"]}

default allow := false

# Always open, no token required — health checks and metrics scraping
# shouldn't need a login (see bridge_server.py, these routes skip auth
# entirely and never call OPA — listed here too for documentation, this
# rule is never actually evaluated for them).
open_routes := {"/api/health", "/metrics"}

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
    "/api/banks",
    "/api/banks/profile",
    "/api/banks/xray",
    "/api/banks/peer-cluster",
    "/api/banks/ma-fit",
    "/api/banks/filing-diff",
    "/api/banks/risk-score",
    "/api/banks/candles",
    "/api/banks/market-snapshot",
    "/api/risk-leaderboard",
    "/api/compare",
    "/api/population-metrics",
    "/api/metric-distribution",
    "/api/percentile-heatmap",
    "/api/asset-treemap",
    "/api/banks/trends",
    "/api/briefing",
    # GET/POST/DELETE all need the same role (managing your own watchlist
    # isn't analyst-gated) — this set format can't express per-method rules
    # on the same path, but the bridge only ever calls authorize() with the
    # request's actual method, so one entry here covers all three verbs.
    "/api/watchlist",
}

# Compute-heavier "what-if" actions: require the analyst role specifically.
# stress-test is a good fit here BECAUSE it's a standalone panel with its own
# user-triggered sliders/API call, not bundled into the core profile load.
analyst_routes := {
    "/api/banks/stress-test",
    # The MCP server has NO authorization of its own (OPA is only enforced
    # here, at the REST bridge) — a persona can call run_stress_test or any
    # other tool directly through the agent loop with no secondary check.
    # This whole-endpoint gate is therefore the SOLE enforcement point for
    # the entire agent fleet, not a redundant one — keep it analyst-only
    # until/unless real per-tool authorization is built inside the loop.
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
