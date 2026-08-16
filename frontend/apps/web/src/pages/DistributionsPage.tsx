import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { chartColors } from '../colors';
import { RECHARTS_ENTRANCE } from '../chartMotion';
import { pct } from '../metricFormat';
import { ChartTooltipShell } from '../components/ChartTooltip';
import type { HistogramBin, MetricDistributionResult } from '../types';
import { ExportCsvButton } from '../components/ExportCsvButton';
import { BankSearch } from '../components/BankSearch';
import { GroupComparisonChart } from '../components/GroupComparisonChart';
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
  return pct(v, 1);
}

function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

// The histogram is already fetched for the chart itself, so a selected bank's
// percentile is estimated from those same bins (linear interpolation within the
// bin containing its value) rather than adding another request. This is real,
// derived-from-landed-data math, just bin-resolution-limited near the edges —
// hence "~" in the label rather than claiming exact-rank precision.
function estimatePercentileFromHistogram(value: number, histogram: HistogramBin[], total: number): number {
  if (total <= 0 || histogram.length === 0) return 0;
  let cumulative = 0;
  for (let i = 0; i < histogram.length; i++) {
    const bin = histogram[i];
    const isLast = i === histogram.length - 1;
    if (i === 0 && value < bin.lower) break;
    if (!isLast && value >= bin.upper) { cumulative += bin.count; continue; }
    const width = bin.upper - bin.lower;
    const frac = width > 0 ? Math.min(Math.max((value - bin.lower) / width, 0), 1) : 0;
    cumulative += bin.count * frac;
    return (cumulative / total) * 100;
  }
  return (cumulative / total) * 100;
}

function ChartTooltipBox({ active, payload }: {
  active?: boolean; payload?: { payload: { lower: number; upper: number; count: number } }[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <ChartTooltipShell
      label={`${fmt(d.lower)} – ${fmt(d.upper)}`}
      lines={[{ text: `${d.count} bank${d.count === 1 ? '' : 's'}` }]}
    />
  );
}

export function DistributionsPage() {
  const [metric, setMetric] = useState('texas_ratio_pct');
  const [result, setResult] = useState<MetricDistributionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bank, setBank] = useState<{ cert: number; name: string } | null>(null);
  const [bankValue, setBankValue] = useState<number | null>(null);
  const [bankValueLoaded, setBankValueLoaded] = useState(false);
  const colors = chartColors();

  useEffect(() => {
    setResult(null);
    api.metricDistribution(metric, 24)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [metric]);

  // A bank's own value for the metric currently on screen — fetched via the
  // existing /compare route (real Gold field, single cert so the bulk-licensing
  // gate never engages) rather than adding a new endpoint.
  useEffect(() => {
    if (!bank) { setBankValue(null); setBankValueLoaded(false); return; }
    setBankValueLoaded(false);
    api.compareBanks([bank.cert], [metric])
      .then((r) => {
        const row = r.banks[0];
        const v = row ? row[metric] : null;
        setBankValue(typeof v === 'number' ? v : null);
        setBankValueLoaded(true);
      })
      .catch(() => { setBankValue(null); setBankValueLoaded(true); });
  }, [metric, bank]);

  const label = METRIC_OPTIONS.flatMap((g) => g.options).find((o) => o.value === metric)?.label ?? metric;
  const chartData = result?.histogram.map((h) => ({ ...h, mid: (h.lower + h.upper) / 2 })) ?? [];
  const bankPercentile = result && bankValue !== null
    ? estimatePercentileFromHistogram(bankValue, result.histogram, result.count)
    : null;

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
        <div className="distributions-controls">
          <select className="distributions-select" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {METRIC_OPTIONS.map((g) => (
              <optgroup key={g.group} label={g.group}>
                {g.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </optgroup>
            ))}
          </select>
          <BankSearch onSelect={(cert, name) => setBank({ cert, name })} />
          {bank && (
            <span className="distributions-bank-chip">
              {bank.name}
              <button
                type="button"
                className="distributions-bank-chip-clear"
                onClick={() => setBank(null)}
                aria-label="Clear selected bank"
              >
                ×
              </button>
            </span>
          )}
        </div>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {result && (
        <div className="panel">
          <div className="distributions-header-row">
            <h2>{label} — {result.count} banks, {result.quarter}</h2>
            <ExportCsvButton
              filename={`banklens-distribution-${metric}.csv`}
              columns={[
                { key: 'lower', label: 'Bin lower', value: (h) => h.lower, source: 'derived' },
                { key: 'upper', label: 'Bin upper', value: (h) => h.upper, source: 'derived' },
                { key: 'count', label: 'Bank count', value: (h) => h.count, source: 'derived' },
              ]}
              rows={result.histogram}
              meta={{ vintage: result.quarter, sourceLabel: 'FDIC Call Reports (derived distribution)' }}
              label="Download chart data"
            />
          </div>
          <div className="distributions-stats">
            <div className="distributions-stat"><span className="muted">Min</span><span className="tabular">{fmt(result.min)}</span></div>
            <div className="distributions-stat"><span className="muted">P25</span><span className="tabular">{fmt(result.p25)}</span></div>
            <div className="distributions-stat"><span className="muted">Median</span><span className="tabular">{fmt(result.median)}</span></div>
            <div className="distributions-stat"><span className="muted">Mean</span><span className="tabular">{fmt(result.mean)}</span></div>
            <div className="distributions-stat"><span className="muted">P75</span><span className="tabular">{fmt(result.p75)}</span></div>
            <div className="distributions-stat"><span className="muted">P90</span><span className="tabular">{fmt(result.p90)}</span></div>
            <div className="distributions-stat"><span className="muted">Max</span><span className="tabular">{fmt(result.max)}</span></div>
          </div>

          {bank && (
            <p className="distributions-bank-readout">
              {!bankValueLoaded ? (
                <>Loading {bank.name}'s value…</>
              ) : bankValue === null ? (
                <>{bank.name} has no reported value for {label.toLowerCase()} this quarter — not plotted.</>
              ) : (
                <>
                  <Link to={`/bank/${bank.cert}`}>{bank.name}</Link>: {fmt(bankValue)}
                  {bankPercentile !== null && <> — ~{ordinal(Math.round(bankPercentile))} percentile of the population</>}
                </>
              )}
            </p>
          )}

          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <XAxis dataKey="mid" tickFormatter={fmt} tick={{ fill: colors.muted, fontSize: 10.5 }}
                axisLine={{ stroke: colors.baseline }} tickLine={false} />
              <YAxis tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={32} />
              <Tooltip content={<ChartTooltipBox />} cursor={{ fill: 'var(--surface-2)' }} />
              <ReferenceLine x={result.median} stroke={colors.critical} strokeDasharray="3 3"
                label={{ value: 'median', fill: colors.critical, fontSize: 10, position: 'top' }} />
              {bank && bankValue !== null && (
                <ReferenceLine x={bankValue} stroke={colors.violet} strokeWidth={2}
                  label={{
                    value: `${bank.name}${bankPercentile !== null ? ` (~${ordinal(Math.round(bankPercentile))} pctile)` : ''}`,
                    fill: colors.violet, fontSize: 10, position: 'insideTopLeft',
                  }} />
              )}
              <Bar dataKey="count" radius={[3, 3, 0, 0]} fill={colors.blue} {...RECHARTS_ENTRANCE} />
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

      {/* E5 — a metric's distribution SHAPE across clusters/size bands/states/
          peer sets, standalone from the single global histogram above so it
          doesn't entangle with that panel's own state. */}
      <GroupComparisonChart />
    </div>
  );
}
