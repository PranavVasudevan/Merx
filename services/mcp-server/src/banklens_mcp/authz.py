"""Per-tool authorization for the MCP server.

platform/auth/opa/policy.rego used to say plainly that the MCP server had no
authorization of its own — any process that could spawn it got all of
tools.TOOLS with zero checks, and the REST bridge's /api/assistant/ask gate was
the sole enforcement point for the entire agent fleet. This module closes that
gap: every `tools/call` is evaluated against the SAME OPA policy the bridge
already evaluates REST routes against (banklens_common.authz.opa_query, the
same HTTP mechanism services/api-gateway/src/auth.py uses — not a second,
invented authorization system), keyed by tool name instead of by REST path.

MCP_TOOL_TIERS below is a hand-kept MIRROR of policy.rego's mcp_viewer_tools /
mcp_analyst_tools sets. It is used ONLY when OPA itself is unreachable (e.g. a
bare local run without `docker compose -f platform/docker/docker-compose.dev.yml
up -d opa`) — real OPA is still tried first on every call. Without this
fallback, an unreachable OPA would force a choice between failing every tool
call closed (the MCP server would be unusable in the exact "quick local run
without Docker" scenario server.py's own module docstring already promises
for the audit log) or failing open (a real vulnerability). Re-evaluating the
same tier rules in-process avoids both: enforcement never lapses, it just
stops being hot-reloadable from policy.rego until OPA comes back. Kept in sync
with the rego sets by tests/test_authz.py, the same pattern
services/api-gateway/src/bridge_server.py's ROUTE_TIERS already uses against
this exact file.
"""

from __future__ import annotations

import sys

from banklens_common.authz import OpaUnavailable, opa_query

MCP_TOOL_TIERS: dict[str, str] = {
    "list_banks": "viewer",
    "get_bank_profile": "viewer",
    "get_holding_company": "viewer",
    "get_bank_xray": "viewer",
    "get_peer_cluster": "viewer",
    "find_ma_matches": "viewer",
    "get_ma_pro_forma": "viewer",
    "get_ma_weight_validation": "viewer",
    "run_stress_test": "analyst",
    "run_stress_test_projection": "analyst",
    "get_liquidity_survival": "analyst",
    "run_segmented_stress_test": "analyst",
    "get_irrbb": "viewer",
    "run_correlated_stress": "analyst",
    "get_risk_score": "viewer",
    "get_risk_leaderboard": "viewer",
    "diff_filings": "viewer",
    "get_bank_trends": "viewer",
    "get_quarterly_briefing": "viewer",
    "compare_banks": "viewer",
    "get_population_metrics": "viewer",
    "get_percentile_heatmap": "viewer",
    "get_asset_treemap": "viewer",
    "get_metric_distribution": "viewer",
    "get_price_candles": "viewer",
    "get_market_snapshot": "viewer",
    "get_market_coverage": "viewer",
    "get_market_overview": "viewer",
    "get_data_freshness": "viewer",
    "get_macro_data": "viewer",
    "get_cluster_diagnostics": "viewer",
    "get_model_card": "viewer",
    "get_county_concentration": "viewer",
    "get_branch_map": "viewer",
    "get_ma_network": "viewer",
    "run_bulk_stress_test": "analyst",
    "run_stress_surface": "analyst",
    "run_stress_comparison": "analyst",
    "search_filings_text": "viewer",
    "get_filings_coverage": "viewer",
    "get_population_trend_sparklines": "viewer",
}

_VALID_ROLES = {"viewer", "analyst"}
_opa_warned = False


class AuthorizationError(Exception):
    """Authenticated (or not — see server.py) caller's roles don't clear this
    tool's tier. Raised in-band inside tools/call, same as any other tool
    error (MCP has no separate 403 concept over stdio)."""


def _fallback_allow(tool: str, roles: list[str]) -> bool:
    tier = MCP_TOOL_TIERS.get(tool)
    if tier == "viewer":
        return any(r in _VALID_ROLES for r in roles)
    if tier == "analyst":
        return "analyst" in roles
    return False  # unknown tool: deny, don't guess


def authorize_tool(tool: str, roles: list[str]) -> None:
    """Raises AuthorizationError if `roles` may not call `tool`. Tries the
    real OPA policy first (parity with the REST bridge, and so a policy.rego
    edit takes effect without redeploying this server); falls back to the
    in-process mirror only if OPA is unreachable — see module docstring."""
    global _opa_warned
    try:
        allowed = opa_query({"tool": tool, "roles": roles})
    except OpaUnavailable as exc:
        if not _opa_warned:
            print(f"[banklens_mcp] OPA unavailable ({exc}); falling back to "
                  f"the in-process policy mirror for tool authorization",
                  file=sys.stderr)
            _opa_warned = True
        allowed = _fallback_allow(tool, roles)
    if not allowed:
        raise AuthorizationError(
            f"role(s) {roles} not permitted to call tool '{tool}'")


def filter_authorized(tools: list[str], roles: list[str]) -> list[str]:
    """Batched form of authorize_tool for a caller that needs the whole
    effective subset (e.g. the agent framework intersecting a persona's
    static tool list against what the caller's roles actually permit)
    rather than a single yes/no. Same per-tool OPA/fallback decision as
    authorize_tool, just not raising — order of `tools` is preserved."""
    allowed = []
    for tool in tools:
        try:
            authorize_tool(tool, roles)
        except AuthorizationError:
            continue
        allowed.append(tool)
    return allowed
