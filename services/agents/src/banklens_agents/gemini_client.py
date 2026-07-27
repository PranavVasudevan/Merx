"""Gemini client — same `messages_create(...)` call shape and return shape as
`anthropic_client.py`, so `agent.py` and `supervisor.py` don't need to know or care
which provider is under them (see `providers.py`, which picks one at call time).

Internally translates Anthropic-shaped {messages, tools, tool_choice} into Gemini's
own wire format (system_instruction / contents / function_declarations /
tool_config), and translates Gemini's response back into Anthropic's
{"content": [...], "stop_reason": ...} shape.

Multi-key rotation via `gemini_keys` (ported from project-matcher) — set
GEMINI_API_KEY (main) plus GEMINI_API_KEY_1..GEMINI_API_KEY_4 (backups), or
GEMINI_API_KEYS as a comma list, for "1 main + 4 backups" == 5x the free-tier quota.

Zero-install: stdlib `urllib` only, no `google-generativeai` package.

CAVEAT (documented, not verified live — no Gemini key was available to test with):
the JSON-Schema `type` values BankLens's MCP tools already use ("string", "integer",
"object", ...) are passed straight through as Gemini's `parameters`. Gemini's v1beta
API is documented to accept this OpenAPI-style lowercase schema, but if a real call
ever rejects it, the fix is almost certainly upper-casing type strings — see
https://ai.google.dev/api/caching#Schema.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from . import gemini_keys

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash"  # override with GEMINI_MODEL; names get retired over time

_TRANSIENT_HTTP_STATUS = {500, 502, 503, 504}
_MAX_TRANSIENT_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.0


class MissingApiKey(RuntimeError):
    pass


class GeminiAPIError(RuntimeError):
    pass


def resolve_model(model: str | None) -> str:
    return model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


# ---- Anthropic-shaped <-> Gemini wire format ------------------------------
def _anthropic_tools_to_gemini(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [{"function_declarations": [
        {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
        for t in tools
    ]}]


def _tool_choice_to_config(tool_choice: dict | None) -> dict | None:
    if not tool_choice:
        return None
    if tool_choice.get("type") == "tool" and tool_choice.get("name"):
        return {"function_calling_config": {"mode": "ANY", "allowed_function_names": [tool_choice["name"]]}}
    return {"function_calling_config": {"mode": "AUTO"}}


def _messages_to_contents(messages: list[dict]) -> list[dict]:
    """Anthropic-shaped messages -> Gemini `contents`. Tracks tool_use_id -> name
    so a later tool_result (which only carries the id) can be translated into
    Gemini's functionResponse (which requires the name)."""
    contents: list[dict] = []
    id_to_name: dict[str, str] = {}

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            contents.append({"role": "user" if role == "user" else "model",
                             "parts": [{"text": content}]})
            continue

        parts = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                parts.append({"text": block["text"]})
            elif btype == "tool_use":
                id_to_name[block["id"]] = block["name"]
                parts.append({"functionCall": {"name": block["name"], "args": block["input"]}})
            elif btype == "tool_result":
                name = id_to_name.get(block["tool_use_id"], "unknown_tool")
                parts.append({"functionResponse": {"name": name, "response": {"result": block["content"]}}})
        contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
    return contents


def _gemini_response_to_anthropic(resp: dict) -> dict:
    candidates = resp.get("candidates") or []
    if not candidates:
        return {"content": [{"type": "text", "text": ""}], "stop_reason": "end_turn"}

    parts = candidates[0].get("content", {}).get("parts", [])
    blocks = []
    for i, part in enumerate(parts):
        if "functionCall" in part:
            fc = part["functionCall"]
            blocks.append({"type": "tool_use", "id": f"gemini_call_{i}",
                          "name": fc["name"], "input": fc.get("args", {})})
        elif "text" in part:
            blocks.append({"type": "text", "text": part["text"]})
    stop_reason = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    return {"content": blocks or [{"type": "text", "text": ""}], "stop_reason": stop_reason}


# ---- HTTP ------------------------------------------------------------------
def _post_with_retry(url: str, payload: bytes) -> dict:
    last_exc: Exception | None = None
    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _TRANSIENT_HTTP_STATUS and attempt < _MAX_TRANSIENT_RETRIES:
                time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
                continue
            detail = exc.read().decode("utf-8", errors="ignore")
            err = GeminiAPIError(f"Gemini API error {exc.code}: {detail or exc.reason}")
            err.status_code = exc.code  # tags 401/403/429 for gemini_keys rotation
            raise err from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < _MAX_TRANSIENT_RETRIES:
                time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
                continue
            raise GeminiAPIError(f"Network error calling Gemini API: {exc}") from exc
    raise GeminiAPIError(f"Gemini API call failed after retries: {last_exc}")


def messages_create(
    *, model: str, system: str, messages: list[dict], tools: list[dict] | None = None,
    tool_choice: dict | None = None, max_tokens: int = 1536, api_key: str | None = None,
) -> dict:
    """Same signature/return shape as anthropic_client.messages_create."""
    body: dict[str, Any] = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": _messages_to_contents(messages),
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    gemini_tools = _anthropic_tools_to_gemini(tools)
    if gemini_tools:
        body["tools"] = gemini_tools
    tool_config = _tool_choice_to_config(tool_choice)
    if tool_config:
        body["tool_config"] = tool_config
    payload = json.dumps(body).encode("utf-8")

    def _do(key: str) -> dict:
        url = f"{API_ROOT}/{model}:generateContent?key={key}"
        return _post_with_retry(url, payload)

    raw = gemini_keys.call_with_rotation(
        _do, api_key,
        no_key_error_factory=lambda kind: MissingApiKey(
            "No Gemini API key configured (or all configured keys are exhausted this run). "
            "Set GEMINI_API_KEY (main) + GEMINI_API_KEY_1..GEMINI_API_KEY_4 (backups), or "
            "GEMINI_API_KEYS=key1,key2,... — get keys free at https://aistudio.google.com/apikey"
            if kind == "no_keys" else
            "All configured Gemini keys are exhausted (429) for this process run."
        ),
    )
    return _gemini_response_to_anthropic(raw)
