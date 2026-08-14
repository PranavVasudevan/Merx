import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { api, type BankSearchResult } from '../api';
import { ExportCsvButton } from '../components/ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import type { SavedScreen } from '../types';
import './ScreenerPage.css';

type ScreenerRow = BankSearchResult['banks'][number];

const CSV_COLUMNS: CsvColumn<ScreenerRow>[] = [
  { key: 'name', label: 'Bank', value: (b) => b.name },
  { key: 'cert', label: 'FDIC Cert', value: (b) => b.cert, source: 'fdic' },
  { key: 'loc', label: 'Location', value: (b) => (b.country === 'US' ? b.state ?? '' : b.country ?? '') },
  { key: 'assets_b', label: 'Assets ($B)', value: (b) => b.assets_b, source: 'fdic' },
  { key: 'cluster', label: 'Behavioral cluster', value: (b) => b.cluster ?? '', source: 'derived' },
  { key: 'roa_pct', label: 'ROA %', value: (b) => b.roa_pct, source: 'fdic' },
  { key: 'npl_ratio_pct', label: 'NPL ratio %', value: (b) => b.npl_ratio_pct, source: 'fdic' },
  { key: 'cet1_ratio', label: 'CET1 %', value: (b) => b.cet1_ratio, source: 'fdic' },
];

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
  const [savedScreens, setSavedScreens] = useState<SavedScreen[]>([]);

  useEffect(() => {
    api.getSavedScreens().then((r) => setSavedScreens(r.items)).catch(() => setSavedScreens([]));
  }, []);

  async function saveCurrentScreen() {
    const name = window.prompt('Name this screen:');
    if (!name) return;
    try {
      const r = await api.saveScreen(name, { query, state, country, min_assets_b: minAssets, max_assets_b: maxAssets });
      setSavedScreens(r.items);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function loadScreen(s: SavedScreen) {
    setQuery(String(s.filters.query ?? ''));
    setState(String(s.filters.state ?? ''));
    setCountry(String(s.filters.country ?? ''));
    setMinAssets(s.filters.min_assets_b !== undefined ? String(s.filters.min_assets_b) : '');
    setMaxAssets(s.filters.max_assets_b !== undefined ? String(s.filters.max_assets_b) : '');
  }

  async function deleteScreen(id: number) {
    try {
      const r = await api.deleteSavedScreen(id);
      setSavedScreens(r.items);
    } catch (e) {
      setError((e as Error).message);
    }
  }

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
        <div className="screener-header-row">
          <h2>Screener — {result?.count ?? '…'} banks (full US FDIC population + EU significant institutions)</h2>
          <div className="screener-header-actions">
            <button type="button" className="screener-save-btn" onClick={saveCurrentScreen}>
              ☆ Save this screen
            </button>
            <ExportCsvButton
              filename="banklens-screener.csv"
              columns={CSV_COLUMNS}
              rows={rows}
              meta={{ sourceLabel: 'FDIC BankFind / EBA Transparency Exercise' }}
            />
          </div>
        </div>
        {savedScreens.length > 0 && (
          <div className="screener-saved-screens">
            {savedScreens.map((s) => (
              <span key={s.id} className="screener-saved-screen-chip">
                <button onClick={() => loadScreen(s)}>{s.name}</button>
                <button className="screener-saved-screen-remove" onClick={() => deleteScreen(s.id)} aria-label={`Delete ${s.name}`}>×</button>
              </span>
            ))}
          </div>
        )}
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
