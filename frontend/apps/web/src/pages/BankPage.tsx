import { useEffect, useState } from 'react';
import { stagger } from 'motion';
import { motion } from 'motion/react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { CandlestickChart } from '../components/CandlestickChart';
import { CapitalChart } from '../components/CapitalChart';
import { ConcentrationChart } from '../components/ConcentrationChart';
import { FilingDiffPanel } from '../components/FilingDiffPanel';
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

const DEFAULT_CERT = 6976; // Dime Community Bank — has multi-quarter Bronze for filing-diff

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

  useEffect(() => {
    setProfile(null);
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

  return (
    <div className="bank-page">
      {error && <div className="app-banner-error">{error}</div>}

      {profile && (
        <motion.div className="app-content" initial="hidden" animate="show" variants={containerVariants}>
          <motion.div className="bank-page-header" variants={itemVariants}>
            <h1 className="bank-page-title">{profile.name}</h1>
            <WatchlistButton cert={cert} />
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

          <p className="muted bank-page-footnote">
            {profile.name} (CERT {cert}) · data from FDIC BankFind, {profile.quarter}
          </p>
        </motion.div>
      )}
    </div>
  );
}
