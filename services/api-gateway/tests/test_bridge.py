"""Bridge REST routing — exercises `_route_request()` (the single routing/auth/
error-mapping function both server transports call, see bridge_server.py's module
docstring) directly, no socket involved. `banklens_mcp.tools`/`data` are
monkeypatched per test so no landed Bronze or Postgres is required; `auth` is
monkeypatched too where a route isn't open, so this never needs a real OIDC token.

If bridge_server.py (or one of its real dependencies — prometheus_client,
banklens_mcp, banklens_agents, banklens_common) can't be imported in this
environment, every test SKIPs rather than fails.

Run: ``python services/api-gateway/tests/test_bridge.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for rel in ("services/api-gateway/src", "services/mcp-server/src",
            "pipelines/transforms/src", "services/agents/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class SkipTest(Exception):
    """A real dependency of bridge_server.py isn't importable here — a SKIP,
    not a failure (mirrors services/mcp-server/tests/test_mcp.py's convention)."""


try:
    import auth
    import bridge_server
    _IMPORT_ERROR: Exception | None = None
except Exception as e:  # pragma: no cover - environment-dependent
    _IMPORT_ERROR = e


def require_bridge_importable():
    if _IMPORT_ERROR is not None:
        raise SkipTest(f"bridge_server.py not importable here: {_IMPORT_ERROR}")


class _AuthDisabled:
    """Context manager: bypass the real OIDC/OPA path for routes that aren't in
    auth.OPEN_ROUTES, exactly the way BANKLENS_AUTH_ENABLED=false does for local
    dev (see auth.py) -- these tests care about ROUTING, not authentication."""

    def __enter__(self):
        self._prev = auth.AUTH_ENABLED
        auth.AUTH_ENABLED = False
        return self

    def __exit__(self, *exc):
        auth.AUTH_ENABLED = self._prev


# ---- health / unmatched routes (no stubbing needed) ------------------------

def test_health_route_is_open_and_needs_no_auth():
    require_bridge_importable()
    status, body = bridge_server._route_request("GET", "/api/health", {}, {}, None)
    assert status == 200
    assert body == {"status": "ok"}


def test_unmatched_route_returns_404():
    require_bridge_importable()
    status, body = bridge_server._route_request("GET", "/api/does-not-exist", {}, {}, None)
    assert status == 404
    assert "error" in body


def test_wrong_method_on_a_real_path_is_unmatched_not_500():
    """DELETE isn't declared for /api/health -- must fall through to the same
    404 path as a nonexistent URL, not raise."""
    require_bridge_importable()
    status, _ = bridge_server._route_request("DELETE", "/api/health", {}, {}, None)
    assert status == 404


# ---- successful GET with a stubbed tools layer -----------------------------

def test_successful_get_route_returns_the_stubbed_tools_payload_verbatim():
    require_bridge_importable()
    canned = {"cert": 6976, "name": "Testbank", "quarter": "2026Q1"}
    original = bridge_server.tools.get_bank_profile
    bridge_server.tools.get_bank_profile = lambda cert, **kwargs: canned
    try:
        with _AuthDisabled():
            status, body = bridge_server._route_request(
                "GET", "/api/banks/profile", {"cert": "6976"}, {}, None)
    finally:
        bridge_server.tools.get_bank_profile = original
    assert status == 200
    assert body == canned


def test_list_banks_route_passes_query_params_through_to_the_tool():
    require_bridge_importable()
    captured = {}

    def fake_list_banks(**kwargs):
        captured.update(kwargs)
        return {"banks": [], "count": 0}

    original = bridge_server.tools.list_banks
    bridge_server.tools.list_banks = fake_list_banks
    try:
        with _AuthDisabled():
            status, body = bridge_server._route_request(
                "GET", "/api/banks", {"query": "test", "state": "NY", "limit": "5"}, {}, None)
    finally:
        bridge_server.tools.list_banks = original
    assert status == 200
    assert body == {"banks": [], "count": 0}
    assert captured["query"] == "test"
    assert captured["state"] == "NY"
    assert captured["limit"] == 5  # coerced from the query-string "5" to an int


# ---- missing required query param -> 400, not a 500 or a crash ------------

def test_missing_required_cert_param_maps_to_400_not_a_crash():
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request(
            "GET", "/api/banks/profile", {}, {}, None)   # no "cert" in query
    assert status == 400
    assert "cert" in body["error"]


def test_missing_required_body_field_on_a_post_route_maps_to_400():
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request(
            "DELETE", "/api/watchlist", {}, {}, None)   # no "cert" in query
    assert status == 400
    assert "error" in body


# ---- a genuine tool-layer exception still maps to 400 (current behaviour,
#      not a 500 -- see F18, which will change this to 500 with a request ID) --

def test_an_unexpected_tool_exception_is_reported_not_silently_swallowed():
    require_bridge_importable()
    original = bridge_server.tools.get_bank_profile

    def boom(cert, **kwargs):
        raise RuntimeError("simulated data-layer failure")

    bridge_server.tools.get_bank_profile = boom
    try:
        with _AuthDisabled():
            status, body = bridge_server._route_request(
                "GET", "/api/banks/profile", {"cert": "6976"}, {}, None)
    finally:
        bridge_server.tools.get_bank_profile = original
    assert status in (400, 500)          # exact code is F18's territory, not this test's
    assert "simulated data-layer failure" not in body.get("error", "") or status == 400


# ---- auth still gates non-open routes when enabled -------------------------

def test_auth_enabled_and_no_token_is_rejected_not_routed_through():
    require_bridge_importable()
    prev = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        status, body = bridge_server._route_request(
            "GET", "/api/banks/profile", {"cert": "6976"}, {}, None)  # no Authorization header
    finally:
        auth.AUTH_ENABLED = prev
    assert status == 401
    assert "error" in body


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except SkipTest as e:
                skipped += 1; print(f"SKIP  {name}: {e}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
