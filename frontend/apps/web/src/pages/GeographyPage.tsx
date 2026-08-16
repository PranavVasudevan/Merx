import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { BranchMapCanvas } from '../components/BranchMapCanvas';
import { US_STATES } from '../usStates';
import type { BranchMapResult } from '../types';
import './GeographyPage.css';

// B7: FDIC's Summary of Deposits is landed annually — every branch shown here
// can be up to ~18 months stale relative to a bank's quarterly financials.
function fmtSodVintage(v: BranchMapResult['sod_vintage'] | undefined): string {
  if (!v || v.sod_year == null) return 'not landed';
  const landed = v.fetched_at ? new Date(v.fetched_at).toLocaleDateString() : 'unknown date';
  return `SOD ${v.sod_year} (landed ${landed})`;
}

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
          Every branch across the full FDIC-insured universe (~4,431 banks) —
          real coordinates and real state/county boundaries (Census TopoJSON via
          us-atlas), rendered on a canvas Albers-USA projection — Alaska and Hawaii
          included via their standard insets. No map tiles, no network calls.
          Scroll to zoom, drag to pan; at national zoom, branches are collapsed
          into county-level bubbles (sized by branch count, colored by total
          deposits) rather than 76k overlapping dots — zoom in for individual
          branches. US-only: no public branch-level dataset exists for EU banks the
          way FDIC's Summary of Deposits does — for the EU angle, see the{' '}
          <Link to="/treemap">population treemap</Link>'s "group by country" view.
        </p>
        <select className="geography-select" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All states</option>
          {US_STATES.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </select>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {result && (
        <div className="panel">
          <div className="geography-stats">
            <div className="geography-stat"><span className="muted">Branches represented</span><span className="tabular">{result.branch_count.toLocaleString()}</span></div>
            <div className="geography-stat">
              <span className="muted">Banks represented</span>
              <span className="tabular">
                {result.aggregated ? 'select a state' : Object.keys(result.bank_names).length.toLocaleString()}
              </span>
            </div>
            <div className="geography-stat"><span className="muted">Not shown (territories + bad coords)</span><span className="tabular">{result.excluded_non_contiguous.toLocaleString()}</span></div>
            <div className="geography-stat"><span className="muted">Branch data as of</span><span className="tabular">{fmtSodVintage(result.sod_vintage)}</span></div>
          </div>
          {result.aggregated && (
            <p className="muted geography-subtitle">
              Showing county-level aggregates ({result.cells.length.toLocaleString()} counties/cells) —
              select a state above for individual branch points.
            </p>
          )}
          {loading ? (
            <div className="geography-loading muted">Loading…</div>
          ) : (
            <BranchMapCanvas branches={result.branches} cells={result.cells} bankNames={result.bank_names} height={520} />
          )}
        </div>
      )}
    </div>
  );
}
