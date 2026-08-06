import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import type { User } from 'oidc-client-ts';
import { motion } from 'motion/react';
import { api } from '../api';
import { roles } from '../auth';
import { BankSearch } from './BankSearch';
import { CommandPalette } from './CommandPalette';
import { SkinToggle } from './SkinToggle';
import { NAV_GROUPS } from '../navGroups';
import './NavShell.css';

const ANALYST_ONLY_PATHS = new Set(['/assistant', '/activity', '/stress-lab']);

export function NavShell({ user, onLogout }: { user: User; onLogout: () => void }) {
  const navigate = useNavigate();
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
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
    <div className="app-shell-redesigned">
      {/* Sidebar */}
      <motion.aside
        initial={{ x: -288 }}
        animate={{ x: 0 }}
        className="app-sidebar"
      >
        {/* Logo Section */}
        <div className="app-sidebar-header">
          <div className="app-brand-redesigned">
            <h1 className="app-logo-redesigned">BankLens</h1>
            <span className="muted app-tagline-redesigned">v2.6 Terminal</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="app-nav-redesigned">
          {NAV_GROUPS.map((group) => (
            <div className="app-nav-group-redesigned" key={group.label}>
              <span className="app-nav-group-label-redesigned">{group.label}</span>
              <div className="app-nav-items-redesigned">
                {group.links.map((link) => {
                  const gated = ANALYST_ONLY_PATHS.has(link.to) && !isAnalyst;
                  return (
                    <NavLink
                      key={link.to}
                      to={link.to}
                      end={link.to === '/'}
                      className={({ isActive }) => `app-nav-link-redesigned${isActive ? ' app-nav-link-active-redesigned' : ''}${gated ? ' app-nav-link-gated-redesigned' : ''}`}
                      title={gated ? 'Requires the analyst role' : undefined}
                    >
                      <span className="app-nav-link-label">{link.label}</span>
                      {gated && <span className="app-nav-lock">🔒</span>}
                    </NavLink>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* User Footer */}
        <div className="app-sidebar-footer">
          <div className="app-user-card">
            <p className="text-xs text-muted">Logged in as</p>
            <p className="text-sm font-semibold text-primary truncate">{user.profile.preferred_username}</p>
            <p className="text-xs text-muted">{userRoles.join(', ') || 'viewer'}</p>
          </div>
          <div className="app-sidebar-controls">
            <SkinToggle />
            <button className="app-user-logout-redesigned" onClick={onLogout}>
              Sign out
            </button>
          </div>
        </div>
      </motion.aside>

      {/* Main Content Area */}
      <div className="app-main-redesigned">
        {/* Header */}
        <header className="app-header-redesigned">
          <div className="app-header-left">
            <div className="app-status-indicator">
              <div className="app-status-dot" />
              <span className="text-xs font-mono text-muted uppercase tracking-wider">Live • FDIC Connected</span>
            </div>
          </div>

          <div className="app-header-center">
            <BankSearch onSelect={(c) => navigate(`/bank/${c}`)} />
          </div>

          <div className="app-header-right">
            <CommandPalette />
          </div>
        </header>

        {/* Page Content */}
        <main className="app-content-redesigned">
          <Outlet />
        </main>

        {/* Footer */}
        <footer className="app-footer-redesigned muted">
          BankLens · data from FDIC BankFind, SEC EDGAR, Tiingo
        </footer>
      </div>
    </div>
  );
}
