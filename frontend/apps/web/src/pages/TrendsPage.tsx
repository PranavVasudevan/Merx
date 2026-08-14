import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api, type BankSearchResult } from '../api';
import { chartColors } from '../colors';
import type { BankTrendsResult } from '../types';
import '../components/charts.css';
import './TrendsPage.css';

interface Panel { title: string; lines: { key: string; label: string; color: keyof ReturnType<typeof chartColors> }[]; suffix: string }

const PANELS: Panel[] = [
  { title: 'Total assets ($B)', suffix: 'B',
    lines: [{ key: 'total_assets', label: 'Assets', color: 'blue' }] },
  { title: 'Profitability', suffix: '%',
    lines: [{ key: 'roa_pct', label: 'ROA', color: 'green' },
            { key: 'net_interest_margin_pct', label: 'NIM', color: 'aqua' }] },
  { title: 'Credit quality', suffix: '%',
    lines: [{ key: 'npl_ratio_pct', label: 'NPL ratio', color: 'orange' },
            { key: 'texas_ratio_pct', label: 'Texas Ratio', color: 'red' }] },
  { title: 'Funding mix', suffix: '%',
    lines: [{ key: 'uninsured_deposit_pct', label: 'Uninsured', color: 'magenta' },
            { key: 'brokered_deposit_pct', label: 'Brokered', color: 'violet' }] },
  { title: 'Capital', suffix: '%',
    lines: [{ key: 'cet1_ratio', label: 'CET1', color: 'blue' },
            { key: 'max_loan_concentration_pct', label: 'Max sector conc.', color: 'yellow' }] },
];

function CustomTooltip({ active, payload, label, suffix }: {
  active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string; suffix: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="chart-tooltip-value tabular" style={{ color: p.color }}>
          {p.name}: {p.value?.toFixed(2)}{suffix}
        </div>
      ))}
    </motion.div>
  );
}

export function TrendsPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BankSearchResult['banks']>([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const [cert, setCert] = useState<number | null>(params.get('cert') ? Number(params.get('cert')) : 6976);
  const [trends, setTrends] = useState<BankTrendsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const colors = chartColors();

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

  useEffect(() => {
    if (cert === null) return;
    setLoading(true);
    api.bankTrends(cert)
      .then((r) => { setTrends(r); setError(null); })
      .catch((e: Error) => { setError(e.message); setTrends(null); })
      .finally(() => setLoading(false));
  }, [cert]);

  const chartData = trends?.series.map((s) => ({
    ...s,
    total_assets: typeof s.total_assets === 'number' ? s.total_assets / 1e9 : null,
  }));

  return (
    <div className="trends-page">
      <div className="panel">
        <h2>Trends</h2>
        <p className="muted trends-subtitle">
          One bank's real trajectory across every landed quarter — earnings, credit
          quality, funding mix and capital, not a single snapshot.
        </p>
        <div className="trends-picker" ref={boxRef}>
          <input
            className="trends-picker-input"
            placeholder="Search a bank…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results.length > 0 && setOpen(true)}
          />
          <AnimatePresence>
            {open && results.length > 0 && (
              <motion.div
                className="trends-picker-results"
                initial={{ opacity: 0, y: -6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.98 }}
                transition={{ duration: 0.16, ease: [0.85, 0, 0.15, 1] }}
              >
                {results.map((b) => (
                  <button
                    key={b.cert}
                    className="trends-picker-result"
                    onClick={() => { setCert(b.cert); setQuery(''); setOpen(false); navigate(`/trends?cert=${b.cert}`, { replace: true }); }}
                  >
                    <span className="bsr-name">{b.name}</span>
                    <span className="muted bsr-meta">${b.assets_b.toFixed(1)}B · {b.state ?? '—'}</span>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {trends && (
        <div className="panel">
          <h2>
            <Link to={`/bank/${trends.cert}`}>{trends.name}</Link>
            {' '}— {trends.quarters[0]} to {trends.quarters[trends.quarters.length - 1]}
          </h2>

          <div className="trends-cluster-strip">
            {trends.series.map((s) => (
              <div className="trends-cluster-chip" key={s.quarter} title={s.peer_cluster_label ?? ''}>
                <span className="muted trends-cluster-q">{s.quarter}</span>
                <span className="trends-cluster-label">{s.peer_cluster_label ?? '—'}</span>
              </div>
            ))}
          </div>
          <p className="muted chart-caption trends-cluster-caveat">
            {trends.cluster_mode === 'fixed'
              ? 'Assigned against fixed reference-quarter centroids (not refit each quarter) — a ' +
                'label change here reflects real behavioral movement, not k-means landing ' +
                'differently this quarter.'
              : 'Behavioral clusters are recomputed independently each quarter (k-means over ' +
                'that quarter\'s whole population) — a bank sitting near a cluster boundary ' +
                'can show label changes here even with a stable balance sheet. Run ' +
                'cluster_centroids_cli to enable fixed-centroid assignment and remove this noise.'}
          </p>

          <div className="trends-grid">
            {PANELS.map((p) => (
              <div key={p.title} className="trends-chart-box">
                <h3 className="trends-chart-title">{p.title}</h3>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={chartData} margin={{ top: 4, right: 8, left: -8, bottom: 0 }}>
                    <CartesianGrid stroke={colors.gridline} vertical={false} />
                    <XAxis dataKey="quarter" tick={{ fill: colors.muted, fontSize: 10 }}
                      axisLine={{ stroke: colors.baseline }} tickLine={false} />
                    <YAxis tick={{ fill: colors.muted, fontSize: 10 }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip content={<CustomTooltip suffix={p.suffix} />} />
                    {p.lines.length > 1 && <Legend wrapperStyle={{ fontSize: 10 }} />}
                    {p.lines.map((l) => (
                      <Line key={l.key} type="monotone" dataKey={l.key} name={l.label}
                        stroke={colors[l.color]} strokeWidth={2} dot={{ r: 2.5 }}
                        animationDuration={600} animationEasing="ease-out" connectNulls />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && !trends && <div className="panel"><p className="muted">Loading…</p></div>}
    </div>
  );
}
