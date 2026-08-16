import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { api } from '../api';
import { usePeerSet } from '../PeerSetContext';
import { useQuarter } from '../QuarterContext';
import { fmtAssets, pct } from '../metricFormat';
import type { MetricGroup, PopulationMetricsResult, PopulationTrendSparklinesResult } from '../types';
import { ExportCsvButton } from './ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import { Sparkline } from './Sparkline';
import './MetricGroupPage.css';

export interface MetricColumn {
  key: string;
  label: string;
  /** Formats the raw value for display. Defaults to a 2-decimal percent. */
  format?: (v: number | string | null) => string;
}

export interface MetricGroupPageProps {
  group: MetricGroup;
  title: string;
  subtitle: string;
  columns: MetricColumn[];
  /** Column key sorted on first load and used for the "notable" rail. */
  defaultSort: string;
  defaultDescending?: boolean;
  /** Label for the top-N rail, e.g. "Highest ROA". */
  highlightLabel: string;
}

const defaultFormat = pct;

// D13 — hand-rolled row virtualization (no react-window/react-virtual dep,
// consistent with this codebase's preference for a small owned wrapper over
// a heavy library — see EChart.tsx's own rationale). Only kicks in once the
// table is actually big enough to matter (earnings/credit/funding tables run
// up to ~2,000 rows at "no filter" — every row unvirtualized was visibly
// janky to scroll); a small filtered/sorted result just renders normally.
const VIRTUALIZE_THRESHOLD = 100;
const ROW_HEIGHT_PX = 40;
const VIEWPORT_HEIGHT_PX = 520; // must match .metric-group-table-wrap--virtual's max-height in CSS
const OVERSCAN_ROWS = 8;

/**
 * Shared shell for the earnings/credit/funding pages: they are the same real
 * behavior (fetch one metric group, let the analyst sort/filter/rank it, flag
 * excluded institutions) with a different column set, not three hand-copied pages.
 */
export function MetricGroupPage({
  group, title, subtitle, columns, defaultSort, defaultDescending = true, highlightLabel,
}: MetricGroupPageProps) {
  const [result, setResult] = useState<PopulationMetricsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState(defaultSort);
  const [descending, setDescending] = useState(defaultDescending);
  // E12 — sparkline trend series, batched ONE extra request for the whole
  // loaded population rather than a per-row fetch (see api.populationTrendSparklines).
  const [sparklines, setSparklines] = useState<PopulationTrendSparklinesResult | null>(null);
  const { quarter } = useQuarter(); // D3
  const { activePeerSet } = usePeerSet(); // D5
  const [scrollTop, setScrollTop] = useState(0);

  useEffect(() => {
    api.populationMetrics(group, { limit: 2000, quarter, certs: activePeerSet?.certs })
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [group, quarter, activePeerSet]);

  useEffect(() => {
    if (!result || result.banks.length === 0) { setSparklines(null); return; }
    const certs = result.banks.map((b) => b.cert_number);
    api.populationTrendSparklines(certs, columns.map((c) => c.key))
      .then(setSparklines)
      // Sparklines are supplementary context, not the table's core data — a
      // failure here (e.g. the certs list exceeding MAX_SPARKLINE_CERTS)
      // shouldn't blank out an otherwise-working metric table.
      .catch(() => setSparklines(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `columns` is a
    // per-page constant array literal (see EarningsPage/CreditPage/FundingPage),
    // not state; keying off `result` (which changes once per group/quarter load)
    // is what keeps this to one extra request per page load.
  }, [result]);

  const sparkByCert = useMemo(() => {
    const m = new Map<number, Record<string, (number | null)[]>>();
    for (const b of sparklines?.banks ?? []) m.set(b.cert, b.values);
    return m;
  }, [sparklines]);

  const rows = useMemo(() => {
    if (!result) return [];
    const q = query.trim().toLowerCase();
    const filtered = q
      ? result.banks.filter((b) => b.name.toLowerCase().includes(q)
          || (b.state ?? '').toLowerCase() === q)
      : result.banks;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv : String(av).localeCompare(String(bv));
      return descending ? -cmp : cmp;
    });
  }, [result, query, sortKey, descending]);

  const highlight = useMemo(() => {
    if (!result) return [];
    return [...result.banks]
      .filter((b) => typeof b[defaultSort] === 'number')
      .sort((a, b) => (defaultDescending
        ? (b[defaultSort] as number) - (a[defaultSort] as number)
        : (a[defaultSort] as number) - (b[defaultSort] as number)))
      .slice(0, 8);
  }, [result, defaultSort, defaultDescending]);

  function toggleSort(key: string) {
    if (key === sortKey) { setDescending((d) => !d); return; }
    setSortKey(key);
    setDescending(true);
  }

  const virtualized = rows.length > VIRTUALIZE_THRESHOLD;
  const { startIndex, endIndex } = useMemo(() => {
    if (!virtualized) return { startIndex: 0, endIndex: rows.length };
    const viewportRows = Math.ceil(VIEWPORT_HEIGHT_PX / ROW_HEIGHT_PX);
    const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT_PX) - OVERSCAN_ROWS);
    const end = Math.min(rows.length, start + viewportRows + OVERSCAN_ROWS * 2);
    return { startIndex: start, endIndex: end };
  }, [virtualized, scrollTop, rows.length]);
  const visibleRows = virtualized ? rows.slice(startIndex, endIndex) : rows;

  const highlightCol = columns.find((c) => c.key === defaultSort);
  const maxHighlight = highlight.length
    ? Math.max(...highlight.map((b) => Math.abs(b[defaultSort] as number)))
    : 1;

  const csvColumns: CsvColumn<PopulationMetricsResult['banks'][number]>[] = [
    { key: 'name', label: 'Bank', value: (b) => b.name, source: 'fdic' },
    { key: 'cert_number', label: 'FDIC Cert', value: (b) => b.cert_number, source: 'fdic' },
    { key: 'state', label: 'State', value: (b) => b.state ?? '', source: 'fdic' },
    { key: 'total_assets', label: 'Total assets ($)', value: (b) => b.total_assets, source: 'fdic' },
    ...columns.map((c) => ({
      key: c.key, label: c.label, value: (b: PopulationMetricsResult['banks'][number]) => b[c.key] as string | number | null,
      source: 'fdic' as const,
    })),
    // E12 — each sparkline metric's own trailing per-quarter series as
    // trailing columns, so the CSV carries the same direction context the
    // sparkline glyph shows on screen, not just the latest level.
    ...(sparklines
      ? columns.flatMap((c) => sparklines.quarters.map((q, qi) => ({
          key: `${c.key}__${q}`,
          label: `${c.label} (${q})`,
          value: (b: PopulationMetricsResult['banks'][number]) =>
            sparkByCert.get(b.cert_number)?.[c.key]?.[qi] ?? null,
          source: 'fdic' as const,
        })))
      : []),
  ];

  return (
    <div className="metric-group-page">
      <div className="panel">
        <h2>{title}{result ? ` — ${result.count} banks` : ''}</h2>
        <p className="muted metric-group-subtitle">{subtitle}</p>
        {result && (
          <p className="muted metric-group-meta">
            {result.quarter} · FDIC performance ratios are year-to-date annualized, so a raw
            Q1-vs-Q4 comparison is not like-for-like.
          </p>
        )}
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {result && highlight.length > 0 && (
        <div className="panel">
          <h2>{highlightLabel}</h2>
          <div className="metric-rank-list">
            {highlight.map((b, i) => (
              <Link className="metric-rank-row" key={b.cert_number} to={`/bank/${b.cert_number}`}>
                <span className="muted metric-rank-index tabular">{i + 1}</span>
                <span className="metric-rank-name">{b.name}</span>
                <div className="metric-rank-track">
                  <motion.div
                    className="metric-rank-fill"
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(100, Math.abs(b[defaultSort] as number) / maxHighlight * 100)}%` }}
                    transition={{ duration: 0.5, ease: [0.85, 0, 0.15, 1], delay: i * 0.02 }}
                  />
                </div>
                <span className="tabular metric-rank-value">
                  {(highlightCol?.format ?? defaultFormat)(b[defaultSort])}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="panel">
        <div className="metric-group-filters">
          <input
            className="metric-group-input"
            placeholder="Filter by name or 2-letter state…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <ExportCsvButton
            filename={`banklens-${group}.csv`}
            columns={csvColumns}
            rows={rows}
            meta={{ vintage: result?.quarter, sourceLabel: 'FDIC Call Reports' }}
          />
        </div>
        {virtualized && (
          <p className="muted metric-group-virtual-note">
            Showing rows {startIndex + 1}–{endIndex} of {rows.length} · scroll for more
            (virtualized — table over {VIRTUALIZE_THRESHOLD} rows renders only what's visible).
          </p>
        )}
        <div
          className={`metric-group-table-wrap${virtualized ? ' metric-group-table-wrap--virtual' : ''}`}
          onScroll={virtualized ? (e) => setScrollTop(e.currentTarget.scrollTop) : undefined}
        >
          <table className="metric-group-table">
            <thead>
              <tr>
                <th className="metric-group-th">Bank</th>
                <th className="metric-group-th">State</th>
                <th className="metric-group-th metric-group-th-right">Assets</th>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    className="metric-group-th metric-group-th-right"
                    onClick={() => toggleSort(c.key)}
                  >
                    {c.label}{sortKey === c.key && (descending ? ' ▼' : ' ▲')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {virtualized && startIndex > 0 && (
                <tr style={{ height: startIndex * ROW_HEIGHT_PX }} aria-hidden="true" />
              )}
              {visibleRows.map((b, i) => (
                <motion.tr
                  key={b.cert_number}
                  className="metric-group-row"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1, transition: { delay: virtualized ? 0 : Math.min(i, 25) * 0.008 } }}
                >
                  <td className="metric-group-td-name">
                    <Link to={`/bank/${b.cert_number}`}>{b.name}</Link>
                  </td>
                  <td className="muted">{b.state ?? '—'}</td>
                  <td className="tabular metric-group-td-right">{fmtAssets(b.total_assets)}</td>
                  {columns.map((c) => (
                    <td key={c.key} className="tabular metric-group-td-right">
                      <span className="metric-group-td-value">
                        <span>{(c.format ?? defaultFormat)(b[c.key])}</span>
                        <Sparkline
                          values={sparkByCert.get(b.cert_number)?.[c.key] ?? []}
                          title={`${c.label} — last ${sparklines?.quarters.length ?? 0} quarters`}
                        />
                      </span>
                    </td>
                  ))}
                </motion.tr>
              ))}
              {virtualized && endIndex < rows.length && (
                <tr style={{ height: (rows.length - endIndex) * ROW_HEIGHT_PX }} aria-hidden="true" />
              )}
            </tbody>
          </table>
          {result && rows.length === 0 && (
            <p className="muted metric-group-empty">No banks match “{query}”.</p>
          )}
        </div>
      </div>
    </div>
  );
}
