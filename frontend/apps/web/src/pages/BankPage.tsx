import { useEffect, useState } from 'react';
import { stagger } from 'motion';
import { motion } from 'motion/react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import { CandlestickChart } from '../components/CandlestickChart';
import { CapitalChart } from '../components/CapitalChart';
import { ConcentrationChart } from '../components/ConcentrationChart';
import { CreditTrajectoryPanel } from '../components/CreditTrajectoryPanel';
import { FilingDiffPanel } from '../components/FilingDiffPanel';
import { IrrbbPanel } from '../components/IrrbbPanel';
import { KpiTiles } from '../components/KpiTiles';
import { MaFitPanel } from '../components/MaFitPanel';
import { PeerClusterCard } from '../components/PeerClusterCard';
import { PeerScatter } from '../components/PeerScatter';
import { RiskScorePanel } from '../components/RiskScorePanel';
import { StressPanel } from '../components/StressPanel';
import { WatchlistButton } from '../components/WatchlistButton';
import { XrayPanel } from '../components/XrayPanel';
import type {
  BankProfile, FilingDiffResult, MaFitResult, PeerClusterResult, RiskScoreResult, XrayResult,
} from '../types';
import './BankPage.css';

const DEFAULT_CERT = 6976; // Dime Community Bank — a well-exercised, real example bank

// Same stagger/entrance pattern as the rest of the app (motion.dev/docs/stagger
// + Bklit UI's organic easing) — see theme.css / App.tsx for the shared story.
const containerVariants = {
  hidden: {},
  show: { transition: { delayChildren: stagger(0.07) } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.85, 0, 0.15, 1] as const } },
};

export function BankPage() {
  const params = useParams<{ cert: string }>();
  const cert = Number(params.cert) || DEFAULT_CERT;

  const [profile, setProfile] = useState<BankProfile | null>(null);
  const [xray, setXray] = useState<XrayResult | null>(null);
  const [cluster, setCluster] = useState<PeerClusterResult | null>(null);
  const [maFit, setMaFit] = useState<MaFitResult | null>(null);
  const [riskScore, setRiskScore] = useState<RiskScoreResult | null>(null);
  const [filingDiff, setFilingDiff] = useState<FilingDiffResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tearsheetBusy, setTearsheetBusy] = useState(false);
  const [tearsheetError, setTearsheetError] = useState<string | null>(null);
  // C11 — which population every profile percentile is computed against.
  const [peerBasis, setPeerBasis] = useState<'global' | 'size' | 'cluster'>('global');

  async function downloadTearsheet() {
    setTearsheetBusy(true);
    setTearsheetError(null);
    try {
      await api.downloadTearsheet(cert);
    } catch (e) {
      setTearsheetError(e instanceof Error ? e.message : String(e));
    } finally {
      setTearsheetBusy(false);
    }
  }

  useEffect(() => {
    setProfile(null);
    setError(null);
    setFilingDiff(null);
    Promise.all([
      api.profile(cert, undefined, peerBasis), api.xray(cert), api.peerCluster(cert),
      api.maFit(cert, 8), api.riskScore(cert),
    ])
      .then(([p, x, c, m, r]) => {
        setProfile(p); setXray(x); setCluster(c); setMaFit(m); setRiskScore(r);
      })
      .catch((e) => setError(String(e.message || e)));
    api.filingDiff(cert).then(setFilingDiff).catch(() => setFilingDiff(null));
  }, [cert, peerBasis]);

  return (
    <div className="bank-page">
      {error && <div className="app-banner-error">{error}</div>}

      {profile && (
        <motion.div className="app-content" initial="hidden" animate="show" variants={containerVariants}>
          <motion.div className="bank-page-header" variants={itemVariants}>
            <h1 className="bank-page-title">{profile.name}</h1>
            <div className="bank-page-header-actions">
              <Link className="bank-page-header-link" to={`/trends?cert=${cert}`}>Trends →</Link>
              <select
                className="bank-page-peer-basis"
                value={peerBasis}
                onChange={(e) => setPeerBasis(e.target.value as 'global' | 'size' | 'cluster')}
                title="Which population every profile percentile is computed against (C11)"
              >
                <option value="global">vs. whole population</option>
                <option value="size">vs. size band</option>
                <option value="cluster">vs. peer cluster</option>
              </select>
              <button
                type="button"
                className="bank-page-tearsheet-btn"
                onClick={downloadTearsheet}
                disabled={tearsheetBusy}
                title="Download a PDF tearsheet: profile, X-Ray, capital, concentration, peer cluster, risk score and stress results"
              >
                ⭳ {tearsheetBusy ? 'Building PDF…' : 'PDF tearsheet'}
              </button>
              <WatchlistButton cert={cert} />
            </div>
            {tearsheetError && <span className="app-banner-error bank-page-tearsheet-error">{tearsheetError}</span>}
          </motion.div>
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
              <motion.div variants={itemVariants}><CreditTrajectoryPanel profile={profile} /></motion.div>
              <motion.div variants={itemVariants}>
                {filingDiff ? (
                  <FilingDiffPanel diff={filingDiff} cert={cert} />
                ) : (
                  <div className="panel">
                    <h2>Feature 12 · Filing Diff</h2>
                    <p className="muted">This bank appears in fewer than two landed
                      quarters (it may be a new charter, or a data-landing gap), so
                      there's nothing to compare yet.</p>
                  </div>
                )}
              </motion.div>
            </div>
            <div className="app-col">
              {cluster && <motion.div variants={itemVariants}><PeerClusterCard cluster={cluster} /></motion.div>}
              {riskScore && <motion.div variants={itemVariants}><RiskScorePanel result={riskScore} /></motion.div>}
              {maFit && <motion.div variants={itemVariants}><MaFitPanel result={maFit} cert={cert} /></motion.div>}
            </div>
          </div>

          <motion.div variants={itemVariants}>
            <StressPanel cert={cert} key={cert} />
          </motion.div>
          <motion.div variants={itemVariants}>
            <IrrbbPanel cert={cert} key={`irrbb-${cert}`} />
          </motion.div>
          <motion.div variants={itemVariants}>
            <PeerScatter cert={cert} key={`scatter-${cert}`} />
          </motion.div>

          <p className="muted bank-page-footnote">
            {profile.name} (CERT {cert}) · data from FDIC BankFind, {profile.quarter}
          </p>
        </motion.div>
      )}
    </div>
  );
}
