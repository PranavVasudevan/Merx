import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { US_STATES } from '../usStates';
import { sequentialRamp } from '../colors';
import { CountyChoropleth } from '../components/CountyChoropleth';
import { BankSearch } from '../components/BankSearch';
import type { CountyConcentrationResult, MaProFormaResult } from '../types';
import { ExportCsvButton } from '../components/ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import '../components/ProFormaPanel.css';
import './MarketSharePage.css';

type CountyRow = CountyConcentrationResult['counties'][number];

// The table/CSV export stay capped at the top-150-most-concentrated rows this page
// has always shown (unchanged behavior). The choropleth needs the FULL county set to
// color the whole map, not just the most-concentrated slice, so the fetch below asks
// for more than the ~3,142 counties that exist nationally and the two views slice
// what they need from one shared response — one request, not two.
const TABLE_TOP_N = 150;
const MAP_TOP_N = 3200;

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
  const [selectedFips, setSelectedFips] = useState<string | null>(null);

  // E8 — proposed acquirer/target pair for the choropleth's before/after toggle.
  // Scoped to just feeding the map (no full M&A workflow here — see ProFormaPanel /
  // MaFitPanel on the bank page for the deal-economics calculator this reuses).
  const [acquirerCert, setAcquirerCert] = useState<number | null>(null);
  const [acquirerName, setAcquirerName] = useState('');
  const [targetCert, setTargetCert] = useState<number | null>(null);
  const [targetName, setTargetName] = useState('');
  const [proForma, setProForma] = useState<MaProFormaResult | null>(null);
  const [proFormaError, setProFormaError] = useState<string | null>(null);
  const [proFormaLoading, setProFormaLoading] = useState(false);
  const [beforeAfter, setBeforeAfter] = useState<'before' | 'after'>('after');

  useEffect(() => {
    api.countyConcentration({ state: state || undefined, top_n: MAP_TOP_N })
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
    setSelectedFips(null);
  }, [state]);

  const tableCounties = useMemo(() => result?.counties.slice(0, TABLE_TOP_N) ?? [], [result]);

  const countyByFips = useMemo(
    () => new Map((result?.counties ?? []).map((c) => [c.fips, c])),
    [result],
  );

  const baseValues = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of result?.counties ?? []) if (c.hhi != null) m.set(c.fips, c.hhi);
    return m;
  }, [result]);
  const baseHighlighted = useMemo(
    () => new Set((result?.counties ?? []).filter((c) => c.concentrated).map((c) => c.fips)),
    [result],
  );
  const baseColorMax = useMemo(
    () => Math.max(1, ...(result?.counties ?? []).map((c) => c.hhi ?? 0)),
    [result],
  );

  const proFormaValues = useMemo(() => {
    if (!proForma) return null;
    const m = new Map<string, number>();
    for (const c of proForma.county_impact.counties) {
      const v = beforeAfter === 'before' ? c.hhi_before : c.hhi_after;
      if (v != null) m.set(c.fips, v);
    }
    return m;
  }, [proForma, beforeAfter]);
  const proFormaHighlighted = useMemo(() => {
    if (!proForma) return null;
    return new Set(
      proForma.county_impact.counties
        .filter((c) => (beforeAfter === 'before' ? c.already_above_threshold : c.already_above_threshold || c.crosses_threshold))
        .map((c) => c.fips),
    );
  }, [proForma, beforeAfter]);
  const proFormaColorMax = useMemo(() => {
    if (!proForma) return 1;
    return Math.max(1, ...proForma.county_impact.counties.map((c) => Math.max(c.hhi_before ?? 0, c.hhi_after ?? 0)));
  }, [proForma]);
  const proFormaFocusFips = useMemo(
    () => (proForma ? new Set(proForma.county_impact.counties.map((c) => c.fips)) : null),
    [proForma],
  );

  const inProFormaMode = proForma !== null;
  const mapValues = inProFormaMode ? proFormaValues! : baseValues;
  const mapHighlighted = inProFormaMode ? proFormaHighlighted! : baseHighlighted;
  const mapColorMax = inProFormaMode ? proFormaColorMax : baseColorMax;
  const mapThreshold = proForma?.county_impact.hhi_concentrated_threshold ?? result?.hhi_concentrated_threshold ?? 1800;
  // A proposed merger's affected counties can span states the dropdown alone
  // wouldn't show — the pro-forma view takes over the map's fit/rendering scope
  // rather than staying confined to whatever `state` happens to be selected.
  const stateFipsPrefix = !inProFormaMode && state && result?.counties[0] ? result.counties[0].fips.slice(0, 2) : null;

  const selectedRow = selectedFips ? countyByFips.get(selectedFips) : null;
  const selectedImpact = inProFormaMode && selectedFips
    ? proForma!.county_impact.counties.find((c) => c.fips === selectedFips) ?? null
    : null;

  const ramp = sequentialRamp();
  const legendGradient = `linear-gradient(to right, ${ramp.join(', ')})`;
  const legendThresholdPct = Math.max(0, Math.min(100, (mapThreshold / mapColorMax) * 100));

  function runProForma() {
    if (acquirerCert == null || targetCert == null) return;
    setProFormaLoading(true);
    api.maProForma(targetCert, acquirerCert)
      .then((r) => { setProForma(r); setProFormaError(null); setSelectedFips(null); })
      .catch((e: Error) => { setProForma(null); setProFormaError(e.message); })
      .finally(() => setProFormaLoading(false));
  }

  function clearProForma() {
    setProForma(null); setProFormaError(null);
    setAcquirerCert(null); setAcquirerName('');
    setTargetCert(null); setTargetName('');
    setSelectedFips(null);
  }

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
            screening threshold — many single-branch rural counties are legitimately
            near-monopoly markets by this measure, not a data artifact.
          </p>

          <h3 className="market-share-map-heading">
            {inProFormaMode
              ? `${acquirerName || 'Acquirer'} + ${targetName || 'Target'} — county HHI ${beforeAfter === 'before' ? 'today' : 'after the combination'}`
              : 'County HHI'}
          </h3>

          <div className="market-share-proforma-picker">
            <div className="market-share-proforma-field">
              <span className="muted market-share-proforma-label">Acquirer</span>
              <BankSearch onSelect={(cert, name) => { setAcquirerCert(cert); setAcquirerName(name); }} />
              {acquirerName && <span className="market-share-proforma-picked">{acquirerName}</span>}
            </div>
            <div className="market-share-proforma-field">
              <span className="muted market-share-proforma-label">Target</span>
              <BankSearch onSelect={(cert, name) => { setTargetCert(cert); setTargetName(name); }} />
              {targetName && <span className="market-share-proforma-picked">{targetName}</span>}
            </div>
            <button
              type="button"
              className="market-share-proforma-btn"
              disabled={acquirerCert == null || targetCert == null || proFormaLoading}
              onClick={runProForma}
            >
              {proFormaLoading ? 'Computing…' : 'Compute merger impact'}
            </button>
            {inProFormaMode && (
              <button type="button" className="market-share-proforma-clear" onClick={clearProForma}>
                Clear
              </button>
            )}
          </div>
          {proFormaError && <p className="app-banner-error">{proFormaError}</p>}

          {inProFormaMode && (
            <div className="market-share-proforma-summary">
              <p className="muted chart-caption">
                {proForma!.acquirer.name} acquires {proForma!.target.name}. {' '}
                {proForma!.county_impact.counties_affected} counties where both banks
                currently hold deposits (SOD {proForma!.county_impact.sod_vintage?.sod_year ?? 'unlanded'}) —{' '}
                {proForma!.county_impact.counties_crossing_threshold} would newly cross the Fed's{' '}
                {proForma!.county_impact.hhi_concentrated_threshold} HHI screening threshold.
              </p>
              <div className="market-share-toggle">
                <button
                  type="button"
                  className={`market-share-toggle-btn${beforeAfter === 'before' ? ' active' : ''}`}
                  onClick={() => setBeforeAfter('before')}
                >
                  Before
                </button>
                <button
                  type="button"
                  className={`market-share-toggle-btn${beforeAfter === 'after' ? ' active' : ''}`}
                  onClick={() => setBeforeAfter('after')}
                >
                  After
                </button>
              </div>
            </div>
          )}

          <div className="market-share-map-legend">
            <span className="muted market-share-legend-label">0</span>
            <div className="market-share-legend-bar" style={{ background: legendGradient }}>
              <div className="market-share-legend-threshold" style={{ left: `${legendThresholdPct}%` }} title={`Fed screening threshold — HHI ${mapThreshold}`} />
            </div>
            <span className="muted market-share-legend-label">{mapColorMax.toFixed(0)}</span>
            <span className="market-share-legend-flag"><i /> at/above HHI {mapThreshold}</span>
          </div>

          <CountyChoropleth
            values={mapValues}
            highlighted={mapHighlighted}
            colorDomainMax={mapColorMax}
            stateFipsPrefix={stateFipsPrefix}
            focusFips={inProFormaMode ? proFormaFocusFips : null}
            selectedFips={selectedFips}
            onSelect={setSelectedFips}
            labelFor={(fips) => {
              const row = countyByFips.get(fips);
              return row ? `${row.name ?? fips}, ${row.state ?? ''}` : null;
            }}
            height={520}
          />

          {selectedFips && (
            <div className="market-share-detail-panel">
              {inProFormaMode ? (
                selectedImpact ? (
                  <>
                    <div className="market-share-detail-head">
                      <span className="market-share-detail-name">{selectedImpact.name ?? selectedImpact.fips}, {selectedImpact.state}</span>
                      {selectedImpact.crosses_threshold && <span className="chip chip-high">newly crosses threshold</span>}
                      {selectedImpact.already_above_threshold && <span className="chip chip-high">already concentrated</span>}
                      <button type="button" className="market-share-detail-close" onClick={() => setSelectedFips(null)}>×</button>
                    </div>
                    <div className="pro-forma-county-row">
                      <span>HHI</span>
                      <span className="tabular muted">{selectedImpact.hhi_before?.toFixed(0) ?? '—'} → </span>
                      <span className="tabular">{selectedImpact.hhi_after?.toFixed(0) ?? '—'}</span>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="market-share-detail-head">
                      <span className="market-share-detail-name">{countyByFips.get(selectedFips)?.name ?? selectedFips}</span>
                      <button type="button" className="market-share-detail-close" onClick={() => setSelectedFips(null)}>×</button>
                    </div>
                    <p className="muted">Neither bank in this combination holds deposits here — unaffected by the merger.</p>
                  </>
                )
              ) : selectedRow ? (
                <>
                  <div className="market-share-detail-head">
                    <span className="market-share-detail-name">{selectedRow.name}, {selectedRow.state}</span>
                    {selectedRow.concentrated && <span className="chip chip-high">HHI ≥ {result.hhi_concentrated_threshold}</span>}
                    <button type="button" className="market-share-detail-close" onClick={() => setSelectedFips(null)}>×</button>
                  </div>
                  <div className="market-share-detail-stats muted tabular">
                    {selectedRow.branch_count} branches · {fmtDeposits(selectedRow.total_deposits)} deposits · HHI {selectedRow.hhi?.toFixed(0)}
                  </div>
                  <div className="ms-shares">
                    {selectedRow.shares.map((s) => (
                      <Link className="ms-share-row" key={s.cert} to={`/bank/${s.cert}`}>
                        <span className="ms-share-name">{s.name}</span>
                        <span className="tabular muted">{fmtDeposits(s.deposits)}</span>
                        <span className="tabular ms-share-pct">{s.share_pct.toFixed(1)}%</span>
                      </Link>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="market-share-detail-head">
                    <span className="market-share-detail-name">FIPS {selectedFips}</span>
                    <button type="button" className="market-share-detail-close" onClick={() => setSelectedFips(null)}>×</button>
                  </div>
                  <p className="muted">No landed deposit data for this county.</p>
                </>
              )}
            </div>
          )}

          <div className="market-share-export-row">
            <ExportCsvButton
              filename="banklens-county-concentration.csv"
              columns={COUNTY_CSV_COLUMNS}
              rows={tableCounties}
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
                {tableCounties.map((c) => (
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
