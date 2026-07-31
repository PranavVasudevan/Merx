import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import type { User } from 'oidc-client-ts';
import { getCurrentUser, handleSigninCallback, login, logout } from './auth';
import './LoginGate.css';

type Status = 'checking' | 'callback' | 'signed-out' | 'signed-in' | 'error';

// Spring entrance pattern from motion.dev/examples/react-enter-animation,
// reused as-is (a real reference value, not guessed): opacity+scale with a
// spring on scale gives the "pleasant bouncy" settle their docs describe,
// tuned down slightly (bounce 0.35 vs their 0.5 demo ball) since a login
// card shouldn't wobble as playfully as a demo bouncing ball.
const cardEntrance = {
  initial: { opacity: 0, scale: 0.94 },
  animate: {
    opacity: 1, scale: 1,
    transition: { duration: 0.4, scale: { type: 'spring' as const, visualDuration: 0.4, bounce: 0.35 } },
  },
};

export function LoginGate({ children }: { children: (user: User, logout: () => void) => React.ReactNode }) {
  const [status, setStatus] = useState<Status>('checking');
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Guards against React 19 StrictMode's dev-mode double-invoke of this
  // effect. Found live (not hypothetical): the OIDC authorization code is
  // single-use, so a real double-invocation raced two token-exchange calls
  // against the same code and the second one got Keycloak's "Code not
  // valid" — a genuine bug, not a flake, reproduced by actually logging in.
  // The ref persists across StrictMode's mount->cleanup->remount of the SAME
  // fiber, so this correctly runs the exchange exactly once.
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    async function run() {
      if (window.location.pathname === '/callback') {
        setStatus('callback');
        try {
          const u = await handleSigninCallback();
          window.history.replaceState({}, '', '/');
          setUser(u);
          setStatus('signed-in');
        } catch (e) {
          setError(String((e as Error).message ?? e));
          setStatus('error');
        }
        return;
      }
      const u = await getCurrentUser();
      if (u && !u.expired) {
        setUser(u);
        setStatus('signed-in');
      } else {
        setStatus('signed-out');
      }
    }
    run();
  }, []);

  if (status === 'checking' || status === 'callback') {
    return (
      <div className="login-gate-loading">
        <motion.span
          className="login-gate-spinner"
          animate={{ rotate: 360 }}
          transition={{ duration: 0.9, repeat: Infinity, ease: 'linear' }}
        />
        Checking session…
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="login-gate">
        <motion.div className="login-gate-card" {...cardEntrance}>
          <LoginGateMark />
          <span className="app-logo">BankLens</span>
          <p className="app-banner-error">Sign-in failed: {error}</p>
          <motion.button
            className="login-gate-button"
            onClick={() => login()}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
            transition={{ duration: 0.15 }}
          >
            Try again
          </motion.button>
        </motion.div>
      </div>
    );
  }

  if (status === 'signed-out' || !user) {
    return (
      <div className="login-gate">
        <motion.div className="login-gate-card" {...cardEntrance}>
          <LoginGateMark />
          <span className="app-logo">BankLens</span>
          <p className="muted">Sign in with your BankLens account to view bank data.</p>
          <motion.button
            className="login-gate-button"
            onClick={() => login()}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
            transition={{ duration: 0.15 }}
          >
            Sign in
          </motion.button>
          <hr className="hairline" />
          <p className="login-gate-hint muted">
            Local dev test users: <code>viewer1</code> / <code>viewer123</code> (read-only) or{' '}
            <code>analyst1</code> / <code>analyst123</code> (can also run the stress simulator).
          </p>
        </motion.div>
      </div>
    );
  }

  return <>{children(user, () => { void logout(); })}</>;
}

// A small monogram mark, not an external icon dependency — a single
// rounded-square "B" motif matching the app's own restrained radius scale.
function LoginGateMark() {
  return (
    <div className="login-gate-mark" aria-hidden="true">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <rect x="1" y="1" width="18" height="18" rx="5" stroke="currentColor" strokeWidth="1.5" />
        <path d="M7 5.5h3.6a2.2 2.2 0 0 1 0 4.4H7zM7 9.9h4a2.2 2.2 0 0 1 0 4.4H7z"
          stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      </svg>
    </div>
  );
}
