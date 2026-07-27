"""MCP protocol tests — exercise handle() directly, no stdio.

Most tests (initialize/tools/list/error paths, argument coercion) don't touch the
data layer and run without any landed Bronze. One end-to-end coercion test does call
a real tool against the landed population (same data other suites already rely on).
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


def test_string_integer_argument_is_coerced():
    """Regression test for a REAL bug found live: a local Ollama model sent
    {"cert": "6976"} (string) for an integer-typed param, which then failed a
    dict lookup keyed by real ints with a misleading 'not found' error."""
    schema = {"type": "object", "properties": {"cert": {"type": "integer"}}}
    coerced = server._coerce_arguments({"cert": "6976"}, schema)
    assert coerced == {"cert": 6976} and isinstance(coerced["cert"], int)


def test_array_of_string_integers_coerced():
    schema = {"type": "object", "properties": {
        "certs": {"type": "array", "items": {"type": "integer"}}}}
    coerced = server._coerce_arguments({"certs": ["1", "2", 3]}, schema)
    assert coerced == {"certs": [1, 2, 3]}


def test_lone_scalar_coerced_into_singleton_array():
    schema = {"type": "object", "properties": {
        "certs": {"type": "array", "items": {"type": "integer"}}}}
    coerced = server._coerce_arguments({"certs": "6976"}, schema)
    assert coerced == {"certs": [6976]}


def test_uncoercible_value_passed_through_unchanged():
    schema = {"type": "object", "properties": {"cert": {"type": "integer"}}}
    coerced = server._coerce_arguments({"cert": "not-a-number"}, schema)
    assert coerced == {"cert": "not-a-number"}   # handler's own error will be clear


def test_tools_call_actually_coerces_end_to_end():
    """Full tools/call round trip with a string cert — must succeed, not 400."""
    r = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "get_bank_xray", "arguments": {"cert": "6976"}}})
    text = r["result"]["content"][0]["text"]
    assert not r["result"].get("isError")
    assert "DIME COMMUNITY BANK" in text.upper()


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
