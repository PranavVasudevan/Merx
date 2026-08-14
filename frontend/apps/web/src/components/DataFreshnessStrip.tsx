import { useEffect, useState } from 'react';
import { api } from '../api';
import type { DataFreshnessResult } from '../types';
import './DataFreshnessStrip.css';

// B10 (docs/audit/04-remediation-prompts.md): a compact strip so a user
// always knows how current the data behind the page is, sourced from the
// SAME provenance every Bronze landing already writes — not a hand-maintained
// "last updated" note that can silently drift from what was actually landed.
const SOURCE_LABELS: Record<string, string> = {
  fdic_bankfind: 'FDIC financials',
  fdic_sod: 'FDIC branches (SOD)',
  fdic_failures: 'FDIC failures',
  sec_edgar: 'SEC filings',
  fed_nic: 'Fed NIC (holding cos.)',
  fred: 'FRED macro',
  market_ohlc: 'Market prices',
  eba_transparency: 'EBA (EU banks)',
};

function daysAgo(iso: string | null): string {
  if (!iso) return '';
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return '1 day ago';
  return `${days} days ago`;
}

export function DataFreshnessStrip() {
  const [result, setResult] = useState<DataFreshnessResult | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.dataFreshness().then(setResult).catch(() => setResult(null));
  }, []);

  if (!result) return null;
  const entries = Object.entries(result.sources);
  const landedCount = entries.filter(([, s]) => s.landed).length;

  return (
    <div className="freshness-strip">
      <button
        className="freshness-toggle"
        onClick={() => setOpen((v) => !v)}
        title="Per-source data vintage"
      >
        <span className="freshness-dot" />
        Data freshness ({landedCount}/{entries.length} sources landed)
      </button>
      {open && (
        <div className="freshness-panel">
          {entries.map(([id, s]) => (
            <div className="freshness-row" key={id}>
              <span className="freshness-source">{SOURCE_LABELS[id] ?? id}</span>
              {s.landed ? (
                <>
                  <span className="freshness-time tabular">{daysAgo(s.fetched_at)}</span>
                  {s.record_count !== null && (
                    <span className="muted freshness-count tabular">
                      {s.record_count.toLocaleString()} rows
                    </span>
                  )}
                </>
              ) : (
                <span className="muted freshness-notlanded">not landed</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
