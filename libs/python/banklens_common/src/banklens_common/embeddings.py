"""Ollama embeddings client — $0, local, the same nomic-embed-text model already
pulled for this project (see ollama_client.py's model notes). Stdlib only.

Shared between the filings landing CLI (embeds each chunk once, at land time) and
the MCP search tool (embeds the user's query at request time) — one client, one
place that knows the HTTP shape, so the two never drift.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_HOST = "http://localhost:11434"
DIMENSIONS = 768   # nomic-embed-text's real output size, verified live
_MAX_RETRIES = 2
_BACKOFF_BASE_SECONDS = 1.0


class EmbeddingError(RuntimeError):
    pass


def resolve_host() -> str:
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST)


def embed(text: str, *, model: str = DEFAULT_MODEL, host: str | None = None) -> list[float]:
    """One text -> one 768-dim embedding vector."""
    host = host or resolve_host()
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        req = urllib.request.Request(
            f"{host}/api/embeddings", data=payload,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            vec = body.get("embedding")
            if not isinstance(vec, list) or len(vec) != DIMENSIONS:
                raise EmbeddingError(
                    f"unexpected embedding shape from Ollama: {type(vec)} "
                    f"len={len(vec) if isinstance(vec, list) else '?'} (expected {DIMENSIONS})")
            return vec
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
                continue
            raise EmbeddingError(
                f"Could not reach Ollama at {host} for embeddings — is it running "
                f"and is '{model}' pulled? (`ollama pull {model}`). {exc}") from exc
    raise EmbeddingError(f"Ollama embeddings call failed after retries: {last_exc}")


def to_vector_literal(vec: list[float]) -> str:
    """pgvector's plain-text input format — no pgvector-python client library
    needed, a parameterized `%s::vector` cast handles the rest."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
