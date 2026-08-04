import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { motion } from 'motion/react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { MetricDistributionResult } from '../types';
import '../components/charts.css';
import './DistributionsPage.css';

const METRIC_OPTIONS: { group: string; options: { value: string; label: string }[] }[] = [
  { group: 'Earnings', options: [
    { value: 'roa_pct', label: 'Return on assets' },
    { value: 'roe_pct', label: 'Return on equity' },
    { value: 'net_interest_margin_pct', label: 'Net interest margin' },
    { value: 'efficiency_ratio_pct', label: 'Efficiency ratio' },
  ] },
  { group: 'Credit quality', options: [
    { value: 'npl_ratio_pct', label: 'NPL ratio' },
    { value: 'net_charge_off_rate_pct', label: 'Net charge-off rate' },
    { value: 'texas_ratio_pct', label: 'Texas Ratio' },
  ] },
  { group: 'Funding', options: [
    { value: 'uninsured_deposit_pct', label: 'Uninsured deposits' },
    { value: 'brokered_deposit_pct', label: 'Brokered deposits' },
    { value: 'loan_to_deposit_pct', label: 'Loan / deposit' },
  ] },
  { group: 'Capital & concentration', options: [
    { value: 'cet1_ratio', label: 'CET1 ratio' },
    { value: 'leverage_ratio', label: 'Leverage ratio' },
    { value: 'cre_to_total_capital_pct', label: 'CRE / total capital' },
    { value: 'max_loan_concentration_pct', label: 'Max sector concentration' },
  ] },
];

function fmt(v: number): string {
  return `${v.toFixed(1)}%`;
}

function ChartTooltipBox({ active, payload }: {
  active?: boolean; payload?: { payload: { lower: number; upper: number; count: number } }[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">{fmt(d.lower)} – {fmt(d.upper)}</div>
      <div className="chart-tooltip-value tabular">{d.count} bank{d.count === 1 ? '' : 's'}</div>
    </motion.div>
  );
}

export function DistributionsPage() {
  const [metric, setMetric] = useState('texas_ratio_pct');
  const [result, setResult] = useState<MetricDistributionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const colors = chartColors();

  useEffect(() => {
    setResult(null);
    api.metricDistribution(metric, 24)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [metric]);

  const label = METRIC_OPTIONS.flatMap((g) => g.options).find((o) => o.value === metric)?.label ?? metric;
  const chartData = result?.histogram.map((h) => ({ ...h, mid: (h.lower + h.upper) / 2 })) ?? [];

  return (
    <div className="distributions-page">
      <div className="panel">
        <h2>Distributions</h2>
        <p className="muted distributions-subtitle">
          How one metric is actually spread across the population — the shape a "top 10"
          leaderboard can't show. The first and last bars include everything at or beyond
          the 1st/99th percentile, so a handful of extreme outliers can't flatten the
          rest of the chart into one bar.
        </p>
        <select className="distributions-select" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {METRIC_OPTIONS.map((g) => (
            <optgroup key={g.group} label={g.group}>
              {g.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </optgroup>
          ))}
        </select>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {result && (
        <div className="panel">
          <h2>{label} — {result.count} banks, {result.quarter}</h2>
          <div className="distributions-stats">
            <div className="distributions-stat"><span className="muted">Min</span><span className="tabular">{fmt(result.min)}</span></div>
            <div className="distributions-stat"><span className="muted">P25</span><span className="tabular">{fmt(result.p25)}</span></div>
            <div className="distributions-stat"><span className="muted">Median</span><span className="tabular">{fmt(result.median)}</span></div>
            <div className="distributions-stat"><span className="muted">Mean</span><span className="tabular">{fmt(result.mean)}</span></div>
            <div className="distributions-stat"><span className="muted">P75</span><span className="tabular">{fmt(result.p75)}</span></div>
            <div className="distributions-stat"><span className="muted">P90</span><span className="tabular">{fmt(result.p90)}</span></div>
            <div className="distributions-stat"><span className="muted">Max</span><span className="tabular">{fmt(result.max)}</span></div>
          </div>

          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <XAxis dataKey="mid" tickFormatter={fmt} tick={{ fill: colors.muted, fontSize: 10.5 }}
                axisLine={{ stroke: colors.baseline }} tickLine={false} />
              <YAxis tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={32} />
              <Tooltip content={<ChartTooltipBox />} cursor={{ fill: 'var(--surface-2)' }} />
              <ReferenceLine x={result.median} stroke={colors.critical} strokeDasharray="3 3"
                label={{ value: 'median', fill: colors.critical, fontSize: 10, position: 'top' }} />
              <Bar dataKey="count" radius={[3, 3, 0, 0]} fill={colors.blue}
                animationDuration={600} animationEasing="ease-out" />
            </BarChart>
          </ResponsiveContainer>

          {result.exclusions.excluded_count > 0 && (
            <div className="distributions-exclusions">
              <p className="muted distributions-exclusions-title">
                {result.exclusions.excluded_count} institution{result.exclusions.excluded_count === 1 ? '' : 's'}{' '}
                excluded from this distribution — deposits under {result.exclusions.threshold_pct}% of
                assets (trust, clearing or card-subsidiary charters, not deposit-funded banks):
              </p>
              <ul className="distributions-exclusions-list">
                {result.exclusions.excluded.map((e) => (
                  <li key={e.cert}>
                    <Link to={`/bank/${e.cert}`}>{e.name}</Link>
                    <span className="muted"> — {e.deposits_to_assets_pct?.toFixed(3)}% dep/assets</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
