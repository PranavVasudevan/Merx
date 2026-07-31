"""auth.py tests — the OIDC (Keycloak) + OPA gate in front of the REST bridge.

Hermetic tests cover the pure logic (env-var parsing, claims extraction, the
early-exit paths that never touch the network). The live tests exercise the
real running Keycloak + OPA (see platform/auth/) with real HTTP calls — same
convention as services/mcp-server/tests/test_data.py's landed-data checks:
SKIP, not fail, if that infra isn't up (`docker compose -f
platform/docker/docker-compose.dev.yml up -d keycloak opa`).
"""

from __future__ import annotations

import importlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import auth  # noqa: E402


class SkipTest(Exception):
    pass


def _require_live_keycloak_and_opa():
    try:
        urllib.request.urlopen(
            "http://localhost:8081/realms/banklens/.well-known/openid-configuration", timeout=3)
    except OSError as e:
        raise SkipTest(f"Keycloak not reachable ({e}) — "
                       f"docker compose -f platform/docker/docker-compose.dev.yml up -d keycloak") from e
    try:
        urllib.request.urlopen("http://localhost:8181/health", timeout=3)
    except OSError as e:
        raise SkipTest(f"OPA not reachable ({e}) — "
                       f"docker compose -f platform/docker/docker-compose.dev.yml up -d opa") from e


def _get_token(username: str, password: str) -> str:
    import json
    import urllib.parse
    data = urllib.parse.urlencode({
        "grant_type": "password", "client_id": "banklens-web",
        "username": username, "password": password,
    }).encode()
    req = urllib.request.Request(
        "http://localhost:8081/realms/banklens/protocol/openid-connect/token", data=data)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["access_token"]


# ---- hermetic ---------------------------------------------------------
def test_auth_enabled_defaults_true_when_unset():
    saved = os.environ.pop("BANKLENS_AUTH_ENABLED", None)
    try:
        importlib.reload(auth)
        assert auth.AUTH_ENABLED is True
    finally:
        if saved is not None:
            os.environ["BANKLENS_AUTH_ENABLED"] = saved
        importlib.reload(auth)


def test_auth_enabled_false_disables():
    saved = os.environ.get("BANKLENS_AUTH_ENABLED")
    try:
        for falsy in ("false", "False", "0", ""):
            os.environ["BANKLENS_AUTH_ENABLED"] = falsy
            importlib.reload(auth)
            assert auth.AUTH_ENABLED is False, f"{falsy!r} should disable auth"
    finally:
        if saved is None:
            os.environ.pop("BANKLENS_AUTH_ENABLED", None)
        else:
            os.environ["BANKLENS_AUTH_ENABLED"] = saved
        importlib.reload(auth)


def test_missing_authorization_header_raises_autherror_not_a_network_call():
    try:
        auth.authenticate(None)
        raise AssertionError("expected AuthError")
    except auth.AuthError:
        pass


def test_non_bearer_scheme_raises_autherror():
    try:
        auth.authenticate("Basic dXNlcjpwYXNz")
        raise AssertionError("expected AuthError")
    except auth.AuthError:
        pass


def test_roles_from_claims_extracts_realm_access_roles():
    assert auth.roles_from_claims({"realm_access": {"roles": ["viewer", "analyst"]}}) == ["viewer", "analyst"]


def test_roles_from_claims_missing_key_is_empty_list():
    assert auth.roles_from_claims({}) == []
    assert auth.roles_from_claims({"realm_access": {}}) == []


# ---- live (real Keycloak + OPA) ----------------------------------------
def test_authenticate_rejects_a_malformed_token_as_autherror_not_a_crash():
    """Regression test for a real bug found live: get_signing_key_from_jwt()
    can raise jwt.DecodeError (a PyJWTError, not a PyJWKClientError) for a
    garbage token — this used to fall through uncaught to bridge_server.py's
    generic 400 handler instead of a proper 401."""
    _require_live_keycloak_and_opa()
    try:
        auth.authenticate("Bearer garbage.token.here")
        raise AssertionError("expected AuthError")
    except auth.AuthError:
        pass


def test_authenticate_accepts_a_real_viewer_token():
    _require_live_keycloak_and_opa()
    token = _get_token("viewer1", "viewer123")
    claims = auth.authenticate(f"Bearer {token}")
    assert claims["preferred_username"] == "viewer1"
    assert "viewer" in auth.roles_from_claims(claims)


def test_authenticate_rejects_a_tampered_signature():
    _require_live_keycloak_and_opa()
    token = _get_token("viewer1", "viewer123")
    tampered = token[:-5] + "AAAAA"
    try:
        auth.authenticate(f"Bearer {tampered}")
        raise AssertionError("expected AuthError (tampered signature)")
    except auth.AuthError:
        pass


def test_authorize_viewer_can_read_banks_but_not_stress_test():
    _require_live_keycloak_and_opa()
    auth.authorize("/api/banks", "GET", ["viewer"])  # must not raise
    try:
        auth.authorize("/api/banks/stress-test", "GET", ["viewer"])
        raise AssertionError("expected ForbiddenError")
    except auth.ForbiddenError:
        pass


def test_authorize_analyst_can_stress_test():
    _require_live_keycloak_and_opa()
    auth.authorize("/api/banks/stress-test", "GET", ["analyst"])  # must not raise


def test_authorize_viewer_can_use_ma_fit():
    """Regression test for a real bug found live in a browser: ma-fit used to
    be analyst-only, but App.tsx loads it in the SAME Promise.all() as
    profile/xray/peer-cluster/risk-score for every bank view — a viewer-role
    user got a 403 there and Promise.all's all-or-nothing rejection broke the
    ENTIRE profile view, not just the M&A panel. ma-fit is a read/lookup, not
    a simulation, so viewer access is correct."""
    _require_live_keycloak_and_opa()
    auth.authorize("/api/banks/ma-fit", "GET", ["viewer"])  # must not raise


def test_authorize_no_roles_denied_for_viewer_routes():
    _require_live_keycloak_and_opa()
    try:
        auth.authorize("/api/banks", "GET", [])
        raise AssertionError("expected ForbiddenError")
    except auth.ForbiddenError:
        pass


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
            except Exception as e:  # noqa: BLE001 — a crash must not abort the rest
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
