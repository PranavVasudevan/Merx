import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api, type BankSearchResult } from '../api';
import { categoricalPalette, chartColors } from '../colors';
import { RECHARTS_ENTRANCE } from '../chartMotion';
import { usePeerSet } from '../PeerSetContext';
import { ChartTooltipShell } from '../components/ChartTooltip';
import type { BankTrendsResult, BulkBankTrendsResult } from '../types';
import '../components/charts.css';
import './TrendsPage.css';

// E10 — one representative metric per PANELS category above, so a 12-bank peer
// set renders 5 readable small-multiples (12 lines each) instead of pairing
// two metrics per panel like the single-bank view does (which would put 24
// lines on one chart).
interface SmallMultiple { key: string; title: string; suffix: string; transform?: (v: number) => number }
const SMALL_MULTIPLES: SmallMultiple[] = [
  { key: 'total_assets', title: 'Total assets ($B)', suffix: 'B', transform: (v) => v / 1e9 },
  { key: 'roa_pct_quarterly', title: 'ROA (quarter-isolated)', suffix: '%' },
  { key: 'npl_ratio_pct', title: 'NPL ratio', suffix: '%' },
  { key: 'uninsured_deposit_pct', title: 'Uninsured deposits', suffix: '%' },
  { key: 'cet1_ratio', title: 'CET1 ratio', suffix: '%' },
];

/** Linear-interpolated percentile (numpy/Excel PERCENTILE.INC convention) over
 * an already-sorted ascending array. Returns null for an empty input — a
 * quarter where every bank in the set is missing this metric. */
function percentile(sortedVals: number[], p: number): number | null {
  if (sortedVals.length === 0) return null;
  if (sortedVals.length === 1) return sortedVals[0];
  const idx = (p / 100) * (sortedVals.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sortedVals[lo];
  return sortedVals[lo] + (sortedVals[hi] - sortedVals[lo]) * (idx - lo);
}

const bankKey = (cert: number) => `c${cert}`;

/** Per-quarter rows for one metric panel: each bank's own value under its
 * `c<cert>` key, plus a peer p25/p75 band and bold median computed client-side
 * from the SAME bulk-fetched series (no extra request, no synthetic fill —
 * a quarter with fewer landed banks just has a narrower/absent band). */
function buildPanelData(bulk: BulkBankTrendsResult, sm: SmallMultiple) {
  const transform = sm.transform ?? ((v: number) => v);
  return bulk.quarters.map((quarter) => {
    const row: Record<string, number | string | [number, number] | null> = { quarter };
    const vals: number[] = [];
    for (const b of bulk.banks) {
      const pt = b.series.find((s) => s.quarter === quarter);
      const raw = pt?.[sm.key];
      const v = typeof raw === 'number' ? transform(raw) : null;
      row[bankKey(b.cert)] = v;
      if (v !== null && Number.isFinite(v)) vals.push(v);
    }
    vals.sort((a, b) => a - b);
    const p25 = percentile(vals, 25);
    const p75 = percentile(vals, 75);
    row.median = percentile(vals, 50);
    row.band = p25 !== null && p75 !== null ? [p25, p75] : null;
    return row;
  });
}

function PeerTrendsTooltip({ active, payload, label, suffix, names }: {
  active?: boolean; payload?: { dataKey: string; value: number | [number, number]; color: string }[];
  label?: string; suffix: string; names: Record<string, string>;
}) {
  if (!active || !payload?.length) return null;
  const lines = payload
    .filter((p) => p.dataKey !== 'band' && typeof p.value === 'number')
    .map((p) => ({
      text: `${p.dataKey === 'median' ? 'Peer median' : names[p.dataKey] ?? p.dataKey}: ${(p.value as number).toFixed(2)}${suffix}`,
      style: { color: p.color },
    }));
  return <ChartTooltipShell label={label} lines={lines} />;
}

interface Panel { title: string; lines: { key: string; label: string; color: keyof ReturnType<typeof chartColors> }[]; suffix: string }

const PANELS: Panel[] = [
  { title: 'Total assets ($B)', suffix: 'B',
    lines: [{ key: 'total_assets', label: 'Assets', color: 'blue' }] },
  // C15: FDIC's roa_pct/net_interest_margin_pct are YTD-annualized (a Q1 value
  // and a Q4 value for the same bank blend different amounts of the year, not
  // comparable on one line) — plotting the quarter-isolated counterparts
  // instead, computed from the YTD dollar deltas (gold.quarterly_isolated_ratios).
  { title: 'Profitability (quarter-isolated)', suffix: '%',
    lines: [{ key: 'roa_pct_quarterly', label: 'ROA', color: 'green' },
            { key: 'net_interest_margin_pct_quarterly', label: 'NIM', color: 'aqua' }] },
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
  const lines = payload.map((p) => ({
    text: `${p.name}: ${p.value?.toFixed(2)}${suffix}`,
    style: { color: p.color },
  }));
  return <ChartTooltipShell label={label} lines={lines} />;
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
  const palette = categoricalPalette();

  // E10 — active peer set's trajectories, batched in one request rather than
  // one bankTrends() call per bank in the set.
  const { activePeerSet } = usePeerSet();
  const [peerTrends, setPeerTrends] = useState<BulkBankTrendsResult | null>(null);
  const [peerError, setPeerError] = useState<string | null>(null);
  const [peerLoading, setPeerLoading] = useState(false);

  useEffect(() => {
    if (!activePeerSet || activePeerSet.certs.length === 0) { setPeerTrends(null); setPeerError(null); return; }
    setPeerLoading(true);
    api.bulkBankTrends(activePeerSet.certs)
      .then((r) => { setPeerTrends(r); setPeerError(null); })
      .catch((e: Error) => { setPeerError(e.message); setPeerTrends(null); })
      .finally(() => setPeerLoading(false));
  }, [activePeerSet]);

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
                {p.title.includes('quarter-isolated') && (
                  <p className="muted chart-caption trends-ytd-caveat">
                    FDIC reports ROA/NIM year-to-date annualized (a Q4 value blends the
                    whole year, a Q1 value is one quarter) — these are de-cumulated to
                    each quarter's own figure instead.
                  </p>
                )}
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
                        {...RECHARTS_ENTRANCE} connectNulls />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </div>
      )}

      {activePeerSet && (
        <div className="panel">
          <h2>Peer set — {activePeerSet.name}</h2>
          <p className="muted trends-subtitle">
            Every bank in this saved peer set, overlaid one small chart per metric, with the
            set's own p25–p75 band (shaded) and median (bold line) computed from these {activePeerSet.certs.length} banks'
            real landed history — not the whole population.
          </p>
          {peerError && <p className="app-banner-error">{peerError}</p>}
          {peerLoading && !peerTrends && <p className="muted">Loading peer set trends…</p>}
          {peerTrends && (
            <>
              <div className="trends-peer-legend">
                {peerTrends.banks.map((b, i) => (
                  <span key={b.cert} className="trends-peer-legend-item">
                    <span className="trends-peer-legend-swatch" style={{ background: palette[i % palette.length] }} />
                    {b.name}
                  </span>
                ))}
                <span className="trends-peer-legend-item">
                  <span className="trends-peer-legend-swatch trends-peer-legend-median" style={{ background: colors.text }} />
                  Peer median (p25–p75 band shaded)
                </span>
              </div>
              <div className="trends-grid">
                {SMALL_MULTIPLES.map((sm) => {
                  const data = buildPanelData(peerTrends, sm);
                  const names = Object.fromEntries(peerTrends.banks.map((b) => [bankKey(b.cert), b.name]));
                  return (
                    <div key={sm.key} className="trends-chart-box">
                      <h3 className="trends-chart-title">{sm.title}</h3>
                      <ResponsiveContainer width="100%" height={180}>
                        <ComposedChart data={data} margin={{ top: 4, right: 8, left: -8, bottom: 0 }}>
                          <CartesianGrid stroke={colors.gridline} vertical={false} />
                          <XAxis dataKey="quarter" tick={{ fill: colors.muted, fontSize: 10 }}
                            axisLine={{ stroke: colors.baseline }} tickLine={false} />
                          <YAxis tick={{ fill: colors.muted, fontSize: 10 }} axisLine={false} tickLine={false} width={36} />
                          <Tooltip content={<PeerTrendsTooltip suffix={sm.suffix} names={names} />} />
                          <Area dataKey="band" stroke="none" fill={colors.blue} fillOpacity={0.14}
                            isAnimationActive={false} connectNulls />
                          {peerTrends.banks.map((b, i) => (
                            <Line key={b.cert} type="monotone" dataKey={bankKey(b.cert)} name={b.name}
                              stroke={palette[i % palette.length]} strokeWidth={1.25} dot={false}
                              isAnimationActive={false} connectNulls />
                          ))}
                          <Line type="monotone" dataKey="median" name="Peer median" stroke={colors.text}
                            strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>
                  );
                })}
              </div>
              {peerTrends.skipped.length > 0 && (
                <p className="muted trends-peer-skipped">
                  Skipped (no landed history): {peerTrends.skipped.map((s) => `CERT ${s.cert}`).join(', ')}
                </p>
              )}
            </>
          )}
        </div>
      )}

      {loading && !trends && <div className="panel"><p className="muted">Loading…</p></div>}
    </div>
  );
}
