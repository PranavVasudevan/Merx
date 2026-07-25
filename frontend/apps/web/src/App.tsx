import { useEffect, useState } from 'react';
import { api } from './api';
import './App.css';
import { BankSearch } from './components/BankSearch';
import { CapitalChart } from './components/CapitalChart';
import { ConcentrationChart } from './components/ConcentrationChart';
import { FilingDiffPanel } from './components/FilingDiffPanel';
import { KpiTiles } from './components/KpiTiles';
import { MaFitPanel } from './components/MaFitPanel';
import { PeerClusterCard } from './components/PeerClusterCard';
import { PeerScatter } from './components/PeerScatter';
import { RiskScorePanel } from './components/RiskScorePanel';
import { StressPanel } from './components/StressPanel';
import { XrayPanel } from './components/XrayPanel';
import type {
  BankProfile, FilingDiffResult, MaFitResult, PeerClusterResult, RiskScoreResult, XrayResult,
} from './types';

const DEFAULT_CERT = 6976; // Dime Community Bank — has multi-quarter Bronze for filing-diff

export default function App() {
  const [cert, setCert] = useState(DEFAULT_CERT);
  const [name, setName] = useState('Dime Community Bank');
  const [profile, setProfile] = useState<BankProfile | null>(null);
  const [xray, setXray] = useState<XrayResult | null>(null);
  const [cluster, setCluster] = useState<PeerClusterResult | null>(null);
  const [maFit, setMaFit] = useState<MaFitResult | null>(null);
  const [riskScore, setRiskScore] = useState<RiskScoreResult | null>(null);
  const [filingDiff, setFilingDiff] = useState<FilingDiffResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);

  useEffect(() => {
    api.health().then(() => setBackendUp(true)).catch(() => setBackendUp(false));
  }, []);

  useEffect(() => {
    setError(null);
    setFilingDiff(null);
    Promise.all([
      api.profile(cert), api.xray(cert), api.peerCluster(cert), api.maFit(cert, 8), api.riskScore(cert),
    ])
      .then(([p, x, c, m, r]) => {
        setProfile(p); setXray(x); setCluster(c); setMaFit(m); setRiskScore(r);
      })
      .catch((e) => setError(String(e.message || e)));
    api.filingDiff(cert).then(setFilingDiff).catch(() => setFilingDiff(null));
  }, [cert]);

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
        <BankSearch onSelect={(c, n) => { setCert(c); setName(n); }} />
      </header>

      {error && <div className="app-banner-error">{error}</div>}

      {profile && (
        <>
          <KpiTiles profile={profile} />

          <div className="app-grid">
            <div className="app-col">
              {xray && <XrayPanel xray={xray} />}
              <ConcentrationChart profile={profile} />
              <CapitalChart profile={profile} />
              {filingDiff ? (
                <FilingDiffPanel diff={filingDiff} />
              ) : (
                <div className="panel">
                  <h2>Feature 12 · Filing Diff</h2>
                  <p className="muted">Multi-quarter history not landed for this bank yet
                    (available for Wells Fargo 3511 and Dime Community Bank 6976).</p>
                </div>
              )}
            </div>
            <div className="app-col">
              {cluster && <PeerClusterCard cluster={cluster} />}
              {riskScore && <RiskScorePanel result={riskScore} />}
              {maFit && <MaFitPanel result={maFit} />}
            </div>
          </div>

          <StressPanel cert={cert} key={cert} />
          <PeerScatter cert={cert} key={`scatter-${cert}`} />
        </>
      )}

      <footer className="app-footer muted">
        BankLens · {name} (CERT {cert}) · data from FDIC BankFind, {profile?.quarter ?? ''}
      </footer>
    </div>
  );
}
