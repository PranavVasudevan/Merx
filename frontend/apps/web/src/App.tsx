import type { User } from 'oidc-client-ts';
import { Route, Routes } from 'react-router-dom';
import { NavShell } from './components/NavShell';
import { ActivityPage } from './pages/ActivityPage';
import { AssistantPage } from './pages/AssistantPage';
import { BankPage } from './pages/BankPage';
import { ComparePage } from './pages/ComparePage';
import { OverviewPage } from './pages/OverviewPage';
import { ScreenerPage } from './pages/ScreenerPage';
import { WatchlistPage } from './pages/WatchlistPage';

export default function App({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <Routes>
      <Route element={<NavShell user={user} onLogout={onLogout} />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/screener" element={<ScreenerPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/bank/:cert" element={<BankPage />} />
      </Route>
    </Routes>
  );
}
