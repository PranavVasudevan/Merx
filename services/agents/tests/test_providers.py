"""Provider-selection tests — resolution, defaults, and the $0-by-default guarantee."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_agents import providers  # noqa: E402


def test_default_provider_is_ollama_the_free_one():
    """This project has a hard $0 spending rule — the default MUST be the backend
    that costs nothing to actually run, not the one that happens to be 'best'."""
    saved = os.environ.pop("BANKLENS_LLM_PROVIDER", None)
    try:
        assert providers.resolve_provider(None) == "ollama"
        assert providers.DEFAULT_PROVIDER == "ollama"
    finally:
        if saved is not None:
            os.environ["BANKLENS_LLM_PROVIDER"] = saved


def test_env_var_overrides_default():
    saved = os.environ.get("BANKLENS_LLM_PROVIDER")
    try:
        os.environ["BANKLENS_LLM_PROVIDER"] = "gemini"
        assert providers.resolve_provider(None) == "gemini"
    finally:
        if saved is None:
            os.environ.pop("BANKLENS_LLM_PROVIDER", None)
        else:
            os.environ["BANKLENS_LLM_PROVIDER"] = saved


def test_explicit_arg_wins_over_env():
    os.environ["BANKLENS_LLM_PROVIDER"] = "gemini"
    try:
        assert providers.resolve_provider("anthropic") == "anthropic"
    finally:
        os.environ.pop("BANKLENS_LLM_PROVIDER", None)


def test_get_client_returns_the_right_module():
    name, client = providers.get_client("ollama")
    assert name == "ollama"
    assert client.__name__.endswith("ollama_client")


def test_unknown_provider_raises_value_error():
    raised = False
    try:
        providers.get_client("not_a_provider")
    except ValueError as e:
        raised = True
        assert "not_a_provider" in str(e)
    assert raised


def test_resolve_model_anthropic_alias():
    assert providers.resolve_model("anthropic", "sonnet") == "claude-sonnet-5"


def test_resolve_model_ollama_uses_own_default():
    saved = os.environ.pop("OLLAMA_MODEL", None)
    try:
        assert providers.resolve_model("ollama", None) == "llama3.2:1b"
    finally:
        if saved is not None:
            os.environ["OLLAMA_MODEL"] = saved


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
