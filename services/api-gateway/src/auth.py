"""OIDC (Keycloak) authentication + OPA authorization for the REST bridge.

Two distinct, real checks, not one check wearing two names:

  1. Authentication (`authenticate`): is this a real, unexpired, unforged
     identity? Verified against Keycloak's actual signed JWT (RS256,
     signature checked against Keycloak's own JWKS — not just decoded and
     trusted). Realm/client/roles/test-users are scripted in
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
up Keycloak+OPA, not an oversight.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import jwt
from jwt import PyJWKClient

AUTH_ENABLED = os.environ.get("BANKLENS_AUTH_ENABLED", "true").strip().lower() not in ("false", "0", "")
KEYCLOAK_ISSUER = os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8081/realms/banklens")
OPA_URL = os.environ.get("OPA_URL", "http://localhost:8181/v1/data/banklens/allow")

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
    """Keycloak or OPA couldn't be reached — caller should respond 503 (fail closed)."""


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs")
    return _jwk_client


def authenticate(auth_header: str | None) -> dict:
    """Verify a `Bearer <JWT>` header against Keycloak's real JWKS (signature,
    expiry, issuer). Returns the validated claims dict."""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthError("missing Authorization: Bearer <token> header")
    token = auth_header[len("Bearer "):]
    try:
        client = _get_jwk_client()
        signing_key = client.get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError as e:
        # The JWKS endpoint itself is unreachable — that's an infra problem,
        # not a bad token.
        raise AuthUnavailable(f"could not reach Keycloak JWKS: {e}") from e
    except jwt.PyJWTError as e:
        # Malformed token (bad base64, no "kid", garbage structure) — found
        # live: a garbage Authorization header raised jwt.DecodeError here,
        # which is NOT a PyJWKClientError, and fell through uncaught to a
        # generic 400 instead of a proper 401. Every PyJWTError subclass from
        # this call means "not a valid token", so all of them map to AuthError.
        raise AuthError(f"invalid token: {e}") from e
    try:
        return jwt.decode(
            token, signing_key.key, algorithms=["RS256"], issuer=KEYCLOAK_ISSUER,
            # Scope note: no audience restriction in this reference — a real
            # deployment would map/verify `aud` for the specific client too.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid token: {e}") from e


def roles_from_claims(claims: dict) -> list[str]:
    return claims.get("realm_access", {}).get("roles", [])


def authorize(path: str, method: str, roles: list[str]) -> None:
    """Ask OPA whether `roles` may perform `method` on `path`. Raises
    ForbiddenError on a real deny, AuthUnavailable if OPA can't be reached."""
    body = json.dumps({"input": {"path": path, "method": method, "roles": roles}}).encode()
    req = urllib.request.Request(OPA_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.loads(resp.read())
    except (OSError, urllib.error.URLError) as e:
        raise AuthUnavailable(f"could not reach OPA: {e}") from e
    if not result.get("result"):
        raise ForbiddenError(f"role(s) {roles} not permitted for {method} {path}")
