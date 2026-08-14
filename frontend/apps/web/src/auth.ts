// Real OIDC Authorization Code + PKCE login (see
// platform/auth/keycloak/banklens-realm.json for the local-dev Keycloak
// realm/client/test-users), via `oidc-client-ts` — a well-vetted library, not
// a hand-rolled PKCE implementation (state/nonce/PKCE-verifier handling has
// real security implications; this project would rather use a maintained
// library than risk a subtle homegrown bug, the same reasoning as using
// QuantLib for bond math instead of re-deriving it).
//
// Any standards-compliant OIDC provider works, not just Keycloak — set
// VITE_OIDC_AUTHORITY/VITE_OIDC_CLIENT_ID (see .env.example) to point this at
// Auth0/Clerk/Supabase Auth's free tier instead. Both default to the local
// Keycloak realm docker-compose.dev.yml stands up, so local dev is unchanged.
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts';

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL ?? 'http://localhost:8081';
const AUTHORITY = import.meta.env.VITE_OIDC_AUTHORITY ?? `${KEYCLOAK_URL}/realms/banklens`;
const CLIENT_ID = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'banklens-web';
// Matches the backend's OIDC_ROLES_CLAIM default (services/api-gateway/src/auth.py)
// — the same access token is decoded on both sides, so the claim path must agree.
const ROLES_CLAIM = import.meta.env.VITE_OIDC_ROLES_CLAIM ?? 'realm_access.roles';

export const userManager = new UserManager({
  authority: AUTHORITY,
  client_id: CLIENT_ID,
  redirect_uri: `${window.location.origin}/callback`,
  post_logout_redirect_uri: window.location.origin,
  response_type: 'code',
  scope: 'openid profile',
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  automaticSilentRenew: false,
});

export function getCurrentUser(): Promise<User | null> {
  return userManager.getUser();
}

export function login(): Promise<void> {
  return userManager.signinRedirect();
}

export async function logout(): Promise<void> {
  try {
    await userManager.signoutRedirect();
  } catch {
    // Keycloak's end-session endpoint can be finicky in a bare local-dev
    // setup (no realm logout page configured beyond the default) — falling
    // back to a local session clear still logs the user out of THIS app,
    // which is what matters for the reference UI even if the Keycloak SSO
    // session technically outlives it.
    await userManager.removeUser();
    window.location.href = '/';
  }
}

export function handleSigninCallback(): Promise<User> {
  return userManager.signinRedirectCallback();
}

// Roles live in the ACCESS token's claims, not the ID token's (`user.profile`)
// — found live in a real browser session: Keycloak's default "roles" client
// scope mapper only adds `realm_access` to the access token by default, so
// reading it off `user.profile` silently always returned []. The bridge/OPA
// already read roles from the access token via the SAME VITE_OIDC_ROLES_CLAIM
// path (see services/api-gateway/src/auth.py's OIDC_ROLES_CLAIM) — this
// decodes the SAME token the bridge actually authorizes against, so the
// badge can't drift from what's actually enforced.
export function roles(user: User | null): string[] {
  if (!user?.access_token) return [];
  try {
    const payload = user.access_token.split('.')[1];
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    const claims = JSON.parse(decoded) as Record<string, unknown>;
    // Mirrors the backend's roles_from_claims(): try ROLES_CLAIM as an exact
    // top-level key first (an Auth0-style namespaced claim is a URL, never
    // nested, and contains dots a naive path-split would mis-parse), then
    // fall back to walking it as a dotted path (Keycloak's nested shape).
    const exact = claims[ROLES_CLAIM];
    if (Array.isArray(exact)) return exact as string[];
    let node: unknown = claims;
    for (const part of ROLES_CLAIM.split('.')) {
      if (typeof node !== 'object' || node === null) return [];
      node = (node as Record<string, unknown>)[part];
    }
    return Array.isArray(node) ? (node as string[]) : [];
  } catch {
    return [];
  }
}
