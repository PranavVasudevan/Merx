import { Suspense, lazy } from 'react';
import type { User } from 'oidc-client-ts';
import { Route, Routes } from 'react-router-dom';
import { NavShell } from './components/NavShell';
import { PeerSetProvider } from './PeerSetContext';
import { QuarterProvider } from './QuarterContext';

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
const EarningsPage = lazy(() => import('./pages/EarningsPage').then(m => ({ default: m.EarningsPage })));
const CreditPage = lazy(() => import('./pages/CreditPage').then(m => ({ default: m.CreditPage })));
const FundingPage = lazy(() => import('./pages/FundingPage').then(m => ({ default: m.FundingPage })));
const HeatmapPage = lazy(() => import('./pages/HeatmapPage').then(m => ({ default: m.HeatmapPage })));
const TreemapPage = lazy(() => import('./pages/TreemapPage').then(m => ({ default: m.TreemapPage })));
const DistributionsPage = lazy(() => import('./pages/DistributionsPage').then(m => ({ default: m.DistributionsPage })));
const TrendsPage = lazy(() => import('./pages/TrendsPage').then(m => ({ default: m.TrendsPage })));
const BriefingPage = lazy(() => import('./pages/BriefingPage').then(m => ({ default: m.BriefingPage })));
const FilingDiffPage = lazy(() => import('./pages/FilingDiffPage').then(m => ({ default: m.FilingDiffPage })));
const ClustersPage = lazy(() => import('./pages/ClustersPage').then(m => ({ default: m.ClustersPage })));
const ModelPage = lazy(() => import('./pages/ModelPage').then(m => ({ default: m.ModelPage })));
const BacktestPage = lazy(() => import('./pages/BacktestPage').then(m => ({ default: m.BacktestPage })));
const GeographyPage = lazy(() => import('./pages/GeographyPage').then(m => ({ default: m.GeographyPage })));
const MarketSharePage = lazy(() => import('./pages/MarketSharePage').then(m => ({ default: m.MarketSharePage })));
const MarketPage = lazy(() => import('./pages/MarketPage').then(m => ({ default: m.MarketPage })));
const NetworkPage = lazy(() => import('./pages/NetworkPage').then(m => ({ default: m.NetworkPage })));
const StressLabPage = lazy(() => import('./pages/StressLabPage').then(m => ({ default: m.StressLabPage })));
const FilingsPage = lazy(() => import('./pages/FilingsPage').then(m => ({ default: m.FilingsPage })));
const PortfolioPage = lazy(() => import('./pages/PortfolioPage').then(m => ({ default: m.PortfolioPage })));
const GlossaryPage = lazy(() => import('./pages/GlossaryPage').then(m => ({ default: m.GlossaryPage })));

function RouteFallback() {
  return <div className="route-loading muted">Loading…</div>;
}

export default function App({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <QuarterProvider>
    <PeerSetProvider>
    <Routes>
      <Route element={<NavShell user={user} onLogout={onLogout} />}>
        <Route index element={<Suspense fallback={<RouteFallback />}><OverviewPage /></Suspense>} />
        <Route path="/screener" element={<Suspense fallback={<RouteFallback />}><ScreenerPage /></Suspense>} />
        <Route path="/compare" element={<Suspense fallback={<RouteFallback />}><ComparePage /></Suspense>} />
        <Route path="/earnings" element={<Suspense fallback={<RouteFallback />}><EarningsPage /></Suspense>} />
        <Route path="/credit" element={<Suspense fallback={<RouteFallback />}><CreditPage /></Suspense>} />
        <Route path="/funding" element={<Suspense fallback={<RouteFallback />}><FundingPage /></Suspense>} />
        <Route path="/heatmap" element={<Suspense fallback={<RouteFallback />}><HeatmapPage /></Suspense>} />
        <Route path="/treemap" element={<Suspense fallback={<RouteFallback />}><TreemapPage /></Suspense>} />
        <Route path="/distributions" element={<Suspense fallback={<RouteFallback />}><DistributionsPage /></Suspense>} />
        <Route path="/trends" element={<Suspense fallback={<RouteFallback />}><TrendsPage /></Suspense>} />
        <Route path="/briefing" element={<Suspense fallback={<RouteFallback />}><BriefingPage /></Suspense>} />
        <Route path="/filing-diff" element={<Suspense fallback={<RouteFallback />}><FilingDiffPage /></Suspense>} />
        <Route path="/clusters" element={<Suspense fallback={<RouteFallback />}><ClustersPage /></Suspense>} />
        <Route path="/model" element={<Suspense fallback={<RouteFallback />}><ModelPage /></Suspense>} />
        <Route path="/backtest" element={<Suspense fallback={<RouteFallback />}><BacktestPage /></Suspense>} />
        <Route path="/geography" element={<Suspense fallback={<RouteFallback />}><GeographyPage /></Suspense>} />
        <Route path="/market-share" element={<Suspense fallback={<RouteFallback />}><MarketSharePage /></Suspense>} />
        <Route path="/market" element={<Suspense fallback={<RouteFallback />}><MarketPage /></Suspense>} />
        <Route path="/network" element={<Suspense fallback={<RouteFallback />}><NetworkPage /></Suspense>} />
        <Route path="/stress-lab" element={<Suspense fallback={<RouteFallback />}><StressLabPage /></Suspense>} />
        <Route path="/filings" element={<Suspense fallback={<RouteFallback />}><FilingsPage /></Suspense>} />
        <Route path="/watchlist" element={<Suspense fallback={<RouteFallback />}><WatchlistPage /></Suspense>} />
        <Route path="/portfolio" element={<Suspense fallback={<RouteFallback />}><PortfolioPage /></Suspense>} />
        <Route path="/glossary" element={<Suspense fallback={<RouteFallback />}><GlossaryPage /></Suspense>} />
        <Route path="/assistant" element={<Suspense fallback={<RouteFallback />}><AssistantPage /></Suspense>} />
        <Route path="/activity" element={<Suspense fallback={<RouteFallback />}><ActivityPage /></Suspense>} />
        <Route path="/bank/:cert" element={<Suspense fallback={<RouteFallback />}><BankPage /></Suspense>} />
      </Route>
    </Routes>
    </PeerSetProvider>
    </QuarterProvider>
  );
}
