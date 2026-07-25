"""Hermetic MCP protocol tests — exercise handle() directly, no stdio, no data.

The initialize / tools/list / error paths don't touch the data layer, so these run
without any landed Bronze. (Tool execution itself is covered by scripts/mcp_demo.py
against real data.)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import server  # noqa: E402


def test_initialize_reports_server_info():
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}})
    assert r["result"]["serverInfo"]["name"] == "banklens"
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_initialized_notification_has_no_response():
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_exposes_all_features():
    r = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    for expected in ("get_bank_xray", "get_peer_cluster", "find_ma_matches",
                     "run_stress_test", "diff_filings", "list_banks", "compare_banks"):
        assert expected in names
    # every tool has a description and an input schema
    assert all(t["description"] and t["inputSchema"]["type"] == "object"
               for t in r["result"]["tools"])


def test_unknown_tool_is_an_error():
    r = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "does_not_exist", "arguments": {}}})
    assert "error" in r


def test_unknown_method_returns_error():
    r = server.handle({"jsonrpc": "2.0", "id": 4, "method": "no/such/method"})
    assert r["error"]["code"] == -32601


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
