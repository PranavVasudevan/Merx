import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { api } from '../api';
import { fmtAssets, pct } from '../metricFormat';
import type { MetricGroup, PopulationMetricsResult } from '../types';
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

  useEffect(() => {
    api.populationMetrics(group, { limit: 2000 })
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [group]);

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

  const highlightCol = columns.find((c) => c.key === defaultSort);
  const maxHighlight = highlight.length
    ? Math.max(...highlight.map((b) => Math.abs(b[defaultSort] as number)))
    : 1;

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
        </div>
        <div className="metric-group-table-wrap">
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
              {rows.map((b, i) => (
                <motion.tr
                  key={b.cert_number}
                  className="metric-group-row"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1, transition: { delay: Math.min(i, 25) * 0.008 } }}
                >
                  <td className="metric-group-td-name">
                    <Link to={`/bank/${b.cert_number}`}>{b.name}</Link>
                  </td>
                  <td className="muted">{b.state ?? '—'}</td>
                  <td className="tabular metric-group-td-right">{fmtAssets(b.total_assets)}</td>
                  {columns.map((c) => (
                    <td key={c.key} className="tabular metric-group-td-right">
                      {(c.format ?? defaultFormat)(b[c.key])}
                    </td>
                  ))}
                </motion.tr>
              ))}
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
