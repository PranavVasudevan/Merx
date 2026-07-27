"""Provider selection — picks which backend's `messages_create` the agent loop and
supervisor call, with the SAME shape regardless of provider.

Default is **ollama** (set BANKLENS_LLM_PROVIDER to override) — this project has a
hard $0 spending constraint, and Ollama is the only backend that costs literally
nothing to actually run, right now, on this machine. `anthropic` and `gemini` are
fully built and tested (loop mechanics + request/response translation), but calling
them for real costs money (Anthropic) or needs a free-but-still-external API key
(Gemini) — wire up keys and switch providers whenever that's actually wanted.
"""

from __future__ import annotations

import os
from types import ModuleType

from . import anthropic_client, gemini_client, ollama_client

PROVIDERS: dict[str, ModuleType] = {
    "anthropic": anthropic_client,
    "gemini": gemini_client,
    "ollama": ollama_client,
}

DEFAULT_PROVIDER = "ollama"


def resolve_provider(name: str | None = None) -> str:
    return name or os.environ.get("BANKLENS_LLM_PROVIDER", DEFAULT_PROVIDER)


def get_client(name: str | None = None) -> tuple[str, ModuleType]:
    """Return (provider_name, client_module). Raises ValueError for an unknown name."""
    provider = resolve_provider(name)
    client = PROVIDERS.get(provider)
    if client is None:
        raise ValueError(f"unknown provider '{provider}' — choose one of {list(PROVIDERS)}")
    return provider, client


def resolve_model(provider_name: str, model: str | None) -> str:
    """Each client module exposes its own resolve_model except anthropic_client,
    which uses a MODELS alias dict (opus/sonnet/haiku) — normalize that here so
    callers don't need a per-provider branch."""
    client = PROVIDERS[provider_name]
    if hasattr(client, "resolve_model"):
        return client.resolve_model(model)
    return client.MODELS.get(model, model) if model else client.MODELS["sonnet"]
