"""Anthropic client tests — request-building and key-resolution, no network calls."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_agents import anthropic_client as ac  # noqa: E402


def test_get_api_key_prefers_env_var():
    old = os.environ.get("ANTHROPIC_API_KEY")
    old_dotenv = ac._load_dotenv_key
    try:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-from-env"
        assert ac.get_api_key() == "sk-test-from-env"
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old
        ac._load_dotenv_key = old_dotenv


def test_missing_key_raises_helpful_error():
    old = os.environ.pop("ANTHROPIC_API_KEY", None)
    old_dotenv = ac._load_dotenv_key
    try:
        ac._load_dotenv_key = lambda: None
        raised = False
        try:
            ac.get_api_key()
        except ac.MissingApiKey as e:
            raised = True
            assert "console.anthropic.com" in str(e)
        assert raised
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old
        ac._load_dotenv_key = old_dotenv


def test_models_map_has_all_three_tiers():
    assert set(ac.MODELS) == {"opus", "sonnet", "haiku"}
    assert all(v.startswith("claude-") for v in ac.MODELS.values())


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
