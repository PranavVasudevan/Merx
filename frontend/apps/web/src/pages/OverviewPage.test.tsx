import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OverviewPage } from './OverviewPage';
import { api } from '../api';

vi.mock('../api', () => ({
  api: {
    population: vi.fn(),
    riskLeaderboard: vi.fn(),
  },
}));

const BANK = {
  cert: 1, name: 'Testbank', assets_b: 10, cet1: 12.5, uninsured_pct: 20, cre_pct: 10,
  cluster_id: 0, cluster_label: 'Core-funded', state: 'NY',
};

const EMPTY_LEADERBOARD = { count: 0, model_trained_on: '', note: '', top: [] };

function renderPage() {
  return render(<MemoryRouter><OverviewPage /></MemoryRouter>);
}

afterEach(() => vi.resetAllMocks());

describe('OverviewPage', () => {
  it('renders KPI tiles from a normal population response', async () => {
    vi.mocked(api.population).mockResolvedValue({ banks: [BANK] });
    vi.mocked(api.riskLeaderboard).mockResolvedValue(EMPTY_LEADERBOARD);
    renderPage();
    // A single bank's combined-assets KPI ("$10B") is unambiguous, unlike the
    // bank-count tile, whose "1" text collides with the peer-cluster count.
    expect(await screen.findByText('$10B')).toBeInTheDocument();
    expect(screen.getByText('The US bank population, at a glance')).toBeInTheDocument();
  });

  it('renders the hero without crashing on an empty population', async () => {
    vi.mocked(api.population).mockResolvedValue({ banks: [] });
    vi.mocked(api.riskLeaderboard).mockResolvedValue(EMPTY_LEADERBOARD);
    renderPage();
    expect(screen.getByText('The US bank population, at a glance')).toBeInTheDocument();
    await waitFor(() => expect(api.population).toHaveBeenCalled());
    // No KPI row: stats is null for an empty population.
    expect(screen.queryByText('Banks in the population')).not.toBeInTheDocument();
  });

  it('renders an error banner instead of crashing when population fails', async () => {
    vi.mocked(api.population).mockRejectedValue(new Error('bridge unreachable'));
    vi.mocked(api.riskLeaderboard).mockResolvedValue(EMPTY_LEADERBOARD);
    renderPage();
    expect(await screen.findByText('bridge unreachable')).toBeInTheDocument();
  });

  it('shows a dedicated message when the risk model is untrained, without failing the whole page', async () => {
    vi.mocked(api.population).mockResolvedValue({ banks: [BANK] });
    vi.mocked(api.riskLeaderboard).mockRejectedValue(new Error('model not trained yet'));
    renderPage();
    expect(await screen.findByText('Deposit-flight model not trained yet.')).toBeInTheDocument();
    expect(screen.getByText('The US bank population, at a glance')).toBeInTheDocument();
  });
});
