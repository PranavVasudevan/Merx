import { Link } from 'react-router-dom';
import type { HoldingCompanyResult } from '../types';
import './HoldingCompanyPanel.css';

function fmtUsd(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${(v / 1e6).toFixed(1)}M`;
}

function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${v.toFixed(2)}%`;
}

/** D4 — holding-company roll-up: consolidated Y-9C financials, sibling
 * charters under the same group, and which figures are charter-level vs.
 * consolidated. Depends on B4 (Fed NIC connector) actually being landed. */
export function HoldingCompanyPanel({ result }: { result: HoldingCompanyResult }) {
  if (!result.has_holding_company) {
    return (
      <div className="panel">
        <h2>Holding company</h2>
        <p className="muted">{result.note}</p>
      </div>
    );
  }

  const siblings = result.sibling_charters ?? [];

  return (
    <div className="panel">
      <h2>Holding company{result.holding_company?.name ? ` — ${result.holding_company.name}` : ''}</h2>
      {!result.holding_company && (
        <p className="muted">{result.note}</p>
      )}
      {result.holding_company && (
        <>
          <p className="muted hc-caption">
            Consolidated FR Y-9C financials (RSSD {result.holding_company_rssd}), {result.holding_company.period} —
            distinct from this charter's own FDIC Call Report figures below.
          </p>
          <div className="hc-grid">
            <div className="hc-col">
              <div className="hc-col-label">This charter</div>
              <div className="hc-row"><span className="muted">Total assets</span><span className="tabular">{fmtUsd(result.charter_level?.total_assets)}</span></div>
              <div className="hc-row"><span className="muted">CET1 ratio</span><span className="tabular">{fmtPct(result.charter_level?.cet1_ratio)}</span></div>
              <div className="hc-row"><span className="muted">Leverage ratio</span><span className="tabular">{fmtPct(result.charter_level?.leverage_ratio)}</span></div>
            </div>
            <div className="hc-col">
              <div className="hc-col-label">Consolidated group</div>
              <div className="hc-row"><span className="muted">Total assets</span><span className="tabular">{fmtUsd(result.holding_company.total_assets)}</span></div>
              <div className="hc-row"><span className="muted">CET1 ratio</span><span className="tabular">{fmtPct(result.holding_company.cet1_ratio)}</span></div>
              <div className="hc-row"><span className="muted">Tier 1 leverage ratio</span><span className="tabular">{fmtPct(result.holding_company.tier1_leverage_ratio)}</span></div>
              <div className="hc-row"><span className="muted">Net income</span><span className="tabular">{fmtUsd(result.holding_company.net_income)}</span></div>
              <div className="hc-row"><span className="muted">Goodwill</span><span className="tabular">{fmtUsd(result.holding_company.goodwill)}</span></div>
            </div>
          </div>
        </>
      )}
      {siblings.length > 0 && (
        <div className="hc-siblings">
          <p className="muted hc-siblings-label">
            {siblings.length} other FDIC charter{siblings.length === 1 ? '' : 's'} under this same holding company:
          </p>
          <ul className="hc-siblings-list">
            {siblings.map((s) => (
              <li key={s.cert}>
                <Link to={`/bank/${s.cert}`}>{s.name}</Link>
                <span className="muted"> — {fmtUsd(s.total_assets)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {siblings.length === 0 && result.holding_company_rssd && (
        <p className="muted hc-single-charter">Single-charter holding company — no sibling FDIC banks under this RSSD.</p>
      )}
    </div>
  );
}
