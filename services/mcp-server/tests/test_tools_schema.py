"""F4 — handler/registry schema drift. `get_asset_treemap`'s handler validated
`group_by` against `("peer_cluster_label", "state", "country")` while its
registry `inputSchema` enum only listed `["peer_cluster_label", "state"]`,
making `"country"` unreachable from any real MCP/agent client even though the
handler itself supported it fully. This test catches that whole CLASS of
drift generically: every tool's declared `inputSchema.properties` must be a
real parameter the handler function actually accepts, and every non-default
handler parameter must be declared `required` in the schema — a structural,
mechanical check via `inspect.signature`, not a re-implementation of each
handler's own validation logic.

Run: ``python services/mcp-server/tests/test_tools_schema.py``  (no pytest needed)
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "mcp-server" / "src"))
sys.path.insert(0, str(ROOT / "pipelines" / "transforms" / "src"))

from banklens_mcp.tools import TOOLS  # noqa: E402


def _handler_params(fn) -> inspect.Signature:
    return inspect.signature(fn)


def test_every_tool_has_a_name_description_schema_and_handler():
    for t in TOOLS:
        for key in ("name", "description", "inputSchema", "handler"):
            assert key in t, f"tool missing {key!r}: {t.get('name', '<unnamed>')}"


def test_every_schema_property_is_a_real_handler_parameter():
    """A schema key an MCP client could send but the handler function has no
    parameter for at all is either dead (client sends it, handler silently
    ignores it via **kwargs, or crashes with TypeError) — either way a real
    contract bug worth catching."""
    problems = []
    for t in TOOLS:
        sig = _handler_params(t["handler"])
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_kwargs:
            continue
        schema_props = set(t["inputSchema"].get("properties", {}))
        handler_params = set(sig.parameters)
        extra = schema_props - handler_params
        if extra:
            problems.append(f"{t['name']}: schema declares {extra} but handler has no such parameter")
    assert not problems, "\n" + "\n".join(problems)


def test_every_required_handler_parameter_is_declared_in_the_schema():
    """A handler parameter with no default (the caller MUST supply it) that
    isn't even declared in the schema at all is unreachable from any
    schema-driven client — the class of bug this whole file exists to catch,
    just for a parameter that's REQUIRED rather than optional."""
    problems = []
    for t in TOOLS:
        sig = _handler_params(t["handler"])
        schema_props = set(t["inputSchema"].get("properties", {}))
        for name, p in sig.parameters.items():
            if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if p.default is inspect.Parameter.empty and name not in schema_props:
                problems.append(f"{t['name']}: handler requires {name!r} but it's not in inputSchema.properties at all")
    assert not problems, "\n" + "\n".join(problems)


def test_every_required_handler_parameter_is_marked_required_in_the_schema():
    """Declared in `properties` but missing from `required` understates the
    real contract: a schema-driven client may reasonably omit it and get a
    TypeError instead of a clear "missing required param" error."""
    problems = []
    for t in TOOLS:
        sig = _handler_params(t["handler"])
        required = set(t["inputSchema"].get("required", []))
        for name, p in sig.parameters.items():
            if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if p.default is inspect.Parameter.empty and name not in required:
                problems.append(f"{t['name']}: handler requires {name!r} but it's not in inputSchema.required")
    assert not problems, "\n" + "\n".join(problems)


def test_get_asset_treemap_country_enum_is_reachable():
    """The specific regression this file was written for — pin it directly,
    not just via the generic structural checks above."""
    t = next(x for x in TOOLS if x["name"] == "get_asset_treemap")
    assert "country" in t["inputSchema"]["properties"]["group_by"]["enum"]


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
