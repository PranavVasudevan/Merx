import { Fragment, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { US_STATES } from '../usStates';
import type { CountyConcentrationResult } from '../types';
import { ExportCsvButton } from '../components/ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import './MarketSharePage.css';

type CountyRow = CountyConcentrationResult['counties'][number];

const COUNTY_CSV_COLUMNS: CsvColumn<CountyRow>[] = [
  { key: 'name', label: 'County', value: (c) => `${c.name}, ${c.state}`, source: 'fdic' },
  { key: 'branch_count', label: 'Branches', value: (c) => c.branch_count, source: 'fdic' },
  { key: 'total_deposits', label: 'Total deposits ($)', value: (c) => c.total_deposits, source: 'fdic' },
  { key: 'hhi', label: 'HHI', value: (c) => c.hhi ?? '', source: 'derived' },
  { key: 'concentrated', label: 'Concentrated (HHI≥1800)', value: (c) => (c.concentrated ? 'yes' : 'no'), source: 'derived' },
  { key: 'top_bank', label: 'Top bank', value: (c) => c.shares[0]?.name ?? '', source: 'fdic' },
  { key: 'top_bank_share_pct', label: 'Top bank share %', value: (c) => c.shares[0]?.share_pct ?? '', source: 'fdic' },
];

function fmtDeposits(v: number): string {
  return v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${(v / 1e6).toFixed(1)}M`;
}

// B7: FDIC's Summary of Deposits is landed annually, so every branch-derived
// figure on this page can be up to ~18 months stale relative to the quarterly
// financials shown elsewhere — surfaced structurally, not left implicit.
function fmtSodVintage(v: { sod_year: number | null; fetched_at: string | null } | undefined): string {
  if (!v || v.sod_year == null) return 'not landed';
  const landed = v.fetched_at ? new Date(v.fetched_at).toLocaleDateString() : 'unknown date';
  return `SOD ${v.sod_year} (landed ${landed})`;
}

export function MarketSharePage() {
  const [state, setState] = useState('');
  const [result, setResult] = useState<CountyConcentrationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    api.countyConcentration({ state: state || undefined, top_n: 150 })
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [state]);

  return (
    <div className="market-share-page">
      <div className="panel">
        <h2>Deposit market concentration</h2>
        <p className="muted market-share-subtitle">
          Feature 15 — real county-level deposit HHI (Herfindahl-Hirschman Index)
          over the FULL FDIC-insured universe (~4,431 banks, $18.1T in branch
          deposits) — county (FIPS state+county) is the market definition the
          Federal Reserve and DOJ actually use for bank-merger competitive review.
        </p>
        <select className="market-share-select" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All states</option>
          {US_STATES.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </select>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {result && (
        <div className="panel">
          <div className="market-share-stats">
            <div className="market-share-stat"><span className="muted">Counties</span><span className="tabular">{result.county_count.toLocaleString()}</span></div>
            <div className="market-share-stat"><span className="muted">Concentrated (HHI ≥ {result.hhi_concentrated_threshold})</span><span className="tabular">{result.concentrated_count.toLocaleString()}</span></div>
            <div className="market-share-stat"><span className="muted">Share</span><span className="tabular">{((result.concentrated_count / result.county_count) * 100).toFixed(0)}%</span></div>
            <div className="market-share-stat"><span className="muted">Branch data as of</span><span className="tabular">{fmtSodVintage(result.sod_vintage)}</span></div>
          </div>
          <p className="muted chart-caption market-share-caveat">
            HHI ≥ 1,800 is the Federal Reserve's own Bank Merger Competitive Review
            screening threshold — sorted most-concentrated first. Many single-branch
            rural counties are legitimately near-monopoly markets by this measure,
            not a data artifact.
          </p>

          <div className="market-share-export-row">
            <ExportCsvButton
              filename="banklens-county-concentration.csv"
              columns={COUNTY_CSV_COLUMNS}
              rows={result.counties}
              meta={{ vintage: fmtSodVintage(result.sod_vintage), sourceLabel: 'FDIC Summary of Deposits' }}
            />
          </div>
          <div className="market-share-table-wrap">
            <table className="market-share-table">
              <thead>
                <tr>
                  <th className="ms-th">County</th>
                  <th className="ms-th ms-th-right">Branches</th>
                  <th className="ms-th ms-th-right">Deposits</th>
                  <th className="ms-th ms-th-right">HHI</th>
                  <th className="ms-th">Top bank</th>
                </tr>
              </thead>
              <tbody>
                {result.counties.map((c) => (
                  <Fragment key={c.fips}>
                    <tr
                      className={`ms-row${c.concentrated ? ' ms-row-concentrated' : ''}`}
                      onClick={() => setExpanded(expanded === c.fips ? null : c.fips)}
                    >
                      <td className="ms-td-name">{c.name}, {c.state}</td>
                      <td className="tabular ms-td-right">{c.branch_count}</td>
                      <td className="tabular ms-td-right">{fmtDeposits(c.total_deposits)}</td>
                      <td className="tabular ms-td-right ms-hhi">{c.hhi?.toFixed(0)}</td>
                      <td className="ms-td-top">
                        {c.shares[0] && (
                          <>
                            <Link to={`/bank/${c.shares[0].cert}`} onClick={(e) => e.stopPropagation()}>{c.shares[0].name}</Link>
                            <span className="muted"> ({c.shares[0].share_pct.toFixed(0)}%)</span>
                          </>
                        )}
                      </td>
                    </tr>
                    {expanded === c.fips && (
                      <tr className="ms-expand-row">
                        <td colSpan={5}>
                          <div className="ms-shares">
                            {c.shares.map((s) => (
                              <Link className="ms-share-row" key={s.cert} to={`/bank/${s.cert}`}>
                                <span className="ms-share-name">{s.name}</span>
                                <span className="tabular muted">{fmtDeposits(s.deposits)}</span>
                                <span className="tabular ms-share-pct">{s.share_pct.toFixed(1)}%</span>
                              </Link>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
