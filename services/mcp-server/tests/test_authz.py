"""Per-tool MCP authorization tests. No pytest needed.

OPA itself is never running in this test environment (no
`docker compose -f platform/docker/docker-compose.dev.yml up -d opa`), so
every authorize_tool() call here exercises the in-process fallback mirror —
that IS the thing under test: it must actually deny/allow correctly, not
just be present. See banklens_mcp/authz.py's module docstring for why that
fallback exists at all instead of failing every call closed or open.

Run: ``python services/mcp-server/tests/test_authz.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "mcp-server" / "src"))
sys.path.insert(0, str(ROOT / "pipelines" / "transforms" / "src"))

from banklens_mcp import authz  # noqa: E402
from banklens_mcp.tools import TOOLS  # noqa: E402

POLICY_REGO = ROOT / "platform" / "auth" / "opa" / "policy.rego"


def _rego_set(name: str) -> set[str]:
    text = POLICY_REGO.read_text(encoding="utf-8")
    m = re.search(name + r"\s*:=\s*\{(.*?)\}\s*\n", text, re.S)
    assert m, f"{name} not found in {POLICY_REGO}"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


# ---- fallback evaluator: the actual enforcement path in this environment --
def test_viewer_role_denied_analyst_tier_tool():
    """The acceptance criteria in one assertion: a viewer-only session must
    not be able to run a compute-heavier what-if simulator."""
    try:
        authz.authorize_tool("run_stress_test", ["viewer"])
        assert False, "expected AuthorizationError"
    except authz.AuthorizationError:
        pass


def test_analyst_role_allowed_analyst_tier_tool():
    authz.authorize_tool("run_stress_test", ["analyst"])  # must not raise


def test_analyst_role_also_covers_viewer_tier_tools():
    authz.authorize_tool("get_bank_profile", ["analyst"])  # must not raise


def test_viewer_role_allowed_viewer_tier_tool():
    authz.authorize_tool("get_bank_profile", ["viewer"])  # must not raise


def test_no_roles_denies_everything():
    for tool in ("get_bank_profile", "run_stress_test"):
        try:
            authz.authorize_tool(tool, [])
            assert False, f"expected AuthorizationError for {tool} with no roles"
        except authz.AuthorizationError:
            pass


def test_unknown_role_denied():
    try:
        authz.authorize_tool("get_bank_profile", ["guest"])
        assert False, "expected AuthorizationError"
    except authz.AuthorizationError:
        pass


def test_unknown_tool_denied_not_guessed():
    try:
        authz.authorize_tool("delete_everything", ["analyst"])
        assert False, "expected AuthorizationError"
    except authz.AuthorizationError:
        pass


# ---- single-source-of-truth sync --------------------------------------
def test_every_tool_is_tiered():
    names = {t["name"] for t in TOOLS}
    assert names == set(authz.MCP_TOOL_TIERS), (
        f"missing from MCP_TOOL_TIERS: {names - set(authz.MCP_TOOL_TIERS)}; "
        f"stale entries: {set(authz.MCP_TOOL_TIERS) - names}")


def test_python_mirror_matches_policy_rego():
    """MCP_TOOL_TIERS is a hand-kept mirror of policy.rego's mcp_viewer_tools/
    mcp_analyst_tools — this is what keeps them from silently drifting apart,
    the same role bridge_server.py's own (referenced) route/policy sync check
    plays for REST routes."""
    rego_viewer = _rego_set("mcp_viewer_tools")
    rego_analyst = _rego_set("mcp_analyst_tools")
    assert not (rego_viewer & rego_analyst), "a tool can't be in both tiers"
    py_viewer = {t for t, tier in authz.MCP_TOOL_TIERS.items() if tier == "viewer"}
    py_analyst = {t for t, tier in authz.MCP_TOOL_TIERS.items() if tier == "analyst"}
    assert py_viewer == rego_viewer, (
        f"viewer mismatch: python-only={py_viewer - rego_viewer}, "
        f"rego-only={rego_viewer - py_viewer}")
    assert py_analyst == rego_analyst, (
        f"analyst mismatch: python-only={py_analyst - rego_analyst}, "
        f"rego-only={rego_analyst - py_analyst}")


# ---- server.py wiring: session roles gate tools/call end to end ----------
def test_server_session_enforces_role_at_tools_call():
    from banklens_mcp import server

    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "roles": ["viewer"]}})
    denied = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "run_stress_test",
                                       "arguments": {"cert": 1}}})
    assert denied["result"]["isError"] is True
    assert "not permitted" in denied["result"]["content"][0]["text"]

    server.handle({"jsonrpc": "2.0", "id": 3, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "roles": ["analyst"]}})
    allowed = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "get_market_coverage", "arguments": {}}})
    assert allowed["result"].get("isError") is not True


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:  # a crash is a failure, but must not abort the file
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
