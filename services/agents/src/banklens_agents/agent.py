"""The agent tool-calling loop: user question -> LLM -> MCP tool calls -> answer.

Provider-agnostic: whichever backend `providers.get_client()` resolves to (Ollama by
default — see providers.py for why), the loop logic is identical, since every
client module returns the same {"content": [...], "stop_reason": ...} shape.

Bounded to MAX_TURNS tool round-trips so a confused model can't loop forever burning
tokens (or, for Ollama, wall-clock — local inference is slow, see project-matcher's
own notes: ~200s for 6 candidates). Every tool call is recorded in the returned
transcript (in addition to the MCP server's own per-call audit log) for a second,
agent-side audit trail.

Duplicate-call guard: caught live against a small local model (llama3.2:1b) — it
gets the correct tool result every time, but doesn't reliably recognize "I now have
enough information, stop calling tools and answer." Left alone it just re-issues the
identical call until MAX_TURNS. A repeated (name, arguments) pair is answered from
cache (no wasted MCP round-trip) with an explicit nudge appended; two repeats in a
row force one final tools=None call so the loop is GUARANTEED to end with a real
answer instead of the generic "stopped" message, even against a stubborn small model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import providers
from .mcp_client import MCPStdioClient
from .personas import Persona

MAX_TURNS = 6
_NUDGE = (" [NOTE: you already called this exact tool with these exact arguments and "
         "got this result above. You have enough information now — respond in plain "
         "text with your final analysis. Do NOT call any tool again.]")


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    result_preview: str


@dataclass
class AgentResult:
    persona: str
    question: str
    answer: str
    provider: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    turns: int = 0


def _to_tool_schemas(mcp_tools: list[dict], allowed: tuple[str, ...]) -> list[dict]:
    """MCP tool listings -> the {name, description, input_schema} shape every
    provider client expects (each client translates this into its own wire format)."""
    allowed_set = set(allowed)
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
        for t in mcp_tools if t["name"] in allowed_set
    ]


def _call_signature(name: str, arguments) -> tuple:
    """A hashable fingerprint for a (tool, arguments) pair, used to detect and
    dedup repeat calls. Defensively tolerant of non-dict `arguments` — a weak
    model's malformed tool-call JSON can put a string or list there instead of an
    object (each provider client should already guard against this before
    constructing a tool_use block, but this is the last line of defense so a
    client-layer gap never crashes the loop with an AttributeError)."""
    if isinstance(arguments, dict):
        items = tuple(sorted((k, str(v)) for k, v in arguments.items()))
    else:
        items = (("_raw", str(arguments)),)
    return (name, items)


def _looks_like_stray_tool_call(text: str, tool_names: set[str]) -> bool:
    """A weak model's 'final answer' can itself be a malformed, hallucinated tool-call
    fragment instead of prose. Caught live in two distinct shapes from the SAME
    model (llama3.2:1b) on different runs: `{"get_bank_xray": {...}}` (tool name as
    the key) and `{"tool": "list_banks", "query": ..., ...}` (tool name as a "tool"
    field's value, arguments flattened to the top level instead of nested) — check
    both. Never show either raw artifact to the user as if it were a real analysis."""
    stripped = text.strip()
    if not stripped.startswith("{"):
        return False
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    return any(k in tool_names for k in parsed) or parsed.get("tool") in tool_names


def run_agent(persona: Persona, question: str, *, model: str | None = None,
             provider: str | None = None, on_event=None) -> AgentResult:
    """Run one agent turn-loop for `question` under `persona`. `on_event(kind, payload)`
    is called for live progress (kind in "tool_call", "tool_result", "final")."""
    provider_name, client = providers.get_client(provider)
    model_id = providers.resolve_model(provider_name, model)

    with MCPStdioClient(requester=f"agent:{persona.key}") as mcp:
        mcp_tools = mcp.list_tools()
        tools = _to_tool_schemas(mcp_tools, persona.tool_names)

        tool_names = {t["name"] for t in tools}
        messages: list[dict] = [{"role": "user", "content": question}]
        result = AgentResult(persona=persona.key, question=question, answer="", provider=provider_name)
        seen_calls: dict[tuple, str] = {}
        consecutive_repeats = 0

        def _finalize(text: str) -> str:
            """Never surface a stray tool-call artifact as if it were a real answer —
            fall back to the last real tool result instead (see _looks_like_stray_tool_call).
            If there's no real tool result to fall back on either, say so honestly
            rather than showing the raw artifact OR a bare '(no answer produced)'."""
            if text and not _looks_like_stray_tool_call(text, tool_names):
                return text
            if seen_calls:
                last = next(reversed(seen_calls.values()))
                return ("The model could not produce a clean written summary, but here is "
                       f"the underlying data it retrieved: {last[:500]}")
            if text:  # it WAS a stray tool-call artifact, and no data was ever retrieved
                return ("The model attempted a tool call but produced it in an unrecognized "
                       "format, and no data was retrieved. Try rephrasing the question, or "
                       "retry — small local models are inconsistent at this.")
            return "(no answer produced)"

        for turn in range(1, MAX_TURNS + 1):
            result.turns = turn
            resp = client.messages_create(model=model_id, system=persona.system_prompt,
                                          messages=messages, tools=tools)
            content = resp.get("content", [])
            messages.append({"role": "assistant", "content": content})

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses:
                raw = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                result.answer = _finalize(raw)
                if on_event:
                    on_event("final", result.answer)
                return result

            tool_results = []
            any_repeat_this_turn = False
            for tu in tool_uses:
                sig = _call_signature(tu["name"], tu["input"])
                if sig in seen_calls:
                    any_repeat_this_turn = True
                    text = seen_calls[sig]
                    if on_event:
                        on_event("tool_call", {"name": tu["name"], "input": tu["input"], "repeat": True})
                else:
                    if on_event:
                        on_event("tool_call", {"name": tu["name"], "input": tu["input"]})
                    text = mcp.call_tool(tu["name"], tu["input"])
                    seen_calls[sig] = text
                preview = text if len(text) <= 400 else text[:400] + "…"
                result.tool_calls.append(ToolCallRecord(tu["name"], tu["input"], preview))
                if on_event:
                    on_event("tool_result", {"name": tu["name"], "preview": preview})
                result_text = text + (_NUDGE if sig in seen_calls and any_repeat_this_turn else "")
                tool_results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": result_text})
            messages.append({"role": "user", "content": tool_results})

            consecutive_repeats = consecutive_repeats + 1 if any_repeat_this_turn else 0
            if consecutive_repeats >= 2:
                # Guaranteed termination: force one final call with NO tools, so the
                # model literally cannot call anything again and must produce text.
                final = client.messages_create(model=model_id, system=persona.system_prompt,
                                               messages=messages, tools=None)
                result.turns = turn + 1
                raw = "".join(b.get("text", "") for b in final.get("content", [])
                             if b.get("type") == "text")
                result.answer = _finalize(raw)
                if on_event:
                    on_event("final", result.answer)
                return result

        result.answer = "(stopped: exceeded max tool-call turns without a final answer)"
        return result


def to_json(result: AgentResult) -> dict:
    return {
        "persona": result.persona, "question": result.question, "answer": result.answer,
        "provider": result.provider, "turns": result.turns,
        "tool_calls": [{"name": c.name, "arguments": c.arguments, "result_preview": c.result_preview}
                       for c in result.tool_calls],
    }
