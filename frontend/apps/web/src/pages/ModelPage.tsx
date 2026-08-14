import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip,
  XAxis, YAxis, ZAxis,
} from 'recharts';
import { motion } from 'motion/react';
import { api } from '../api';
import { chartColors } from '../colors';
import { RISK_DISCLAIMER } from '../csvExport';
import type {
  MaWeightValidationResult, ModelCardDriverPoint, ModelCardResult, XrayValidationResult,
} from '../types';
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
      <div className="chart-tooltip-sub muted">raw model output {d.risk_score.toFixed(3)} (not a probability)</div>
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
  const [maWeights, setMaWeights] = useState<MaWeightValidationResult | null>(null);
  const [maWeightsError, setMaWeightsError] = useState<string | null>(null);
  const [xrayVal, setXrayVal] = useState<XrayValidationResult | null>(null);
  const [xrayValError, setXrayValError] = useState<string | null>(null);

  useEffect(() => {
    api.modelCard()
      .then((r) => { setCard(r); setError(null); })
      .catch((e: Error) => setError(e.message));
    api.maWeightValidation()
      .then((r) => { setMaWeights(r); setMaWeightsError(null); })
      .catch((e: Error) => setMaWeightsError(e.message));
    api.xrayValidation()
      .then((r) => { setXrayVal(r); setXrayValError(null); })
      .catch((e: Error) => setXrayValError(e.message));
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
        <p className="muted chart-caption">{RISK_DISCLAIMER}</p>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {card && (
        <>
          <div className="panel">
            <h2>Model card</h2>
            <p className="muted chart-caption">
              Do not read this model as validated — the point of everything below is to show
              precisely how uncertain a linear model fit on a handful of real failures is.
            </p>
            <div className="model-stats">
              <div className="model-stat">
                <span className="muted">In-sample AUC</span>
                <span className="tabular">
                  {card.auc}
                  {card.bootstrap && (
                    <span className="muted"> [{card.bootstrap.auc.lo}, {card.bootstrap.auc.hi}]</span>
                  )}
                </span>
              </div>
              <div className="model-stat"><span className="muted">Trained on</span><span className="tabular">{card.trained_on}</span></div>
              <div className="model-stat"><span className="muted">Positives</span><span className="tabular">{card.positives.length}</span></div>
              <div className="model-stat"><span className="muted">Scored quarter</span><span className="tabular">{card.scored_quarter}</span></div>
              {card.bootstrap && (
                <div className="model-stat">
                  <span className="muted">Bootstrap resamples</span>
                  <span className="tabular">{card.bootstrap.n_boot_used}/{card.bootstrap.n_boot}</span>
                </div>
              )}
            </div>
            <table className="model-coef-table">
              <thead>
                <tr>
                  <th className="model-th">Feature</th>
                  <th className="model-th model-th-right">Weight (standardized)</th>
                  <th className="model-th model-th-right">95% bootstrap CI</th>
                  <th className="model-th model-th-right">Imputed</th>
                </tr>
              </thead>
              <tbody>
                {sortedFeatures.map((f) => {
                  const w = card.weights[card.features.indexOf(f)];
                  const ci = card.bootstrap?.coefficients[f];
                  return (
                    <tr key={f}>
                      <td className="model-td-name">{FEATURE_LABELS[f] ?? f}</td>
                      <td className="tabular model-td-right" style={{ color: w >= 0 ? 'var(--status-critical)' : 'var(--cat-blue)' }}>
                        {w >= 0 ? '+' : ''}{w.toFixed(3)}
                      </td>
                      <td className="tabular model-td-right muted">
                        {ci ? `[${ci.lo}, ${ci.hi}]` : '—'}
                      </td>
                      <td className="tabular model-td-right muted">
                        {card.imputation_rates[f] !== undefined ? `${card.imputation_rates[f]}%` : '—'}
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
            <h2>Precision / recall at the true base rate</h2>
            <p className="muted chart-caption">
              Evaluated at the real rarity of failure (a handful of positives among the full
              pooled training set) — not resampled or balanced. AUC alone can look deceptively
              good on a rare-event problem; this shows what precision actually costs at each
              recall level.
            </p>
            {card.pr_curve.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={card.pr_curve} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="var(--gridline)" />
                  <XAxis dataKey="recall" type="number" domain={[0, 1]} tick={{ fontSize: 10.5 }}
                    tickFormatter={(v: number) => v.toFixed(1)} label={{ value: 'recall', position: 'insideBottom', offset: -2, fontSize: 11 }} />
                  <YAxis dataKey="precision" type="number" domain={[0, 1]} tick={{ fontSize: 10.5 }}
                    tickFormatter={(v: number) => v.toFixed(1)} label={{ value: 'precision', angle: -90, position: 'insideLeft', fontSize: 11 }} />
                  <Tooltip formatter={(v, name) => [typeof v === 'number' ? v.toFixed(3) : v, name]} />
                  <Line type="monotone" dataKey="precision" stroke="var(--cat-blue)" dot={false} strokeWidth={2} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : <p className="muted">No PR curve persisted — retrain via deposit_flight_cli.</p>}
          </div>

          <div className="panel">
            <h2>Calibration curve</h2>
            <p className="muted chart-caption">
              Predicted probability vs. observed positive rate, binned. A well-calibrated model's
              points sit on the diagonal. With only a handful of true positives most bins will show
              0% observed — that is the honest finding, not a bug.
            </p>
            {card.calibration_curve.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={card.calibration_curve} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="var(--gridline)" />
                  <XAxis dataKey="mean_predicted" type="number" domain={[0, 1]} tick={{ fontSize: 10.5 }}
                    tickFormatter={(v: number) => v.toFixed(1)} label={{ value: 'mean predicted', position: 'insideBottom', offset: -2, fontSize: 11 }} />
                  <YAxis type="number" domain={[0, 1]} tick={{ fontSize: 10.5 }}
                    tickFormatter={(v: number) => v.toFixed(1)} label={{ value: 'observed rate', angle: -90, position: 'insideLeft', fontSize: 11 }} />
                  <Tooltip formatter={(v, name) => [typeof v === 'number' ? v.toFixed(3) : v, name]} />
                  <Line type="linear" dataKey="diag" data={[{ mean_predicted: 0, diag: 0 }, { mean_predicted: 1, diag: 1 }]}
                    stroke="var(--baseline)" strokeDasharray="4 4" dot={false} isAnimationActive={false} legendType="none" name="perfect calibration" />
                  <Line type="monotone" dataKey="observed_rate" stroke="var(--status-critical)" dot={{ r: 3 }} strokeWidth={2} isAnimationActive={false} name="observed" />
                </LineChart>
              </ResponsiveContainer>
            ) : <p className="muted">No calibration curve persisted — retrain via deposit_flight_cli.</p>}
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

          <div className="panel">
            <h2>M&amp;A fit-score weight validation (C9)</h2>
            <p className="muted chart-caption">
              Whether <code>ma_fit.DEFAULT_WEIGHTS</code> (funding 45%, business 25%, size 15%, geo
              15% — hand-set, never previously tested) actually rank REAL acquirers above
              non-acquirers, validated against real deal history: FDIC's own `failures` endpoint
              names the acquiring institution for every FDIC-resolved failure, matched by name
              against that quarter's landed population.
            </p>
            {maWeightsError && (
              <p className="muted">
                {maWeightsError.includes('not run yet')
                  ? 'Not run yet — run ma_weights_cli (scripts/ma_weights.ps1).'
                  : maWeightsError}
              </p>
            )}
            {maWeights && (
              <>
                <div className="model-stats">
                  <div className="model-stat"><span className="muted">Real deals matched</span><span className="tabular">{maWeights.n_deals_total}</span></div>
                  <div className="model-stat"><span className="muted">Weighted default mean</span><span className="tabular">{maWeights.weighted_default_mean_percentile ?? '—'}</span></div>
                  <div className="model-stat"><span className="muted">Weighted refit mean</span><span className="tabular">{maWeights.weighted_refit_mean_percentile ?? '—'}</span></div>
                  <div className="model-stat"><span className="muted">Decision</span><span className="tabular">{maWeights.decision}</span></div>
                </div>
                <p className="muted chart-caption">{maWeights.note}</p>
                <table className="model-coef-table">
                  <thead>
                    <tr>
                      <th className="model-th">Quarter</th>
                      <th className="model-th model-th-right">Matched deals</th>
                      <th className="model-th model-th-right">Mean acquirer percentile</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(maWeights.per_quarter).map(([label, q]) => (
                      <tr key={label}>
                        <td className="model-td-name">{label}</td>
                        <td className="tabular model-td-right">{q.n_matched_deals}</td>
                        <td className="tabular model-td-right">{q.mean_percentile ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel">
            <h2>X-Ray forward-return validation (C10)</h2>
            <p className="muted chart-caption">
              The cheapest genuine validation available for the X-Ray rule engine: do banks it
              flags high-risk subsequently underperform in the market? Built from real landed
              Tiingo price history joined to X-Ray severity as of each historical quarter —
              published either way, per this feature's own instruction that a null result is as
              reportable as a real one.
            </p>
            {xrayValError && (
              <p className="muted">
                {xrayValError.includes('not run yet')
                  ? 'Not run yet — run xray_validation_cli (scripts/xray_validation.ps1).'
                  : xrayValError}
              </p>
            )}
            {xrayVal && (
              xrayVal.n_total === 0 ? (
                <p className="muted">
                  No observations yet — {xrayVal.tickers_with_landed_price_data} tickers have
                  landed price data. Run scripts/land_market_data.ps1 (needs a free
                  TIINGO_API_KEY) to land coverage, then re-run scripts/xray_validation.ps1.
                </p>
              ) : (
                <>
                  <div className="model-stats">
                    <div className="model-stat"><span className="muted">Observations</span><span className="tabular">{xrayVal.n_total}</span></div>
                    <div className="model-stat"><span className="muted">Horizon</span><span className="tabular">{xrayVal.horizon_trading_days}d</span></div>
                    <div className="model-stat"><span className="muted">High vs low spread</span><span className="tabular">{xrayVal.high_vs_low_spread_pp ?? '—'}pp</span></div>
                    <div className="model-stat"><span className="muted">p-value</span><span className="tabular">{xrayVal.p_value ?? '—'}</span></div>
                  </div>
                  <table className="model-coef-table">
                    <thead>
                      <tr>
                        <th className="model-th">Severity</th>
                        <th className="model-th model-th-right">n</th>
                        <th className="model-th model-th-right">Mean forward return</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(['low', 'elevated', 'high'] as const).map((sev) => (
                        <tr key={sev}>
                          <td className="model-td-name">{sev}</td>
                          <td className="tabular model-td-right">{xrayVal.by_severity[sev].n}</td>
                          <td className="tabular model-td-right">{xrayVal.by_severity[sev].mean ?? '—'}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="muted chart-caption">{xrayVal.note}</p>
                </>
              )
            )}
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
