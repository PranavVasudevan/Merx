import { useEffect, useMemo, useState } from 'react';
import type { EChartsOption } from 'echarts';
import { api } from '../api';
import { chartColors } from '../colors';
import { baseEChartTheme, tooltipHtml, tooltipStyle } from '../echartsTheme';
import type { BankTrendsResult } from '../types';
import { EChart } from './EChart';
import { ChartEmpty, ChartError } from './ChartTooltip';
import './charts.css';
import './CompositionSankeyPanel.css';

// E11 — composition MIGRATION, not levels. FundingPage/CreditPage already show
// deposit-type and loan-category mix as point-in-time percentages (population-wide
// tables); nothing shows how one bank's own mix shifted quarter over quarter. This
// renders that shift as an ECharts Sankey: one column of nodes per landed quarter,
// one node per category, links between a category's consecutive-quarter nodes sized
// by that category's share. It is NOT literal dollars moving between categories —
// there is no cross-category flow in the underlying data, only each category's own
// share changing over time — so links only ever connect the SAME category across
// adjacent quarters, never different categories to each other.

type MixKind = 'deposits' | 'loans';

interface Category {
  key: string;       // BankTrendPoint field name, or 'other_deposits' (synthetic residual)
  label: string;
  color: string;
}

// The 8 DISJOINT loan-category leaves gold.concentration_ratios()/LOAN_CATEGORIES
// computes as % of gross loans — the same set Feature 11 ranks over, so these sum
// to ~100% of a bank's gross loan book each quarter (rounding aside).
const LOAN_CATEGORIES: Omit<Category, 'color'>[] = [
  { key: 'concentration_ratio_construction', label: 'Construction' },
  { key: 'concentration_ratio_multifamily', label: 'Multifamily' },
  { key: 'concentration_ratio_nonfarm_nonres', label: 'Nonfarm nonres. CRE' },
  { key: 'concentration_ratio_residential_mortgage', label: 'Residential mortgage' },
  { key: 'concentration_ratio_farmland', label: 'Farmland' },
  { key: 'concentration_ratio_agricultural', label: 'Agricultural' },
  { key: 'concentration_ratio_c_and_i', label: 'C&I' },
  { key: 'concentration_ratio_consumer', label: 'Consumer' },
];

// Deposit-type mix has no ready-made disjoint leaf set the way loans do: Gold
// exposes core_deposit_pct and brokered_deposit_pct as two independently-computed
// ratios (FDIC's COREDEP definition already nets brokered and jumbo time deposits
// out of "core"), not a full partition. `other_deposits` below is a residual —
// total minus those two reported components, clamped at 0 — so the three bars
// always sum to ~100%. It is disclosed as a computed residual, not a directly
// reported FDIC field, in the panel's caption.
const OTHER_DEPOSITS_KEY = 'other_deposits';

function depositCategories(): Omit<Category, 'color'>[] {
  return [
    { key: 'core_deposit_pct', label: 'Core deposits' },
    { key: 'brokered_deposit_pct', label: 'Brokered deposits' },
    { key: OTHER_DEPOSITS_KEY, label: 'Other / non-core' },
  ];
}

interface SankeyNodeDatum {
  name: string;
  quarter: string;
  categoryLabel: string;
  pct: number;
  itemStyle: { color: string };
  label: { formatter: () => string };
}

interface SankeyLinkDatum {
  source: string;
  target: string;
  value: number;
  fromPct: number;
  toPct: number;
  categoryLabel: string;
}

function buildSankey(
  trends: BankTrendsResult, categories: Category[],
  valueOf: (quarter: string, cat: Category) => number | null,
): { nodes: SankeyNodeDatum[]; links: SankeyLinkDatum[] } {
  const nodes: SankeyNodeDatum[] = [];
  const links: SankeyLinkDatum[] = [];
  const quarters = trends.quarters;

  for (const cat of categories) {
    let prevQuarter: string | null = null;
    let prevPct: number | null = null;
    for (const q of quarters) {
      const pct = valueOf(q, cat);
      if (pct === null) {
        // No fabricated interpolation across a landing gap — the chain simply
        // breaks here and resumes if/when the category reappears.
        prevQuarter = null;
        prevPct = null;
        continue;
      }
      const name = `${q}|${cat.key}`;
      nodes.push({
        name, quarter: q, categoryLabel: cat.label, pct,
        itemStyle: { color: cat.color },
        label: { formatter: () => cat.label },
      });
      if (prevQuarter !== null && prevPct !== null) {
        links.push({
          source: `${prevQuarter}|${cat.key}`, target: name,
          // Link width = average of the two endpoints' own share, so a node's
          // total incident width tracks its real quarter-over-quarter share —
          // not a literal transferred amount (see file header).
          value: Math.max(0.01, (prevPct + pct) / 2),
          fromPct: prevPct, toPct: pct, categoryLabel: cat.label,
        });
      }
      prevQuarter = q;
      prevPct = pct;
    }
  }
  return { nodes, links };
}

export function CompositionSankeyPanel({ cert }: { cert: number }) {
  const [trends, setTrends] = useState<BankTrendsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<MixKind>('deposits');
  const colors = chartColors();

  useEffect(() => {
    setTrends(null);
    setError(null);
    api.bankTrends(cert).then(setTrends).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [cert]);

  const categories = useMemo<Category[]>(() => {
    if (kind === 'loans') {
      const palette = [colors.orange, colors.blue, colors.violet, colors.green,
        colors.aqua, colors.yellow, colors.magenta, colors.red];
      return LOAN_CATEGORIES.map((c, i) => ({ ...c, color: palette[i % palette.length] }));
    }
    const palette = [colors.green, colors.red, colors.muted];
    return depositCategories().map((c, i) => ({ ...c, color: palette[i] }));
  }, [kind, colors]);

  const { nodes, links, quartersCovered } = useMemo(() => {
    if (!trends) return { nodes: [] as SankeyNodeDatum[], links: [] as SankeyLinkDatum[], quartersCovered: 0 };
    const valueOf = (quarter: string, cat: Category): number | null => {
      const point = trends.series.find((s) => s.quarter === quarter);
      if (!point) return null;
      if (cat.key === OTHER_DEPOSITS_KEY) {
        const core = point.core_deposit_pct;
        const brokered = point.brokered_deposit_pct;
        if (typeof core !== 'number' || typeof brokered !== 'number') return null;
        return Math.max(0, Math.round((100 - core - brokered) * 10) / 10);
      }
      const v = point[cat.key];
      return typeof v === 'number' ? Math.round(v * 10) / 10 : null;
    };
    const { nodes: n, links: l } = buildSankey(trends, categories, valueOf);
    return { nodes: n, links: l, quartersCovered: trends.quarters.length };
  }, [trends, categories]);

  const option = useMemo<EChartsOption>(() => {
    const theme = baseEChartTheme();
    return {
      tooltip: {
        ...tooltipStyle(),
        formatter: (params: unknown) => {
          const p = params as { dataType: 'node' | 'edge'; data: SankeyNodeDatum | SankeyLinkDatum };
          if (p.dataType === 'node') {
            const d = p.data as SankeyNodeDatum;
            return tooltipHtml(d.categoryLabel, [{ text: `${d.quarter}: ${d.pct.toFixed(1)}%` }]);
          }
          const d = p.data as SankeyLinkDatum;
          return tooltipHtml(d.categoryLabel, [{ text: `${d.fromPct.toFixed(1)}% → ${d.toPct.toFixed(1)}%` }]);
        },
      },
      series: [{
        type: 'sankey',
        data: nodes,
        links,
        emphasis: { focus: 'adjacency' },
        nodeAlign: 'left',
        nodeGap: 10,
        nodeWidth: 14,
        lineStyle: { color: 'gradient', opacity: 0.35, curveness: 0.5 },
        label: { color: theme.textStyle.color, fontSize: 10.5 },
      }],
    };
  }, [nodes, links]);

  const legend = useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of categories) seen.set(c.label, c.color);
    return Array.from(seen.entries());
  }, [categories]);

  const height = Math.max(320, categories.length * 46);

  return (
    <div className="panel">
      <div className="composition-sankey-header">
        <h2>Composition migration — {kind === 'deposits' ? 'deposit mix' : 'loan mix'} across landed quarters</h2>
        <select
          className="composition-sankey-select"
          value={kind}
          onChange={(e) => setKind(e.target.value as MixKind)}
          title="Which mix to trace across this bank's landed quarter history"
        >
          <option value="deposits">Deposit-type mix</option>
          <option value="loans">Loan-category mix</option>
        </select>
      </div>
      {error && <ChartError>{error}</ChartError>}
      {!error && !trends && <ChartEmpty>Loading quarter history…</ChartEmpty>}
      {trends && quartersCovered < 2 && (
        <ChartEmpty>This bank has fewer than two landed quarters, so there's no migration to trace yet.</ChartEmpty>
      )}
      {trends && quartersCovered >= 2 && (
        <>
          <EChart
            option={option}
            height={height}
            resetKey={`${cert}-${kind}-${quartersCovered}`}
            ariaLabel={`Sankey diagram of ${kind === 'deposits' ? 'deposit-type' : 'loan-category'} mix migration across ${trends.name}'s landed quarters, from ${trends.quarters[0]} to ${trends.quarters[trends.quarters.length - 1]}`}
          />
          <div className="scatter-legend">
            {legend.map(([label, color]) => (
              <span key={label}><i style={{ background: color }} /> {label}</span>
            ))}
          </div>
          <p className="muted chart-caption">
            Each column is a landed quarter ({trends.quarters[0]} → {trends.quarters[trends.quarters.length - 1]}); each
            node is one category's share that quarter. Flows connect the SAME category across consecutive quarters —
            this shows composition changing over time, not money moving between categories.
            {kind === 'deposits' && ' "Other / non-core" is a computed residual (100% − core − brokered), not a directly reported FDIC field.'}
            {' '}A gap in a category's line means it wasn't landed/reported that quarter, not zero.
          </p>
        </>
      )}
    </div>
  );
}
