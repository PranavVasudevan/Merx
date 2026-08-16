"""F19 — a real, machine-readable OpenAPI 3.1 contract for the REST bridge,
generated from the SAME route tables `_route_request` actually dispatches
from (`ROUTES`/`POST_ROUTES`/`DELETE_ROUTES`/`ROUTE_TIERS` in bridge_server.py,
`auth.OPEN_ROUTES`) — never a hand-maintained parallel list, so it cannot
drift from what the bridge actually serves the way `docs/api/mcp-tools.md`
(F2) would have if it weren't regenerated from `tools.TOOLS` the same way.

Scope, honestly stated rather than silently under-delivered: paths, methods,
and the auth tier (viewer/analyst/open) per route are 100% mechanically
derived and cannot go stale. Response BODIES are intentionally left as
`type: object` (opaque) rather than full per-field JSON Schema — the bridge's
33 routes return whatever dict each handler in bridge_server.py/tools.py
happens to build (see F13's mypy.ini header: this repo's Python is
non-strict, and no Gold/Silver/route-response TypedDicts exist to introspect
field-by-field). The real, precise, currently-accurate shape for every route
already lives in `frontend/apps/web/src/types.ts` (hand-maintained, and the
thing the actual UI is built against) — claiming to also derive matching
per-field OpenAPI schemas here, without a real generator loop tying the two
together, would make this spec LOOK more authoritative than it is. What this
DOES give real teeth to: a route added/removed/re-tiered without updating
this file is a `scripts/generate_openapi.py --check` CI failure (the literal F19
acceptance test — "response-shape drift ... becomes a CI failure" — for the
part of "shape" this can honestly promise: which routes exist, under which
method, behind which auth tier).

This module takes the route tables as PARAMETERS rather than importing
bridge_server.py directly, so bridge_server.py can import THIS module (to
serve GET /api/openapi.json) without a circular import.
"""

from __future__ import annotations

# F16 — /api/assistant/ask streams Server-Sent Events and bypasses
# POST_ROUTES entirely (see bridge_server.py's comment at that table), so it
# isn't mechanically visible to the generator via post_routes. Documented
# here as the one hand-maintained exception, not silently missing from the
# contract.
SSE_ROUTES: dict[str, str] = {
    "/api/assistant/ask": "analyst",
}

_OPENAPI_VERSION = "3.1.0"


def _security_for(route: str, tier: str | None, open_routes: set[str]) -> tuple[list[dict], dict]:
    if route in open_routes:
        return [], {}
    extensions = {"x-banklens-tier": tier} if tier else {}
    return [{"bearerAuth": []}], extensions


def _json_operation(method: str, route: str, tier: str | None, open_routes: set[str]) -> dict:
    security, extensions = _security_for(route, tier, open_routes)
    op = {
        "operationId": f"{method.lower()}_{route.strip('/').replace('/', '_').replace('-', '_')}",
        "responses": {
            "200": {
                "description": "Success. Exact field-level shape not modeled here — see the "
                               "matching call in frontend/apps/web/src/api.ts and its return "
                               "type in frontend/apps/web/src/types.ts for the real contract.",
                "content": {"application/json": {"schema": {"type": "object"}}},
            },
            "400": {"description": "Validation failure (a bad/missing parameter, or similar) — "
                                   "see bridge_server.py's _route_request (F18)."},
        },
        **extensions,
    }
    if method in ("GET", "DELETE"):
        op["parameters"] = [{
            "name": "query", "in": "query", "required": False,
            "description": "Route-specific query parameters — not individually modeled here "
                           "(see this module's docstring); the authoritative list is the "
                           "handler lambda for this route in bridge_server.py.",
            "schema": {"type": "object"},
            "style": "form", "explode": True,
        }]
    if method == "POST":
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    if security:
        op["security"] = security
        op["responses"]["401"] = {"description": "Missing/invalid bearer token."}
        op["responses"]["403"] = {"description": f"Authenticated but missing the '{tier}' role."}
    return op


def _sse_operation(route: str, tier: str) -> dict:
    """F16 — the one route that doesn't return `application/json`."""
    return {
        "operationId": "post_assistant_ask",
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"persona": {"type": "string"}, "question": {"type": "string"}},
                "required": ["persona", "question"],
            }}},
        },
        "responses": {
            "200": {
                "description": "Server-Sent Events stream (F16) — a sequence of "
                               "`event: <kind>\\ndata: <json>\\n\\n` frames, kind in "
                               "tool_call/tool_result/final/timeout/error/result. See "
                               "bridge_server.py's _assistant_ask_sse and "
                               "frontend/apps/web/src/types.ts's AssistantStreamEvent for the "
                               "exact per-kind payload shapes.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            },
            "401": {"description": "Missing/invalid bearer token."},
            "403": {"description": f"Authenticated but missing the '{tier}' role."},
        },
        "security": [{"bearerAuth": []}],
        "x-banklens-tier": tier,
    }


def build_openapi_spec(*, get_routes: list[tuple[str, str, object]],
                       post_routes: list[tuple[str, str, object]],
                       delete_routes: list[tuple[str, str, object]],
                       route_tiers: dict[str, str], open_routes: set[str],
                       version: str = "0.0.0") -> dict:
    """Build the full OpenAPI document. `get_routes`/`post_routes`/
    `delete_routes` are bridge_server.py's ROUTES/POST_ROUTES/DELETE_ROUTES
    (each a list of (method, path, handler) — handler is unused, present only
    because that's the table's real shape); `route_tiers` is ROUTE_TIERS;
    `open_routes` is auth.OPEN_ROUTES."""
    paths: dict[str, dict] = {}

    def add(method: str, route: str) -> None:
        paths.setdefault(route, {})[method.lower()] = _json_operation(
            method, route, route_tiers.get(route), open_routes)

    for method, route, _fn in get_routes:
        add(method, route)
    for method, route, _fn in post_routes:
        add(method, route)
    for method, route, _fn in delete_routes:
        add(method, route)

    # /metrics and /api/openapi.json themselves: open, undocumented-in-detail
    # infra endpoints, not part of the app's data API — listed for
    # completeness (a spec that silently omits routes it serves is its own
    # kind of drift) without claiming a meaningful response schema.
    paths["/metrics"] = {"get": {
        "operationId": "get_metrics", "security": [],
        "responses": {"200": {"description": "Prometheus text-format metrics.",
                              "content": {"text/plain": {"schema": {"type": "string"}}}}},
    }}
    paths["/api/openapi.json"] = {"get": {
        "operationId": "get_openapi_spec", "security": [],
        "responses": {"200": {"description": "This document.",
                              "content": {"application/json": {"schema": {"type": "object"}}}}},
    }}

    for route, tier in SSE_ROUTES.items():
        paths.setdefault(route, {})["post"] = _sse_operation(route, tier)

    return {
        "openapi": _OPENAPI_VERSION,
        "info": {
            "title": "BankLens REST Bridge", "version": version,
            "description": "Generated from bridge_server.py's own route tables (F19) — see "
                           "services/api-gateway/src/openapi_spec.py's module docstring for "
                           "exactly what this does and does not model.",
        },
        "servers": [{"url": "/api", "description": "Relative to the bridge's own origin"}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            },
        },
        "paths": dict(sorted(paths.items())),
    }
