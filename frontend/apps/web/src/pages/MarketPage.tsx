import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import type { EChartsOption } from 'echarts';
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import { api, type BankSearchResult } from '../api';
import { chartColors } from '../colors';
import { EChart } from '../components/EChart';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { ExportCsvButton } from '../components/ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import type { MarketMetricsRow, MarketOverviewResult } from '../types';
import '../components/charts.css';
import './MarketPage.css';

const MAX_CUSTOM_BANKS = 12;
const TOP_N_OPTIONS = [10, 15, 20, 30];
const WINDOW_OPTIONS: { value: number; label: string }[] = [
  { value: 90, label: '~90 trading days' },
  { value: 180, label: '~180 trading days' },
  { value: 365, label: '~365 trading days' },
];

type SortKey = keyof Pick<MarketMetricsRow,
  'name' | 'total_return_pct' | 'realized_volatility_pct' | 'vol_vs_peer_median_pct' |
  'max_drawdown_pct' | 'beta_vs_peer_basket' | 'tangible_book_value_usd'>;

function fmtPct(v: number | null, decimals = 2): string {
  if (v === null || v === undefined) return '—';
  return `${v > 0 ? '+' : ''}${v.toFixed(decimals)}%`;
}

function fmtRatio(v: number | null): string {
  if (v === null || v === undefined) return '—';
  return v.toFixed(2);
}

function fmtUsd(v: number | null): string {
  if (v === null || v === undefined) return '—';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  return `${sign}$${abs.toLocaleString()}`;
}

// Categorical palette cycled across as many priced banks as are in view —
// the same 8 tokens theme.css defines for every other multi-series chart in
// the product (see colors.ts), not a bespoke palette for this page alone.
function palette(colors: ReturnType<typeof chartColors>): string[] {
  return [colors.blue, colors.green, colors.magenta, colors.yellow,
          colors.aqua, colors.orange, colors.violet, colors.red];
}

function PerfTooltip({ active, payload, label }: {
  active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">{label}</div>
      {payload.slice(0, 10).map((p) => (
        <div key={p.name} className="chart-tooltip-value tabular" style={{ color: p.color, fontSize: 'var(--text-xs)' }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : '—'}
        </div>
      ))}
    </motion.div>
  );
}

function ScatterTooltip({ active, payload }: {
  active?: boolean; payload?: { payload: { name: string; return_pct: number | null; volatility_pct: number | null } }[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">{d.name}</div>
      <div className="chart-tooltip-sub">Return: {fmtPct(d.return_pct)}</div>
      <div className="chart-tooltip-sub">Realized vol (ann.): {fmtPct(d.volatility_pct, 1)}</div>
    </motion.div>
  );
}

export function MarketPage() {
  const [topN, setTopN] = useState(15);
  const [windowDays, setWindowDays] = useState(180);
  const [customBanks, setCustomBanks] = useState<{ cert: number; name: string }[]>([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BankSearchResult['banks']>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  const [result, setResult] = useState<MarketOverviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [sortKey, setSortKey] = useState<SortKey>('realized_volatility_pct');
  const [descending, setDescending] = useState(true);

  const colors = chartColors();
  const useCustom = customBanks.length >= 2;

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      api.searchBanks(query, undefined, 8)
        .then((r) => {
          setResults(r.banks.filter((b) => !customBanks.some((c) => c.cert === b.cert)));
          setPickerOpen(true);
        })
        .catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [query, customBanks]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setPickerOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  useEffect(() => {
    setLoading(true);
    api.marketOverview(useCustom
      ? { certs: customBanks.map((b) => b.cert), window_days: windowDays }
      : { top_n: topN, window_days: windowDays })
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => { setError(e.message); setResult(null); })
      .finally(() => setLoading(false));
  }, [topN, windowDays, useCustom, customBanks]);

  function addBank(cert: number, name: string) {
    if (customBanks.length >= MAX_CUSTOM_BANKS || customBanks.some((b) => b.cert === cert)) return;
    setCustomBanks((b) => [...b, { cert, name }]);
    setQuery('');
    setPickerOpen(false);
  }

  function removeBank(cert: number) {
    setCustomBanks((b) => b.filter((x) => x.cert !== cert));
  }

  function toggleSort(key: SortKey) {
    if (key === sortKey) { setDescending((d) => !d); return; }
    setSortKey(key);
    setDescending(true);
  }

  const pal = palette(colors);

  // ---- relative performance: one recharts row per shared trading date ----
  const perfData = useMemo(() => {
    if (!result) return { rows: [] as Record<string, number | string | null>[], series: [] as { cert: number; name: string }[] };
    const seriesMaps = result.performance_series.map((s) => ({
      cert: s.cert, name: s.name, map: new Map(s.series.map((p) => [p.date, p.value])),
    }));
    const dates = new Set<string>();
    seriesMaps.forEach((s) => s.map.forEach((_, d) => dates.add(d)));
    const sortedDates = [...dates].sort();
    const rows = sortedDates.map((date) => {
      const row: Record<string, number | string | null> = { date };
      seriesMaps.forEach((s) => { row[`c${s.cert}`] = s.map.get(date) ?? null; });
      return row;
    });
    return { rows, series: seriesMaps.map((s) => ({ cert: s.cert, name: s.name })) };
  }, [result]);

  // ---- correlation heatmap option ----
  const corrOption = useMemo(() => {
    if (!result || result.correlation.certs.length < 2) return {} as EChartsOption;
    const theme = baseEChartTheme();
    const { labels, matrix } = result.correlation;
    const data: [number, number, number | null][] = [];
    matrix.forEach((row, y) => row.forEach((v, x) => data.push([x, y, v])));
    const opt: EChartsOption = {
      grid: { left: 160, right: 24, top: 16, bottom: 90, containLabel: false },
      tooltip: {
        ...tooltipStyle(),
        formatter: (p: unknown) => {
          const cell = (Array.isArray(p) ? p[0] : p) as { data?: [number, number, number | null] };
          if (!cell.data) return '';
          const [x, y, v] = cell.data;
          return `<strong>${labels[y]}</strong> vs <strong>${labels[x]}</strong><br/>`
            + (v === null ? 'not enough overlapping trading days' : `correlation: ${v.toFixed(2)}`);
        },
      },
      xAxis: {
        type: 'category', data: labels,
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5, rotate: 40 },
        axisLine: theme.axisLine, splitArea: { show: true },
      },
      yAxis: {
        type: 'category', data: labels,
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5 },
        axisLine: theme.axisLine, inverse: true,
      },
      visualMap: {
        min: -1, max: 1, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 0,
        inRange: { color: [colors.divNeg, colors.surface2, colors.divPos] },
        textStyle: { color: theme.textStyle.color },
      },
      series: [{
        type: 'heatmap', data,
        emphasis: { itemStyle: { borderColor: colors.text, borderWidth: 1 } },
        itemStyle: { borderColor: colors.surface, borderWidth: 1 },
      }],
    };
    return opt;
  }, [result, colors]);

  const sortedMetrics = useMemo(() => {
    if (!result) return [];
    return [...result.metrics].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv));
      return descending ? -cmp : cmp;
    });
  }, [result, sortKey, descending]);

  const csvColumns: CsvColumn<MarketMetricsRow>[] = [
    { key: 'name', label: 'Bank', value: (r) => r.name, source: 'fdic' },
    { key: 'ticker', label: 'Ticker', value: (r) => r.ticker ?? '', source: 'tiingo' },
    { key: 'total_return_pct', label: `Total return % (${result?.window_days ?? ''}d window)`, value: (r) => r.total_return_pct ?? '', source: 'tiingo' },
    { key: 'realized_volatility_pct', label: 'Realized volatility % (ann.)', value: (r) => r.realized_volatility_pct ?? '', source: 'tiingo' },
    { key: 'vol_vs_peer_median_pct', label: 'Vol vs peer median (pp)', value: (r) => r.vol_vs_peer_median_pct ?? '', source: 'derived' },
    { key: 'max_drawdown_pct', label: 'Max drawdown %', value: (r) => r.max_drawdown_pct ?? '', source: 'tiingo' },
    { key: 'beta_vs_peer_basket', label: 'Beta vs equal-weighted peer basket', value: (r) => r.beta_vs_peer_basket ?? '', source: 'derived' },
    { key: 'tangible_book_value_usd', label: 'Tangible book value ($)', value: (r) => r.tangible_book_value_usd ?? '', source: 'fdic' },
    { key: 'price_to_tangible_book_value', label: 'Price / tangible book value', value: () => 'not available (no landed shares-outstanding data)', source: 'derived' },
    { key: 'price_to_earnings', label: 'Price / earnings', value: () => 'not available (no landed diluted-EPS data)', source: 'derived' },
  ];

  return (
    <div className="market-page">
      <div className="panel">
        <h2>Market</h2>
        <p className="muted market-subtitle">
          E2 — cross-bank view of real landed Tiingo prices: relative performance,
          a returns/volatility scatter, a pairwise return-correlation matrix, and a
          per-bank metrics table. Only banks with a crosswalk-matched ticker AND a
          landed price history feed the charts below — coverage is stated exactly,
          not silently narrowed.
        </p>

        <div className="market-controls">
          <div className="market-control-group">
            <label className="muted market-control-label">Peer set</label>
            <div className="market-picker" ref={boxRef}>
              <input
                className="market-picker-input"
                placeholder={customBanks.length >= MAX_CUSTOM_BANKS
                  ? `Maximum ${MAX_CUSTOM_BANKS} banks` : 'Search a bank to pin to a custom set…'}
                value={query}
                disabled={customBanks.length >= MAX_CUSTOM_BANKS}
                onChange={(e) => setQuery(e.target.value)}
                onFocus={() => results.length > 0 && setPickerOpen(true)}
              />
              <AnimatePresence>
                {pickerOpen && results.length > 0 && (
                  <motion.div
                    className="market-picker-results"
                    initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.16 }}
                  >
                    {results.map((b) => (
                      <button key={b.cert} className="market-picker-result" onClick={() => addBank(b.cert, b.name)}>
                        <span>{b.name}</span>
                        <span className="muted">${b.assets_b.toFixed(1)}B · {b.state ?? '—'}</span>
                      </button>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
          {!useCustom && (
            <div className="market-control-group">
              <label className="muted market-control-label">Top-N by assets</label>
              <select className="market-select" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
                {TOP_N_OPTIONS.map((n) => <option key={n} value={n}>{n} banks</option>)}
              </select>
            </div>
          )}
          <div className="market-control-group">
            <label className="muted market-control-label">Window</label>
            <select className="market-select" value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))}>
              {WINDOW_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        </div>

        {customBanks.length > 0 && (
          <div className="market-chips">
            {customBanks.map((b) => (
              <div key={b.cert} className="market-chip">
                <Link to={`/bank/${b.cert}`} className="market-chip-name">{b.name}</Link>
                <button className="market-chip-remove" onClick={() => removeBank(b.cert)} aria-label={`Remove ${b.name}`}>×</button>
              </div>
            ))}
            {customBanks.length === 1 && <span className="muted market-chip-hint">Add one more to use this as the peer set (else Top-N applies).</span>}
          </div>
        )}

        {error && <p className="app-banner-error">{error}</p>}
        {loading && !result && <p className="muted">Loading…</p>}

        {result && (
          <p className="muted market-coverage-banner">
            <strong>{result.coverage_note}</strong> Quarter {result.quarter} · beta is
            computed against an equal-weighted basket of every priced bank shown here
            (no dedicated bank-index ticker is landed — see the metrics table note
            below), not a market index.
          </p>
        )}
      </div>

      {result && result.priced_count === 0 && (
        <div className="panel">
          <p className="muted">
            None of the {result.requested_count} banks in this view have landed price
            data yet. Market data needs its own free Tiingo API key and lands over
            time under a persisted hourly-budget cursor — see
            <code> scripts/land_market_data.ps1</code>.
          </p>
        </div>
      )}

      {result && result.priced_count > 0 && (
        <>
          <div className="panel">
            <h2>Relative performance (rebased to 100)</h2>
            <p className="muted chart-caption">
              Each priced bank's adjusted close, rebased to 100 at the first bar of
              its own windowed series — comparable trajectories regardless of price
              level.
            </p>
            <ResponsiveContainer width="100%" height={360}>
              <LineChart data={perfData.rows} margin={{ top: 8, right: 16, left: -8, bottom: 4 }}>
                <CartesianGrid stroke={colors.gridline} />
                <XAxis dataKey="date" tick={{ fill: colors.muted, fontSize: 10 }}
                  axisLine={{ stroke: colors.baseline }} tickLine={false}
                  interval="preserveStartEnd" minTickGap={40} />
                <YAxis tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false}
                  domain={['auto', 'auto']} />
                <Tooltip content={<PerfTooltip />} />
                {perfData.series.length <= 15 && <Legend wrapperStyle={{ fontSize: 11 }} />}
                {perfData.series.map((s, i) => (
                  <Line key={s.cert} type="monotone" dataKey={`c${s.cert}`} name={s.name}
                    stroke={pal[i % pal.length]} dot={false} strokeWidth={1.5}
                    connectNulls animationDuration={500} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="panel">
            <h2>Return vs realized volatility</h2>
            <p className="muted chart-caption">
              One point per priced bank — total return over the window (y) against
              annualized realized volatility over the same window (x).
            </p>
            <ResponsiveContainer width="100%" height={340}>
              <ScatterChart margin={{ top: 8, right: 16, left: -8, bottom: 4 }}>
                <CartesianGrid stroke={colors.gridline} />
                <XAxis type="number" dataKey="volatility_pct" name="Volatility" unit="%"
                  tick={{ fill: colors.muted, fontSize: 11 }} axisLine={{ stroke: colors.baseline }} tickLine={false}
                  label={{ value: 'Realized volatility % (annualized)', position: 'insideBottom', offset: -2, fill: colors.muted, fontSize: 11 }} />
                <YAxis type="number" dataKey="return_pct" name="Return" unit="%"
                  tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false}
                  label={{ value: 'Total return %', angle: -90, position: 'insideLeft', fill: colors.muted, fontSize: 11 }} />
                <ZAxis range={[50, 50]} />
                <Tooltip content={<ScatterTooltip />} cursor={{ strokeDasharray: '3 3', stroke: colors.baseline }} />
                <Scatter data={result.scatter} fill={colors.blue} fillOpacity={0.75} animationDuration={500} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>

          <div className="panel">
            <h2>Return correlation matrix</h2>
            <p className="muted chart-caption">
              Pairwise Pearson correlation of daily returns among priced banks over
              shared trading days (min. 10 overlapping days; grey/blank cells mean
              too little overlap to compute).
            </p>
            {result.correlation.certs.length >= 2 ? (
              <EChart
                option={corrOption}
                height={Math.max(360, result.correlation.labels.length * 22 + 120)}
                resetKey={`${result.quarter}-${result.correlation.certs.join(',')}`}
                ariaLabel="Pairwise return correlation heatmap across priced banks"
              />
            ) : (
              <p className="muted">Need at least 2 priced banks to compute a correlation matrix.</p>
            )}
          </div>

          <div className="panel">
            <h2>Per-bank market metrics</h2>
            <p className="muted market-metrics-note">
              {result.per_share_metrics_note}
            </p>
            <div className="market-export-row">
              <ExportCsvButton
                filename="banklens-market-metrics.csv"
                columns={csvColumns}
                rows={sortedMetrics}
                meta={{ vintage: result.quarter, sourceLabel: 'Tiingo EOD prices + FDIC Call Reports' }}
              />
            </div>
            <div className="market-table-wrap">
              <table className="market-table">
                <thead>
                  <tr>
                    <th className="market-th market-th-sortable" onClick={() => toggleSort('name')}>Bank{sortKey === 'name' ? (descending ? ' ▼' : ' ▲') : ''}</th>
                    <th className="market-th">Ticker</th>
                    <th className="market-th market-th-right market-th-sortable" onClick={() => toggleSort('total_return_pct')}>Return{sortKey === 'total_return_pct' ? (descending ? ' ▼' : ' ▲') : ''}</th>
                    <th className="market-th market-th-right market-th-sortable" onClick={() => toggleSort('realized_volatility_pct')}>Volatility{sortKey === 'realized_volatility_pct' ? (descending ? ' ▼' : ' ▲') : ''}</th>
                    <th className="market-th market-th-right market-th-sortable" onClick={() => toggleSort('vol_vs_peer_median_pct')}>Vol vs peer median{sortKey === 'vol_vs_peer_median_pct' ? (descending ? ' ▼' : ' ▲') : ''}</th>
                    <th className="market-th market-th-right market-th-sortable" onClick={() => toggleSort('max_drawdown_pct')}>Max drawdown{sortKey === 'max_drawdown_pct' ? (descending ? ' ▼' : ' ▲') : ''}</th>
                    <th className="market-th market-th-right market-th-sortable" onClick={() => toggleSort('beta_vs_peer_basket')}>Beta{sortKey === 'beta_vs_peer_basket' ? (descending ? ' ▼' : ' ▲') : ''}</th>
                    <th className="market-th market-th-right market-th-sortable" onClick={() => toggleSort('tangible_book_value_usd')}>Tangible book value{sortKey === 'tangible_book_value_usd' ? (descending ? ' ▼' : ' ▲') : ''}</th>
                    <th className="market-th market-th-right" title="Not computed — no landed shares-outstanding data">P/TBV</th>
                    <th className="market-th market-th-right" title="Not computed — no landed diluted-EPS data">P/E</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedMetrics.map((r) => (
                    <tr key={r.cert} className="market-row">
                      <td className="market-td-name"><Link to={`/bank/${r.cert}`}>{r.name}</Link></td>
                      <td className="muted">{r.ticker}</td>
                      <td className={`tabular market-td-right ${(r.total_return_pct ?? 0) >= 0 ? 'market-up' : 'market-down'}`}>{fmtPct(r.total_return_pct)}</td>
                      <td className="tabular market-td-right">{fmtPct(r.realized_volatility_pct, 1)}</td>
                      <td className="tabular market-td-right">{r.vol_vs_peer_median_pct === null ? '—' : `${r.vol_vs_peer_median_pct > 0 ? '+' : ''}${r.vol_vs_peer_median_pct.toFixed(1)}pp`}</td>
                      <td className="tabular market-td-right market-down">{fmtPct(r.max_drawdown_pct, 1)}</td>
                      <td className="tabular market-td-right">{fmtRatio(r.beta_vs_peer_basket)}</td>
                      <td className="tabular market-td-right">{fmtUsd(r.tangible_book_value_usd)}</td>
                      <td className="tabular market-td-right muted">n/a</td>
                      <td className="tabular market-td-right muted">n/a</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {result && result.banks.some((b) => !b.has_price_data) && (
        <div className="panel">
          <h2>Banks in view without landed price data</h2>
          <ul className="market-uncovered-list">
            {result.banks.filter((b) => !b.has_price_data).map((b) => (
              <li key={b.cert}>
                <Link to={`/bank/${b.cert}`}>{b.name}</Link>
                <span className="muted">{b.ticker ? ` — ticker ${b.ticker} matched, price not landed yet` : ' — no crosswalk-matched ticker'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
