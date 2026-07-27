"""Ollama client tests — JSON extraction, tool-call parsing, and the safe-fallback
paths, with the HTTP call monkeypatched (no live Ollama server required).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import banklens_agents.ollama_client as oc  # noqa: E402

_TOOLS = [{"name": "get_bank_xray", "description": "risk breakdown",
          "input_schema": {"type": "object", "properties": {"cert": {"type": "integer"}},
                           "required": ["cert"]}}]


def test_extract_json_direct():
    assert oc._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_fenced():
    assert oc._extract_json('here:\n```json\n{"a": 1}\n```\nthanks') == {"a": 1}


def test_extract_json_embedded_in_prose():
    assert oc._extract_json('Sure! {"tool": "x", "arguments": {"cert": 1}} is my answer.') == \
        {"tool": "x", "arguments": {"cert": 1}}


def test_extract_json_trailing_comma_fixup():
    assert oc._extract_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_extract_json_returns_none_not_raise_on_garbage():
    assert oc._extract_json("not json at all, just prose") is None
    assert oc._extract_json("@@@@@@@@@@@@") is None


def test_messages_create_valid_tool_call(monkeypatch):
    monkeypatch.setattr(oc, "_generate", lambda prompt, model, host:
                        '{"tool": "get_bank_xray", "arguments": {"cert": 6976}}')
    resp = oc.messages_create(model="llama3.2:1b", system="sys",
                              messages=[{"role": "user", "content": "how risky is Dime?"}],
                              tools=_TOOLS)
    assert resp["stop_reason"] == "tool_use"
    block = resp["content"][0]
    assert block["type"] == "tool_use" and block["name"] == "get_bank_xray"
    assert block["input"] == {"cert": 6976}


def test_messages_create_falls_back_to_text_on_bad_json(monkeypatch):
    """A weak model failing to produce valid JSON must never crash the loop —
    the raw text becomes the final answer instead."""
    monkeypatch.setattr(oc, "_generate", lambda prompt, model, host: "I don't know how to help.")
    resp = oc.messages_create(model="llama3.2:1b", system="sys",
                              messages=[{"role": "user", "content": "hello"}], tools=_TOOLS)
    assert resp["stop_reason"] == "end_turn"
    assert resp["content"][0]["text"] == "I don't know how to help."


def test_messages_create_no_tools_is_plain_completion(monkeypatch):
    monkeypatch.setattr(oc, "_generate", lambda prompt, model, host: "plain answer")
    resp = oc.messages_create(model="llama3.2:1b", system="sys",
                              messages=[{"role": "user", "content": "hi"}])
    assert resp == {"content": [{"type": "text", "text": "plain answer"}], "stop_reason": "end_turn"}


def test_forced_tool_choice_valid_json(monkeypatch):
    monkeypatch.setattr(oc, "_generate", lambda prompt, model, host:
                        '{"name": "get_bank_xray", "input": {"cert": 3511}}')
    resp = oc.messages_create(model="llama3.2:1b", system="sys",
                              messages=[{"role": "user", "content": "q"}], tools=_TOOLS,
                              tool_choice={"type": "tool", "name": "get_bank_xray"})
    assert resp["content"][0]["input"] == {"cert": 3511}


def test_forced_tool_choice_enum_fallback_on_bad_json(monkeypatch):
    """The supervisor's routing case: a forced enum-valued tool. If JSON parsing
    fails, fall back to matching an allowed enum value found in the raw text."""
    route_tool = [{"name": "route", "description": "pick one",
                  "input_schema": {"type": "object",
                                   "properties": {"persona": {"type": "string",
                                                              "enum": ["risk_analyst", "ma_scout"]}}}}]
    monkeypatch.setattr(oc, "_generate", lambda prompt, model, host:
                        "I think this is clearly a case for the ma_scout persona.")
    resp = oc.messages_create(model="llama3.2:1b", system="sys",
                              messages=[{"role": "user", "content": "q"}], tools=route_tool,
                              tool_choice={"type": "tool", "name": "route"})
    assert resp["content"][0]["input"]["persona"] == "ma_scout"


def test_resolve_model_default_and_env_override(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert oc.resolve_model(None) == "llama3.2:1b"
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
    assert oc.resolve_model(None) == "qwen2.5-coder:3b"
    assert oc.resolve_model("explicit-model") == "explicit-model"  # explicit arg wins


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
                            import os
                            os.environ[k] = v
                        def delenv(self, k, raising=True):
                            import os
                            os.environ.pop(k, None)
                    fn(_MP())
                else:
                    fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
