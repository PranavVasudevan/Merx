"""Tests for the agent turn-loop (services/agents/src/banklens_agents/agent.py),
in particular F16's `cancel_event` cooperative-cancellation addition — until now
this loop had no tests at all (it normally needs a live provider + a real MCP
stdio subprocess, neither of which belongs in a fast stdlib test). Fakes both
so the loop logic itself — not Ollama, not the MCP server — is what's under test.

Run: ``python services/agents/tests/test_agent.py``
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "agents" / "src"))
sys.path.insert(0, str(REPO / "services" / "mcp-server" / "src"))

from banklens_agents import agent as agent_mod  # noqa: E402
from banklens_agents.personas import Persona  # noqa: E402


class _FakeMCPClient:
    """Stands in for MCPStdioClient — no subprocess, no real MCP server."""

    def __init__(self, tool_results: dict[str, str] | None = None):
        self._tool_results = tool_results or {}
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_tools(self):
        return [{"name": "get_bank_xray", "description": "d", "inputSchema": {}}]

    def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        return self._tool_results.get(name, "some tool result")


class _FakeProviderClient:
    """`responses` is a list of `resp` dicts returned in order, one per
    `messages_create` call — mirrors the real {"content": [...]} shape every
    provider client (see providers.py) returns."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.call_count = 0

    def messages_create(self, *, model, system, messages, tools):
        self.call_count += 1
        if self._responses:
            return self._responses.pop(0)
        # Loop-forever safety net for a test that miscounts expected calls —
        # fail loudly with a stray-tool-call-shaped answer rather than IndexError.
        return {"content": [{"type": "text", "text": "(no more fake responses configured)"}]}


def _text_response(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _tool_call_response(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": arguments}]}


_PERSONA = Persona(key="test_persona", label="Test", system_prompt="be terse",
                   tool_names=("get_bank_xray",))


def _patch_provider(monkeypatch_holder, client):
    agent_mod.providers.get_client = lambda name=None: ("fake", client)
    agent_mod.providers.resolve_model = lambda provider_name, model: "fake-model"


def _patch_mcp(mcp_client):
    agent_mod.MCPStdioClient = lambda requester="", roles=None: mcp_client


def test_normal_run_returns_a_real_answer_and_no_partial_flag():
    client = _FakeProviderClient([_text_response("the answer")])
    _patch_provider(None, client)
    _patch_mcp(_FakeMCPClient())

    result = agent_mod.run_agent(_PERSONA, "a question?")
    assert result.answer == "the answer"
    assert result.partial is False
    assert result.turns == 1
    assert client.call_count == 1


def test_cancel_event_set_before_any_turn_returns_partial_without_calling_provider():
    client = _FakeProviderClient([_text_response("should never be reached")])
    _patch_provider(None, client)
    _patch_mcp(_FakeMCPClient())

    cancel = threading.Event()
    cancel.set()
    result = agent_mod.run_agent(_PERSONA, "a question?", cancel_event=cancel)

    assert result.partial is True
    assert "deadline was reached" in result.answer
    assert client.call_count == 0, "cancellation before turn 1 must not make any provider call"


def test_cancel_event_set_between_turns_stops_the_loop_and_keeps_prior_tool_data():
    # Turn 1: model calls a tool. Turn 2 would answer, but cancel_event fires
    # first — the loop must stop at the turn-2 boundary instead of calling the
    # provider again, and the partial answer must surface turn 1's real data.
    client = _FakeProviderClient([
        _tool_call_response("get_bank_xray", {"cert": 12345}),
        _text_response("should never be reached — cancelled before this turn"),
    ])
    _patch_provider(None, client)
    _patch_mcp(_FakeMCPClient({"get_bank_xray": "XRAY_DATA_12345"}))

    cancel = threading.Event()
    events: list[tuple[str, object]] = []

    def on_event(kind, payload):
        events.append((kind, payload))
        if kind == "tool_result":
            cancel.set()  # simulate the deadline firing right after the tool call

    result = agent_mod.run_agent(_PERSONA, "a question?", on_event=on_event, cancel_event=cancel)

    assert result.partial is True
    assert "XRAY_DATA_12345" in result.answer
    assert client.call_count == 1, "must not have made the second (post-cancel) provider call"
    assert any(kind == "timeout" for kind, _ in events), "on_event must fire a 'timeout' event"


def test_to_json_includes_partial_flag():
    result = agent_mod.AgentResult(persona="p", question="q", answer="a", partial=True)
    payload = agent_mod.to_json(result)
    assert payload["partial"] is True


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {e!r}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
