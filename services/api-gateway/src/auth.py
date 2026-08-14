"""OIDC authentication + OPA authorization for the REST bridge.

Two distinct, real checks, not one check wearing two names:

  1. Authentication (`authenticate`): is this a real, unexpired, unforged
     identity? Verified against the provider's actual signed JWT (RS256,
     signature checked against the provider's own JWKS — not just decoded
     and trusted). Any standards-compliant OIDC provider works (Keycloak is
     the local-dev default; Auth0/Clerk/Supabase Auth free tiers work
     unchanged, see OIDC_ISSUER below) — the JWKS location is resolved via
     the standard `<issuer>/.well-known/openid-configuration` discovery
     document, not a Keycloak-specific path. Keycloak's own realm/client/
     roles/test-users are scripted in
     `platform/auth/keycloak/banklens-realm.json`, not manually clicked
     through the admin console.

  2. Authorization (`authorize`): given that identity's roles, is THIS
     specific action allowed? Delegated to OPA (`platform/auth/opa/policy.rego`)
     — a real policy engine making a real decision (today: "viewer" role can
     read bank data, "analyst" role is additionally required for the
     stress-test simulator and M&A-fit matcher), not a hardcoded if/else that
     could just as easily live in this file. The point of using OPA is that
     the policy is data the bridge doesn't need to be redeployed to change.

Fails CLOSED, not open: if Keycloak's JWKS endpoint or OPA are unreachable,
requests are rejected (503), not silently allowed through. This is the
opposite of banklens_common.db's Postgres-unreachable fallback elsewhere in
this codebase — losing the audit trail there is low-stakes; silently
disabling an auth gate here would be a real vulnerability, not an acceptable
degradation.

Set BANKLENS_AUTH_ENABLED=false to disable this entirely — a deliberate,
documented escape hatch for a quick local dev loop that doesn't want to stand
up an OIDC provider + OPA, not an oversight.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import jwt
from jwt import PyJWKClient

from banklens_common.authz import OpaUnavailable, opa_query

AUTH_ENABLED = os.environ.get("BANKLENS_AUTH_ENABLED", "true").strip().lower() not in ("false", "0", "")
# OIDC_ISSUER replaces the old Keycloak-only KEYCLOAK_ISSUER name; the old
# name is still read as a fallback so an existing .env keeps working.
OIDC_ISSUER = os.environ.get(
    "OIDC_ISSUER", os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8081/realms/banklens"))
# Where the caller's roles live inside the decoded token: either a single
# top-level claim key (e.g. an Auth0 namespaced custom claim like
# "https://banklens.example.com/roles") or a dotted path into a nested claim
# (Keycloak's own shape, "realm_access.roles", the default). See
# roles_from_claims() for how both forms are resolved.
OIDC_ROLES_CLAIM = os.environ.get("OIDC_ROLES_CLAIM", "realm_access.roles")
# OPA_URL and the actual POST-to-OPA mechanism live in banklens_common.authz
# now — the MCP server's per-tool authorization (services/mcp-server/src/
# banklens_mcp/authz.py) needs the identical HTTP call this bridge makes, so
# that logic was pulled into the one shared module both services import
# rather than each maintaining its own urllib client against the same OPA.

# Routes that never require a token — a health/liveness check has to work
# before anyone has logged in, and this bridge's own /metrics is handled
# separately in bridge_server.py (never even reaches this module).
OPEN_ROUTES = {"/api/health"}

_jwk_client: PyJWKClient | None = None


class AuthError(Exception):
    """Authentication failed — caller should respond 401."""


class ForbiddenError(Exception):
    """Authenticated, but OPA denied this action — caller should respond 403."""


class AuthUnavailable(Exception):
    """The OIDC provider or OPA couldn't be reached — caller should respond 503 (fail closed)."""


def _discover_jwks_uri(issuer: str) -> str:
    """Resolve the JWKS endpoint via the standard OIDC discovery document at
    `<issuer>/.well-known/openid-configuration` — every real provider
    (Keycloak, Auth0, Clerk, Supabase Auth) publishes one, so this works
    without any provider-specific path logic. Falls back to Keycloak's fixed
    `/protocol/openid-connect/certs` path only if the discovery document
    itself can't be fetched/parsed, so local dev keeps working through a
    transient hiccup; a genuinely bad/wrong issuer still surfaces as a real
    JWKS failure in `authenticate()`, not a silently-wrong fallback URL."""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{issuer}/.well-known/openid-configuration"), timeout=5
        ) as resp:
            doc = json.loads(resp.read())
        jwks_uri = doc.get("jwks_uri")
        if jwks_uri:
            return jwks_uri
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        pass
    return f"{issuer}/protocol/openid-connect/certs"


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(_discover_jwks_uri(OIDC_ISSUER))
    return _jwk_client


def authenticate(auth_header: str | None) -> dict:
    """Verify a `Bearer <JWT>` header against the OIDC provider's real JWKS
    (signature, expiry, issuer). Returns the validated claims dict."""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthError("missing Authorization: Bearer <token> header")
    token = auth_header[len("Bearer "):]
    try:
        client = _get_jwk_client()
        signing_key = client.get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError as e:
        # The JWKS endpoint itself is unreachable — that's an infra problem,
        # not a bad token.
        raise AuthUnavailable(f"could not reach the OIDC provider's JWKS: {e}") from e
    except jwt.PyJWTError as e:
        # Malformed token (bad base64, no "kid", garbage structure) — found
        # live: a garbage Authorization header raised jwt.DecodeError here,
        # which is NOT a PyJWKClientError, and fell through uncaught to a
        # generic 400 instead of a proper 401. Every PyJWTError subclass from
        # this call means "not a valid token", so all of them map to AuthError.
        raise AuthError(f"invalid token: {e}") from e
    try:
        return jwt.decode(
            token, signing_key.key, algorithms=["RS256"], issuer=OIDC_ISSUER,
            # Scope note: no audience restriction in this reference — a real
            # deployment would map/verify `aud` for the specific client too.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid token: {e}") from e


def roles_from_claims(claims: dict) -> list[str]:
    """Read OIDC_ROLES_CLAIM out of the decoded token — either as an exact
    top-level key (Auth0-style namespaced custom claims are never nested, and
    real URLs contain dots that a naive dotted-path split would mis-parse) or,
    if that key isn't present, as a dotted path into a nested claim
    (Keycloak's "realm_access.roles" default)."""
    if isinstance(claims.get(OIDC_ROLES_CLAIM), list):
        return claims[OIDC_ROLES_CLAIM]
    node = claims
    for part in OIDC_ROLES_CLAIM.split("."):
        if not isinstance(node, dict):
            return []
        node = node.get(part)
    return node if isinstance(node, list) else []


def authorize(path: str, method: str, roles: list[str]) -> None:
    """Ask OPA whether `roles` may perform `method` on `path`. Raises
    ForbiddenError on a real deny, AuthUnavailable if OPA can't be reached.

    Fails closed on purpose (unlike the MCP server's authorize_tool(), which
    falls back to an in-process policy mirror if OPA is unreachable): this
    bridge is a real network-exposed HTTP service, so degrading availability
    over a real security gate is the right tradeoff here in a way it isn't
    for a locally-spawned stdio process — see banklens_mcp.authz's docstring
    for why that server made the opposite call."""
    try:
        allowed = opa_query({"path": path, "method": method, "roles": roles})
    except OpaUnavailable as e:
        raise AuthUnavailable(str(e)) from e
    if not allowed:
        raise ForbiddenError(f"role(s) {roles} not permitted for {method} {path}")
