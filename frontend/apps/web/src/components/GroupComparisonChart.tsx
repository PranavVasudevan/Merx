import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import type { BoxplotSeriesOption, ScatterSeriesOption } from 'echarts/charts';
import { EChart } from './EChart';
import { BankSearch } from './BankSearch';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { api } from '../api';
import { categoricalPalette, chartColors } from '../colors';
import { pct } from '../metricFormat';
import type { MetricGroup, PopulationMetricRow } from '../types';
import { ExportCsvButton } from './ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import './GroupComparisonChart.css';

// A curated cross-group metric list (mirrors the Distributions page's own
// selector) but each option is tagged with the backend METRIC_GROUPS key it
// actually lives in (services/mcp-server/src/banklens_mcp/tools.py) — capital
// and concentration are two different groups server-side even though the
// Distributions page's UI folds them into one visual section.
const METRIC_OPTIONS: { section: string; metricGroup: MetricGroup; options: { value: string; label: string }[] }[] = [
  { section: 'Earnings', metricGroup: 'earnings', options: [
    { value: 'roa_pct', label: 'Return on assets' },
    { value: 'roe_pct', label: 'Return on equity' },
    { value: 'net_interest_margin_pct', label: 'Net interest margin' },
    { value: 'efficiency_ratio_pct', label: 'Efficiency ratio' },
  ] },
  { section: 'Credit quality', metricGroup: 'credit', options: [
    { value: 'npl_ratio_pct', label: 'NPL ratio' },
    { value: 'net_charge_off_rate_pct', label: 'Net charge-off rate' },
    { value: 'texas_ratio_pct', label: 'Texas Ratio' },
    { value: 'allowance_coverage_pct', label: 'Allowance coverage' },
  ] },
  { section: 'Funding', metricGroup: 'funding', options: [
    { value: 'uninsured_deposit_pct', label: 'Uninsured deposits' },
    { value: 'brokered_deposit_pct', label: 'Brokered deposits' },
    { value: 'loan_to_deposit_pct', label: 'Loan / deposit' },
    { value: 'core_deposit_pct', label: 'Core deposits' },
  ] },
  { section: 'Capital', metricGroup: 'capital', options: [
    { value: 'cet1_ratio', label: 'CET1 ratio' },
    { value: 'leverage_ratio', label: 'Leverage ratio' },
    { value: 'cre_to_total_capital_pct', label: 'CRE / total capital' },
  ] },
  { section: 'Concentration', metricGroup: 'concentration', options: [
    { value: 'concentration_ratio_cre', label: 'CRE concentration' },
    { value: 'concentration_ratio_c_and_i', label: 'C&I concentration' },
    { value: 'max_loan_concentration_pct', label: 'Max sector concentration' },
  ] },
];

type GroupBy = 'cluster' | 'size_band' | 'state' | 'country' | 'peer_set';

const GROUP_BY_OPTIONS: { value: GroupBy; label: string }[] = [
  { value: 'cluster', label: 'Behavioral cluster' },
  { value: 'size_band', label: 'Size band' },
  { value: 'state', label: 'State (US)' },
  { value: 'country', label: 'Country (US + EU)' },
  { value: 'peer_set', label: 'Custom peer set vs. rest' },
];

// Same conventional size bands _size_bucket() in
// services/mcp-server/src/banklens_mcp/tools.py uses for the cluster
// diagnostics page, reused here so "size band" means the same thing on both
// pages rather than a second, slightly different bucketing scheme.
const SIZE_BUCKETS: [number, string][] = [
  [1e9, 'Community bank (under $1B)'],
  [10e9, 'Community ($1B-$10B)'],
  [50e9, 'Regional ($10B-$50B)'],
  [250e9, 'Super-regional ($50B-$250B)'],
  [Infinity, 'Global systemically important (over $250B)'],
];
const SIZE_BUCKET_ORDER = SIZE_BUCKETS.map(([, label]) => label);

function sizeBucket(assets: number | null): string {
  if (assets === null || assets === undefined) return 'Unknown';
  for (const [cutoff, label] of SIZE_BUCKETS) if (assets < cutoff) return label;
  return SIZE_BUCKETS[SIZE_BUCKETS.length - 1][1];
}

const MIN_GROUP_N = 3; // fewer than this and a box/whisker plot is not a meaningful shape

interface BoxStats {
  name: string;
  n: number;
  min: number; q1: number; median: number; q3: number; max: number;
  whiskerLow: number; whiskerHigh: number;
  outliers: number[];
}

interface BankPoint { cert: number; name: string; value: number; group: string }

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] !== undefined
    ? sorted[base] + rest * (sorted[base + 1] - sorted[base])
    : sorted[base];
}

function computeBoxStats(name: string, values: number[]): BoxStats {
  const sorted = [...values].sort((a, b) => a - b);
  const q1 = quantile(sorted, 0.25);
  const median = quantile(sorted, 0.5);
  const q3 = quantile(sorted, 0.75);
  const iqr = q3 - q1;
  const lowerFence = q1 - 1.5 * iqr;
  const upperFence = q3 + 1.5 * iqr;
  const inFence = sorted.filter((v) => v >= lowerFence && v <= upperFence);
  const whiskerLow = inFence.length ? inFence[0] : sorted[0];
  const whiskerHigh = inFence.length ? inFence[inFence.length - 1] : sorted[sorted.length - 1];
  const outliers = sorted.filter((v) => v < whiskerLow || v > whiskerHigh);
  return {
    name, n: sorted.length, min: sorted[0], q1, median, q3, max: sorted[sorted.length - 1],
    whiskerLow, whiskerHigh, outliers,
  };
}

/**
 * E5 — a metric's distribution SHAPE across behavioral clusters, size bands,
 * states, countries or a user-built peer set, not just its ranking or one
 * global histogram (that's DistributionsPage's own chart, above/beside this
 * one). An ECharts boxplot per group, with an optional jittered-scatter
 * ("beeswarm") overlay showing every individual bank.
 *
 * Chose beeswarm over a true violin: ECharts has no native violin series, and
 * a violin needs a custom series that KDE-renders its own path per category —
 * meaningfully more code and a second numerical routine (bandwidth selection)
 * to get right and keep right. A jittered scatter reuses the same per-bank
 * values already fetched for the boxplot, needs no extra math, and still
 * answers the actual question ("is this cluster bimodal, skewed, tight?") by
 * showing every real data point instead of a smoothed density estimate.
 *
 * Data: population-metrics (get_population_metrics), the same tool
 * MetricGroupPage's earnings/credit/funding/capital/concentration pages already
 * call — one request per metric GROUP returns every bank's cert, state,
 * country, total_assets, peer_cluster_label and every metric in that group, so
 * quartiles/grouping are computed here client-side rather than adding a new
 * backend endpoint.
 */
export function GroupComparisonChart() {
  const navigate = useNavigate();
  const [metric, setMetric] = useState('cre_to_total_capital_pct');
  const [groupBy, setGroupBy] = useState<GroupBy>('cluster');
  const [showBeeswarm, setShowBeeswarm] = useState(false);
  const [rows, setRows] = useState<PopulationMetricRow[] | null>(null);
  const [quarter, setQuarter] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [peerSet, setPeerSet] = useState<{ cert: number; name: string }[]>([]);

  const selectedOption = METRIC_OPTIONS.flatMap((g) => g.options.map((o) => ({ ...o, metricGroup: g.metricGroup })))
    .find((o) => o.value === metric);
  const metricGroup = selectedOption?.metricGroup ?? 'capital';
  const metricLabel = selectedOption?.label ?? metric;

  useEffect(() => {
    setRows(null);
    setError(null);
    api.populationMetrics(metricGroup, { limit: 5000 })
      .then((r) => { setRows(r.banks); setQuarter(r.quarter); })
      .catch((e: Error) => setError(e.message));
  }, [metricGroup]);

  const peerCerts = useMemo(() => new Set(peerSet.map((b) => b.cert)), [peerSet]);

  function addPeer(cert: number, name: string) {
    setPeerSet((s) => (s.some((b) => b.cert === cert) ? s : [...s, { cert, name }]));
  }
  function removePeer(cert: number) {
    setPeerSet((s) => s.filter((b) => b.cert !== cert));
  }

  const { boxes, points, excluded } = useMemo(() => {
    if (!rows) return { boxes: [] as BoxStats[], points: [] as BankPoint[], excluded: [] as { name: string; n: number }[] };

    const byGroup = new Map<string, { cert: number; name: string; value: number }[]>();
    for (const r of rows) {
      const raw = r[metric];
      if (typeof raw !== 'number' || Number.isNaN(raw)) continue;
      let g: string;
      if (groupBy === 'cluster') g = r.peer_cluster_label ?? 'Unclassified';
      else if (groupBy === 'state') g = r.state ?? 'Unknown';
      else if (groupBy === 'country') g = (r.country as string | null) ?? 'Unknown';
      else if (groupBy === 'size_band') g = sizeBucket(r.total_assets);
      else g = peerCerts.has(r.cert_number) ? 'Selected peer set' : 'Rest of population';
      if (groupBy === 'peer_set' && peerCerts.size === 0) continue;
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g)!.push({ cert: r.cert_number, name: r.name, value: raw });
    }

    const included: BoxStats[] = [];
    const excl: { name: string; n: number }[] = [];
    const pts: BankPoint[] = [];
    for (const [name, entries] of byGroup) {
      if (entries.length < MIN_GROUP_N) { excl.push({ name, n: entries.length }); continue; }
      included.push(computeBoxStats(name, entries.map((e) => e.value)));
      for (const e of entries) pts.push({ cert: e.cert, name: e.name, value: e.value, group: name });
    }

    // Ordering: size bands get their natural small->large order; peer-set gets
    // a fixed [selected, rest]; everything else (cluster/state/country) sorts
    // by median descending so the highest-median group reads left-to-right.
    if (groupBy === 'size_band') {
      included.sort((a, b) => SIZE_BUCKET_ORDER.indexOf(a.name) - SIZE_BUCKET_ORDER.indexOf(b.name));
    } else if (groupBy === 'peer_set') {
      included.sort((a) => (a.name === 'Selected peer set' ? -1 : 1));
    } else {
      included.sort((a, b) => b.median - a.median);
    }

    return { boxes: included, points: pts, excluded: excl };
  }, [rows, metric, groupBy, peerCerts]);

  const option = useMemo<EChartsOption>(() => {
    if (!boxes.length) return {};
    const theme = baseEChartTheme();
    const palette = categoricalPalette();
    const colors = chartColors();
    const categories = boxes.map((b) => b.name);
    const nByName = new Map(boxes.map((b) => [b.name, b.n]));

    const boxplotData = boxes.map((b) => [b.whiskerLow, b.q1, b.median, b.q3, b.whiskerHigh]);
    const outlierData: [number, number][] = [];
    boxes.forEach((b, i) => b.outliers.forEach((v) => outlierData.push([i, v])));

    const beeData = showBeeswarm
      ? points.map((p) => {
        const idx = categories.indexOf(p.group);
        // Deterministic jitter (seeded from cert) rather than Math.random() so
        // re-rendering the same option (theme flip, resize) doesn't reshuffle
        // every dot's x position.
        const seed = (p.cert % 997) / 997 - 0.5;
        return { value: [idx + seed * 0.55, p.value], name: p.name, cert: p.cert };
      })
      : [];

    const series: (BoxplotSeriesOption | ScatterSeriesOption)[] = [
      {
        type: 'boxplot',
        name: metricLabel,
        data: boxplotData,
        boxWidth: showBeeswarm ? ['12%', '28%'] : ['22%', '45%'],
        itemStyle: {
          borderColor: colors.text,
          borderWidth: 1.2,
        },
        z: 2,
      },
    ];

    if (showBeeswarm) {
      series.push({
        type: 'scatter',
        name: 'Banks',
        data: beeData,
        symbolSize: 5,
        itemStyle: { color: colors.blue, opacity: 0.55 },
        z: 1,
      });
    } else if (outlierData.length) {
      series.push({
        type: 'scatter',
        name: 'Outliers',
        data: outlierData,
        symbolSize: 6,
        itemStyle: { color: colors.critical, opacity: 0.85 },
        z: 3,
      });
    }

    return {
      backgroundColor: 'transparent',
      textStyle: theme.textStyle,
      color: palette,
      grid: { left: 56, right: 20, top: 16, bottom: 64, containLabel: false },
      xAxis: {
        type: 'category',
        data: categories,
        boundaryGap: true,
        axisLine: theme.axisLine,
        axisTick: { show: false },
        axisLabel: {
          color: theme.textStyle.color,
          fontSize: 10.5,
          interval: 0,
          rotate: categories.length > 5 ? 20 : 0,
          formatter: (v: string) => `${v}\n(n=${nByName.get(v) ?? 0})`,
        },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: theme.textStyle.color, fontSize: 11, formatter: (v: number) => pct(v, 1) },
        axisLine: { show: false },
        splitLine: theme.splitLine,
      },
      tooltip: {
        ...tooltipStyle(),
        trigger: 'item',
        formatter: (p: unknown) => {
          const param = p as {
            seriesType: string; name?: string; value?: number[] | number;
            data?: { name?: string; cert?: number; value?: number[] };
          };
          if (param.seriesType === 'boxplot') {
            const b = boxes.find((x) => x.name === param.name);
            if (!b) return '';
            return `<strong>${b.name}</strong> (n=${b.n})<br/>`
              + `Max ${pct(b.max, 2)}<br/>Q3 ${pct(b.q3, 2)}<br/>Median ${pct(b.median, 2)}<br/>`
              + `Q1 ${pct(b.q1, 2)}<br/>Min ${pct(b.min, 2)}`;
          }
          const d = param.data;
          if (d?.name && d.value) {
            return `<strong>${d.name}</strong><br/>${pct(d.value[1], 2)}${d.cert ? '<br/><span style="opacity:.65">Click to open</span>' : ''}`;
          }
          const v = Array.isArray(param.value) ? param.value[1] : param.value;
          return typeof v === 'number' ? pct(v, 2) : '';
        },
      },
      series,
    };
  }, [boxes, points, showBeeswarm, metricLabel]);

  const onEvents = useMemo(() => ({
    click: (params: unknown) => {
      const p = params as { seriesType?: string; data?: { cert?: number } };
      if (p.seriesType === 'scatter' && p.data?.cert) navigate(`/bank/${p.data.cert}`);
    },
  }), [navigate]);

  const csvRows = boxes;
  const csvColumns: CsvColumn<BoxStats>[] = [
    { key: 'group', label: 'Group', value: (b) => b.name, source: 'derived' },
    { key: 'n', label: 'Banks', value: (b) => b.n, source: 'derived' },
    { key: 'min', label: 'Min', value: (b) => b.min, source: 'derived' },
    { key: 'q1', label: 'P25', value: (b) => b.q1, source: 'derived' },
    { key: 'median', label: 'Median', value: (b) => b.median, source: 'derived' },
    { key: 'q3', label: 'P75', value: (b) => b.q3, source: 'derived' },
    { key: 'max', label: 'Max', value: (b) => b.max, source: 'derived' },
    { key: 'outliers', label: 'Outlier count', value: (b) => b.outliers.length, source: 'derived' },
  ];

  return (
    <div className="panel gcc-panel">
      <h2>Distribution shape by group</h2>
      <p className="muted gcc-subtitle">
        The same metric can have the same mean in two clusters and a completely different shape —
        tight and unimodal in one, bimodal or fat-tailed in another. This is a box-and-whisker plot
        (median, IQR box, Tukey whiskers, fence outliers as dots) per group, with an optional overlay
        showing every individual bank.
      </p>

      <div className="gcc-controls">
        <select className="gcc-select" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {METRIC_OPTIONS.map((g) => (
            <optgroup key={g.section} label={g.section}>
              {g.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </optgroup>
          ))}
        </select>
        <select className="gcc-select" value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)}>
          {GROUP_BY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <label className="gcc-toggle">
          <input type="checkbox" checked={showBeeswarm} onChange={(e) => setShowBeeswarm(e.target.checked)} />
          Show every bank (beeswarm)
        </label>
        {boxes.length > 0 && (
          <ExportCsvButton
            filename={`banklens-group-comparison-${metric}-${groupBy}.csv`}
            columns={csvColumns}
            rows={csvRows}
            meta={{ vintage: quarter ?? undefined, sourceLabel: 'FDIC Call Reports (derived group quartiles)' }}
            label="Download group stats"
          />
        )}
      </div>

      {groupBy === 'peer_set' && (
        <div className="gcc-peer-picker">
          <BankSearch onSelect={addPeer} />
          <div className="gcc-peer-chips">
            {peerSet.map((b) => (
              <span key={b.cert} className="gcc-peer-chip">
                {b.name}
                <button type="button" onClick={() => removePeer(b.cert)} aria-label={`Remove ${b.name}`}>×</button>
              </span>
            ))}
            {peerSet.length === 0 && (
              <span className="muted gcc-peer-empty">
                Add banks to build a peer set — compared against every other bank in this metric group.
              </span>
            )}
          </div>
        </div>
      )}

      {error && <p className="app-banner-error">{error}</p>}

      {!error && rows && boxes.length === 0 && (
        <p className="muted gcc-empty">
          {groupBy === 'peer_set' && peerCerts.size === 0
            ? 'Add at least one bank above to compare it against the rest of the population.'
            : `Not enough banks with a reported value in any group (need ${MIN_GROUP_N}+ per group).`}
        </p>
      )}

      {boxes.length > 0 && (
        <>
          <EChart
            option={option}
            height={380}
            resetKey={`${metric}-${groupBy}-${showBeeswarm}`}
            onEvents={onEvents}
            ariaLabel={`${metricLabel} distribution by ${groupBy.replace('_', ' ')}, box plot`}
          />
          {excluded.length > 0 && (
            <p className="muted gcc-excluded">
              {excluded.length} group{excluded.length === 1 ? '' : 's'} omitted (fewer than {MIN_GROUP_N} banks
              with a reported value): {excluded.map((e) => `${e.name} (${e.n})`).join(', ')}.
            </p>
          )}
        </>
      )}
    </div>
  );
}
