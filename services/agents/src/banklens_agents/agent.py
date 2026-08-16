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
import threading
from dataclasses import dataclass, field

from banklens_mcp.authz import filter_authorized

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
    citation_url: str | None = None


@dataclass
class AgentResult:
    persona: str
    question: str
    answer: str
    provider: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    turns: int = 0
    # Caller roles this run was scoped to, and the tool set that survived
    # intersecting persona.tool_names against them (G2) — recorded even when
    # no tool from the excluded set was ever called, so the audit trail shows
    # what was AVAILABLE for the run, not just what got used.
    roles: tuple[str, ...] = field(default_factory=tuple)
    effective_tools: tuple[str, ...] = field(default_factory=tuple)
    # F16 — set when `cancel_event` fired mid-loop (a caller-side deadline
    # elapsed) rather than the model producing a real final answer. `answer`
    # is still populated (an honest explanation, or the last tool result
    # retrieved so far — see the cancellation branch below), so a caller that
    # doesn't care about the distinction can keep just reading `answer`.
    partial: bool = False


# D12 — citations: which frontend page actually shows the data a given tool
# call returned, so a claim in the answer can be deep-linked back to its
# proof rather than trusted on the model's word alone. Deliberately partial:
# only tools with an obvious, stable single-page home are mapped; a tool
# whose result is spread across several pages (or has none yet) gets no
# citation link rather than a guessed/misleading one.
_CERT_PAGE_TOOLS = {
    "get_bank_profile", "get_bank_xray", "get_peer_cluster", "get_risk_score",
    "get_holding_company", "find_ma_matches", "get_ma_pro_forma", "get_price_candles",
    "get_market_snapshot", "get_irrbb", "diff_filings", "get_metric_lineage",
    "run_stress_test", "run_stress_test_projection", "get_liquidity_survival",
    "run_segmented_stress_test", "run_correlated_stress", "run_stress_surface",
    "run_stress_comparison",
}
_CERT_TRENDS_TOOLS = {"get_bank_trends"}
_STATIC_PAGE_TOOLS = {
    "get_percentile_heatmap": "/heatmap",
    "get_asset_treemap": "/treemap",
    "get_metric_distribution": "/distributions",
    "get_market_overview": "/market",
    "get_market_coverage": "/market",
    "get_cluster_diagnostics": "/clusters",
    "get_model_card": "/model",
    "get_county_concentration": "/geography",
    "get_branch_map": "/geography",
    "get_ma_network": "/network",
    "get_risk_leaderboard": "/screener",
    "get_quarterly_briefing": "/briefing",
    "get_backtest_results": "/backtest",
    "get_filing_diff_population_summary": "/filing-diff",
    "search_filings_text": "/filings",
    "get_filings_coverage": "/filings",
    "list_banks": "/screener",
}
_POPULATION_GROUP_PAGES = {"earnings": "/earnings", "credit": "/credit", "funding": "/funding"}


def _citation_url(name: str, arguments: dict) -> str | None:
    cert = arguments.get("cert") if isinstance(arguments, dict) else None
    if name in _CERT_PAGE_TOOLS and cert is not None:
        return f"/bank/{cert}"
    if name in _CERT_TRENDS_TOOLS and cert is not None:
        return f"/trends?cert={cert}"
    if name == "get_population_metrics" and isinstance(arguments, dict):
        return _POPULATION_GROUP_PAGES.get(arguments.get("group"))
    return _STATIC_PAGE_TOOLS.get(name)


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
             provider: str | None = None, on_event=None,
             roles: list[str] | None = None,
             cancel_event: threading.Event | None = None,
             history: list[dict] | None = None) -> AgentResult:
    """Run one agent turn-loop for `question` under `persona`. `on_event(kind, payload)`
    is called for live progress (kind in "tool_call", "tool_result", "final").

    `history` (D12): prior turns of this same conversation, as plain
    `{"role": "user"|"assistant", "content": str}` pairs — the FINAL answer text
    of each earlier turn, not that turn's internal tool_use/tool_result content
    blocks. Deliberately not round-tripping the raw provider-internal `messages`
    list here: that shape is provider-specific (each client in this package
    translates it differently, see ollama_client.py/gemini_client.py) and can
    carry large tool-result payloads turn over turn, which would make every
    later turn in a long conversation resend everything every prior turn ever
    retrieved. A plain question/answer transcript is enough for the model to
    stay on-topic across a follow-up, at a bounded and predictable size.

    `cancel_event` (F16): checked at the top of every turn (i.e. before each
    provider call, the part that can legitimately take tens of seconds to
    minutes against Ollama). When set, the loop stops at that boundary and
    returns a partial result (`AgentResult.partial=True`) instead of starting
    another turn — cooperative, not preemptive: a provider call already
    in-flight when `cancel_event` fires still runs to completion, this only
    stops the NEXT one from starting. The caller (bridge_server._stream_
    assistant_answer) is the one actually enforcing a wall-clock deadline;
    this is what lets that enforcement actually shorten a still-running loop
    instead of just abandoning it unobserved.

    `roles`: the authenticated caller's roles (from bridge_server's JWT claims),
    if this run has one. When given, persona.tool_names is intersected against
    what G1's OPA policy (via authz.filter_authorized, the same primitive the
    MCP server itself uses) actually permits those roles — a viewer asking
    through the same persona as an analyst sees a strictly smaller tool set,
    not just the persona's static list. `None` (a trusted local CLI run with
    no caller-role context) skips the intersection entirely, preserving the
    persona's full static tool set — see mcp_client.py for the matching
    behavior on the MCP-transport side."""
    provider_name, client = providers.get_client(provider)
    model_id = providers.resolve_model(provider_name, model)

    persona_tools = list(persona.tool_names)
    allowed = tuple(filter_authorized(persona_tools, roles)) if roles is not None else persona.tool_names

    with MCPStdioClient(requester=f"agent:{persona.key}", roles=roles) as mcp:
        mcp_tools = mcp.list_tools()
        tools = _to_tool_schemas(mcp_tools, allowed)

        tool_names = {t["name"] for t in tools}
        messages: list[dict] = [*(history or []), {"role": "user", "content": question}]
        result = AgentResult(persona=persona.key, question=question, answer="", provider=provider_name,
                             roles=tuple(roles) if roles is not None else (),
                             effective_tools=tuple(sorted(tool_names)))
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

        def _cancelled() -> AgentResult:
            """F16 — `cancel_event` fired: stop here rather than starting another
            provider call. Same last-tool-result fallback `_finalize` uses for a
            stray artifact, but an honest "ran out of time" framing instead."""
            result.partial = True
            if seen_calls:
                last = next(reversed(seen_calls.values()))
                result.answer = ("(partial — the deadline was reached before the model "
                                 f"produced a final answer; here is the last data it retrieved: "
                                 f"{last[:500]})")
            else:
                result.answer = ("(partial — the deadline was reached before the model "
                                 "retrieved any data or produced an answer)")
            if on_event:
                # A dict, not a bare string — matches bridge_server.py's own
                # deadline-notice "timeout" event shape ({"message": ...}), so
                # a caller reading this stream can handle one "timeout" event
                # shape regardless of which of the two ever actually fires.
                on_event("timeout", {"message": result.answer})
            return result

        for turn in range(1, MAX_TURNS + 1):
            if cancel_event is not None and cancel_event.is_set():
                return _cancelled()
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
                citation_url = _citation_url(tu["name"], tu["input"])
                result.tool_calls.append(ToolCallRecord(tu["name"], tu["input"], preview, citation_url))
                if on_event:
                    on_event("tool_result", {"name": tu["name"], "preview": preview, "citation_url": citation_url})
                result_text = text + (_NUDGE if sig in seen_calls and any_repeat_this_turn else "")
                tool_results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": result_text})
            messages.append({"role": "user", "content": tool_results})

            consecutive_repeats = consecutive_repeats + 1 if any_repeat_this_turn else 0
            if consecutive_repeats >= 2:
                if cancel_event is not None and cancel_event.is_set():
                    return _cancelled()
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
        "provider": result.provider, "turns": result.turns, "partial": result.partial,
        "roles": list(result.roles), "effective_tools": list(result.effective_tools),
        "tool_calls": [{"name": c.name, "arguments": c.arguments, "result_preview": c.result_preview,
                       "citation_url": c.citation_url} for c in result.tool_calls],
    }
