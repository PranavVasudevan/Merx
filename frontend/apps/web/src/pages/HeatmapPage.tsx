import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { EChart } from '../components/EChart';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { api } from '../api';
import { chartColors } from '../colors';
import type { HeatmapResult } from '../types';
import './HeatmapPage.css';

const METRIC_LABELS: Record<string, string> = {
  uninsured_deposit_pct: 'Uninsured deposits',
  loan_to_deposit_pct: 'Loan / deposit',
  max_loan_concentration_pct: 'Max sector concentration',
  cre_to_total_capital_pct: 'CRE / capital',
  cet1_ratio: 'CET1',
  leverage_ratio: 'Leverage',
  roa_pct: 'ROA',
  net_interest_margin_pct: 'NIM',
  npl_ratio_pct: 'NPL ratio',
  texas_ratio_pct: 'Texas Ratio',
};

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: 'total_assets', label: 'Largest banks' },
  { value: 'texas_ratio_pct', label: 'Highest Texas Ratio' },
  { value: 'uninsured_deposit_pct', label: 'Highest uninsured deposits' },
  { value: 'cet1_ratio', label: 'Thinnest CET1' },
];

export function HeatmapPage() {
  const navigate = useNavigate();
  const [result, setResult] = useState<HeatmapResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState('total_assets');
  const [topN, setTopN] = useState(40);

  useEffect(() => {
    api.percentileHeatmap(topN, sortBy)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [sortBy, topN]);

  const option = useMemo(() => {
    if (!result) return {} as EChartsOption;
    const theme = baseEChartTheme();
    const colors = chartColors();
    // A percentile heatmap is deliberately NEUTRAL, not good/bad: high CET1 percentile
    // is healthy, high NPL percentile is not, and baking one direction into the color
    // scale would silently misrepresent half the columns. It shows relative standing
    // vs peers only — the metric label says what the number means.
    const data: [number, number, number | null][] = [];
    result.banks.forEach((b, y) => {
      b.cells.forEach((c, x) => data.push([x, y, c]));
    });
    const opt: EChartsOption = {
      grid: { left: 220, right: 24, top: 16, bottom: 70, containLabel: false },
      tooltip: {
        ...tooltipStyle(),
        formatter: (p: unknown) => {
          const cell = (Array.isArray(p) ? p[0] : p) as { data?: [number, number, number | null] };
          if (!cell.data) return '';
          const [x, y, v] = cell.data;
          const bank = result.banks[y];
          const metric = METRIC_LABELS[result.metrics[x]] ?? result.metrics[x];
          return `<strong>${bank.name}</strong><br/>${metric}: ${v === null ? 'n/a' : `${v.toFixed(1)}th percentile`}`;
        },
      },
      xAxis: {
        type: 'category',
        data: result.metrics.map((m) => METRIC_LABELS[m] ?? m),
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5, rotate: 28 },
        axisLine: theme.axisLine, splitArea: { show: true },
      },
      yAxis: {
        type: 'category',
        data: result.banks.map((b) => b.name),
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5 },
        axisLine: theme.axisLine, inverse: true,
      },
      visualMap: {
        min: 0, max: 100, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 0,
        inRange: { color: [colors.seq100, colors.seq300, colors.seq450, colors.seq600] },
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
  }, [result]);

  const onEvents = useMemo(() => ({
    click: (params: unknown) => {
      const p = params as { data?: [number, number, number | null] };
      if (!result || !p.data) return;
      const bank = result.banks[p.data[1]];
      if (bank) navigate(`/bank/${bank.cert}`);
    },
  }), [result, navigate]);

  return (
    <div className="heatmap-page">
      <div className="panel">
        <h2>Risk & performance heatmap</h2>
        <p className="muted heatmap-subtitle">
          Percentile standing vs the full population, not raw values — the color shows
          how unusual a bank's number is, not whether it's good or bad (a high CET1
          percentile is healthy; a high NPL percentile is not). Click a cell to open
          that bank.
        </p>
        <div className="heatmap-controls">
          <select className="heatmap-select" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <select className="heatmap-select" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
            {[20, 40, 60, 100].map((n) => <option key={n} value={n}>{n} banks</option>)}
          </select>
        </div>
        {error && <p className="app-banner-error">{error}</p>}
        {result && (
          <EChart
            option={option}
            height={Math.max(420, result.banks.length * 20 + 100)}
            resetKey={`${sortBy}-${topN}`}
            ariaLabel="Bank risk and performance percentile heatmap"
            onEvents={onEvents}
          />
        )}
      </div>
    </div>
  );
}
