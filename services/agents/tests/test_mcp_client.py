"""MCPStdioClient tests — spawns the real MCP server subprocess (no network calls),
proving agents reach BankLens ONLY through MCP.

Every test here needs real landed Bronze data, because the MCP server warms its
population cache on startup. `data/` is git-ignored (reproducible from the landing
scripts), so on a fresh clone or in CI these SKIP rather than fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "mcp-server" / "src"))

from banklens_agents.mcp_client import MCPStdioClient  # noqa: E402


class SkipTest(Exception):
    """Landed Bronze data isn't present — a legitimate SKIP, not a failure."""


def require_landed_data():
    from banklens_mcp import data
    if not data.available_quarters():
        raise SkipTest(f"no landed population under {data._POP_DIR} "
                       f"(run scripts/run_vertical_slice.ps1 / the landing scripts)")


def test_list_tools_returns_all_features():
    require_landed_data()
    with MCPStdioClient() as client:
        tools = client.list_tools()
    names = {t["name"] for t in tools}
    assert len(tools) == 20   # 9 feature tools + get_price_candles + get_market_snapshot
                              # + get_risk_leaderboard + get_population_metrics
                              # + get_metric_distribution + get_percentile_heatmap
                              # + get_asset_treemap + get_bank_trends + get_quarterly_briefing
                              # + get_cluster_diagnostics + get_model_card
    assert "get_bank_xray" in names and "get_risk_score" in names
    assert "get_price_candles" in names and "get_market_snapshot" in names


def test_call_tool_returns_real_data():
    require_landed_data()
    with MCPStdioClient() as client:
        text = client.call_tool("get_bank_xray", {"cert": 6976})
    data = json.loads(text)
    assert data["name"] == "DIME COMMUNITY BANK"
    assert data["overall_risk"] in ("low", "elevated", "high")


def test_call_tool_error_is_returned_not_raised():
    require_landed_data()
    with MCPStdioClient() as client:
        text = client.call_tool("get_bank_xray", {"cert": 999999999})
    assert "error" in text.lower()


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
            except Exception as e:  # noqa: BLE001 — a crash must not abort the rest
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
