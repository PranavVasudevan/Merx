import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { motion } from 'motion/react';
import { chartColors } from '../colors';
import './charts.css';

export interface LegContribution {
  leg: string;
  label: string;
  /** Dollars of total_capital_hit that disappear when this leg is held out —
   * i.e. this leg's marginal contribution to the capital hit, including its
   * share of any interaction (e.g. the SVB chain: rate shock -> AFS/HTM
   * marks, deposit outflow -> forces the HTM sale that realizes them). */
  contribution: number;
  applicable: boolean;
}

function fmtB(v: number): string {
  return `$${(v / 1e9).toFixed(2)}B`;
}

function TornadoTip({ active, payload }: { active?: boolean; payload?: { payload: LegContribution }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">{d.label}</div>
      <div className="chart-tooltip-value tabular">{fmtB(d.contribution)}</div>
      <div className="chart-tooltip-sub muted">
        {d.applicable ? 'capital hit attributable to this leg (held-out diff)' : 'not applicable to this bank'}
      </div>
    </motion.div>
  );
}

/**
 * E3(b) — tornado chart: each shock leg's MARGINAL contribution to the total
 * capital hit, ranked. Computed by the caller as base.total_capital_hit minus
 * an "all-legs-minus-this-one" re-run's total_capital_hit (see
 * StressLabPage's `legContributions` — several real run_stress_test calls,
 * no fabricated split of one number). A leg the bank can't be shocked on
 * (`legs_not_applied`, e.g. no disclosed deposit total) shows a zero/absent
 * bar rather than an invented value, styled distinctly.
 */
export function MarginalContributionChart({ contributions }: { contributions: LegContribution[] }) {
  const colors = chartColors();
  const data = [...contributions].sort((a, b) => a.contribution - b.contribution);
  const height = Math.max(90, data.length * 34);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, left: 4, bottom: 0 }}>
        <XAxis type="number" tick={{ fill: colors.muted, fontSize: 10.5 }}
          axisLine={{ stroke: colors.baseline }} tickLine={false}
          tickFormatter={(v: number) => fmtB(v)} />
        <YAxis type="category" dataKey="label" tick={{ fill: colors.muted, fontSize: 10.5 }}
          axisLine={false} tickLine={false} width={150} />
        <Tooltip content={<TornadoTip />} cursor={{ fill: 'var(--surface-2)' }} />
        <Bar dataKey="contribution" radius={3} maxBarSize={18} animationDuration={600} animationEasing="ease-out">
          {data.map((d, i) => (
            <Cell key={i} fill={d.applicable ? colors.critical : colors.muted}
              fillOpacity={d.applicable ? 1 : 0.35} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
