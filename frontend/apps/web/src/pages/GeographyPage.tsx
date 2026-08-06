import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { BranchMapCanvas } from '../components/BranchMapCanvas';
import { CONTIGUOUS_STATES } from '../usStates';
import type { BranchMapResult } from '../types';
import './GeographyPage.css';

export function GeographyPage() {
  const [state, setState] = useState('');
  const [result, setResult] = useState<BranchMapResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api.branchMap(state || undefined)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [state]);

  return (
    <div className="geography-page">
      <div className="panel">
        <h2>Branch geography</h2>
        <p className="muted geography-subtitle">
          Every branch across the full FDIC-insured universe (~4,431 banks, not just
          the $1B–$250B analytical slice) — real coordinates, projected with a
          hand-rolled Albers Equal-Area Conic (no map tiles, no network calls).
          Overlapping dots compound into real density, darkest where branches
          cluster. US-only: no public branch-level dataset exists for EU banks the
          way FDIC's Summary of Deposits does — for the EU angle, see the{' '}
          <Link to="/treemap">population treemap</Link>'s "group by country" view.
        </p>
        <select className="geography-select" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All contiguous states</option>
          {CONTIGUOUS_STATES.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </select>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {result && (
        <div className="panel">
          <div className="geography-stats">
            <div className="geography-stat"><span className="muted">Branches shown</span><span className="tabular">{result.branch_count.toLocaleString()}</span></div>
            <div className="geography-stat"><span className="muted">Banks represented</span><span className="tabular">{Object.keys(result.bank_names).length.toLocaleString()}</span></div>
            <div className="geography-stat"><span className="muted">Not shown (AK/HI/territories)</span><span className="tabular">{result.excluded_non_contiguous.toLocaleString()}</span></div>
          </div>
          {loading ? (
            <div className="geography-loading muted">Loading…</div>
          ) : (
            <BranchMapCanvas branches={result.branches} bankNames={result.bank_names} height={520} />
          )}
        </div>
      )}
    </div>
  );
}
