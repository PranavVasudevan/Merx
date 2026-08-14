import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScreenerPage } from './ScreenerPage';
import { api } from '../api';

vi.mock('../api', () => ({
  api: { screenBanks: vi.fn(), getSavedScreens: vi.fn() },
}));

const ROW = {
  cert: 1, name: 'Testbank', state: 'NY', country: 'US', assets_b: 10, cluster: 'Core-funded',
  roa_pct: 1.1, npl_ratio_pct: 0.5, cet1_ratio: 12.5,
};

function renderPage() {
  return render(<MemoryRouter><ScreenerPage /></MemoryRouter>);
}

afterEach(() => vi.resetAllMocks());

function stubSavedScreens() {
  vi.mocked(api.getSavedScreens).mockResolvedValue({ items: [] });
}

describe('ScreenerPage', () => {
  // screenBanks() fires 250ms after mount (debounced on the filter inputs), so
  // every assertion here has to wait past that debounce.
  it('renders matching rows from a normal search response', async () => {
    stubSavedScreens();
    vi.mocked(api.screenBanks).mockResolvedValue({ count: 1, banks: [ROW] });
    renderPage();
    expect(await screen.findByText('Testbank')).toBeInTheDocument();
    expect(screen.getByText('$10.0B')).toBeInTheDocument();
  });

  it('shows the empty-filters message instead of crashing on a zero-row response', async () => {
    stubSavedScreens();
    vi.mocked(api.screenBanks).mockResolvedValue({ count: 0, banks: [] });
    renderPage();
    expect(await screen.findByText('No banks match these filters.')).toBeInTheDocument();
  });

  it('renders an error banner instead of crashing when the search fails', async () => {
    stubSavedScreens();
    vi.mocked(api.screenBanks).mockRejectedValue(new Error('bridge unreachable'));
    renderPage();
    expect(await screen.findByText('bridge unreachable')).toBeInTheDocument();
  });

  it('never leaves the loading state permanently stuck', async () => {
    stubSavedScreens();
    vi.mocked(api.screenBanks).mockResolvedValue({ count: 1, banks: [ROW] });
    renderPage();
    await waitFor(() => expect(api.screenBanks).toHaveBeenCalled());
    expect(await screen.findByText('Testbank')).toBeInTheDocument();
  });
});
