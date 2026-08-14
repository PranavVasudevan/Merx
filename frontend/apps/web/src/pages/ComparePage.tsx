import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Link } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { api, type BankSearchResult } from '../api';
import { useQuarter } from '../QuarterContext';
import type { CompareResult } from '../types';
import { ExportCsvButton } from '../components/ExportCsvButton';
import type { CsvColumn } from '../csvExport';
import { EChart } from '../components/EChart';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { chartColors } from '../colors';
import './ComparePage.css';

// D6 — a starting default, not a hardcoded ceiling: the metric picker below
// is driven by the real Gold schema (banklens_mcp.tools.RANK_METRICS, the
// same catalog /heatmap's picker uses), so any Gold metric can be added.
const DEFAULT_METRICS = [
  'uninsured_deposit_pct', 'loan_to_deposit_pct', 'concentration_ratio_cre',
  'cet1_ratio', 'leverage_ratio', 'roa_pct', 'net_interest_margin_pct',
  'npl_ratio_pct', 'texas_ratio_pct', 'brokered_deposit_pct',
];

const METRIC_LABELS: Record<string, string> = {
  uninsured_deposit_pct: 'Uninsured deposits',
  loan_to_deposit_pct: 'Loan / deposit ratio',
  concentration_ratio_cre: 'CRE concentration',
  cet1_ratio: 'CET1 ratio',
  leverage_ratio: 'Leverage ratio',
  roa_pct: 'Return on assets',
  net_interest_margin_pct: 'Net interest margin',
  npl_ratio_pct: 'NPL ratio',
  texas_ratio_pct: 'Texas Ratio',
  brokered_deposit_pct: 'Brokered deposits',
  tier1_rbc_ratio: 'Tier 1 RBC',
  total_rbc_ratio: 'Total RBC',
  core_deposit_pct: 'Core deposits',
  efficiency_ratio_pct: 'Efficiency ratio',
  max_loan_concentration_pct: 'Max sector concentration',
};

const MAX_BANKS = 6;
const RADAR_MAX_METRICS = 8;

function fmtMetric(v: number | string | null): string {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number' ? `${v.toFixed(1)}%` : String(v);
}

function metricLabel(m: string): string {
  return METRIC_LABELS[m] ?? m;
}

export function ComparePage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BankSearchResult['banks']>([]);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<{ cert: number; name: string }[]>([]);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const { quarter } = useQuarter(); // D3

  // D6 — metric picker driven by the real Gold schema (reuses /heatmap's own
  // catalog rather than a second hand-maintained metric list).
  const [availableMetrics, setAvailableMetrics] = useState<string[]>(DEFAULT_METRICS);
  const [metrics, setMetrics] = useState<string[]>(DEFAULT_METRICS);
  const [addMetric, setAddMetric] = useState('');
  const [view, setView] = useState<'table' | 'radar'>('table');
  const colors = chartColors();

  useEffect(() => {
    api.percentileHeatmap(1).then((r) => setAvailableMetrics(r.available_metrics)).catch(() => {});
  }, []);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      api.searchBanks(query, undefined, 8)
        .then((r) => {
          setResults(r.banks.filter((b) => !selected.some((s) => s.cert === b.cert)));
          setOpen(true);
        })
        .catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [query, selected]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  useEffect(() => {
    if (selected.length < 2) { setCompare(null); return; }
    api.compareBanks(selected.map((s) => s.cert), metrics, quarter)
      .then((r) => { setCompare(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [selected, metrics, quarter]);

  function addBank(cert: number, name: string) {
    if (selected.length >= MAX_BANKS || selected.some((s) => s.cert === cert)) return;
    setSelected((s) => [...s, { cert, name }]);
    setQuery('');
    setOpen(false);
  }

  function removeBank(cert: number) {
    setSelected((s) => s.filter((b) => b.cert !== cert));
  }

  function addMetricToSet(m: string) {
    if (!m || metrics.includes(m)) return;
    setMetrics((prev) => [...prev, m]);
    setAddMetric('');
  }

  function removeMetric(m: string) {
    setMetrics((prev) => prev.filter((x) => x !== m));
  }

  // D6 — a normalised radar: each axis is min-max scaled to 0-100 across just
  // the SELECTED banks (not the whole population), so heterogeneous units
  // (percent ratios, percentage points) share one visual scale honestly —
  // it shows relative standing among these banks, not an absolute score.
  const radarMetrics = metrics.slice(0, RADAR_MAX_METRICS);
  const radarOption = useMemo<EChartsOption>(() => {
    if (!compare || radarMetrics.length < 3) return {};
    const theme = baseEChartTheme();
    const ranges = radarMetrics.map((m) => {
      const vals = compare.banks.map((b) => b[m]).filter((v): v is number => typeof v === 'number');
      const lo = vals.length ? Math.min(...vals) : 0;
      const hi = vals.length ? Math.max(...vals) : 1;
      return { lo, hi: hi > lo ? hi : lo + 1 };
    });
    const palette = [colors.blue, colors.critical, colors.warning, colors.good, colors.violet, colors.aqua];
    return {
      tooltip: tooltipStyle(),
      legend: { top: 0, textStyle: { color: theme.textStyle.color, fontSize: 11 } },
      radar: {
        indicator: radarMetrics.map((m) => ({ name: metricLabel(m), min: 0, max: 100 })),
        axisName: { color: theme.textStyle.color, fontSize: 10.5 },
        splitLine: { lineStyle: { color: theme.axisLine.lineStyle.color } },
        axisLine: { lineStyle: { color: theme.axisLine.lineStyle.color } },
        splitArea: { show: false },
      },
      series: [{
        type: 'radar',
        data: compare.banks.map((b, i) => ({
          name: b.name,
          value: radarMetrics.map((m, x) => {
            const v = b[m];
            if (typeof v !== 'number') return 0;
            const { lo, hi } = ranges[x];
            return Math.round(((v - lo) / (hi - lo)) * 100);
          }),
          lineStyle: { color: palette[i % palette.length] },
          areaStyle: { color: palette[i % palette.length], opacity: 0.08 },
          itemStyle: { color: palette[i % palette.length] },
        })),
      }],
    };
  }, [compare, radarMetrics, colors]);

  return (
    <div className="compare-page">
      <div className="panel">
        <h2>Compare banks</h2>
        <p className="muted compare-note">Pick 2–{MAX_BANKS} banks to compare side by side across any Gold metric.</p>

        <div className="compare-picker" ref={boxRef}>
          <input
            className="compare-picker-input"
            placeholder={selected.length >= MAX_BANKS ? `Maximum ${MAX_BANKS} banks` : 'Search a bank to add…'}
            value={query}
            disabled={selected.length >= MAX_BANKS}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results.length > 0 && setOpen(true)}
          />
          <AnimatePresence>
            {open && results.length > 0 && (
              <motion.div
                className="compare-picker-results"
                initial={{ opacity: 0, y: -6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.98 }}
                transition={{ duration: 0.16, ease: [0.85, 0, 0.15, 1] }}
              >
                {results.map((b, i) => (
                  <motion.button
                    key={b.cert}
                    className="compare-picker-result"
                    onClick={() => addBank(b.cert, b.name)}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1, transition: { delay: i * 0.02, duration: 0.15 } }}
                    whileHover={{ x: 2 }}
                  >
                    <span className="bsr-name">{b.name}</span>
                    <span className="muted bsr-meta">${b.assets_b.toFixed(1)}B · {b.state ?? '—'}</span>
                  </motion.button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="compare-chips">
          <AnimatePresence>
            {selected.map((b) => (
              <motion.div
                key={b.cert}
                className="compare-chip"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.15 }}
              >
                <Link to={`/bank/${b.cert}`} className="compare-chip-name">{b.name}</Link>
                <button className="compare-chip-remove" onClick={() => removeBank(b.cert)} aria-label={`Remove ${b.name}`}>×</button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>

        <div className="compare-metric-picker">
          <span className="muted compare-metric-picker-label">Metrics:</span>
          {metrics.map((m) => (
            <span key={m} className="compare-metric-chip">
              {metricLabel(m)}
              <button onClick={() => removeMetric(m)} aria-label={`Remove ${metricLabel(m)}`}>×</button>
            </span>
          ))}
          <select
            className="compare-metric-add"
            value={addMetric}
            onChange={(e) => addMetricToSet(e.target.value)}
          >
            <option value="">+ add metric…</option>
            {availableMetrics.filter((m) => !metrics.includes(m)).map((m) => (
              <option key={m} value={m}>{metricLabel(m)}</option>
            ))}
          </select>
        </div>

        {error && <p className="app-banner-error">{error}</p>}
        {selected.length === 1 && <p className="muted compare-empty">Add one more bank to compare.</p>}
        {selected.length === 0 && <p className="muted compare-empty">No banks selected yet.</p>}

        {compare && (
          <div className="compare-table-wrap">
            <div className="compare-export-row">
              <div className="compare-view-toggle">
                <button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}>Table</button>
                <button className={view === 'radar' ? 'active' : ''} onClick={() => setView('radar')}>Radar</button>
              </div>
              <ExportCsvButton
                filename="banklens-compare.csv"
                columns={[
                  { key: 'metric', label: 'Metric', value: (m: string) => metricLabel(m) },
                  ...compare.banks.map((b) => ({
                    key: String(b.cert), label: b.name,
                    value: (m: string) => b[m] as string | number | null, source: 'fdic' as const,
                  })),
                ] as CsvColumn<string>[]}
                rows={compare.metrics}
                meta={{ sourceLabel: 'FDIC Call Reports' }}
              />
            </div>

            {view === 'radar' && (
              radarMetrics.length >= 3 ? (
                <>
                  <p className="muted compare-radar-caption">
                    Each axis is min-max normalised across just these {compare.banks.length} banks (0-100) —
                    relative standing among the selected set, not an absolute score. Shows up to {RADAR_MAX_METRICS} metrics.
                  </p>
                  <EChart option={radarOption} height={420} resetKey={`${selected.map((s) => s.cert).join(',')}-${radarMetrics.join(',')}`} ariaLabel="Normalised radar comparison" />
                </>
              ) : (
                <p className="muted">Add at least 3 metrics to render a radar view.</p>
              )
            )}

            {view === 'table' && (
              <table className="compare-table">
                <thead>
                  <tr>
                    <th className="compare-th-metric"></th>
                    {compare.banks.map((b) => (
                      <th key={b.cert} className="compare-th">
                        <Link to={`/bank/${b.cert}`}>{b.name}</Link>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {compare.metrics.map((m) => (
                    <tr key={m}>
                      <td className="compare-td-metric muted">{metricLabel(m)}</td>
                      {compare.banks.map((b) => (
                        <td key={b.cert} className="compare-td tabular">{fmtMetric(b[m])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
