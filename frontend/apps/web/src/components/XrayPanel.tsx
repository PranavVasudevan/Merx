import { motion } from 'motion/react';
import type { XrayResult } from '../types';
import './XrayPanel.css';

const SEV_LABEL: Record<string, string> = { low: 'Low', elevated: 'Elevated', high: 'High' };

export function XrayPanel({ xray }: { xray: XrayResult }) {
  return (
    <div className="panel">
      <h2>Feature 11 · Balance-Sheet X-Ray</h2>
      <div className="xray-head">
        <span className={`chip chip-${xray.overall_risk}`}>{SEV_LABEL[xray.overall_risk]} risk</span>
        <span className="muted">{xray.flag_count} flag{xray.flag_count === 1 ? '' : 's'} vs supervisory thresholds</span>
        {!xray.fully_assessed && (
          <span className="muted xray-coverage-chip">
            {xray.rules_evaluated}/{xray.rules_total} checks run
          </span>
        )}
      </div>

      {!xray.fully_assessed && (
        <p className="xray-coverage-note">
          Only <strong>{xray.rules_evaluated} of {xray.rules_total}</strong> supervisory checks could
          run for this bank — the rest have no disclosed data behind them
          ({xray.rules_not_evaluated.slice(0, 3).map((r) => r.replace(/_/g, ' ')).join(', ')}
          {xray.rules_not_evaluated.length > 3 && `, +${xray.rules_not_evaluated.length - 3} more`}).
          A low flag count here means <em>less was checked</em>, not necessarily a safer bank.
        </p>
      )}

      {xray.flags.length === 0 && (
        <p className="muted xray-empty">
          {xray.fully_assessed
            ? 'No structural outliers — diversified, well-capitalized.'
            : 'No outliers among the checks that could run — see the coverage note above.'}
        </p>
      )}

      <div className="xray-flags">
        {xray.flags.map((f) => (
          <div className="xray-flag" key={f.metric}>
            <div className="xray-flag-top">
              <span className={`chip chip-${f.severity}`}>{SEV_LABEL[f.severity]}</span>
              <span className="xray-factor">{f.factor}</span>
              <span className="xray-value tabular">{f.value}</span>
            </div>
            {f.peer_percentile !== undefined && (
              <div className="xray-pctile-track">
                <motion.div
                  className="xray-pctile-fill"
                  initial={{ width: 0 }}
                  animate={{ width: `${f.peer_percentile}%` }}
                  transition={{ duration: 0.7, ease: [0.85, 0, 0.15, 1] }}
                />
                <span className="xray-pctile-label muted tabular">{f.peer_percentile}th percentile vs peers</span>
              </div>
            )}
            <p className="xray-note secondary">{f.note}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
