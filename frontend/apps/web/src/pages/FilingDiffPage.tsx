import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import { api, type BankSearchResult } from '../api';
import type { FilingDiffResult } from '../types';
import './FilingDiffPage.css';

function fmtValue(v: number | null, kind: 'dollar' | 'ratio'): string {
  if (v === null) return '—';
  if (kind === 'dollar') {
    const abs = Math.abs(v);
    return `${v < 0 ? '-' : ''}$${abs >= 1e9 ? (abs / 1e9).toFixed(2) + 'B' : (abs / 1e6).toFixed(1) + 'M'}`;
  }
  return `${v.toFixed(2)}%`;
}

export function FilingDiffPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BankSearchResult['banks']>([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const [cert, setCert] = useState<number | null>(params.get('cert') ? Number(params.get('cert')) : 6976);
  const [quarters, setQuarters] = useState<string[]>([]);
  const [quarterA, setQuarterA] = useState<string | undefined>(undefined);
  const [quarterB, setQuarterB] = useState<string | undefined>(undefined);
  const [diff, setDiff] = useState<FilingDiffResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      api.searchBanks(query, undefined, 8).then((r) => { setResults(r.banks); setOpen(true); }).catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  // Populate the quarter pickers from the bank's own real trend history — no
  // separate "which quarters exist for this bank" endpoint needed.
  useEffect(() => {
    if (cert === null) return;
    api.bankTrends(cert).then((r) => setQuarters(r.quarters)).catch(() => setQuarters([]));
    setQuarterA(undefined);
    setQuarterB(undefined);
  }, [cert]);

  useEffect(() => {
    if (cert === null) return;
    api.filingDiff(cert, quarterA, quarterB)
      .then((r) => { setDiff(r); setError(null); })
      .catch((e: Error) => { setError(e.message); setDiff(null); });
  }, [cert, quarterA, quarterB]);

  return (
    <div className="filing-diff-page">
      <div className="panel">
        <h2>Filing diff</h2>
        <p className="muted filing-diff-subtitle">
          Every tracked line item, side by side across two quarters — not just the
          ones that cleared the statistical-outlier bar. Highlighted rows are moves
          that are unusual versus this bank's own history (z-score), not an absolute
          cutoff.
        </p>
        <div className="filing-diff-controls">
          <div className="filing-diff-picker" ref={boxRef}>
            <input
              className="filing-diff-input"
              placeholder="Search a bank…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => results.length > 0 && setOpen(true)}
            />
            <AnimatePresence>
              {open && results.length > 0 && (
                <motion.div
                  className="filing-diff-results"
                  initial={{ opacity: 0, y: -6, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.98 }}
                  transition={{ duration: 0.16, ease: [0.85, 0, 0.15, 1] }}
                >
                  {results.map((b) => (
                    <button
                      key={b.cert}
                      className="filing-diff-result"
                      onClick={() => { setCert(b.cert); setQuery(''); setOpen(false); navigate(`/filing-diff?cert=${b.cert}`, { replace: true }); }}
                    >
                      <span className="bsr-name">{b.name}</span>
                      <span className="muted bsr-meta">${b.assets_b.toFixed(1)}B · {b.state ?? '—'}</span>
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {quarters.length > 1 && (
            <>
              <select className="filing-diff-select" value={quarterA ?? ''}
                onChange={(e) => setQuarterA(e.target.value || undefined)}>
                <option value="">Older quarter (auto)</option>
                {quarters.map((q) => <option key={q} value={q}>{q}</option>)}
              </select>
              <select className="filing-diff-select" value={quarterB ?? ''}
                onChange={(e) => setQuarterB(e.target.value || undefined)}>
                <option value="">Newer quarter (auto)</option>
                {quarters.map((q) => <option key={q} value={q}>{q}</option>)}
              </select>
            </>
          )}
        </div>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {diff && (
        <div className="panel">
          <h2><Link to={`/bank/${cert}`}>{diff.name}</Link> — {diff.from_quarter} → {diff.to_quarter}</h2>
          <p className="muted">{diff.n_flags} of {diff.line_items.length} tracked items flagged as unusual.</p>
          <div className="filing-diff-table-wrap">
            <table className="filing-diff-table">
              <thead>
                <tr>
                  <th className="filing-diff-th">Item</th>
                  <th className="filing-diff-th filing-diff-th-right">{diff.from_quarter}</th>
                  <th className="filing-diff-th filing-diff-th-right">{diff.to_quarter}</th>
                  <th className="filing-diff-th filing-diff-th-right">Change</th>
                  <th className="filing-diff-th filing-diff-th-right">z</th>
                </tr>
              </thead>
              <tbody>
                {diff.line_items.map((li) => (
                  <tr key={li.metric} className={li.flagged ? 'filing-diff-row-flagged' : ''}>
                    <td className="filing-diff-td-name">
                      {li.flagged && (
                        <span className={`filing-diff-arrow ${li.direction === 'up' ? 'filing-diff-up' : 'filing-diff-down'}`}>
                          {li.direction === 'up' ? '▲' : '▼'}
                        </span>
                      )}
                      {li.item}
                    </td>
                    <td className="tabular filing-diff-td-right">{fmtValue(li.quarter_a_value, li.kind)}</td>
                    <td className="tabular filing-diff-td-right">{fmtValue(li.quarter_b_value, li.kind)}</td>
                    <td className="tabular filing-diff-td-right">
                      {li.change === null ? '—' : `${li.change > 0 ? '+' : ''}${li.change}${li.unit}`}
                    </td>
                    <td className="tabular muted filing-diff-td-right">{li.z !== null ? li.z.toFixed(2) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
