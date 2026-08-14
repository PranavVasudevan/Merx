import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Link } from 'react-router-dom';
import { api, type BankSearchResult } from '../api';
import type { CompareResult } from '../types';
import { ExportCsvButton } from '../components/ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import './ComparePage.css';

const METRIC_LABELS: Record<string, string> = {
  uninsured_deposit_pct: 'Uninsured deposits',
  loan_to_deposit_pct: 'Loan / deposit ratio',
  concentration_ratio_cre: 'CRE concentration',
  cet1_ratio: 'CET1 ratio',
  leverage_ratio: 'Leverage ratio',
  roa_pct: 'Return on assets',
  net_interest_margin_pct: 'Net interest margin',
  npl_ratio_pct: 'NPL ratio',
  texas_ratio_pct: 'Texas Ratio',
  brokered_deposit_pct: 'Brokered deposits',
};

const MAX_BANKS = 6;

function fmtMetric(v: number | string | null): string {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number' ? `${v.toFixed(1)}%` : String(v);
}

export function ComparePage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BankSearchResult['banks']>([]);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<{ cert: number; name: string }[]>([]);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      api.searchBanks(query, undefined, 8)
        .then((r) => {
          setResults(r.banks.filter((b) => !selected.some((s) => s.cert === b.cert)));
          setOpen(true);
        })
        .catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [query, selected]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  useEffect(() => {
    if (selected.length < 2) { setCompare(null); return; }
    api.compareBanks(selected.map((s) => s.cert))
      .then((r) => { setCompare(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [selected]);

  function addBank(cert: number, name: string) {
    if (selected.length >= MAX_BANKS || selected.some((s) => s.cert === cert)) return;
    setSelected((s) => [...s, { cert, name }]);
    setQuery('');
    setOpen(false);
  }

  function removeBank(cert: number) {
    setSelected((s) => s.filter((b) => b.cert !== cert));
  }

  return (
    <div className="compare-page">
      <div className="panel">
        <h2>Compare banks</h2>
        <p className="muted compare-note">Pick 2–{MAX_BANKS} banks to compare side by side across core metrics.</p>

        <div className="compare-picker" ref={boxRef}>
          <input
            className="compare-picker-input"
            placeholder={selected.length >= MAX_BANKS ? `Maximum ${MAX_BANKS} banks` : 'Search a bank to add…'}
            value={query}
            disabled={selected.length >= MAX_BANKS}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results.length > 0 && setOpen(true)}
          />
          <AnimatePresence>
            {open && results.length > 0 && (
              <motion.div
                className="compare-picker-results"
                initial={{ opacity: 0, y: -6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.98 }}
                transition={{ duration: 0.16, ease: [0.85, 0, 0.15, 1] }}
              >
                {results.map((b, i) => (
                  <motion.button
                    key={b.cert}
                    className="compare-picker-result"
                    onClick={() => addBank(b.cert, b.name)}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1, transition: { delay: i * 0.02, duration: 0.15 } }}
                    whileHover={{ x: 2 }}
                  >
                    <span className="bsr-name">{b.name}</span>
                    <span className="muted bsr-meta">${b.assets_b.toFixed(1)}B · {b.state ?? '—'}</span>
                  </motion.button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="compare-chips">
          <AnimatePresence>
            {selected.map((b) => (
              <motion.div
                key={b.cert}
                className="compare-chip"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.15 }}
              >
                <Link to={`/bank/${b.cert}`} className="compare-chip-name">{b.name}</Link>
                <button className="compare-chip-remove" onClick={() => removeBank(b.cert)} aria-label={`Remove ${b.name}`}>×</button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>

        {error && <p className="app-banner-error">{error}</p>}
        {selected.length === 1 && <p className="muted compare-empty">Add one more bank to compare.</p>}
        {selected.length === 0 && <p className="muted compare-empty">No banks selected yet.</p>}

        {compare && (
          <div className="compare-table-wrap">
            <div className="compare-export-row">
              <ExportCsvButton
                filename="banklens-compare.csv"
                columns={[
                  { key: 'metric', label: 'Metric', value: (m: string) => METRIC_LABELS[m] ?? m },
                  ...compare.banks.map((b) => ({
                    key: String(b.cert), label: b.name,
                    value: (m: string) => b[m] as string | number | null, source: 'fdic' as const,
                  })),
                ] as CsvColumn<string>[]}
                rows={compare.metrics}
                meta={{ sourceLabel: 'FDIC Call Reports' }}
              />
            </div>
            <table className="compare-table">
              <thead>
                <tr>
                  <th className="compare-th-metric"></th>
                  {compare.banks.map((b) => (
                    <th key={b.cert} className="compare-th">
                      <Link to={`/bank/${b.cert}`}>{b.name}</Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compare.metrics.map((m) => (
                  <tr key={m}>
                    <td className="compare-td-metric muted">{METRIC_LABELS[m] ?? m}</td>
                    {compare.banks.map((b) => (
                      <td key={b.cert} className="compare-td tabular">{fmtMetric(b[m])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
