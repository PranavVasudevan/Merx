# platform/auth — real OIDC (Keycloak) + OPA authorization

**Status: real, not scaffolding.** Gates the REST bridge
(`services/api-gateway/src/bridge_server.py`) behind an actual OIDC login and
a real policy-engine authorization decision — verified end-to-end in a real
browser (login redirect → Keycloak → callback → real bank data loads) as well
as via direct HTTP calls (see `CHANGELOG.md` for both).

## Two different questions, two different systems

1. **Authentication** ("is this a real identity?") — Keycloak issues a signed
   JWT; the bridge verifies its signature against Keycloak's own JWKS
   (`services/api-gateway/src/auth.py::authenticate()`). Not just decoded and
   trusted — signature, expiry, and issuer are all checked.
2. **Authorization** ("can THIS identity do THIS action?") — delegated to
   [Open Policy Agent](https://www.openpolicyagent.org/) (`opa/policy.rego`),
   not a hardcoded if/else in the bridge. Today's policy: a `viewer` role can
   read bank data; the `analyst` role is additionally required for the
   capital-buffer stress simulator (`/api/banks/stress-test`) — a
   deliberately-triggered, standalone "what-if" action, not a passive read.

## Fails closed, not open

If Keycloak's JWKS endpoint or OPA are unreachable, the bridge rejects the
request (503) — it does **not** silently let it through. This is the
opposite of `banklens_common.db`'s Postgres-unreachable fallback elsewhere in
this codebase (losing the audit trail there is low-stakes); silently
disabling an auth gate would be a real vulnerability. Verified live: stopped
the `opa` container mid-session and confirmed an otherwise-valid, authenticated
request got a 503, not a 200.

Set `BANKLENS_AUTH_ENABLED=false` to disable this entirely for a quick local
dev loop that doesn't want to stand up Keycloak+OPA — a deliberate escape
hatch, not an oversight.

## Setup — fully scripted, not manually clicked through the admin console

`keycloak/banklens-realm.json` defines the whole realm on import
(`--import-realm`): the `banklens-web` public client (Authorization Code +
PKCE for the real browser flow, direct-access-grants enabled for scripted
verification), two roles (`viewer`, `analyst`), and two test users
(`viewer1`/`viewer123`, `analyst1`/`analyst123`, the latter has both roles).

```powershell
docker compose -f ../docker/docker-compose.dev.yml up -d keycloak opa
# Keycloak admin console: http://localhost:8081 (KEYCLOAK_ADMIN_USER/PASSWORD in .env)
# OPA: http://localhost:8181
```

**A real Keycloak 26 gotcha, found live, not anticipated**: the realm import
initially failed every login with `"Account is not fully set up"` even
though the test users had `requiredActions: []` and valid password
credentials (confirmed via the Keycloak admin REST API). Reproduced the exact
failure in a real browser to isolate it: Keycloak redirected to
`VERIFY_PROFILE` — Keycloak 26's default User Profile schema requires
`firstName`/`lastName`, and without them it force-triggers that required
action regardless of the user's own `requiredActions` list. Fixed by adding
`firstName`/`lastName` to both test users in the realm JSON.

## Verify it yourself

```powershell
# get a real token (password grant, for scripted checks — the frontend uses the real Authorization Code+PKCE flow)
$body = @{ grant_type = 'password'; client_id = 'banklens-web'; username = 'viewer1'; password = 'viewer123' }
Invoke-RestMethod -Uri http://localhost:8081/realms/banklens/protocol/openid-connect/token -Method Post -Body $body

# OPA's own decision, directly
$input = @{ input = @{ path = '/api/banks/stress-test'; method = 'GET'; roles = @('viewer') } } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8181/v1/data/banklens/allow -Method Post -Body $input -ContentType 'application/json'
# {"result": false} — viewer can't; retry with roles=@('analyst') -> {"result": true}
```

Or run `python services/api-gateway/tests/test_auth.py` — hermetic tests run
always; live tests against real Keycloak+OPA SKIP (not fail) if that infra
isn't up.
