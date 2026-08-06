import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { api, type BankSearchResult } from '../api';
import './ScreenerPage.css';

type SortKey = 'name' | 'state' | 'country' | 'assets_b' | 'cluster' | 'roa_pct' | 'npl_ratio_pct' | 'cet1_ratio';

function fmtPct(v: number | null): string {
  return v === null || v === undefined ? '—' : `${v.toFixed(2)}%`;
}

export function ScreenerPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [state, setState] = useState('');
  const [country, setCountry] = useState('');
  const [minAssets, setMinAssets] = useState('');
  const [maxAssets, setMaxAssets] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('assets_b');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [result, setResult] = useState<BankSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      api.screenBanks({
        query: query || undefined,
        state: state || undefined,
        country: country || undefined,
        min_assets_b: minAssets ? Number(minAssets) : undefined,
        max_assets_b: maxAssets ? Number(maxAssets) : undefined,
        limit: 200,
      })
        .then((r) => { setResult(r); setError(null); })
        .catch((e: Error) => setError(e.message))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [query, state, country, minAssets, maxAssets]);

  const rows = [...(result?.banks ?? [])].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    const av = a[sortKey] ?? '';
    const bv = b[sortKey] ?? '';
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'name' || key === 'state' || key === 'cluster' ? 'asc' : 'desc');
    }
  }

  return (
    <div className="screener-page">
      <div className="panel">
        <h2>Screener — {result?.count ?? '…'} banks (US $1B–$250B population + EU significant institutions)</h2>
        <div className="screener-filters">
          <input
            className="screener-input"
            placeholder="Search by name…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <input
            className="screener-input screener-input-narrow"
            placeholder="State (e.g. NY)"
            maxLength={2}
            value={state}
            onChange={(e) => setState(e.target.value.toUpperCase())}
          />
          <input
            className="screener-input screener-input-narrow"
            placeholder="Country (e.g. DE)"
            maxLength={2}
            value={country}
            onChange={(e) => setCountry(e.target.value.toUpperCase())}
          />
          <input
            className="screener-input screener-input-narrow"
            placeholder="Min $B"
            type="number"
            value={minAssets}
            onChange={(e) => setMinAssets(e.target.value)}
          />
          <input
            className="screener-input screener-input-narrow"
            placeholder="Max $B"
            type="number"
            value={maxAssets}
            onChange={(e) => setMaxAssets(e.target.value)}
          />
        </div>

        {error && <p className="app-banner-error">{error}</p>}

        <div className="screener-table-wrap">
          <table className="screener-table">
            <thead>
              <tr>
                <th onClick={() => toggleSort('name')} className="screener-th">
                  Bank{sortKey === 'name' && (sortDir === 'asc' ? ' ▲' : ' ▼')}
                </th>
                <th onClick={() => toggleSort('state')} className="screener-th">
                  Loc.{sortKey === 'state' && (sortDir === 'asc' ? ' ▲' : ' ▼')}
                </th>
                <th onClick={() => toggleSort('assets_b')} className="screener-th screener-th-right">
                  Assets{sortKey === 'assets_b' && (sortDir === 'asc' ? ' ▲' : ' ▼')}
                </th>
                <th onClick={() => toggleSort('cluster')} className="screener-th">
                  Behavioral cluster{sortKey === 'cluster' && (sortDir === 'asc' ? ' ▲' : ' ▼')}
                </th>
                <th onClick={() => toggleSort('roa_pct')} className="screener-th screener-th-right">
                  ROA{sortKey === 'roa_pct' && (sortDir === 'asc' ? ' ▲' : ' ▼')}
                </th>
                <th onClick={() => toggleSort('npl_ratio_pct')} className="screener-th screener-th-right">
                  NPL ratio{sortKey === 'npl_ratio_pct' && (sortDir === 'asc' ? ' ▲' : ' ▼')}
                </th>
                <th onClick={() => toggleSort('cet1_ratio')} className="screener-th screener-th-right">
                  CET1{sortKey === 'cet1_ratio' && (sortDir === 'asc' ? ' ▲' : ' ▼')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b, i) => (
                <motion.tr
                  key={b.cert}
                  className="screener-row"
                  onClick={() => navigate(`/bank/${b.cert}`)}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1, transition: { delay: Math.min(i, 20) * 0.012 } }}
                >
                  <td className="screener-td-name">{b.name}</td>
                  <td>{b.country === 'US' ? (b.state ?? '—') : (b.country ?? '—')}</td>
                  <td className="tabular screener-td-right">${b.assets_b.toFixed(1)}B</td>
                  <td className="muted">{b.cluster ?? '—'}</td>
                  <td className="tabular screener-td-right">{fmtPct(b.roa_pct)}</td>
                  <td className="tabular screener-td-right">{fmtPct(b.npl_ratio_pct)}</td>
                  <td className="tabular screener-td-right">{fmtPct(b.cet1_ratio)}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
          {!loading && rows.length === 0 && (
            <p className="muted screener-empty">No banks match these filters.</p>
          )}
        </div>
      </div>
    </div>
  );
}
