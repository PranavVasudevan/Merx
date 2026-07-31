// Real OIDC Authorization Code + PKCE login against Keycloak (see
// platform/auth/keycloak/banklens-realm.json for the realm/client/test-users),
// via `oidc-client-ts` — a well-vetted library, not a hand-rolled PKCE
// implementation (state/nonce/PKCE-verifier handling has real security
// implications; this project would rather use a maintained library than risk
// a subtle homegrown bug, the same reasoning as using QuantLib for bond math
// instead of re-deriving it).
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts';

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL ?? 'http://localhost:8081';
const REALM = 'banklens';
const CLIENT_ID = 'banklens-web';

export const userManager = new UserManager({
  authority: `${KEYCLOAK_URL}/realms/${REALM}`,
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

// Realm roles live in the ACCESS token's claims, not the ID token's
// (`user.profile`) — found live in a real browser session: Keycloak's
// default "roles" client scope mapper only adds `realm_access` to the access
// token by default, so reading it off `user.profile` silently always
// returned []. The bridge/OPA already read roles from the access token (see
// services/api-gateway/src/auth.py) — this decodes the SAME token the
// bridge actually authorizes against, so the badge can't drift from what's
// actually enforced.
export function roles(user: User | null): string[] {
  if (!user?.access_token) return [];
  try {
    const payload = user.access_token.split('.')[1];
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    const claims = JSON.parse(decoded) as { realm_access?: { roles?: string[] } };
    return claims.realm_access?.roles ?? [];
  } catch {
    return [];
  }
}
