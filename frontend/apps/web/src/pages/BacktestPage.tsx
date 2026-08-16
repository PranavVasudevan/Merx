import { useEffect, useState } from 'react';
import { api } from '../api';
import type { BacktestOutcome, BacktestResults } from '../types';
import './BacktestPage.css';

const SIGNAL_LABELS: Record<string, string> = {
  xray_high_risk: 'X-Ray high/elevated risk',
  deposit_flight_top_decile: 'Deposit-flight top decile',
  filing_diff_flagged: 'Filing-diff any flag',
};

function LiftBar({ outcome }: { outcome: BacktestOutcome }) {
  if (outcome.base_n === 0) {
    return <span className="muted backtest-nodata">not computed by this harness</span>;
  }
  const lift = outcome.lift;
  const significant = lift !== null && (outcome.flagged_hit_rate.lo ?? 0) > (outcome.base_hit_rate.hi ?? 1);
  return (
    <div className="backtest-outcome-row">
      <span className="backtest-outcome-label">{outcome.label}</span>
      <span className="tabular backtest-outcome-rate">
        {outcome.flagged_hit_rate.point !== null ? `${(outcome.flagged_hit_rate.point * 100).toFixed(1)}%` : '—'}
        <span className="muted"> (n={outcome.flagged_n})</span>
      </span>
      <span className="muted tabular backtest-outcome-vs">vs</span>
      <span className="tabular muted backtest-outcome-rate">
        {outcome.base_hit_rate.point !== null ? `${(outcome.base_hit_rate.point * 100).toFixed(1)}%` : '—'}
        <span className="muted"> (n={outcome.base_n})</span>
      </span>
      <span className={`backtest-lift-chip ${significant ? 'backtest-lift-sig' : ''}`}>
        lift {lift !== null ? lift.toFixed(2) : '—'}×
      </span>
    </div>
  );
}

export function BacktestPage() {
  const [result, setResult] = useState<BacktestResults | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.backtestResults()
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="backtest-page">
      <div className="panel">
        <h2>Backtest (C14)</h2>
        <p className="muted backtest-subtitle">
          Nothing in this product had ever been backtested before this page: not the
          deposit-flight score, not the X-Ray flags, not the filing-diff flags. For each
          signal, did banks it flagged subsequently show deposit outflows, capital
          deterioration, credit deterioration, or failure/exit from the population — more
          often than the rest of the population? Pooled across every landed quarter
          transition. A null result (lift near 1×) is reported here exactly like a real one.
        </p>
        {error && (
          <p className="app-banner-error">
            {error.includes('not run yet') ? 'Not run yet — run scripts/backtest.ps1.' : error}
          </p>
        )}
      </div>

      {result && (
        <>
          <div className="panel">
            <div className="model-stats">
              <div className="model-stat"><span className="muted">Quarters covered</span><span className="tabular">{result.quarters_covered.length}</span></div>
              <div className="model-stat"><span className="muted">Transitions pooled</span><span className="tabular">{result.n_transitions}</span></div>
              <div className="model-stat"><span className="muted">Horizon</span><span className="tabular">{result.horizon_quarters}q</span></div>
            </div>
            <p className="muted chart-caption">{result.note}</p>
          </div>

          {Object.entries(result.results).map(([signal, outcomes]) => (
            <div className="panel" key={signal}>
              <h2>{SIGNAL_LABELS[signal] ?? signal}</h2>
              <p className="muted chart-caption">{result.signal_definitions[signal]}</p>
              <div className="backtest-outcomes">
                {Object.entries(outcomes).map(([key, o]) => <LiftBar key={key} outcome={o} />)}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
