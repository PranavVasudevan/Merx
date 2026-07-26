"""Minimal Anthropic Messages API client — stdlib `urllib` only, no `anthropic`
pip package. Same philosophy as the FDIC connector: zero installs, fully inspectable.

Reads the key from $ANTHROPIC_API_KEY (or a .env file at the repo root) — never
hardcoded, never logged, never sent anywhere but api.anthropic.com.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Friendly names -> model IDs (see claude-api skill / system prompt for current IDs).
MODELS = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5-20251001",
}

REPO = Path(__file__).resolve().parents[4]


class MissingApiKey(RuntimeError):
    pass


def _load_dotenv_key() -> str | None:
    env_path = REPO / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY") or _load_dotenv_key()
    if not key:
        raise MissingApiKey(
            "ANTHROPIC_API_KEY not set. Get a key from https://console.anthropic.com/settings/keys "
            "and either `set ANTHROPIC_API_KEY=...` in your shell, or add "
            "ANTHROPIC_API_KEY=... to .env at the repo root (already git-ignored)."
        )
    return key


def messages_create(
    *, model: str, system: str, messages: list[dict], tools: list[dict] | None = None,
    tool_choice: dict | None = None, max_tokens: int = 1536, api_key: str | None = None,
) -> dict:
    """One call to POST /v1/messages. Returns the parsed JSON response."""
    key = api_key or get_api_key()
    body: dict = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API error {e.code}: {detail}") from e
