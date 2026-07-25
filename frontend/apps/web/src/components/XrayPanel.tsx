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
      </div>

      {xray.flags.length === 0 && (
        <p className="muted xray-empty">No structural outliers — diversified, well-capitalized.</p>
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
                <div className="xray-pctile-fill" style={{ width: `${f.peer_percentile}%` }} />
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
