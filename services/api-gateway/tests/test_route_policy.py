"""Route/policy drift test — see bridge_server.py's ROUTE_TIERS docstring: these
were four hand-maintained parallel lists (ROUTE_TIERS, policy.rego, api.ts,
NavShell.tsx) and a missing policy entry already broke an entire page live (OPA
denies by default; the frontend's Promise.all rejects all-or-nothing on one 403).

Parses ROUTE_TIERS, OPEN_ROUTES and the three Rego route sets straight out of the
real source TEXT rather than importing bridge_server.py/auth.py, deliberately:
bridge_server.py pulls in banklens_mcp/banklens_agents/prometheus_client at module
scope, none of which this test should need installed just to catch a drift bug.
No OPA runtime involved either — this only checks the two hand-maintained lists
agree with each other, not that OPA evaluates them correctly.

Run: ``python services/api-gateway/tests/test_route_policy.py``  (no pytest needed)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BRIDGE_SRC = (REPO / "services" / "api-gateway" / "src" / "bridge_server.py").read_text(encoding="utf-8")
AUTH_SRC = (REPO / "services" / "api-gateway" / "src" / "auth.py").read_text(encoding="utf-8")
POLICY_SRC = (REPO / "platform" / "auth" / "opa" / "policy.rego").read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _extract_braced_block(text: str, marker: str) -> str:
    """Everything between `marker {` (or `marker := {`) and the next line that is
    just a bare `}` — matches this repo's actual formatting (no nested dicts/sets
    inside ROUTE_TIERS or any Rego set here, so a simple line-based scan is exact,
    not an approximation)."""
    start = text.index(marker)
    body_start = text.index("{", start) + 1
    close = re.search(r"\n\s*\}", text[body_start:])
    assert close, f"no closing '}}' found for block starting at {marker!r}"
    return text[body_start: body_start + close.start()]


def parse_route_tiers() -> dict[str, str]:
    block = _extract_braced_block(BRIDGE_SRC, "ROUTE_TIERS: dict[str, str] = {")
    return dict(re.findall(r'"(/[^"]+)":\s*"(viewer|analyst)"', _strip_comments(block)))


def parse_rego_set(name: str) -> set[str]:
    block = _extract_braced_block(POLICY_SRC, f"{name} := {{")
    return set(re.findall(r'"(/[^"]+)"', _strip_comments(block)))


def parse_auth_open_routes() -> set[str]:
    m = re.search(r"OPEN_ROUTES\s*=\s*\{([^}]*)\}", AUTH_SRC)
    assert m, "OPEN_ROUTES not found in auth.py"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


ROUTE_TIERS = parse_route_tiers()
VIEWER_ROUTES = parse_rego_set("viewer_routes")
ANALYST_ROUTES = parse_rego_set("analyst_routes")
OPEN_ROUTES_REGO = parse_rego_set("open_routes")
OPEN_ROUTES_AUTH = parse_auth_open_routes()


def test_parsing_actually_found_routes():
    """A parser that silently matches nothing would make every test below
    vacuously pass — assert real content was extracted before trusting any of it."""
    assert len(ROUTE_TIERS) > 10
    assert len(VIEWER_ROUTES) > 10
    assert len(ANALYST_ROUTES) > 0


def test_every_viewer_tier_route_is_declared_viewer_in_policy():
    viewer_in_bridge = {r for r, tier in ROUTE_TIERS.items() if tier == "viewer"}
    missing = viewer_in_bridge - VIEWER_ROUTES
    assert not missing, f"routes tiered 'viewer' in bridge_server.py but absent from policy.rego's viewer_routes: {missing}"


def test_every_analyst_tier_route_is_declared_analyst_in_policy():
    analyst_in_bridge = {r for r, tier in ROUTE_TIERS.items() if tier == "analyst"}
    missing = analyst_in_bridge - ANALYST_ROUTES
    assert not missing, f"routes tiered 'analyst' in bridge_server.py but absent from policy.rego's analyst_routes: {missing}"


def test_no_viewer_tier_route_is_also_listed_analyst_in_policy():
    viewer_in_bridge = {r for r, tier in ROUTE_TIERS.items() if tier == "viewer"}
    wrong_tier = viewer_in_bridge & ANALYST_ROUTES
    assert not wrong_tier, f"routes tiered 'viewer' in bridge_server.py but sit in policy.rego's analyst_routes (wrong tier): {wrong_tier}"


def test_no_analyst_tier_route_is_also_listed_viewer_in_policy():
    analyst_in_bridge = {r for r, tier in ROUTE_TIERS.items() if tier == "analyst"}
    wrong_tier = analyst_in_bridge & VIEWER_ROUTES
    assert not wrong_tier, f"routes tiered 'analyst' in bridge_server.py but sit in policy.rego's viewer_routes (wrong tier): {wrong_tier}"


def test_policy_has_no_extra_viewer_routes_absent_from_bridge():
    """The reverse direction of drift: a route removed from ROUTE_TIERS should
    also disappear from the policy, not linger there unused/stale."""
    declared = set(ROUTE_TIERS)
    extra = VIEWER_ROUTES - declared
    assert not extra, f"policy.rego's viewer_routes references routes not in bridge_server.py's ROUTE_TIERS: {extra}"


def test_policy_has_no_extra_analyst_routes_absent_from_bridge():
    declared = set(ROUTE_TIERS)
    extra = ANALYST_ROUTES - declared
    assert not extra, f"policy.rego's analyst_routes references routes not in bridge_server.py's ROUTE_TIERS: {extra}"


def test_viewer_and_analyst_route_sets_in_policy_are_disjoint():
    overlap = VIEWER_ROUTES & ANALYST_ROUTES
    assert not overlap, f"routes declared in BOTH policy.rego route sets (ambiguous tier): {overlap}"


def test_auth_open_routes_matches_policy_open_routes():
    assert OPEN_ROUTES_AUTH == OPEN_ROUTES_REGO or OPEN_ROUTES_AUTH <= OPEN_ROUTES_REGO, (
        f"auth.py's OPEN_ROUTES {OPEN_ROUTES_AUTH} is not a subset of "
        f"policy.rego's open_routes {OPEN_ROUTES_REGO}"
    )


def test_open_routes_never_also_appear_tiered_in_route_tiers():
    """A route that skips auth entirely (open) has no business also carrying a
    viewer/analyst tier — that tier would be dead code the OPA check never reaches."""
    overlap = OPEN_ROUTES_AUTH & set(ROUTE_TIERS)
    assert not overlap, f"routes are both open (skip auth) AND tiered in ROUTE_TIERS: {overlap}"


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
