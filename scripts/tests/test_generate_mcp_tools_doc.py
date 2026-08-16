"""Tests for scripts/generate_mcp_tools_doc.py — the regenerator for
docs/api/mcp-tools.md (a follow-up to F2/F20's "keep docs honest" work: this
doc had gone stale, 42 tools claimed vs. 46 actually registered).

Run: ``python scripts/tests/test_generate_mcp_tools_doc.py``
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import generate_mcp_tools_doc as gen  # noqa: E402


def test_param_str_marks_required_params_bold_and_leaves_optional_plain():
    assert gen._param_str("cert", {"type": "integer"}, {"cert"}) == "**cert**: integer"
    assert gen._param_str("state", {"type": "string"}, {"cert"}) == "state: string"


def test_param_str_renders_enum_schemas_with_the_enum_notation():
    schema = {"type": "string", "enum": ["mild", "moderate", "severe"]}
    assert gen._param_str("severity", schema, set()) == "severity: enum(mild|moderate|severe)"


def test_render_includes_the_real_current_tool_count():
    from banklens_mcp.tools import TOOLS
    text = gen.render()
    assert f"exposes {len(TOOLS)} tools" in text


def test_render_includes_every_registered_tool_name():
    from banklens_mcp.tools import TOOLS
    text = gen.render()
    for tool in TOOLS:
        assert f"### `{tool['name']}`" in text


def test_render_marks_a_tool_missing_from_mcp_tool_tiers_as_untiered():
    """Real, currently-true regression check: several tools ARE missing from
    MCP_TOOL_TIERS right now (see test_authz.py's test_every_tool_is_tiered)
    — the generator must surface that honestly, not silently default them to
    a fabricated tier."""
    from banklens_mcp.authz import MCP_TOOL_TIERS
    from banklens_mcp.tools import TOOLS
    untiered = [t["name"] for t in TOOLS if not MCP_TOOL_TIERS.get(t["name"])]
    if not untiered:
        return  # the tiering gap has since been fixed — nothing to check
    text = gen.render()
    assert f"### `{untiered[0]}` — UNTIERED" in text


def test_render_uses_none_params_for_a_tool_with_no_properties():
    text = gen.render()
    assert "### `get_market_coverage` — viewer\n\n" in text
    idx = text.index("### `get_market_coverage`")
    assert "Params: (none)" in text[idx:idx + 400]


def test_check_mode_passes_against_the_currently_committed_file():
    """Smoke test against the real committed doc, not synthetic input — a
    failure here means the committed file is genuinely stale, not a test bug."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_mcp_tools_doc.py"), "--check"],
        capture_output=True, text=True, cwd=str(REPO))
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {e!r}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
