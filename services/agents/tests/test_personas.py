"""Persona/tool-registry consistency — catches typo'd tool names in personas.py
before they'd silently strip a tool from a specialist at runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "mcp-server" / "src"))

from banklens_agents.personas import PERSONAS  # noqa: E402
from banklens_mcp.tools import TOOL_BY_NAME  # noqa: E402


def test_every_persona_tool_exists_in_the_registry():
    known = set(TOOL_BY_NAME)
    for persona in PERSONAS.values():
        unknown = set(persona.tool_names) - known
        assert not unknown, f"{persona.key} references unknown tools: {unknown}"


def test_every_persona_has_at_least_one_tool():
    for persona in PERSONAS.values():
        assert len(persona.tool_names) > 0


def test_generalist_has_every_tool():
    assert set(PERSONAS["generalist"].tool_names) == set(TOOL_BY_NAME)


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
