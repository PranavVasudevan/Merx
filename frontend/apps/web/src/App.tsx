import { Suspense, lazy } from 'react';
import type { User } from 'oidc-client-ts';
import { Route, Routes } from 'react-router-dom';
import { NavShell } from './components/NavShell';

// Every route is code-split. Eager imports put all pages plus three charting
// libraries into one 1,015,105-byte chunk that every visitor downloaded regardless
// of which page they opened; with ~20 routes that only gets worse. Overview is the
// landing route and is lazy too — its chunk is fetched immediately anyway, and
// keeping the list uniform means no route silently drifts back into the main bundle.
const OverviewPage = lazy(() => import('./pages/OverviewPage').then(m => ({ default: m.OverviewPage })));
const ScreenerPage = lazy(() => import('./pages/ScreenerPage').then(m => ({ default: m.ScreenerPage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then(m => ({ default: m.ComparePage })));
const WatchlistPage = lazy(() => import('./pages/WatchlistPage').then(m => ({ default: m.WatchlistPage })));
const AssistantPage = lazy(() => import('./pages/AssistantPage').then(m => ({ default: m.AssistantPage })));
const ActivityPage = lazy(() => import('./pages/ActivityPage').then(m => ({ default: m.ActivityPage })));
const BankPage = lazy(() => import('./pages/BankPage').then(m => ({ default: m.BankPage })));

function RouteFallback() {
  return <div className="route-loading muted">Loading…</div>;
}

export default function App({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <Routes>
      <Route element={<NavShell user={user} onLogout={onLogout} />}>
        <Route index element={<Suspense fallback={<RouteFallback />}><OverviewPage /></Suspense>} />
        <Route path="/screener" element={<Suspense fallback={<RouteFallback />}><ScreenerPage /></Suspense>} />
        <Route path="/compare" element={<Suspense fallback={<RouteFallback />}><ComparePage /></Suspense>} />
        <Route path="/watchlist" element={<Suspense fallback={<RouteFallback />}><WatchlistPage /></Suspense>} />
        <Route path="/assistant" element={<Suspense fallback={<RouteFallback />}><AssistantPage /></Suspense>} />
        <Route path="/activity" element={<Suspense fallback={<RouteFallback />}><ActivityPage /></Suspense>} />
        <Route path="/bank/:cert" element={<Suspense fallback={<RouteFallback />}><BankPage /></Suspense>} />
      </Route>
    </Routes>
  );
}
