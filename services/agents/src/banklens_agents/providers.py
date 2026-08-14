"""Provider selection — picks which backend's `messages_create` the agent loop and
supervisor call, with the SAME shape regardless of provider.

Default is **ollama** when explicitly chosen (set BANKLENS_LLM_PROVIDER to force
it, or any other provider) — this project has a hard $0 spending constraint, and
Ollama is the only backend that costs literally nothing to actually run. But
Ollama needs a local model server with GBs of weights, which no free-tier host
can run — a deployment with BANKLENS_LLM_PROVIDER unset would otherwise default
to a provider that's unreachable by construction. So with NO explicit choice
(env var unset, no `name` argument), resolve_provider() auto-detects instead:
probe Ollama with a short timeout, and if it's not there, fall back to Gemini's
free tier (genuinely free, no card, see gemini_keys.py's multi-key rotation) if
a key is configured. `anthropic` is NEVER chosen by auto-detection — it's the
one provider that costs real money, so using it always requires an explicit
BANKLENS_LLM_PROVIDER=anthropic or provider="anthropic" argument.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from types import ModuleType

from . import anthropic_client, gemini_client, gemini_keys, ollama_client

PROVIDERS: dict[str, ModuleType] = {
    "anthropic": anthropic_client,
    "gemini": gemini_client,
    "ollama": ollama_client,
}

DEFAULT_PROVIDER = "ollama"

_OLLAMA_PROBE_TIMEOUT_S = 1.5


class NoProviderAvailable(RuntimeError):
    """Neither Ollama nor Gemini is usable, and no provider was explicitly
    chosen — the caller needs to fix ITS environment, not silently hang
    against an unreachable default (which is what a hardcoded "ollama"
    default did before this)."""


def _ollama_reachable(host: str | None = None) -> bool:
    """A short-timeout reachability probe, NOT a full request — auto-detection
    needs to fail fast onto Gemini rather than wait out a real call's much
    longer timeout (ollama_client's own request timeout is 120s) before
    deciding Ollama isn't there."""
    host = host or ollama_client.resolve_host()
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=_OLLAMA_PROBE_TIMEOUT_S):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def resolve_provider(name: str | None = None) -> str:
    if name:
        return name
    explicit = os.environ.get("BANKLENS_LLM_PROVIDER")
    if explicit:
        return explicit
    # No explicit choice anywhere -> auto-detect. Still never Anthropic (see
    # module docstring) — only between the two $0 options.
    if _ollama_reachable():
        return "ollama"
    if gemini_keys.usable_keys():
        return "gemini"
    raise NoProviderAvailable(
        f"No LLM provider available: Ollama isn't reachable at {ollama_client.resolve_host()} "
        "(start it with `ollama serve`, pull a model, or check OLLAMA_HOST) and no "
        "GEMINI_API_KEY is configured (free tier, no card — get one at "
        "https://aistudio.google.com/apikey and set GEMINI_API_KEY). Set "
        "BANKLENS_LLM_PROVIDER to force a specific provider instead of auto-detecting."
    )


def get_client(name: str | None = None) -> tuple[str, ModuleType]:
    """Return (provider_name, client_module). Raises ValueError for an unknown
    name, or NoProviderAvailable if auto-detection found nothing usable."""
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
