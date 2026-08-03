"""Cross-check the REST bridge's route table against the OPA policy.

These used to be four hand-maintained parallel lists — `bridge_server.ROUTES`,
`policy.rego`'s viewer_routes/analyst_routes, `api.ts`, and `NavShell.tsx`. A missing
policy entry already broke an entire page once: OPA is `default allow := false`, and
the frontend loads several endpoints in one `Promise.all`, which rejects
all-or-nothing on a single 403 — so one absent line took down a whole view rather than
one panel (see the comment at policy.rego's viewer_routes).

The expansion adds many more routes, so this makes that class of drift a failing test
rather than something found in a browser. Fully hermetic: parses the .rego text, no
running OPA needed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge_server  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
POLICY = REPO / "platform" / "auth" / "opa" / "policy.rego"


def _rego_set(name: str) -> set[str]:
    """Extract a `name := { "a", "b" }` set literal from the Rego source."""
    text = POLICY.read_text(encoding="utf-8")
    m = re.search(rf"^{name}\s*:=\s*\{{(.*?)\}}", text, re.MULTILINE | re.DOTALL)
    if not m:
        raise AssertionError(f"{name} not found in {POLICY}")
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _declared_routes() -> set[str]:
    """Every route the bridge actually serves, across all verbs, minus open ones."""
    paths = set()
    for table in (bridge_server.ROUTES, bridge_server.POST_ROUTES, bridge_server.DELETE_ROUTES):
        for _method, path, _fn in table:
            paths.add(path)
    return paths - set(bridge_server.auth.OPEN_ROUTES)


def test_every_served_route_declares_a_tier():
    missing = _declared_routes() - set(bridge_server.ROUTE_TIERS)
    assert not missing, (
        f"routes served by the bridge with no ROUTE_TIERS entry: {sorted(missing)} — "
        f"add them, or they cannot be checked against the OPA policy")


def test_no_tier_declared_for_a_route_that_does_not_exist():
    stale = set(bridge_server.ROUTE_TIERS) - _declared_routes()
    assert not stale, f"ROUTE_TIERS names routes the bridge no longer serves: {sorted(stale)}"


def test_viewer_routes_match_the_policy():
    declared = {p for p, tier in bridge_server.ROUTE_TIERS.items() if tier == "viewer"}
    policy = _rego_set("viewer_routes")
    assert declared - policy == set(), (
        f"viewer routes absent from policy.rego (every request to them will 403): "
        f"{sorted(declared - policy)}")
    assert policy - declared == set(), (
        f"policy.rego grants viewer access to routes the bridge doesn't serve: "
        f"{sorted(policy - declared)}")


def test_analyst_routes_match_the_policy():
    declared = {p for p, tier in bridge_server.ROUTE_TIERS.items() if tier == "analyst"}
    policy = _rego_set("analyst_routes")
    assert declared - policy == set(), (
        f"analyst routes absent from policy.rego: {sorted(declared - policy)}")
    assert policy - declared == set(), (
        f"policy.rego names analyst routes the bridge doesn't serve: "
        f"{sorted(policy - declared)}")


def test_tiers_are_disjoint():
    """A route in both sets would let a viewer reach an analyst-only capability."""
    overlap = _rego_set("viewer_routes") & _rego_set("analyst_routes")
    assert not overlap, f"routes in BOTH policy tiers: {sorted(overlap)}"


def test_open_routes_are_not_also_gated():
    gated = set(bridge_server.auth.OPEN_ROUTES) & (
        _rego_set("viewer_routes") | _rego_set("analyst_routes"))
    assert not gated, f"open routes also listed as gated: {sorted(gated)}"


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
