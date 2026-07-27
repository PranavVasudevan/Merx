"""Agent tool-calling loop — the LLM call is monkeypatched (on the default ollama_client
provider) to return canned responses, so this tests the REAL round-trip against the
REAL MCP server (real data, real tool dispatch) without needing any API key or a
running local model. Provider-agnostic loop logic — see agent.py/providers.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import banklens_agents.agent as agent_mod  # noqa: E402
import banklens_agents.ollama_client as ollama_client  # noqa: E402
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
    monkeypatch.setattr(ollama_client, "messages_create",
                        _tool_use_then_final("get_bank_xray", {"cert": 6976},
                                             "Dime Community Bank is HIGH risk due to CRE concentration."))
    persona = PERSONAS["risk_analyst"]
    result = agent_mod.run_agent(persona, "how risky is Dime?", provider="ollama")

    assert result.provider == "ollama"
    assert result.turns == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_bank_xray"
    assert "DIME COMMUNITY BANK" in result.tool_calls[0].result_preview.upper()
    assert "HIGH risk" in result.answer


def test_agent_with_no_tool_calls_returns_immediately(monkeypatch):
    def fake(**kwargs):
        return {"content": [{"type": "text", "text": "No tool needed."}], "stop_reason": "end_turn"}
    monkeypatch.setattr(ollama_client, "messages_create", fake)

    result = agent_mod.run_agent(PERSONAS["generalist"], "hello", provider="ollama")
    assert result.turns == 1
    assert result.tool_calls == []
    assert result.answer == "No tool needed."


def test_duplicate_tool_calls_terminate_with_a_real_answer(monkeypatch):
    """Regression test for a REAL failure found live against llama3.2:1b: the model
    got the correct tool result every time but kept re-calling the SAME tool
    instead of answering. The loop must (a) not waste a real MCP round-trip on the
    repeat and (b) still terminate with an actual answer, not the generic
    '(stopped: exceeded max turns)' message."""
    import banklens_agents.mcp_client as mcp_client_mod

    real_calls = {"n": 0}
    orig_call_tool = mcp_client_mod.MCPStdioClient.call_tool

    def counting_call_tool(self, name, arguments):
        real_calls["n"] += 1
        return orig_call_tool(self, name, arguments)
    monkeypatch.setattr(mcp_client_mod.MCPStdioClient, "call_tool", counting_call_tool)

    def always_repeats_the_same_call(*, model, system, messages, tools=None, tool_choice=None,
                                     max_tokens=1536, api_key=None):
        if tools is None:  # the forced final no-tools synthesis call
            return {"content": [{"type": "text", "text": "Dime is high risk due to CRE concentration."}],
                    "stop_reason": "end_turn"}
        return {"content": [{"type": "tool_use", "id": "toolu_x",
                             "name": "get_bank_xray", "input": {"cert": 6976}}],
                "stop_reason": "tool_use"}
    monkeypatch.setattr(ollama_client, "messages_create", always_repeats_the_same_call)

    persona = PERSONAS["risk_analyst"]
    result = agent_mod.run_agent(persona, "how risky is Dime?", provider="ollama")

    assert real_calls["n"] == 1                     # deduped — not called 3+ times
    assert len(result.tool_calls) >= 3               # still recorded every "call" in the transcript
    assert "high risk" in result.answer.lower()      # a REAL answer, not the generic stop message
    assert "stopped: exceeded" not in result.answer


def test_stray_tool_call_artifact_is_replaced_with_real_data(monkeypatch):
    """Regression test for a REAL failure found live against llama3.2:1b: after a
    SUCCESSFUL tool call with real data, its 'final answer' turn was itself a
    malformed JSON tool-call fragment, e.g. '{"get_bank_xray": {...}}' — never show
    that raw artifact to the user as if it were a real analysis."""
    calls = {"n": 0}

    def fake(*, model, system, messages, tools=None, tool_choice=None, max_tokens=1536, api_key=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": [{"type": "tool_use", "id": "toolu_1",
                                 "name": "get_bank_xray", "input": {"cert": 6976}}],
                    "stop_reason": "tool_use"}
        # the "final answer" is itself a stray tool-call-shaped artifact
        return {"content": [{"type": "text",
                             "text": '{"get_bank_xray": {"cert": "6976", "arguments": {}}}'}],
                "stop_reason": "end_turn"}
    monkeypatch.setattr(ollama_client, "messages_create", fake)

    result = agent_mod.run_agent(PERSONAS["risk_analyst"], "how risky is Dime?", provider="ollama")
    assert "get_bank_xray" not in result.answer or '"get_bank_xray":' not in result.answer
    assert "underlying data it retrieved" in result.answer  # the honest fallback kicked in


def test_normal_prose_answer_passes_through_unchanged(monkeypatch):
    def fake(**kwargs):
        return {"content": [{"type": "text", "text": "Dime is high risk due to CRE concentration."}],
                "stop_reason": "end_turn"}
    monkeypatch.setattr(ollama_client, "messages_create", fake)
    result = agent_mod.run_agent(PERSONAS["generalist"], "how risky is Dime?", provider="ollama")
    assert result.answer == "Dime is high risk due to CRE concentration."


def test_unknown_provider_raises():
    raised = False
    try:
        agent_mod.run_agent(PERSONAS["generalist"], "hello", provider="not_a_real_provider")
    except ValueError as e:
        raised = True
        assert "unknown provider" in str(e)
    assert raised


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                import inspect
                if "monkeypatch" in inspect.signature(fn).parameters:
                    class _MP:
                        def setattr(self, obj, attr, val):
                            setattr(obj, attr, val)
                    fn(_MP())
                else:
                    fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
