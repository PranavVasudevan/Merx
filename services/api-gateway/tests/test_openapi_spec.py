"""Tests for openapi_spec.py (F19) — the generator that builds
docs/api/openapi.json from bridge_server.py's own route tables. Exercised
against small synthetic tables here (not the real bridge's 69 paths) so this
stays fast and independent of what routes happen to exist right now; the
real-tables regeneration is covered separately by
`python scripts/generate_openapi.py --check` in CI.

Run: ``python services/api-gateway/tests/test_openapi_spec.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "api-gateway" / "src"))

import openapi_spec  # noqa: E402

GET_ROUTES = [("GET", "/api/health", None), ("GET", "/api/banks/profile", None)]
POST_ROUTES = [("POST", "/api/watchlist", None)]
DELETE_ROUTES = [("DELETE", "/api/watchlist", None)]
ROUTE_TIERS = {"/api/banks/profile": "viewer", "/api/watchlist": "viewer"}
OPEN_ROUTES = {"/api/health"}


def _spec():
    return openapi_spec.build_openapi_spec(
        get_routes=GET_ROUTES, post_routes=POST_ROUTES, delete_routes=DELETE_ROUTES,
        route_tiers=ROUTE_TIERS, open_routes=OPEN_ROUTES, version="9.9.9")


def test_top_level_shape_is_a_valid_openapi_3_1_document():
    spec = _spec()
    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["version"] == "9.9.9"
    assert "bearerAuth" in spec["components"]["securitySchemes"]


def test_open_route_has_no_security_requirement_and_no_401_403():
    spec = _spec()
    op = spec["paths"]["/api/health"]["get"]
    assert "security" not in op
    assert "401" not in op["responses"]
    assert "403" not in op["responses"]


def test_tiered_route_carries_its_tier_and_auth_error_responses():
    spec = _spec()
    op = spec["paths"]["/api/banks/profile"]["get"]
    assert op["x-banklens-tier"] == "viewer"
    assert op["security"] == [{"bearerAuth": []}]
    assert "401" in op["responses"]
    assert "403" in op["responses"]


def test_post_route_has_a_json_request_body():
    spec = _spec()
    op = spec["paths"]["/api/watchlist"]["post"]
    assert op["requestBody"]["required"] is True
    assert "application/json" in op["requestBody"]["content"]


def test_get_and_delete_routes_get_a_query_parameter_block():
    spec = _spec()
    assert spec["paths"]["/api/banks/profile"]["get"]["parameters"]
    assert spec["paths"]["/api/watchlist"]["delete"]["parameters"]


def test_same_path_different_methods_merge_into_one_path_item():
    spec = _spec()
    watchlist = spec["paths"]["/api/watchlist"]
    assert set(watchlist) == {"post", "delete"}


def test_metrics_and_openapi_json_are_always_present_even_if_not_in_input_tables():
    spec = _spec()
    assert "/metrics" in spec["paths"]
    assert "/api/openapi.json" in spec["paths"]
    # Neither is a real business route, so neither should be auth-gated.
    assert "security" not in spec["paths"]["/metrics"]["get"] or spec["paths"]["/metrics"]["get"]["security"] == []


def test_sse_route_gets_a_text_event_stream_response_not_json():
    spec = _spec()
    op = spec["paths"]["/api/assistant/ask"]["post"]
    assert "text/event-stream" in op["responses"]["200"]["content"]
    assert op["x-banklens-tier"] == "analyst"


def test_sse_route_present_even_though_it_is_not_in_any_input_route_table():
    """F16 — /api/assistant/ask bypasses POST_ROUTES entirely for dispatch,
    so it must NOT be missing from the generated contract just because the
    caller's post_routes list (correctly) doesn't include it."""
    spec = _spec()
    assert "/api/assistant/ask" not in [r for m, r, f in POST_ROUTES]
    assert "/api/assistant/ask" in spec["paths"]


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
