import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BankPage } from './BankPage';
import { api } from '../api';
import { QuarterProvider } from '../QuarterContext';
import type { BankProfile } from '../types';

// BankPage's own job is orchestration (fetch by cert, show/hide by state) —
// every child panel here takes already-fetched data as props and is tested
// on its own, so it's stubbed out rather than re-modeling every panel's full
// data contract just to keep this smoke test from crashing on missing fields.
vi.mock('../components/AnnotationsPanel', () => ({ AnnotationsPanel: () => <div /> }));
vi.mock('../components/CandlestickChart', () => ({ CandlestickChart: () => <div /> }));
vi.mock('../components/CapitalChart', () => ({ CapitalChart: () => <div /> }));
vi.mock('../components/CompositionSankeyPanel', () => ({ CompositionSankeyPanel: () => <div /> }));
vi.mock('../components/ConcentrationChart', () => ({ ConcentrationChart: () => <div /> }));
vi.mock('../components/CreditTrajectoryPanel', () => ({ CreditTrajectoryPanel: () => <div /> }));
vi.mock('../components/FilingDiffPanel', () => ({ FilingDiffPanel: () => <div /> }));
vi.mock('../components/HoldingCompanyPanel', () => ({ HoldingCompanyPanel: () => <div /> }));
vi.mock('../components/IrrbbPanel', () => ({ IrrbbPanel: () => <div /> }));
vi.mock('../components/KpiTiles', () => ({ KpiTiles: () => <div /> }));
vi.mock('../components/MaFitPanel', () => ({ MaFitPanel: () => <div /> }));
vi.mock('../components/PeerClusterCard', () => ({ PeerClusterCard: () => <div /> }));
vi.mock('../components/PeerScatter', () => ({ PeerScatter: () => <div /> }));
vi.mock('../components/RiskScorePanel', () => ({ RiskScorePanel: () => <div /> }));
vi.mock('../components/StressPanel', () => ({ StressPanel: () => <div /> }));
vi.mock('../components/WatchlistButton', () => ({ WatchlistButton: () => <div /> }));
vi.mock('../components/XrayPanel', () => ({ XrayPanel: () => <div /> }));

vi.mock('../api', () => ({
  api: {
    profile: vi.fn(), xray: vi.fn(), peerCluster: vi.fn(), maFit: vi.fn(), riskScore: vi.fn(),
    filingDiff: vi.fn(), downloadTearsheet: vi.fn(),
    // D3 — QuarterProvider (mounted below, BankPage now reads useQuarter())
    // fetches this on mount regardless of which page is under it.
    quarters: vi.fn(),
    // D4 — separate independent call, must not block the core Promise.all.
    holdingCompany: vi.fn(),
  },
}));

// Minimal stand-in — every consumer of the fuller shape is mocked above, so
// BankPage only ever reads `.name`/`.quarter` from this itself.
const PROFILE = { name: 'Testbank', quarter: '2026Q1' } as unknown as BankProfile;

function renderAt(cert: number) {
  return render(
    <MemoryRouter initialEntries={[`/bank/${cert}`]}>
      <QuarterProvider>
        <Routes><Route path="/bank/:cert" element={<BankPage />} /></Routes>
      </QuarterProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.resetAllMocks());

describe('BankPage', () => {
  it('renders the bank title once all core panels resolve', async () => {
    vi.mocked(api.quarters).mockResolvedValue({ quarters: ['2026Q1'], latest: '2026Q1' });
    vi.mocked(api.profile).mockResolvedValue(PROFILE);
    vi.mocked(api.xray).mockResolvedValue(null as never);
    vi.mocked(api.peerCluster).mockResolvedValue(null as never);
    vi.mocked(api.maFit).mockResolvedValue(null as never);
    vi.mocked(api.riskScore).mockResolvedValue(null as never);
    vi.mocked(api.holdingCompany).mockResolvedValue(null as never);
    vi.mocked(api.filingDiff).mockResolvedValue(null as never);
    renderAt(1);
    expect(await screen.findByText('Testbank')).toBeInTheDocument();
  });

  it('renders an error banner instead of crashing when the core Promise.all rejects', async () => {
    vi.mocked(api.quarters).mockResolvedValue({ quarters: ['2026Q1'], latest: '2026Q1' });
    vi.mocked(api.profile).mockRejectedValue(new Error('no such bank'));
    vi.mocked(api.xray).mockResolvedValue(null as never);
    vi.mocked(api.peerCluster).mockResolvedValue(null as never);
    vi.mocked(api.maFit).mockResolvedValue(null as never);
    vi.mocked(api.riskScore).mockResolvedValue(null as never);
    vi.mocked(api.holdingCompany).mockResolvedValue(null as never);
    vi.mocked(api.filingDiff).mockResolvedValue(null as never);
    renderAt(1);
    expect(await screen.findByText('no such bank')).toBeInTheDocument();
  });

  it('falls back to the "not enough quarters" note when filingDiff has its own independent failure', async () => {
    vi.mocked(api.quarters).mockResolvedValue({ quarters: ['2026Q1'], latest: '2026Q1' });
    vi.mocked(api.profile).mockResolvedValue(PROFILE);
    vi.mocked(api.xray).mockResolvedValue(null as never);
    vi.mocked(api.peerCluster).mockResolvedValue(null as never);
    vi.mocked(api.maFit).mockResolvedValue(null as never);
    vi.mocked(api.riskScore).mockResolvedValue(null as never);
    vi.mocked(api.holdingCompany).mockResolvedValue(null as never);
    vi.mocked(api.filingDiff).mockRejectedValue(new Error('too few quarters'));
    renderAt(1);
    expect(await screen.findByText('Testbank')).toBeInTheDocument();
    expect(await screen.findByText(/nothing to compare yet/)).toBeInTheDocument();
  });
});
