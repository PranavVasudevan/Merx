import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { api } from '../api';
import type { QuarterlyBriefingResult } from '../types';
import './BriefingPage.css';

function fmtChange(m: { change: number; metric: string }): string {
  const unit = m.metric === 'total_assets' ? '' : 'pp';
  return `${m.change > 0 ? '+' : ''}${m.change.toFixed(2)}${unit}`;
}

export function BriefingPage() {
  const [b, setB] = useState<QuarterlyBriefingResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.quarterlyBriefing(8)
      .then((r) => { setB(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, []);

  const topTransitions = b
    ? Object.entries(b.cluster_migrations.by_transition).sort((a, c) => c[1] - a[1]).slice(0, 6)
    : [];
  const maxTransition = topTransitions.length ? topTransitions[0][1] : 1;

  return (
    <div className="briefing-page">
      <div className="panel">
        <h2>Quarterly briefing</h2>
        <p className="muted briefing-subtitle">
          What changed across the full landed FDIC population between the two most
          recently landed quarters — not a per-bank drill-down (see Trends and Filing
          Diff for that).
        </p>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {b && (
        <>
          <div className="panel">
            <h2>{b.prior_quarter} → {b.quarter}</h2>
            <div className="briefing-stats">
              <div className="briefing-stat">
                <span className="muted">Population</span>
                <span className="tabular">{b.prior_population_count} → {b.population_count}</span>
              </div>
              <div className="briefing-stat">
                <span className="muted">Entered slice</span>
                <span className="tabular">{b.entered.length}</span>
              </div>
              <div className="briefing-stat">
                <span className="muted">Exited slice</span>
                <span className="tabular">{b.exited.length}</span>
              </div>
              <div className="briefing-stat">
                <span className="muted">Cluster changes</span>
                <span className="tabular">{b.cluster_migrations.count}</span>
              </div>
            </div>
            {(b.entered.length > 0 || b.exited.length > 0) && (
              <div className="briefing-churn">
                {b.entered.length > 0 && (
                  <div>
                    <h3 className="briefing-subhead">Newly in the population</h3>
                    <p className="muted briefing-name-list">{b.entered.join(' · ')}</p>
                  </div>
                )}
                {b.exited.length > 0 && (
                  <div>
                    <h3 className="briefing-subhead">No longer in the slice</h3>
                    <p className="muted briefing-name-list">{b.exited.join(' · ')}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="panel">
            <h2>Biggest movers</h2>
            <div className="briefing-movers">
              {b.top_movers.map((m, i) => (
                <motion.div
                  className="briefing-mover-row"
                  key={`${m.cert}-${m.metric}`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1, transition: { delay: Math.min(i, 12) * 0.02 } }}
                >
                  <span className={`briefing-mover-arrow ${m.change > 0 ? 'briefing-up' : 'briefing-down'}`}>
                    {m.change > 0 ? '▲' : '▼'}
                  </span>
                  <span className="briefing-mover-label">{m.label}</span>
                  <Link to={`/bank/${m.cert}`} className="briefing-mover-name">{m.name}</Link>
                  <span className="muted tabular briefing-mover-from-to">
                    {m.from.toFixed(2)} → {m.to.toFixed(2)}
                  </span>
                  <span className="tabular briefing-mover-change">{fmtChange(m)}</span>
                </motion.div>
              ))}
            </div>
          </div>

          <div className="panel">
            <h2>Behavioral cluster migrations</h2>
            <p className="muted chart-caption briefing-cluster-caveat">
              {b.cluster_migrations.method === 'fixed_centroids'
                ? 'Assigned against fixed reference-quarter centroids, not a fresh refit each ' +
                  'quarter — a bank near a cluster boundary with a stable balance sheet keeps the ' +
                  'same label instead of flipping on refit noise.'
                : 'Clusters are recomputed independently each quarter — a bank near a cluster ' +
                  'boundary can show a label change here even with a stable balance sheet. Run ' +
                  'cluster_centroids_cli to enable fixed-centroid assignment and remove this noise.'}
              {' '}{b.cluster_migrations.refit_comparison.note}
            </p>
            <div className="briefing-transitions">
              {topTransitions.map(([pair, count]) => (
                <div className="briefing-transition-row" key={pair}>
                  <span className="briefing-transition-label">{pair}</span>
                  <div className="briefing-transition-track">
                    <motion.div
                      className="briefing-transition-fill"
                      initial={{ width: 0 }}
                      animate={{ width: `${(count / maxTransition) * 100}%` }}
                      transition={{ duration: 0.5, ease: [0.85, 0, 0.15, 1] }}
                    />
                  </div>
                  <span className="tabular muted briefing-transition-count">{count}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <h2>Risk leaderboard entrants</h2>
            {!b.risk_model_trained && (
              <p className="muted">Deposit-flight model not trained — run deposit_flight_cli.</p>
            )}
            {b.risk_model_trained && b.risk_leaderboard_entrants.length === 0 && (
              <p className="muted">No new entrants to the top-8 riskiest this quarter.</p>
            )}
            {b.risk_model_trained && b.risk_leaderboard_entrants.length > 0 && (
              <div className="briefing-entrants">
                {b.risk_leaderboard_entrants.map((r) => (
                  <Link className="briefing-entrant-row" key={r.cert} to={`/bank/${r.cert}`}>
                    <span className="tabular briefing-entrant-score">
                      {r.resemblance_percentile === null ? '—' : `${r.resemblance_percentile.toFixed(0)}th pctile`}
                    </span>
                    <span>{r.name}</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
