"""Gemini client translation-logic tests — the HTTP layer is monkeypatched (no key,
no network needed), so this verifies the Anthropic-shaped <-> Gemini wire-format
translation is correct in both directions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import banklens_agents.gemini_client as gc  # noqa: E402

_TOOLS = [{"name": "get_bank_xray", "description": "risk breakdown",
          "input_schema": {"type": "object", "properties": {"cert": {"type": "integer"}}}}]


def test_tools_translate_to_function_declarations():
    out = gc._anthropic_tools_to_gemini(_TOOLS)
    assert out[0]["function_declarations"][0]["name"] == "get_bank_xray"
    assert out[0]["function_declarations"][0]["parameters"]["properties"]["cert"]["type"] == "integer"


def test_tool_choice_forces_allowed_function_names():
    cfg = gc._tool_choice_to_config({"type": "tool", "name": "route"})
    assert cfg["function_calling_config"]["mode"] == "ANY"
    assert cfg["function_calling_config"]["allowed_function_names"] == ["route"]


def test_simple_user_message_becomes_a_content_part():
    contents = gc._messages_to_contents([{"role": "user", "content": "hello"}])
    assert contents == [{"role": "user", "parts": [{"text": "hello"}]}]


def test_tool_use_and_result_round_trip_preserves_function_name():
    """The tricky part: Anthropic's tool_result only carries a tool_use_id, but
    Gemini's functionResponse needs the NAME — must be recovered from the earlier
    tool_use block with the matching id."""
    messages = [
        {"role": "user", "content": "how risky is Dime?"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "get_bank_xray", "input": {"cert": 6976}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"overall_risk": "high"}'}]},
    ]
    contents = gc._messages_to_contents(messages)
    assert contents[1]["parts"][0]["functionCall"] == {"name": "get_bank_xray", "input": {"cert": 6976}} \
        or contents[1]["parts"][0]["functionCall"]["name"] == "get_bank_xray"
    fr = contents[2]["parts"][0]["functionResponse"]
    assert fr["name"] == "get_bank_xray"
    assert fr["response"]["result"] == '{"overall_risk": "high"}'


def test_gemini_function_call_response_becomes_tool_use_block():
    raw = {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "get_bank_xray", "args": {"cert": 6976}}}]}}]}
    out = gc._gemini_response_to_anthropic(raw)
    assert out["stop_reason"] == "tool_use"
    assert out["content"][0] == {"type": "tool_use", "id": "gemini_call_0",
                                 "name": "get_bank_xray", "input": {"cert": 6976}}


def test_gemini_text_response_becomes_text_block():
    raw = {"candidates": [{"content": {"parts": [{"text": "the risk is low"}]}}]}
    out = gc._gemini_response_to_anthropic(raw)
    assert out == {"content": [{"type": "text", "text": "the risk is low"}], "stop_reason": "end_turn"}


def test_messages_create_end_to_end_with_mocked_http(monkeypatch):
    monkeypatch.setattr(gc, "_post_with_retry", lambda url, payload:
                        {"candidates": [{"content": {"parts": [
                            {"functionCall": {"name": "get_bank_xray", "args": {"cert": 6976}}}]}}]})
    resp = gc.messages_create(model="gemini-3.5-flash", system="sys",
                              messages=[{"role": "user", "content": "q"}],
                              tools=_TOOLS, api_key="fake-key-bypasses-pool")
    assert resp["content"][0]["name"] == "get_bank_xray"


def test_resolve_model_default_and_env_override(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert gc.resolve_model(None) == "gemini-3.5-flash"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    assert gc.resolve_model(None) == "gemini-custom"


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
                        def setenv(self, k, v):
                            os.environ[k] = v
                        def delenv(self, k, raising=True):
                            os.environ.pop(k, None)
                    fn(_MP())
                else:
                    fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
