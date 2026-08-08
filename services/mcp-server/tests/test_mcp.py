"""MCP protocol + tool-contract tests. Exercises handle() directly, no stdio.

Protocol tests are hermetic. Tests needing landed Bronze SKIP rather than fail —
`data/` is git-ignored and reproducible from the landing scripts, so a fresh clone
or CI legitimately won't have it.

Run: ``python services/mcp-server/tests/test_mcp.py``  (no pytest needed)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "mcp-server" / "src"))
sys.path.insert(0, str(ROOT / "pipelines" / "transforms" / "src"))

from banklens_mcp import server  # noqa: E402
from banklens_mcp.tools import TOOLS, TOOL_BY_NAME  # noqa: E402


class SkipTest(Exception):
    """Needs landed Bronze that isn't present — a SKIP, not a failure."""


def require_landed_data():
    from banklens_mcp import data
    if not data.available_quarters():
        raise SkipTest("no landed population (run the landing scripts)")


def require_eu_data():
    from banklens_mcp import data
    require_landed_data()
    if not data._eu_silver():
        raise SkipTest("no landed EBA data (run scripts/land_eba.ps1)")


# ---- protocol ------------------------------------------------------------
def test_initialize_reports_server_info():
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}})
    assert r["result"]["serverInfo"]["name"] == "banklens"
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_initialize_captures_client_info_as_requester():
    """clientInfo.name is the only caller identity a stdio server gets — it must
    reach the audit log, or every call is attributed to "unknown"."""
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18",
                              "clientInfo": {"name": "agent:screener"}}})
    assert server._requester == "agent:screener"


def test_notifications_get_no_response():
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_and_unknown_tool_are_errors():
    assert "error" in server.handle({"jsonrpc": "2.0", "id": 1, "method": "no/such"})
    r = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "nope", "arguments": {}}})
    assert "error" in r


def test_malformed_arguments_are_an_in_band_error_not_a_crash():
    """A client sending a bare string instead of an object must not kill the server
    subprocess for every other in-flight call."""
    r = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "get_bank_profile", "arguments": "oops"}})
    assert r["result"].get("isError") is True


# ---- tool registry contracts ---------------------------------------------
def test_every_tool_has_a_name_description_schema_and_handler():
    assert len(TOOLS) >= 27
    for t in TOOLS:
        assert t["name"] and t["description"], t
        assert t["inputSchema"]["type"] == "object", t["name"]
        assert callable(t["handler"]), t["name"]


def test_tool_names_are_unique():
    names = [t["name"] for t in TOOLS]
    assert len(names) == len(set(names))


def test_all_six_features_plus_search_are_exposed():
    """The tool surface IS the product contract — every feature must be callable,
    not just visible in the UI."""
    required = {
        "get_bank_xray",          # F11
        "diff_filings",           # F12
        "get_risk_score",         # F13
        "get_peer_cluster",       # F14
        "find_ma_matches",        # F15
        "run_stress_test",        # F16
        "search_filings_text",    # F17
        "list_banks", "get_bank_profile", "compare_banks",
    }
    assert required <= {t["name"] for t in TOOLS}


def test_tools_list_is_serialisable_over_the_wire():
    """tools/list crosses a JSON boundary — a non-serialisable schema would break
    every client at handshake, not at call time."""
    r = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    json.dumps(r)
    assert len(r["result"]["tools"]) == len(TOOLS)


def test_string_integer_arguments_are_coerced():
    """Caught live from a local model emitting {"cert": "6976"} for an integer
    param, which then failed an int-keyed lookup with a misleading "not found"."""
    coerced = server._coerce_arguments({"cert": "6976"},
                                       TOOL_BY_NAME["get_bank_profile"]["inputSchema"])
    assert coerced["cert"] == 6976


def test_lone_scalar_coerced_into_singleton_array():
    schema = TOOL_BY_NAME["compare_banks"]["inputSchema"]
    assert server._coerce_arguments({"certs": 3511}, schema)["certs"] == [3511]


# ---- integration (needs landed data) -------------------------------------
def test_list_banks_returns_real_rows():
    require_landed_data()
    from banklens_mcp import tools
    res = tools.list_banks(limit=5)
    assert res["count"] > 0
    assert all(b["cert"] and b["name"] for b in res["banks"])


def test_eu_banks_are_in_the_population_and_filterable():
    require_eu_data()
    from banklens_mcp import tools
    res = tools.list_banks(country="DE", limit=50)
    assert res["banks"] and all(b["country"] == "DE" for b in res["banks"])


def test_eu_bank_stress_test_runs_and_discloses_the_skipped_leg():
    """EU banks became stress-testable once capital dollars were derived from
    ratio x RWA. The deposit leg still can't run, and must say so."""
    require_eu_data()
    from banklens_mcp import data, tools
    eu = next(g for g in data.population()["gold"]
              if g.get("country") not in (None, "US"))
    r = tools.run_stress(eu["cert_number"], loan_loss_pct=3.0,
                         deposit_outflow_pct=25.0, rate_shock_bps=200)
    assert r["before"]["cet1"] > 0 and r["after"]["cet1"] >= 0
    assert r["fully_covered"] is False
    assert "deposit_outflow" in {l["leg"] for l in r["legs_not_applied"]}


def test_eu_bank_xray_reports_partial_coverage():
    require_eu_data()
    from banklens_mcp import data, tools
    eu = next(g for g in data.population()["gold"]
              if g.get("country") not in (None, "US"))
    r = tools.get_bank_xray(eu["cert_number"])
    assert r["fully_assessed"] is False
    assert 0 < r["rules_evaluated"] < r["rules_total"]


def test_eu_certs_never_collide_with_us_certs():
    require_eu_data()
    from banklens_mcp import data
    gold = data.population()["gold"]
    us = {g["cert_number"] for g in gold if g.get("country") == "US"}
    eu = {g["cert_number"] for g in gold if g.get("country") not in (None, "US")}
    assert eu and not (us & eu)


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except SkipTest as e:
                skipped += 1; print(f"SKIP  {name}: {e}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:  # a crash is a failure, but must not abort the file
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
