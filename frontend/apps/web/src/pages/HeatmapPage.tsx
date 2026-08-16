import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { EChart } from '../components/EChart';
import { baseEChartTheme, tooltipHtml, tooltipStyle } from '../echartsTheme';
import { api } from '../api';
import { chartColors, divergingRamp, sequentialRamp } from '../colors';
import { agglomerativeCluster } from '../hierarchicalClustering';
import type { HeatmapResult } from '../types';
import { ExportCsvButton } from '../components/ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import './HeatmapPage.css';

// Labels for every metric peers.RANK_METRICS computes a percentile rank for
// (see banklens_transforms/peers.py) — a superset of the curated
// HEATMAP_METRICS default, since E6 lets the analyst pick beyond the default
// 10. Falls back to the raw field name for anything unmapped, so a metric
// the backend adds later still renders (just less prettily) instead of
// vanishing from the picker.
const METRIC_LABELS: Record<string, string> = {
  uninsured_deposit_pct: 'Uninsured deposits',
  loan_to_deposit_pct: 'Loan / deposit',
  concentration_ratio_cre: 'CRE concentration',
  concentration_ratio_c_and_i: 'C&I concentration',
  concentration_ratio_residential_mortgage: 'Residential mortgage concentration',
  concentration_ratio_consumer: 'Consumer concentration',
  concentration_ratio_agricultural: 'Agricultural concentration',
  max_loan_concentration_pct: 'Max sector concentration',
  cre_to_equity_pct: 'CRE / equity',
  cre_to_total_capital_pct: 'CRE / capital',
  cet1_ratio: 'CET1',
  tier1_rbc_ratio: 'Tier 1 RBC',
  total_rbc_ratio: 'Total RBC',
  leverage_ratio: 'Leverage',
  core_deposit_pct: 'Core deposits',
  roa_pct: 'ROA',
  net_interest_margin_pct: 'NIM',
  efficiency_ratio_pct: 'Efficiency ratio',
  npl_ratio_pct: 'NPL ratio',
  texas_ratio_pct: 'Texas Ratio',
  brokered_deposit_pct: 'Brokered deposits',
};

// Mirrors the backend's own default (tools.HEATMAP_METRICS) purely so the
// metric picker has something to show pre-checked before the first response
// lands — the real, authoritative catalog is `result.available_metrics`,
// fetched from the server every load (see peers.RANK_METRICS), not this list.
const DEFAULT_METRICS = [
  'uninsured_deposit_pct', 'loan_to_deposit_pct', 'max_loan_concentration_pct',
  'cre_to_total_capital_pct', 'cet1_ratio', 'leverage_ratio', 'roa_pct',
  'net_interest_margin_pct', 'npl_ratio_pct', 'texas_ratio_pct',
];

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: 'total_assets', label: 'Largest banks' },
  { value: 'texas_ratio_pct', label: 'Highest Texas Ratio' },
  { value: 'uninsured_deposit_pct', label: 'Highest uninsured deposits' },
  { value: 'cet1_ratio', label: 'Thinnest CET1' },
];

type OrderMode = 'sort' | 'clustered';
type ColorMode = 'sequential' | 'diverging';

export function HeatmapPage() {
  const navigate = useNavigate();
  const [result, setResult] = useState<HeatmapResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState('total_assets');
  const [topN, setTopN] = useState(40);
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(DEFAULT_METRICS);
  const [availableMetrics, setAvailableMetrics] = useState<string[]>(DEFAULT_METRICS);
  const [orderMode, setOrderMode] = useState<OrderMode>('sort');
  const [colorMode, setColorMode] = useState<ColorMode>('sequential');

  useEffect(() => {
    api.percentileHeatmap(topN, sortBy, selectedMetrics)
      .then((r) => {
        setResult(r);
        setError(null);
        setAvailableMetrics(r.available_metrics);
      })
      .catch((e: Error) => setError(e.message));
  }, [sortBy, topN, selectedMetrics]);

  function toggleMetric(m: string) {
    setSelectedMetrics((prev) => {
      if (prev.includes(m)) {
        // Keep at least one column — an empty selection has nothing to show
        // and would silently fall back to the server default, which would
        // desync from what the picker displays as checked.
        return prev.length > 1 ? prev.filter((x) => x !== m) : prev;
      }
      return [...prev, m];
    });
  }

  // Row (and, when there's more than a couple columns, column) order via
  // average-linkage agglomerative clustering over the percentile vectors —
  // see hierarchicalClustering.ts. O(n^3) on up to ~100 rows / ~20 columns
  // (topN caps at 100, metrics at peers.RANK_METRICS' length), which is a
  // few hundred thousand distance comparisons — well under a frame, so it
  // recomputes directly in this useMemo rather than needing memoized
  // incremental updates.
  const { orderedBanks, colOrder } = useMemo(() => {
    if (!result) return { orderedBanks: [] as HeatmapResult['banks'], colOrder: [] as number[] };
    const identityCols = result.metrics.map((_, i) => i);
    if (orderMode !== 'clustered') return { orderedBanks: result.banks, colOrder: identityCols };
    const rowVectors = result.banks.map((b) => b.cells);
    const { order: rowOrder } = agglomerativeCluster(rowVectors);
    const banks = rowOrder.map((i) => result.banks[i]);
    let cols = identityCols;
    if (result.metrics.length > 2) {
      const colVectors = result.metrics.map((_, x) => result.banks.map((b) => b.cells[x]));
      cols = agglomerativeCluster(colVectors).order;
    }
    return { orderedBanks: banks, colOrder: cols };
  }, [result, orderMode]);

  const option = useMemo(() => {
    if (!result) return {} as EChartsOption;
    const theme = baseEChartTheme();
    const colors = chartColors();
    // A percentile heatmap is deliberately NEUTRAL, not good/bad: high CET1 percentile
    // is healthy, high NPL percentile is not, and baking one direction into the color
    // scale would silently misrepresent half the columns. It shows relative standing
    // vs peers only — the metric label says what the number means. The diverging
    // option below is still neutral in the same way: it only marks distance from the
    // population median in either direction, not a good/bad side.
    const data: [number, number, number | null][] = [];
    orderedBanks.forEach((b, y) => {
      colOrder.forEach((srcX, x) => data.push([x, y, b.cells[srcX]]));
    });
    const orderedMetricKeys = colOrder.map((x) => result.metrics[x]);
    const inRange = colorMode === 'diverging' ? divergingRamp() : sequentialRamp();
    const opt: EChartsOption = {
      grid: { left: 220, right: 24, top: 16, bottom: 70, containLabel: false },
      tooltip: {
        ...tooltipStyle(),
        formatter: (p: unknown) => {
          const cell = (Array.isArray(p) ? p[0] : p) as { data?: [number, number, number | null] };
          if (!cell.data) return '';
          const [x, y, v] = cell.data;
          const bank = orderedBanks[y];
          const metric = METRIC_LABELS[orderedMetricKeys[x]] ?? orderedMetricKeys[x];
          return tooltipHtml(bank.name, [
            { text: `${metric}: ${v === null ? 'n/a' : `${v.toFixed(1)}th percentile`}` },
          ]);
        },
      },
      xAxis: {
        type: 'category',
        data: orderedMetricKeys.map((m) => METRIC_LABELS[m] ?? m),
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5, rotate: 28 },
        axisLine: theme.axisLine, splitArea: { show: true },
      },
      yAxis: {
        type: 'category',
        data: orderedBanks.map((b) => b.name),
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5 },
        axisLine: theme.axisLine, inverse: true,
      },
      visualMap: {
        min: 0, max: 100, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 0,
        inRange: { color: inRange },
        textStyle: { color: theme.textStyle.color },
      },
      series: [{
        type: 'heatmap',
        data,
        emphasis: { itemStyle: { borderColor: colors.text, borderWidth: 1 } },
        itemStyle: { borderColor: colors.surface, borderWidth: 1 },
      }],
    };
    return opt;
  }, [result, orderedBanks, colOrder, colorMode]);

  const onEvents = useMemo(() => ({
    click: (params: unknown) => {
      const p = params as { data?: [number, number, number | null] };
      if (!p.data) return;
      const bank = orderedBanks[p.data[1]];
      if (bank) navigate(`/bank/${bank.cert}`);
    },
  }), [orderedBanks, navigate]);

  const orderedMetricKeysForCsv = result ? colOrder.map((x) => result.metrics[x]) : [];

  return (
    <div className="heatmap-page">
      <div className="panel">
        <h2>Risk & performance heatmap</h2>
        <p className="muted heatmap-subtitle">
          Percentile standing vs the full population, not raw values — the color shows
          how unusual a bank's number is, not whether it's good or bad (a high CET1
          percentile is healthy; a high NPL percentile is not). Click a cell to open
          that bank. "Clustered order" groups rows (and columns) by similarity across
          the selected metrics instead of a single sort key, so structure in the grid —
          blocks of banks that look alike across many dimensions at once — becomes
          visible rather than hidden inside one column's ranking.
        </p>
        <div className="heatmap-controls">
          <select
            className="heatmap-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            title="Which top-N population to pull into the grid — row DISPLAY order is separately controlled by the toggle below"
          >
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <select className="heatmap-select" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
            {[20, 40, 60, 100].map((n) => <option key={n} value={n}>{n} banks</option>)}
          </select>
          <div className="heatmap-toggle-group" role="group" aria-label="Row order">
            <button
              type="button"
              className={`heatmap-toggle-btn${orderMode === 'sort' ? ' active' : ''}`}
              onClick={() => setOrderMode('sort')}
            >
              Sort-key order
            </button>
            <button
              type="button"
              className={`heatmap-toggle-btn${orderMode === 'clustered' ? ' active' : ''}`}
              onClick={() => setOrderMode('clustered')}
              title="Group similar banks (and metrics) together via hierarchical clustering"
            >
              Clustered order
            </button>
          </div>
          <div className="heatmap-toggle-group" role="group" aria-label="Color scale">
            <button
              type="button"
              className={`heatmap-toggle-btn${colorMode === 'sequential' ? ' active' : ''}`}
              onClick={() => setColorMode('sequential')}
            >
              Sequential
            </button>
            <button
              type="button"
              className={`heatmap-toggle-btn${colorMode === 'diverging' ? ' active' : ''}`}
              onClick={() => setColorMode('diverging')}
              title="Diverging color scale centered at the 50th percentile"
            >
              Diverging (centered at 50th)
            </button>
          </div>
          {result && (
            <ExportCsvButton
              filename="banklens-heatmap.csv"
              columns={[
                { key: 'name', label: 'Bank', value: (b) => b.name, source: 'fdic' },
                ...orderedMetricKeysForCsv.map((m, x) => ({
                  key: m, label: METRIC_LABELS[m] ?? m,
                  value: (b: HeatmapResult['banks'][number]) => b.cells[colOrder[x]] ?? '', source: 'derived' as const,
                })),
              ] as CsvColumn<HeatmapResult['banks'][number]>[]}
              rows={orderedBanks}
              meta={{ sourceLabel: 'FDIC Call Reports (percentile vs. population)' }}
              label="Download chart data"
            />
          )}
        </div>
        <div className="heatmap-metric-picker">
          <span className="muted heatmap-metric-picker-label">Metrics ({selectedMetrics.length}):</span>
          {availableMetrics.map((m) => (
            <button
              key={m}
              type="button"
              className={`heatmap-metric-chip${selectedMetrics.includes(m) ? ' active' : ''}`}
              onClick={() => toggleMetric(m)}
              aria-pressed={selectedMetrics.includes(m)}
            >
              {METRIC_LABELS[m] ?? m}
            </button>
          ))}
          {selectedMetrics.join(',') !== DEFAULT_METRICS.join(',') && (
            <button type="button" className="heatmap-metric-reset" onClick={() => setSelectedMetrics(DEFAULT_METRICS)}>
              Reset to default
            </button>
          )}
        </div>
        {error && <p className="app-banner-error">{error}</p>}
        {result && (
          <EChart
            option={option}
            height={Math.max(420, orderedBanks.length * 20 + 100)}
            resetKey={`${sortBy}-${topN}-${orderMode}-${colorMode}-${selectedMetrics.join(',')}`}
            ariaLabel="Bank risk and performance percentile heatmap"
            onEvents={onEvents}
          />
        )}
      </div>
    </div>
  );
}
