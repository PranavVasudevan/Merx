import { useEffect, useState } from 'react';
import { api } from '../api';
import type { MaProFormaResult } from '../types';
import './StressPanel.css';
import './ProFormaPanel.css';

function fmtB(v: number): string {
  return `$${(v / 1e9).toFixed(2)}B`;
}

export function ProFormaPanel({ targetCert, acquirerCert }: { targetCert: number; acquirerCert: number }) {
  const [result, setResult] = useState<MaProFormaResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [premium, setPremium] = useState(20);

  useEffect(() => {
    api.maProForma(targetCert, acquirerCert, { premiumToTbvPct: premium })
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => { setResult(null); setError(e.message); });
  }, [targetCert, acquirerCert, premium]);

  if (error) return <p className="app-banner-error">{error}</p>;
  if (!result) return <p className="muted">Loading pro-forma…</p>;

  const crossing = result.county_impact.counties.filter((c) => c.crosses_threshold);

  return (
    <div className="pro-forma-panel">
      <p className="muted chart-caption stress-lab-cmp-caption">
        {result.acquirer.name} acquires {result.target.name}. {result.note}
      </p>
      <label className="stress-slider pro-forma-premium">
        <span>Premium to tangible book value <b className="tabular">{premium}%</b></span>
        <input type="range" min={0} max={100} step={5} value={premium}
          onChange={(e) => setPremium(Number(e.target.value))} />
      </label>
      <div className="stress-lab-cmp-grid pro-forma-grid">
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">Combined assets</div>
          <div className="stress-lab-cmp-loss tabular">{fmtB(result.combined.combined_assets)}</div>
        </div>
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">Goodwill created</div>
          <div className="stress-lab-cmp-loss tabular">{fmtB(result.combined.goodwill_created)}</div>
        </div>
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">Combined CET1 ratio</div>
          <div className="stress-lab-cmp-loss tabular">{result.combined.combined_cet1_ratio_pct ?? '—'}%</div>
        </div>
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">TBV dilution (aggregate)</div>
          <div className="stress-lab-cmp-loss tabular">{result.combined.tangible_book_value_dilution_pct ?? '—'}%</div>
        </div>
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">Earn-back (aggregate)</div>
          <div className="stress-lab-cmp-loss tabular">
            {result.combined.earn_back_years === null ? 'n/a' : `${result.combined.earn_back_years}y`}
          </div>
        </div>
      </div>

      <h3 className="pro-forma-subhead">County concentration impact</h3>
      <p className="muted chart-caption">
        {result.county_impact.counties_affected} counties where both banks currently hold deposits
        (SOD {result.county_impact.sod_vintage?.sod_year ?? 'unlanded'}) —{' '}
        {result.county_impact.counties_crossing_threshold} would cross the Fed's{' '}
        {result.county_impact.hhi_concentrated_threshold} HHI screening threshold.
      </p>
      {crossing.length > 0 && (
        <div className="pro-forma-county-list">
          {crossing.map((c) => (
            <div className="pro-forma-county-row" key={c.fips}>
              <span>{c.name ?? c.fips}, {c.state}</span>
              <span className="tabular muted">{c.hhi_before?.toFixed(0)} → </span>
              <span className="tabular stress-bad-text">{c.hhi_after?.toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
