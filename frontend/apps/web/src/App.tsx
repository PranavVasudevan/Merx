import { useEffect, useState } from 'react';
import { stagger } from 'motion';
import { motion } from 'motion/react';
import type { User } from 'oidc-client-ts';
import { api } from './api';
import { roles } from './auth';
import './App.css';
import { BankSearch } from './components/BankSearch';
import { CandlestickChart } from './components/CandlestickChart';
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

// Entrance stagger — pattern from motion.dev/docs/stagger, adapted: a parent
// variant delays its children via delayChildren: stagger(...), each child
// fades+rises with the same organic easing Bklit UI uses for chart/data
// transitions (theme.css's --ease-organic), so panel entrance and in-panel
// chart animation read as one consistent motion language, not two.
const containerVariants = {
  hidden: {},
  show: { transition: { delayChildren: stagger(0.07) } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.85, 0, 0.15, 1] as const } },
};

export default function App({ user, onLogout }: { user: User; onLogout: () => void }) {
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
        <div className="app-user">
          <span className="muted app-user-name">
            {user.profile.preferred_username} · {roles(user).join(', ') || 'no role'}
          </span>
          <button className="app-user-logout" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      {error && <div className="app-banner-error">{error}</div>}

      {profile && (
        <motion.div className="app-content" initial="hidden" animate="show" variants={containerVariants}>
          <motion.div variants={itemVariants}>
            <KpiTiles profile={profile} />
          </motion.div>
          <motion.div variants={itemVariants}>
            <CandlestickChart cert={cert} key={`candles-${cert}`} />
          </motion.div>

          <div className="app-grid">
            <div className="app-col">
              {xray && <motion.div variants={itemVariants}><XrayPanel xray={xray} /></motion.div>}
              <motion.div variants={itemVariants}><ConcentrationChart profile={profile} /></motion.div>
              <motion.div variants={itemVariants}><CapitalChart profile={profile} /></motion.div>
              <motion.div variants={itemVariants}>
                {filingDiff ? (
                  <FilingDiffPanel diff={filingDiff} />
                ) : (
                  <div className="panel">
                    <h2>Feature 12 · Filing Diff</h2>
                    <p className="muted">Multi-quarter history not landed for this bank yet
                      (available for Wells Fargo 3511 and Dime Community Bank 6976).</p>
                  </div>
                )}
              </motion.div>
            </div>
            <div className="app-col">
              {cluster && <motion.div variants={itemVariants}><PeerClusterCard cluster={cluster} /></motion.div>}
              {riskScore && <motion.div variants={itemVariants}><RiskScorePanel result={riskScore} /></motion.div>}
              {maFit && <motion.div variants={itemVariants}><MaFitPanel result={maFit} /></motion.div>}
            </div>
          </div>

          <motion.div variants={itemVariants}>
            <StressPanel cert={cert} key={cert} />
          </motion.div>
          <motion.div variants={itemVariants}>
            <PeerScatter cert={cert} key={`scatter-${cert}`} />
          </motion.div>
        </motion.div>
      )}

      <footer className="app-footer muted">
        BankLens · {name} (CERT {cert}) · data from FDIC BankFind, {profile?.quarter ?? ''}
      </footer>
    </div>
  );
}
