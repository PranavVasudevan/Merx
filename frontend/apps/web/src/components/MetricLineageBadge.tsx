import { useState } from 'react';
import { api } from '../api';
import { useQuarter } from '../QuarterContext';
import type { MetricLineageResult } from '../types';
import './MetricLineageBadge.css';

// G9 — "how is this computed?" affordance: click reveals the exact gold.py
// function, Silver/FDIC source field(s) and values, and the landing Bronze
// partition's path/checksum/fetch time behind ONE metric. Deliberately only
// wired to the handful of tiles whose metric is in the bounded
// banklens_mcp.data._METRIC_LINEAGE set — see KpiTiles.tsx for which.
export function MetricLineageBadge({ cert, metric }: { cert: number; metric: string }) {
  const { quarter } = useQuarter();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<MetricLineageResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function toggle() {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (data || loading) return;
    setLoading(true);
    api.metricLineage(cert, metric, quarter)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  return (
    <span className="lineage-badge-wrap">
      <button
        type="button"
        className="lineage-badge"
        aria-label="How is this computed?"
        title="How is this computed?"
        onClick={toggle}
      >
        ⓘ
      </button>
      {open && (
        <div className="lineage-popover panel">
          {loading && <div className="muted">Loading lineage…</div>}
          {error && <div className="lineage-error">{error}</div>}
          {data && (
            <>
              <div className="lineage-formula tabular">{data.formula}</div>
              <div className="lineage-row muted">{data.gold_function}</div>
              <table className="lineage-fields">
                <tbody>
                  {data.source_fields.map((f) => (
                    <tr key={f.silver_field}>
                      <td className="muted">{f.silver_field} ({f.fdic_field})</td>
                      <td className="tabular">{f.value ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.provenance_available ? (
                <div className="lineage-source">
                  <div className="muted">Bronze partition</div>
                  <div className="tabular lineage-mono">{data.bronze_partition}</div>
                  <div className="muted">Checksum (sha256)</div>
                  <div className="tabular lineage-mono">{data.checksum}</div>
                  <div className="muted">Fetched</div>
                  <div className="tabular">{data.fetched_at}</div>
                  {data.source_url && (
                    <a href={data.source_url} target="_blank" rel="noreferrer" className="lineage-link">
                      Source URL ↗
                    </a>
                  )}
                </div>
              ) : (
                <div className="lineage-error">
                  No Bronze provenance recorded for this row (a disclosed gap, not fabricated).
                </div>
              )}
            </>
          )}
        </div>
      )}
    </span>
  );
}
