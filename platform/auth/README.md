# Auth architecture

Two services enforce authorization against **one** policy file
(`platform/auth/opa/policy.rego`): the REST bridge (`services/api-gateway`) and
the MCP server (`services/mcp-server`). Both authenticate against the same OIDC
provider and ask the same OPA instance the same question — "given this
identity's roles, is this specific action allowed?" — for their own kind of
action (an HTTP route for the bridge, a `tools/call` for the MCP server).

## Authentication (OIDC)

`services/api-gateway/src/auth.py` verifies a `Bearer <JWT>` header against the
issuer's real signed JWKS (RS256 signature, expiry, issuer — not just decoded
and trusted). Any standards-compliant OIDC provider works, not only Keycloak:
the JWKS endpoint is resolved via the standard
`<issuer>/.well-known/openid-configuration` discovery document, falling back to
Keycloak's fixed `/protocol/openid-connect/certs` path only if that discovery
document itself can't be fetched.

Config (`.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `OIDC_ISSUER` (falls back to the older `KEYCLOAK_ISSUER`) | `http://localhost:8081/realms/banklens` | The provider issuer URL. |
| `OIDC_ROLES_CLAIM` | `realm_access.roles` | Where roles live in the decoded token — a top-level key (Auth0-style namespaced claims) or a dotted path into a nested claim (Keycloak's default shape). |

Local dev's Keycloak realm/client/roles/test users are scripted in
`platform/auth/keycloak/banklens-realm.json`, not clicked through by hand.

## Authorization (OPA)

`platform/auth/opa/policy.rego` is the single source of truth for who can do
what. It defines three route sets for the REST bridge —

- `open_routes` — no token required at all (`/api/health`, `/metrics`).
- `viewer_routes` — any authenticated `viewer` or `analyst` role.
- `analyst_routes` — `analyst` role only (the heavier what-if simulators:
  stress tests, the assistant, the activity feeds).

— and the equivalent `mcp_viewer_tools` / `mcp_analyst_tools` sets for the MCP
server's per-tool checks, keyed by tool name instead of by path. The two route
tables aren't hand-synced by memory: `services/api-gateway/tests/test_route_policy.py`
and `services/mcp-server/tests/test_authz.py` fail CI if `bridge_server.py`'s
`ROUTE_TIERS` / `banklens_mcp.authz.MCP_TOOL_TIERS` ever drift from the Rego
sets they mirror.

The bridge calls OPA over HTTP via `banklens_common.authz.opa_query` (the same
helper both services import, so there's one client, not two). **The bridge
fails closed**: if the OIDC provider's JWKS or OPA itself is unreachable, the
request is rejected (503), never silently allowed through.

The MCP server takes the opposite default for OPA-unreachability specifically
— see `services/mcp-server/src/banklens_mcp/authz.py`'s docstring. It tries
real OPA first on every call, but falls back to the in-process
`MCP_TOOL_TIERS` mirror if OPA can't be reached, rather than either failing
every tool call closed (making a bare local run without
`docker compose -f platform/docker/docker-compose.dev.yml up -d opa`
unusable) or failing open (a real vulnerability). Enforcement never lapses —
it just stops being hot-reloadable from `policy.rego` until OPA comes back.

## The `BANKLENS_AUTH_ENABLED=false` escape hatch

Setting `BANKLENS_AUTH_ENABLED=false` disables authentication and
authorization entirely — every route becomes reachable with no token. This is
a deliberate, documented local-dev shortcut for a quick loop that doesn't want
to stand up an OIDC provider + OPA, **not a supported deployment mode**.

Two things keep it from becoming an accidental open service:

1. **`bridge_server.py` refuses to start** if auth is disabled and the bridge
   is bound to anything other than loopback (`_require_safe_bind`) — a
   container's `BANKLENS_BRIDGE_HOST=0.0.0.0` is safe only because the
   network namespace, not this bind address, controls real external
   exposure; anything else with auth disabled is refused outright.
2. Every request served in this mode logs a loud, impossible-to-miss stderr
   warning (`_warn_auth_disabled`) as a last line of defence if the loopback
   check is ever bypassed downstream (e.g. loopback traffic proxied out to a
   real network).

Routes that scope data to the caller (e.g. the watchlist) still require a real
`sub` claim even with auth disabled — there's no anonymous user to scope
per-user state to, so those calls raise a clear error telling the caller to
set `BANKLENS_AUTH_ENABLED=true` instead of silently writing to a shared
"no-user" bucket.
