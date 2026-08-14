import { useEffect, useState } from 'react';
import { api } from '../api';
import type { IrrbbResult, IrrbbScenario } from '../types';
import './StressPanel.css';

function fmtB(v: number): string {
  return `${v < 0 ? '−' : ''}$${(Math.abs(v) / 1e6).toFixed(1)}M`;
}

function ScenarioCard({ label, s }: { label: string; s: IrrbbScenario }) {
  return (
    <div className="stress-lab-cmp-col">
      <div className="stress-lab-cmp-label">{label}</div>
      <div className="stress-lab-cmp-loss tabular" style={{ color: s.eve_delta < 0 ? 'var(--status-critical)' : 'var(--status-good)' }}>
        ΔEVE {fmtB(s.eve_delta)}
      </div>
      <div className="muted tabular">
        {s.eve_delta_pct_of_equity === null ? 'n/a % of equity' : `${s.eve_delta_pct_of_equity > 0 ? '+' : ''}${s.eve_delta_pct_of_equity}% of equity`}
      </div>
      <div className="muted tabular" style={{ color: s.nii_delta_12mo < 0 ? 'var(--status-critical)' : 'var(--status-good)' }}>
        Δ12mo NII {fmtB(s.nii_delta_12mo)}
      </div>
    </div>
  );
}

export function IrrbbPanel({ cert }: { cert: number }) {
  const [result, setResult] = useState<IrrbbResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.irrbb(cert)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [cert]);

  if (error) return null; // same quiet-skip convention as other optional bank-page panels
  if (!result) return null;

  return (
    <div className="panel">
      <h2>Interest-rate risk in the banking book</h2>
      <p className="muted chart-caption stress-lab-cmp-caption">
        Economic value of equity (EVE) and 12-month net-interest-income (NII) sensitivity — a
        parallel rate shift and a non-parallel steepener. {result.bucket_coarseness}
      </p>
      <div className="stress-lab-cmp-grid">
        <ScenarioCard label={`Parallel +${result.parallel.shock_bps}bps`} s={result.parallel} />
        <ScenarioCard
          label={`Steepener (${result.non_parallel.short_bps}bps short / +${result.non_parallel.long_bps}bps long)`}
          s={result.non_parallel}
        />
      </div>
    </div>
  );
}
