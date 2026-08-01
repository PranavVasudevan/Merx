import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import type { User } from 'oidc-client-ts';
import { api } from '../api';
import { roles } from '../auth';
import { BankSearch } from './BankSearch';
import './NavShell.css';

// Every route beyond "/" and "/bank/:cert" needs the analyst role — same
// precedent StressPanel already established (compute-heavier/broader-reach
// actions are analyst-gated, plain reads are viewer-level). Kept here as a
// single source of truth so the nav can grey out links a viewer can't use
// instead of only failing after the click.
const ANALYST_ONLY_PATHS = new Set(['/assistant', '/activity']);

const NAV_LINKS: { to: string; label: string }[] = [
  { to: '/', label: 'Overview' },
  { to: '/screener', label: 'Screener' },
  { to: '/compare', label: 'Compare' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/assistant', label: 'Assistant' },
  { to: '/activity', label: 'Activity' },
];

export function NavShell({ user, onLogout }: { user: User; onLogout: () => void }) {
  const navigate = useNavigate();
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const userRoles = roles(user);
  const isAnalyst = userRoles.includes('analyst');

  useEffect(() => {
    api.health().then(() => setBackendUp(true)).catch(() => setBackendUp(false));
  }, []);

  if (backendUp === false) {
    return (
      <div className="app-error">
        <h1>BankLens</h1>
        <p>Can't reach the REST bridge at <code>localhost:8791</code>.</p>
        <p className="muted">Start it with: <code>powershell -File scripts/api_bridge.ps1</code></p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <span className="app-logo">BankLens</span>
          <span className="muted app-tagline">Quant Terminal</span>
        </div>

        <nav className="app-nav">
          {NAV_LINKS.map((link) => {
            const gated = ANALYST_ONLY_PATHS.has(link.to) && !isAnalyst;
            return (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) => `app-nav-link${isActive ? ' app-nav-link-active' : ''}${gated ? ' app-nav-link-gated' : ''}`}
                title={gated ? 'Requires the analyst role' : undefined}
              >
                {link.label}
                {gated && <span className="app-nav-lock" aria-hidden="true">🔒</span>}
              </NavLink>
            );
          })}
        </nav>

        <BankSearch onSelect={(c) => navigate(`/bank/${c}`)} />

        <div className="app-user">
          <span className="muted app-user-name">
            {user.profile.preferred_username} · {userRoles.join(', ') || 'no role'}
          </span>
          <button className="app-user-logout" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <Outlet />

      <footer className="app-footer muted">
        BankLens · data from FDIC BankFind, SEC EDGAR, Tiingo
      </footer>
    </div>
  );
}
