import type { MaFitResult } from '../types';
import './MaFitPanel.css';

export function MaFitPanel({ result }: { result: MaFitResult }) {
  const max = Math.max(...result.candidates.map((c) => c.fit_score), 0.01);
  return (
    <div className="panel">
      <h2>Feature 15 · M&amp;A Fit — top partner candidates</h2>
      <div className="mafit-list">
        {result.candidates.map((c, i) => (
          <div className="mafit-row" key={c.cert_number} title={c.rationale}>
            <span className="mafit-rank muted">{i + 1}</span>
            <span className="mafit-name">{c.name}</span>
            <div className="mafit-bar-track">
              <div className="mafit-bar-fill" style={{ width: `${(c.fit_score / max) * 100}%` }} />
            </div>
            <span className="mafit-score tabular">{c.fit_score.toFixed(2)}</span>
          </div>
        ))}
      </div>
      {result.candidates[0] && (
        <p className="secondary mafit-rationale">
          <b>{result.candidates[0].name}:</b> {result.candidates[0].rationale}
        </p>
      )}
    </div>
  );
}
