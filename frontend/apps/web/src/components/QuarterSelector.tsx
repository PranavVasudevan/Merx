import { useLocation } from 'react-router-dom';
import { fmtQuarter, useQuarter } from '../QuarterContext';
import './QuarterSelector.css';

// D3 — pages backed by annual Summary of Deposits data (not a per-quarter
// financial snapshot) genuinely cannot be time-shifted by this selector; it
// disables with an explanation rather than silently ignoring the selection.
const TIME_INVARIANT_PATHS: Record<string, string> = {
  '/geography': 'Branch map uses FDIC Summary of Deposits, landed annually — not quarter-scoped.',
  '/market-share': 'County concentration uses FDIC Summary of Deposits, landed annually — not quarter-scoped.',
  '/network': 'The M&A network uses the latest landed quarter only.',
  '/clusters': 'Cluster diagnostics describe the current k-selection model, not a point-in-time snapshot.',
  '/model': 'The model card describes the currently-trained model, not a point-in-time snapshot.',
};

export function QuarterSelector() {
  const { quarter, quarters, latest, setQuarter, isLatest } = useQuarter();
  const location = useLocation();
  const disabledReason = TIME_INVARIANT_PATHS[location.pathname];

  if (quarters.length === 0) return null;

  return (
    <div className="quarter-selector" title={disabledReason ?? 'Select which landed quarter to view'}>
      <span className="quarter-selector-label">Quarter</span>
      <select
        className="quarter-selector-select"
        value={quarter ?? latest ?? ''}
        disabled={!!disabledReason}
        onChange={(e) => setQuarter(e.target.value === latest ? null : e.target.value)}
      >
        {quarters.map((q) => (
          <option key={q} value={q}>{fmtQuarter(q)}{q === latest ? ' (latest)' : ''}</option>
        ))}
      </select>
      {!isLatest && !disabledReason && <span className="quarter-selector-badge">historical</span>}
      {disabledReason && <span className="quarter-selector-disabled-note">{disabledReason}</span>}
    </div>
  );
}
