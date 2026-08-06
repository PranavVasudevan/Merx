"""MCP protocol tests — exercise handle() directly, no stdio.

Most tests (initialize/tools/list/error paths, argument coercion) don't touch the
data layer and run without any landed Bronze. One end-to-end coercion test does call
a real tool against the landed population (same data other suites already rely on).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import server  # noqa: E402


class SkipTest(Exception):
    """A test needs landed Bronze data that isn't present. `data/` is git-ignored
    (it's reproducible from the landing scripts), so a fresh clone or CI legitimately
    won't have it — that's a SKIP, not a failure."""


def require_landed_data():
    from banklens_mcp import data
    if not data.available_quarters():
        raise SkipTest(f"no landed population under {data._POP_DIR} "
                       f"(run scripts/run_vertical_slice.ps1 / the landing scripts)")


def test_initialize_reports_server_info():
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}})
    assert r["result"]["serverInfo"]["name"] == "banklens"
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_initialized_notification_has_no_response():
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_initialize_captures_client_info_as_requester():
    """clientInfo.name is the only caller identity a stdio server gets — it must
    flow into the module-level `_requester` that `_audit` stamps on every row."""
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18",
                              "clientInfo": {"name": "agent:screener", "version": "0.1.0"}}})
    assert server._requester == "agent:screener"


def test_initialize_without_client_info_keeps_prior_requester():
    prior = server._requester
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18"}})
    assert server._requester == prior


def test_tools_list_exposes_all_features():
    r = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    for expected in ("get_bank_xray", "get_peer_cluster", "find_ma_matches",
                     "run_stress_test", "diff_filings", "list_banks", "compare_banks",
                     "get_risk_leaderboard"):
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
    """Full tools/call round trip with a string cert — must succeed, not 400.
    The only test in this file that needs real landed data."""
    require_landed_data()
    r = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "get_bank_xray", "arguments": {"cert": "6976"}}})
    text = r["result"]["content"][0]["text"]
    assert not r["result"].get("isError")
    assert "DIME COMMUNITY BANK" in text.upper()


def test_get_risk_leaderboard_sorted_descending():
    """Phase B — population-wide risk ranking (same score_vector/features_from
    the per-bank get_risk_score already uses). Needs landed data AND a trained
    deposit-flight model card, so a missing card is a SKIP, not a failure —
    same reasoning require_landed_data() already applies to missing Bronze."""
    require_landed_data()
    r = server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                       "params": {"name": "get_risk_leaderboard", "arguments": {"top_n": 5}}})
    text = r["result"]["content"][0]["text"]
    if r["result"].get("isError"):
        if "not trained yet" in text:
            raise SkipTest("deposit-flight model not trained yet (run deposit_flight_cli)")
        raise AssertionError(text)
    payload = json.loads(text)
    top = payload["top"]
    assert 0 < len(top) <= 5
    scores = [b["risk_score"] for b in top]
    assert scores == sorted(scores, reverse=True)


def test_non_dict_arguments_is_an_in_band_error_not_a_crash():
    """Regression test for a REAL bug found live: coercion used to run OUTSIDE the
    try/except, so a malformed non-dict `arguments` value (a client sending a bare
    string instead of an object) crashed the whole server subprocess instead of
    producing a clean in-band tool error."""
    r = server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                       "params": {"name": "get_bank_xray", "arguments": "not-a-dict"}})
    assert r is not None                 # handle() must return, not raise
    assert r["result"].get("isError")
    assert "error" in r["result"]["content"][0]["text"].lower()


def test_unknown_tool_is_an_error():
    r = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "does_not_exist", "arguments": {}}})
    assert "error" in r


def test_unknown_method_returns_error():
    r = server.handle({"jsonrpc": "2.0", "id": 4, "method": "no/such/method"})
    assert r["error"]["code"] == -32601


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and name != "require_landed_data":
            try:
                fn(); print(f"PASS  {name}")
            except SkipTest as e:
                skipped += 1; print(f"SKIP  {name}: {e}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:  # noqa: BLE001 — a crash is a failure, but must
                # NOT abort the remaining tests (real bug: an uncaught RuntimeError
                # used to kill the whole file, hiding every other test's result).
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
