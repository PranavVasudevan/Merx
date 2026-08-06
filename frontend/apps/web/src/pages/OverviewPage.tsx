import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { PopulationBank, RiskLeaderboardResult } from '../types';
import './OverviewPage.css';

// Same 0.5/0.15 thresholds RiskScorePanel.tsx uses for the per-bank gauge —
// risk_score is the same score_vector output on the same 0-1 scale, so the
// leaderboard should read as visually consistent with the bank dashboard.
function riskZoneColor(score: number, colors: ReturnType<typeof chartColors>): string {
  if (score >= 0.5) return colors.critical;
  if (score >= 0.15) return colors.warning;
  return colors.good;
}

function fmtB(v: number): string {
  return `$${v >= 1000 ? (v / 1000).toFixed(1) + 'T' : v.toFixed(0) + 'B'}`;
}

export function OverviewPage() {
  const [banks, setBanks] = useState<PopulationBank[] | null>(null);
  const [leaderboard, setLeaderboard] = useState<RiskLeaderboardResult | null>(null);
  const [leaderboardError, setLeaderboardError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lbState, setLbState] = useState('');
  const [lbCluster, setLbCluster] = useState('');
  const colors = chartColors();

  useEffect(() => {
    api.population().then((r) => setBanks(r.banks)).catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    // Own try/catch, not folded into the population error: the deposit-flight
    // model can legitimately be untrained (see get_risk_leaderboard's error
    // message) without the rest of the Overview page being broken.
    api.riskLeaderboard(10, { state: lbState || undefined, cluster_label: lbCluster || undefined })
      .then((r) => { setLeaderboard(r); setLeaderboardError(null); })
      .catch((e) => setLeaderboardError(String(e.message || e)));
  }, [lbState, lbCluster]);

  const stats = useMemo(() => {
    if (!banks || banks.length === 0) return null;
    const totalAssets = banks.reduce((s, b) => s + b.assets_b, 0);
    const cet1s = banks.map((b) => b.cet1).filter((v): v is number => v !== null);
    const avgCet1 = cet1s.reduce((s, v) => s + v, 0) / (cet1s.length || 1);
    const highUninsured = banks.filter((b) => b.uninsured_pct >= 40).length;
    const highCre = banks.filter((b) => b.cre_pct >= 50).length;

    const byCluster = new Map<string, number>();
    for (const b of banks) {
      const label = b.cluster_label || 'Unclustered';
      byCluster.set(label, (byCluster.get(label) ?? 0) + 1);
    }
    const clusters = [...byCluster.entries()].sort((a, b) => b[1] - a[1]);

    const states = [...new Set(banks.map((b) => b.state).filter((s): s is string => !!s))].sort();

    return { totalAssets, avgCet1, highUninsured, highCre, clusters, states };
  }, [banks]);

  if (error) {
    return <div className="app-banner-error">{error}</div>;
  }

  return (
    <div className="overview-page">
      <div className="overview-hero panel">
        <h1 className="overview-title">The $1B–$250B US bank population, at a glance</h1>
        <p className="secondary overview-subtitle">
          Real FDIC BankFind data, refreshed each quarter. Every number below is computed from the
          same Gold-layer data the per-bank dashboard uses — nothing here is a mock.
        </p>
        <div className="overview-ctas">
          <Link className="overview-cta overview-cta-primary" to="/screener">Screen all banks →</Link>
          <Link className="overview-cta" to="/compare">Compare banks →</Link>
          <Link className="overview-cta" to="/assistant">Ask the assistant →</Link>
        </div>
      </div>

      {stats && banks && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <div className="overview-kpi-row">
            <div className="panel overview-kpi">
              <div className="overview-kpi-label muted">Banks in the slice</div>
              <div className="overview-kpi-value tabular">{banks.length.toLocaleString()}</div>
              <div className="overview-kpi-sub muted">$1B–$250B assets, 2026Q1</div>
            </div>
            <div className="panel overview-kpi">
              <div className="overview-kpi-label muted">Combined assets</div>
              <div className="overview-kpi-value tabular">{fmtB(stats.totalAssets)}</div>
              <div className="overview-kpi-sub muted">sum across the slice</div>
            </div>
            <div className="panel overview-kpi">
              <div className="overview-kpi-label muted">Average CET1</div>
              <div className="overview-kpi-value tabular">{stats.avgCet1.toFixed(1)}%</div>
              <div className="overview-kpi-sub muted">min + buffer ~10.5%</div>
            </div>
            <div className="panel overview-kpi">
              <div className="overview-kpi-label muted">High uninsured reliance</div>
              <div className="overview-kpi-value tabular">{stats.highUninsured}</div>
              <div className="overview-kpi-sub muted">≥40% uninsured deposits</div>
            </div>
            <div className="panel overview-kpi">
              <div className="overview-kpi-label muted">CRE-heavy</div>
              <div className="overview-kpi-value tabular">{stats.highCre}</div>
              <div className="overview-kpi-sub muted">≥50% loans in CRE</div>
            </div>
          </div>

          <div className="panel overview-clusters">
            <h2>Behavioral peer clusters (Feature 14)</h2>
            <p className="muted overview-clusters-note">
              Grouped by loan-mix + funding behavior, not asset size — see the Screener to browse by
              cluster.
            </p>
            <div className="overview-cluster-list">
              {stats.clusters.map(([label, count]) => (
                <div className="overview-cluster-row" key={label}>
                  <span className="overview-cluster-label">{label}</span>
                  <div className="overview-cluster-track">
                    <motion.div
                      className="overview-cluster-fill"
                      initial={{ width: 0 }}
                      animate={{ width: `${(count / banks.length) * 100}%` }}
                      transition={{ duration: 0.6, ease: [0.85, 0, 0.15, 1] }}
                    />
                  </div>
                  <span className="tabular muted overview-cluster-count">{count}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel overview-leaderboard">
            <h2>Highest deposit-flight resemblance (Feature 13, population-wide)</h2>
            <p className="muted overview-clusters-note">
              Ranked by structural resemblance to real bank failures (2023: SVB/Signature/First
              Republic) — a high score is a prompt to look closer, not a prediction.
            </p>
            <div className="overview-leaderboard-filters">
              <select className="overview-leaderboard-select" value={lbState} onChange={(e) => setLbState(e.target.value)}>
                <option value="">All states</option>
                {stats.states.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select className="overview-leaderboard-select" value={lbCluster} onChange={(e) => setLbCluster(e.target.value)}>
                <option value="">All clusters</option>
                {stats.clusters.map(([label]) => <option key={label} value={label}>{label}</option>)}
              </select>
            </div>
            {leaderboardError && (
              <p className="muted overview-leaderboard-empty">
                {leaderboardError.includes('not trained yet')
                  ? 'Deposit-flight model not trained yet.'
                  : leaderboardError}
              </p>
            )}
            {leaderboard && leaderboard.top.length === 0 && (
              <p className="muted overview-leaderboard-empty">No banks match this state/cluster filter.</p>
            )}
            {leaderboard && (
              <div className="overview-cluster-list">
                {leaderboard.top.map((b, i) => (
                  <Link className="overview-cluster-row overview-leaderboard-row" key={b.cert} to={`/bank/${b.cert}`}>
                    <span className="muted overview-leaderboard-rank tabular">{i + 1}</span>
                    <span className="overview-cluster-label">{b.name}</span>
                    <div className="overview-cluster-track">
                      <motion.div
                        className="overview-cluster-fill"
                        style={{ background: riskZoneColor(b.risk_score, colors) }}
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.min(100, b.risk_score * 100)}%` }}
                        transition={{ duration: 0.6, ease: [0.85, 0, 0.15, 1] }}
                      />
                    </div>
                    <span className="tabular muted overview-cluster-count">{(b.risk_score * 100).toFixed(1)}%</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </motion.div>
      )}
    </div>
  );
}
