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
const ANALYST_ONLY_PATHS = new Set(['/assistant', '/activity', '/stress-lab']);

// Grouped, not a flat bar: the expansion takes this well past the half-dozen links a
// single row can hold. Groups are the user's mental model (find banks / analyse them /
// my stuff / tooling), and each new page joins a group rather than lengthening a list.
interface NavLink { to: string; label: string }
interface NavGroup { label: string; links: NavLink[] }

const NAV_GROUPS: NavGroup[] = [
  { label: 'Explore', links: [
    { to: '/', label: 'Overview' },
    { to: '/screener', label: 'Screener' },
    { to: '/compare', label: 'Compare' },
  ] },
  { label: 'Analyze', links: [
    { to: '/earnings', label: 'Earnings' },
    { to: '/credit', label: 'Credit' },
    { to: '/funding', label: 'Funding' },
    { to: '/trends', label: 'Trends' },
    { to: '/filing-diff', label: 'Filing Diff' },
    { to: '/briefing', label: 'Briefing' },
  ] },
  { label: 'Visualize', links: [
    { to: '/heatmap', label: 'Heatmap' },
    { to: '/treemap', label: 'Treemap' },
    { to: '/distributions', label: 'Distributions' },
  ] },
  { label: 'Governance', links: [
    { to: '/clusters', label: 'Clusters' },
    { to: '/model', label: 'Model' },
  ] },
  { label: 'Geography', links: [
    { to: '/geography', label: 'Branch Map' },
    { to: '/market-share', label: 'Market Share' },
  ] },
  { label: 'Simulate', links: [
    { to: '/network', label: 'Network' },
    { to: '/stress-lab', label: 'Stress Lab' },
  ] },
  { label: 'Research', links: [
    { to: '/filings', label: 'Filings' },
  ] },
  { label: 'My work', links: [
    { to: '/watchlist', label: 'Watchlist' },
  ] },
  { label: 'Tools', links: [
    { to: '/assistant', label: 'Assistant' },
    { to: '/activity', label: 'Activity' },
  ] },
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
          {NAV_GROUPS.map((group, i) => (
            <div className="app-nav-group" key={group.label}>
              {i > 0 && <span className="app-nav-sep" aria-hidden="true" />}
              <span className="app-nav-group-label">{group.label}</span>
              {group.links.map((link) => {
                const gated = ANALYST_ONLY_PATHS.has(link.to) && !isAnalyst;
                return (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    end={link.to === '/'}
                    className={({ isActive }) => `app-nav-link${isActive ? ' app-nav-link-active' : ''}${gated ? ' app-nav-link-gated' : ''}`}
                    title={gated ? 'Requires the analyst role' : undefined}
                  >
                    {link.label}
                    {gated && <span className="app-nav-lock" aria-hidden="true">🔒</span>}
                  </NavLink>
                );
              })}
            </div>
          ))}
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
