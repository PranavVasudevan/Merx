import { useState } from 'react';
import { motion } from 'motion/react';
import { ProFormaPanel } from './ProFormaPanel';
import type { MaFitResult } from '../types';
import './MaFitPanel.css';

export function MaFitPanel({ result, cert }: { result: MaFitResult; cert: number }) {
  const max = Math.max(...result.candidates.map((c) => c.fit_score), 0.01);
  const [selected, setSelected] = useState<number | null>(null);
  return (
    <div className="panel">
      <h2>Feature 15 · M&amp;A Fit — top partner candidates</h2>
      <p className="muted mafit-subtitle">
        Geo column: real branch-network overlap from landed SOD footprints
        (as of {result.sod_vintage?.sod_year ?? 'an unlanded vintage'}) —
        market-count overlap, with deposit-weighted overlap in parentheses.
        Click a candidate for a pro-forma (C9).
      </p>
      <div className="mafit-list">
        {result.candidates.map((c, i) => (
          <button
            className="mafit-row mafit-row-clickable"
            key={c.cert_number}
            title={c.rationale}
            onClick={() => setSelected(selected === c.cert_number ? null : c.cert_number)}
          >
            <span className="mafit-rank muted">{i + 1}</span>
            <span className="mafit-name">{c.name}</span>
            <div className="mafit-bar-track">
              <motion.div
                className="mafit-bar-fill"
                initial={{ width: 0 }}
                animate={{ width: `${(c.fit_score / max) * 100}%` }}
                transition={{ duration: 0.6, delay: i * 0.03, ease: [0.85, 0, 0.15, 1] }}
              />
            </div>
            {c.geo_overlap !== null && (
              <span className="mafit-geo tabular" title="Branch-network overlap (real SOD footprints, deposit-weighted in parentheses)">
                {(c.geo_overlap * 100).toFixed(0)}%
                {c.geo_overlap_deposit_weighted !== null && ` (${(c.geo_overlap_deposit_weighted * 100).toFixed(0)}%)`}
              </span>
            )}
            <span className="mafit-score tabular">{c.fit_score.toFixed(2)}</span>
          </button>
        ))}
      </div>
      {result.candidates[0] && (
        <p className="secondary mafit-rationale">
          <b>{result.candidates[0].name}:</b> {result.candidates[0].rationale}
        </p>
      )}
      {selected !== null && <ProFormaPanel targetCert={cert} acquirerCert={selected} />}
    </div>
  );
}
