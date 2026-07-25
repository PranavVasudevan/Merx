import type { FilingDiffResult } from '../types';
import './FilingDiffPanel.css';

export function FilingDiffPanel({ diff }: { diff: FilingDiffResult }) {
  return (
    <div className="panel">
      <h2>Feature 12 · Filing Diff — {diff.from_quarter} → {diff.to_quarter}</h2>
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
              <span className="muted tabular fdiff-z">{f.z !== null ? `z=${f.z.toFixed(1)}` : ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
