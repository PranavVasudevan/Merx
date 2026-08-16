import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StressLabPage } from './StressLabPage';
import { api } from '../api';
import type { StressComparisonResult, StressResult } from '../types';

// The three result charts take already-computed props and are covered on their
// own — stubbed here so this smoke test only exercises StressLabPage's own
// fetch/orchestration logic, not every downstream chart's exact data contract.
vi.mock('../components/CapitalWaterfallChart', () => ({ CapitalWaterfallChart: () => <div /> }));
vi.mock('../components/MarginalContributionChart', () => ({ MarginalContributionChart: () => <div /> }));
vi.mock('../components/StressSurfaceChart', () => ({ StressSurfaceChart: () => <div /> }));

vi.mock('../api', () => ({
  api: {
    population: vi.fn(),
    getWatchlist: vi.fn(),
    riskLeaderboard: vi.fn(),
    searchBanks: vi.fn(),
    bulkStressTest: vi.fn(),
    stressComparison: vi.fn(),
    stressProjection: vi.fn(),
    liquiditySurvival: vi.fn(),
    stressTest: vi.fn(),
    stressSurface: vi.fn(),
    // D10 — named scenario registry + user-saved custom scenarios, fetched
    // unconditionally on mount.
    scenarioLibrary: vi.fn(),
    getCustomScenarios: vi.fn(),
  },
}));

// StressLabPage's own legContribs effect reads these two fields directly off
// every stressTest() result (base and 3 "minus one leg" holdouts) — everything
// else downstream is a mocked chart, so this is the only shape that matters.
const STRESS_RESULT = { capital_waterfall: { total_capital_hit: 0 }, legs_not_applied: [] } as unknown as StressResult;

// StressLabPage itself (not just the mocked charts) reads these fields
// straight off `cmp` before any child component ever sees it — see the
// "Pricing-engine comparison" panel around StressLabPage.tsx:312-342.
const LEG = {
  capital_waterfall: { afs_mark_loss: 0, htm_realized_loss: 0 },
  after: { cet1: 10 },
  duration_sources: null,
} as unknown as StressComparisonResult['linear'];
const STRESS_COMPARISON = { cert: 1, name: 'Testbank', linear: LEG, quantlib: LEG } as StressComparisonResult;

function stubHappyPath() {
  vi.mocked(api.population).mockResolvedValue({ banks: [] });
  vi.mocked(api.getWatchlist).mockResolvedValue({ items: [] });
  vi.mocked(api.stressComparison).mockResolvedValue(STRESS_COMPARISON);
  vi.mocked(api.stressProjection).mockResolvedValue(null as never);
  vi.mocked(api.liquiditySurvival).mockResolvedValue(null as never);
  vi.mocked(api.stressTest).mockResolvedValue(STRESS_RESULT);
  vi.mocked(api.stressSurface).mockResolvedValue(null as never);
  vi.mocked(api.scenarioLibrary).mockResolvedValue({ scenarios: [], version: 1 });
  vi.mocked(api.getCustomScenarios).mockResolvedValue({ items: [] });
}

function renderPage() {
  return render(<MemoryRouter><StressLabPage /></MemoryRouter>);
}

afterEach(() => vi.resetAllMocks());

describe('StressLabPage', () => {
  it('renders the sliders and scenario controls without crashing on an empty population', async () => {
    stubHappyPath();
    renderPage();
    expect(screen.getByText('Stress lab')).toBeInTheDocument();
    await waitFor(() => expect(api.population).toHaveBeenCalled(), { timeout: 2000 });
    // Empty population -> default scope's resolved certs are empty -> no
    // watchlist-scope empty-state text should appear (that's scope-specific).
    expect(screen.queryByText('Your watchlist is empty — add banks from any bank page.')).not.toBeInTheDocument();
  });

  it('shows the bulk-scenario error banner instead of crashing when the cross-bank scope is non-empty and the call fails', async () => {
    vi.mocked(api.population).mockResolvedValue({
      banks: [{ cert: 1, name: 'Testbank', state: 'NY', assets_b: 10, cre_pct: 10, uninsured_pct: 20, cet1: 12, cluster_id: 0, cluster_label: 'Core-funded' }],
    });
    vi.mocked(api.getWatchlist).mockResolvedValue({ items: [] });
    vi.mocked(api.bulkStressTest).mockRejectedValue(new Error('bridge unreachable'));
    vi.mocked(api.stressComparison).mockResolvedValue(STRESS_COMPARISON);
    vi.mocked(api.stressProjection).mockResolvedValue(null as never);
    vi.mocked(api.liquiditySurvival).mockResolvedValue(null as never);
    vi.mocked(api.scenarioLibrary).mockResolvedValue({ scenarios: [], version: 1 });
    vi.mocked(api.getCustomScenarios).mockResolvedValue({ items: [] });
    vi.mocked(api.stressTest).mockResolvedValue(STRESS_RESULT);
    vi.mocked(api.stressSurface).mockResolvedValue(null as never);
    renderPage();
    expect(await screen.findByText('bridge unreachable', {}, { timeout: 2000 })).toBeInTheDocument();
  });
});
