import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import { motion } from 'motion/react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { ModelCardDriverPoint, ModelCardResult } from '../types';
import '../components/charts.css';
import './ModelPage.css';

const FEATURE_LABELS: Record<string, string> = {
  uninsured_deposit_pct: 'Uninsured deposit %',
  htm_to_equity: 'HTM securities / equity',
  securities_to_assets: 'Securities / assets',
  loan_to_deposit_pct: 'Loan / deposit',
  deposit_growth_1yr: 'Deposit growth (1yr)',
};

interface BeePoint extends ModelCardDriverPoint { y: number }

function BeeswarmTip({ active, payload }: { active?: boolean; payload?: { payload: BeePoint }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">{d.name}</div>
      <div className="chart-tooltip-value tabular">value {d.value} · log-odds {d.contribution > 0 ? '+' : ''}{d.contribution.toFixed(2)}</div>
      <div className="chart-tooltip-sub muted">risk score {(d.risk_score * 100).toFixed(1)}%</div>
    </motion.div>
  );
}

function DriverBeeswarm({ feature, points }: { feature: string; points: ModelCardDriverPoint[] }) {
  const colors = chartColors();
  const rows = useMemo<BeePoint[]>(
    () => points.filter((p) => p.feature === feature).map((p) => ({ ...p, y: (p.cert % 97) / 97 })),
    [points, feature],
  );
  if (rows.length === 0) return null;
  const min = Math.min(...rows.map((r) => r.contribution));
  const max = Math.max(...rows.map((r) => r.contribution));
  // deposit_growth_1yr has no prior-year deposits landed for the currently-scored
  // quarter, so score_vector imputes it to the training mean for every bank — every
  // contribution is exactly (the same standardized) 0. A scatter chart over a
  // zero-variance column renders a confusing auto-scaled axis that implies spread
  // that isn't there; naming the real reason is more honest than a flat-line chart.
  if (max - min < 1e-6) {
    return (
      <div className="model-beeswarm-row">
        <div className="model-beeswarm-label">{FEATURE_LABELS[feature] ?? feature}</div>
        <p className="muted model-beeswarm-flat">
          Imputed to the training mean for every bank this quarter — no prior-year
          deposits are landed to compute real growth, so this feature contributes
          nothing to any bank's live score right now.
        </p>
      </div>
    );
  }
  const up = rows.filter((r) => r.contribution >= 0);
  const down = rows.filter((r) => r.contribution < 0);
  return (
    <div className="model-beeswarm-row">
      <div className="model-beeswarm-label">{FEATURE_LABELS[feature] ?? feature}</div>
      <ResponsiveContainer width="100%" height={64}>
        <ScatterChart margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
          <CartesianGrid horizontal={false} stroke={colors.gridline} />
          <XAxis type="number" dataKey="contribution" tick={{ fill: colors.muted, fontSize: 10 }}
            axisLine={{ stroke: colors.baseline }} tickLine={false} />
          <YAxis type="number" dataKey="y" hide domain={[0, 1]} />
          <ZAxis range={[14, 14]} />
          <Tooltip content={<BeeswarmTip />} cursor={false} />
          <Scatter data={up} fill={colors.critical} fillOpacity={0.45} animationDuration={500} animationEasing="ease-out" />
          <Scatter data={down} fill={colors.blue} fillOpacity={0.45} animationDuration={500} animationEasing="ease-out" />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ModelPage() {
  const [card, setCard] = useState<ModelCardResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.modelCard()
      .then((r) => { setCard(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, []);

  const sortedFeatures = card
    ? [...card.features].sort((a, b) => {
        const wa = Math.abs(card.weights[card.features.indexOf(a)]);
        const wb = Math.abs(card.weights[card.features.indexOf(b)]);
        return wb - wa;
      })
    : [];

  return (
    <div className="model-page">
      <div className="panel">
        <h2>Deposit-flight model</h2>
        <p className="muted model-subtitle">
          Feature 13 governance — the model card, honest leave-one-out backtest
          against the real failures it trains on, documented exclusions, and how
          it scores the live population.
        </p>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {card && (
        <>
          <div className="panel">
            <h2>Model card</h2>
            <div className="model-stats">
              <div className="model-stat"><span className="muted">In-sample AUC</span><span className="tabular">{card.auc}</span></div>
              <div className="model-stat"><span className="muted">Trained on</span><span className="tabular">{card.trained_on}</span></div>
              <div className="model-stat"><span className="muted">Positives</span><span className="tabular">{card.positives.length}</span></div>
              <div className="model-stat"><span className="muted">Scored quarter</span><span className="tabular">{card.scored_quarter}</span></div>
            </div>
            <table className="model-coef-table">
              <thead>
                <tr>
                  <th className="model-th">Feature</th>
                  <th className="model-th model-th-right">Weight (standardized)</th>
                </tr>
              </thead>
              <tbody>
                {sortedFeatures.map((f) => {
                  const w = card.weights[card.features.indexOf(f)];
                  return (
                    <tr key={f}>
                      <td className="model-td-name">{FEATURE_LABELS[f] ?? f}</td>
                      <td className="tabular model-td-right" style={{ color: w >= 0 ? 'var(--status-critical)' : 'var(--cat-blue)' }}>
                        {w >= 0 ? '+' : ''}{w.toFixed(3)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="muted model-positives">
              Trained to recognize: {card.positives.map((p) => p.name).join(', ')}.
            </p>
          </div>

          <div className="panel">
            <h2>Leave-one-out backtest</h2>
            <p className="muted chart-caption model-loo-caption">
              The honest test: retrain WITHOUT each real failure, then score it
              against the full pooled universe. A model that only "predicts" the
              failures it was trained to recognize proves nothing — this is what
              would have happened if it had never seen them.
            </p>
            <div className="model-loo-table">
              {card.leave_one_out.map((r) => (
                <Link className="model-loo-row" key={r.cert} to={`/bank/${r.cert}`}>
                  <span className="model-loo-name">{r.name}</span>
                  <span className="tabular muted">risk {r.risk.toFixed(3)}</span>
                  <span className="tabular muted">rank {r.rank}/{r.n}</span>
                  <span className="tabular model-loo-pctile">{r.percentile.toFixed(1)}th pctile</span>
                </Link>
              ))}
            </div>
          </div>

          {card.excluded_candidates.length > 0 && (
            <div className="panel">
              <h2>Documented exclusions from training</h2>
              {card.excluded_candidates.map((e) => (
                <p className="muted model-excluded" key={e.cert}>
                  <strong className="model-excluded-name">{e.name}</strong> — {e.reason}
                </p>
              ))}
              {card.training_exclusions.excluded_count > 0 && (
                <p className="muted model-excluded">
                  Plus {card.training_exclusions.excluded_count} non-deposit-funded charters
                  (deposits under {card.training_exclusions.threshold_pct}% of assets — trust,
                  clearing or card-subsidiary charters, not deposit-run candidates) dropped
                  from the pooled training set.
                </p>
              )}
            </div>
          )}

          <div className="panel">
            <h2>Driver contributions — live population</h2>
            <p className="muted chart-caption">
              Every bank in the {card.scored_quarter} population, scored by this model — each
              row is one feature's contribution to that bank's risk score (standardized
              value × weight). Red raises modeled risk, blue lowers it.
            </p>
            {sortedFeatures.map((f) => (
              <DriverBeeswarm key={f} feature={f} points={card.driver_points} />
            ))}
            <div className="model-beeswarm-legend">
              <span><i style={{ background: 'var(--status-critical)' }} /> raises risk</span>
              <span><i style={{ background: 'var(--cat-blue)' }} /> lowers risk</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
