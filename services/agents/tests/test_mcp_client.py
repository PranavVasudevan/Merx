"""MCPStdioClient tests — spawns the real MCP server subprocess (no network calls;
all data is already landed locally), proving agents reach BankLens ONLY through MCP.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_agents.mcp_client import MCPStdioClient  # noqa: E402


def test_list_tools_returns_all_features():
    with MCPStdioClient() as client:
        tools = client.list_tools()
    names = {t["name"] for t in tools}
    assert len(tools) == 11   # 9 feature tools + get_price_candles + get_market_snapshot
    assert "get_bank_xray" in names and "get_risk_score" in names
    assert "get_price_candles" in names and "get_market_snapshot" in names


def test_call_tool_returns_real_data():
    with MCPStdioClient() as client:
        text = client.call_tool("get_bank_xray", {"cert": 6976})
    data = json.loads(text)
    assert data["name"] == "DIME COMMUNITY BANK"
    assert data["overall_risk"] in ("low", "elevated", "high")


def test_call_tool_error_is_returned_not_raised():
    with MCPStdioClient() as client:
        text = client.call_tool("get_bank_xray", {"cert": 999999999})
    assert "error" in text.lower()


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
