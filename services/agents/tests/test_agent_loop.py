"""Agent tool-calling loop — the LLM call (messages_create) is monkeypatched to
return canned responses, so this tests the REAL round-trip against the REAL MCP
server (real data, real tool dispatch) without needing an ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import banklens_agents.agent as agent_mod  # noqa: E402
from banklens_agents.personas import PERSONAS  # noqa: E402


def _tool_use_then_final(tool_name: str, tool_input: dict, final_text: str):
    """A fake messages_create: first call requests a tool, second call finalizes."""
    calls = {"n": 0}

    def fake(*, model, system, messages, tools=None, tool_choice=None, max_tokens=1536, api_key=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": [{"type": "tool_use", "id": "toolu_1",
                                 "name": tool_name, "input": tool_input}],
                    "stop_reason": "tool_use"}
        return {"content": [{"type": "text", "text": final_text}], "stop_reason": "end_turn"}
    return fake


def test_agent_calls_real_tool_and_finalizes(monkeypatch):
    monkeypatch.setattr(agent_mod, "messages_create",
                        _tool_use_then_final("get_bank_xray", {"cert": 6976},
                                             "Dime Community Bank is HIGH risk due to CRE concentration."))
    persona = PERSONAS["risk_analyst"]
    result = agent_mod.run_agent(persona, "how risky is Dime?", model="sonnet")

    assert result.turns == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_bank_xray"
    assert "DIME COMMUNITY BANK" in result.tool_calls[0].result_preview.upper()
    assert "HIGH risk" in result.answer


def test_agent_with_no_tool_calls_returns_immediately(monkeypatch):
    def fake(**kwargs):
        return {"content": [{"type": "text", "text": "No tool needed."}], "stop_reason": "end_turn"}
    monkeypatch.setattr(agent_mod, "messages_create", fake)

    result = agent_mod.run_agent(PERSONAS["generalist"], "hello", model="haiku")
    assert result.turns == 1
    assert result.tool_calls == []
    assert result.answer == "No tool needed."


if __name__ == "__main__":
    import types

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                # minimal monkeypatch shim for standalone (non-pytest) execution
                class _MP:
                    def setattr(self, obj, attr, val):
                        setattr(obj, attr, val)
                fn(_MP())
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
