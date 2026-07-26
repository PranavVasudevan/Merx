"""The agent tool-calling loop: user question -> Claude -> MCP tool calls -> answer.

Bounded to MAX_TURNS tool round-trips so a confused model can't loop forever burning
tokens. Every tool call is recorded in the returned transcript (in addition to the
MCP server's own per-call audit log) for a second, agent-side audit trail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .anthropic_client import MODELS, messages_create
from .mcp_client import MCPStdioClient
from .personas import Persona

MAX_TURNS = 6


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
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    turns: int = 0


def _to_anthropic_tools(mcp_tools: list[dict], allowed: tuple[str, ...]) -> list[dict]:
    allowed_set = set(allowed)
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
        for t in mcp_tools if t["name"] in allowed_set
    ]


def run_agent(persona: Persona, question: str, *, model: str = "sonnet",
             on_event=None) -> AgentResult:
    """Run one agent turn-loop for `question` under `persona`. `on_event(kind, payload)`
    is called for live progress (kind in "tool_call", "tool_result", "final")."""
    model_id = MODELS.get(model, model)

    with MCPStdioClient() as client:
        mcp_tools = client.list_tools()
        tools = _to_anthropic_tools(mcp_tools, persona.tool_names)

        messages: list[dict] = [{"role": "user", "content": question}]
        result = AgentResult(persona=persona.key, question=question, answer="")

        for turn in range(1, MAX_TURNS + 1):
            result.turns = turn
            resp = messages_create(model=model_id, system=persona.system_prompt,
                                   messages=messages, tools=tools)
            content = resp.get("content", [])
            messages.append({"role": "assistant", "content": content})

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses:
                result.answer = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                if on_event:
                    on_event("final", result.answer)
                return result

            tool_results = []
            for tu in tool_uses:
                if on_event:
                    on_event("tool_call", {"name": tu["name"], "input": tu["input"]})
                text = client.call_tool(tu["name"], tu["input"])
                preview = text if len(text) <= 400 else text[:400] + "…"
                result.tool_calls.append(ToolCallRecord(tu["name"], tu["input"], preview))
                if on_event:
                    on_event("tool_result", {"name": tu["name"], "preview": preview})
                tool_results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": text})
            messages.append({"role": "user", "content": tool_results})

        result.answer = "(stopped: exceeded max tool-call turns without a final answer)"
        return result


def to_json(result: AgentResult) -> dict:
    return {
        "persona": result.persona, "question": result.question, "answer": result.answer,
        "turns": result.turns,
        "tool_calls": [{"name": c.name, "arguments": c.arguments, "result_preview": c.result_preview}
                       for c in result.tool_calls],
    }
