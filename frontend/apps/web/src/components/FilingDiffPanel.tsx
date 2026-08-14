import { Link } from 'react-router-dom';
import type { FilingDiffResult } from '../types';
import './FilingDiffPanel.css';

export function FilingDiffPanel({ diff, cert }: { diff: FilingDiffResult; cert: number }) {
  return (
    <div className="panel">
      <div className="fdiff-head">
        <h2>Feature 12 · Filing Diff — {diff.from_quarter} → {diff.to_quarter}</h2>
        <Link className="fdiff-full-link" to={`/filing-diff?cert=${cert}`}>Full side-by-side →</Link>
      </div>
      {diff.flags.length === 0 ? (
        <p className="muted">No unusual line-item shifts — steady vs this bank's own norm.</p>
      ) : (
        <div className="fdiff-list">
          {diff.flags.map((f) => (
            <div className="fdiff-row" key={f.metric}>
              <span className={`fdiff-arrow ${f.direction === 'up' ? 'fdiff-up' : 'fdiff-down'}`}>
                {f.direction === 'up' ? '▲' : '▼'}
              </span>
              <span className="fdiff-item">{f.item}</span>
              <span className="tabular fdiff-change">
                {f.change > 0 ? '+' : ''}{f.change}{f.unit}
              </span>
              <span className="muted tabular fdiff-z">{f.z !== null ? `z=${f.z.toFixed(1)} (n=${f.n})` : ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
