"""Ollama client — same `messages_create(...)` call/return shape as
`anthropic_client.py` and `gemini_client.py` (see `providers.py`), so the agent loop
is fully provider-agnostic.

Uses a plain-text tool-call protocol (describe tools in the prompt, ask for a JSON
action, extract robustly) rather than Ollama's NATIVE tool-calling API
(`/api/chat` with `tools=`) — that native path was tested against qwen2.5-coder:3b
on this machine and returned corrupted output (`"Hello@@@@@@@@..."`, even on a
plain "say hello" prompt with no tools involved — a broken local model/server
state, not a code bug). Plain `/api/generate` + robust JSON extraction is exactly
the approach project-matcher already validated works for small local models
(`matcher/engine/parser.py`'s `_extract_json`) — ported here almost verbatim.

Default model is `llama3.2:1b` — confirmed working cleanly on this machine right
now. `qwen2.5-coder:3b` is nominally more capable at structured output (per
project-matcher's own notes) but was garbled here; re-pull it
(`ollama pull qwen2.5-coder:3b`) and set OLLAMA_MODEL to try it again.

Zero-install: stdlib only, talks to the local Ollama HTTP server.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = "llama3.2:1b"
DEFAULT_HOST = "http://localhost:11434"
_MAX_TRANSIENT_RETRIES = 2
_BACKOFF_BASE_SECONDS = 1.0


class OllamaError(RuntimeError):
    pass


def resolve_model(model: str | None) -> str:
    return model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)


def resolve_host() -> str:
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST)


# ---- robust JSON extraction (ported from project-matcher's parser.py) -----
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(raw: str) -> dict | None:
    """Best-effort extraction of a JSON object from raw model text. Returns None
    (never raises) if nothing parses — callers must have a safe fallback, since a
    weak local model failing to produce valid JSON is an expected, common case."""
    candidates = [raw.strip()]

    fence_match = _FENCE_RE.search(raw)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    start = raw.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(raw[start:i + 1])
                    break

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    for candidate in candidates:
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate).replace("'", '"')
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            continue
    return None


# ---- prompt construction ----------------------------------------------------
def _flatten_messages(messages: list[dict]) -> str:
    """Anthropic-shaped messages -> a readable transcript a plain-completion
    model can follow (no native structured-message support needed)."""
    lines = []
    for msg in messages:
        role = msg["role"].upper()
        content = msg["content"]
        if isinstance(content, str):
            lines.append(f"{role}: {content}")
            continue
        for block in content:
            btype = block.get("type")
            if btype == "text":
                lines.append(f"{role}: {block['text']}")
            elif btype == "tool_use":
                lines.append(f"{role}: [called {block['name']}({json.dumps(block['input'])})]")
            elif btype == "tool_result":
                lines.append(f"TOOL RESULT: {block['content']}")
    return "\n".join(lines)


def _tools_block(tools: list[dict]) -> str:
    lines = ["Available tools:"]
    for t in tools:
        lines.append(f"  - {t['name']}: {t['description']} "
                     f"(arguments schema: {json.dumps(t['input_schema'])})")
    return "\n".join(lines)


# ---- HTTP --------------------------------------------------------------------
def _generate(prompt: str, model: str, host: str) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        req = urllib.request.Request(f"{host}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("response", "")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < _MAX_TRANSIENT_RETRIES:
                time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
                continue
            raise OllamaError(
                f"Could not reach Ollama at {host} — is it running? (`ollama serve`, "
                f"or check OLLAMA_HOST). {exc}"
            ) from exc
    raise OllamaError(f"Ollama call failed after retries: {last_exc}")


def messages_create(
    *, model: str, system: str, messages: list[dict], tools: list[dict] | None = None,
    tool_choice: dict | None = None, max_tokens: int = 1536, api_key: str | None = None,
) -> dict:
    """Same signature/return shape as anthropic_client.messages_create."""
    host = resolve_host()
    transcript = _flatten_messages(messages)

    if tool_choice and tool_choice.get("type") == "tool":
        forced_name = tool_choice["name"]
        tool = next((t for t in (tools or []) if t["name"] == forced_name), None)
        prompt = (
            f"{system}\n\n{transcript}\n\n"
            f"You must respond with ONLY a JSON object calling `{forced_name}` — "
            f"nothing else, no explanation. Schema: "
            f"{json.dumps(tool['input_schema']) if tool else '{}'}\n"
            f'Respond as: {{"name": "{forced_name}", "input": {{...}}}}'
        )
        raw = _generate(prompt, resolve_model(model), host)
        parsed = _extract_json(raw)
        if parsed and isinstance(parsed.get("input"), dict):
            return {"content": [{"type": "tool_use", "id": "ollama_call_0",
                                 "name": forced_name, "input": parsed["input"]}],
                    "stop_reason": "tool_use"}
        # Safe fallback: an enum-constrained forced tool (e.g. the supervisor's
        # `route`) degrades to picking whichever allowed value appears in the raw
        # text, so a weak model's bad JSON never crashes the caller.
        props = (tool or {}).get("input_schema", {}).get("properties", {})
        for key, spec in props.items():
            enum = spec.get("enum")
            if enum:
                hit = next((v for v in enum if v.lower() in raw.lower()), enum[0])
                return {"content": [{"type": "tool_use", "id": "ollama_call_0",
                                     "name": forced_name, "input": {key: hit, "reason": "fallback"}}],
                        "stop_reason": "tool_use"}
        return {"content": [{"type": "text", "text": raw}], "stop_reason": "end_turn"}

    if tools:
        prompt = (
            f"{system}\n\n{_tools_block(tools)}\n\n{transcript}\n\n"
            "To call a tool, respond with ONLY this JSON and nothing else: "
            '{"tool": "<tool_name>", "arguments": {...}}\n'
            "If you already have enough information to answer, respond in plain "
            "text instead (no JSON)."
        )
        raw = _generate(prompt, resolve_model(model), host)
        parsed = _extract_json(raw)
        valid_names = {t["name"] for t in tools}
        if parsed and parsed.get("tool") in valid_names:
            return {"content": [{"type": "tool_use", "id": "ollama_call_0",
                                 "name": parsed["tool"], "input": parsed.get("arguments", {})}],
                    "stop_reason": "tool_use"}
        # No valid tool call parsed -> treat the whole response as the final answer.
        return {"content": [{"type": "text", "text": raw}], "stop_reason": "end_turn"}

    raw = _generate(f"{system}\n\n{transcript}", resolve_model(model), host)
    return {"content": [{"type": "text", "text": raw}], "stop_reason": "end_turn"}
