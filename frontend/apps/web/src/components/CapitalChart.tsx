import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { chartColors } from '../colors';
import type { BankProfile } from '../types';
import './charts.css';

const MINIMUMS: Record<string, number> = { CET1: 7.0, 'Tier 1': 8.5, Total: 10.5, Leverage: 4.0 };

function Tip({ active, payload }: { active?: boolean; payload?: { payload: { label: string; value: number; min: number } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const pass = d.value >= d.min;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{d.label}</div>
      <div className="chart-tooltip-value tabular">{d.value.toFixed(2)}%</div>
      <div className="chart-tooltip-sub muted">min {d.min}% — {pass ? 'passes' : 'breach'}</div>
    </div>
  );
}

export function CapitalChart({ profile }: { profile: BankProfile }) {
  const cap = profile.capital;
  const colors = chartColors();
  const data = [
    { label: 'CET1', value: cap.cet1.value ?? 0, min: MINIMUMS.CET1 },
    { label: 'Tier 1', value: cap.tier1_rbc.value ?? 0, min: MINIMUMS['Tier 1'] },
    { label: 'Total', value: cap.total_rbc.value ?? 0, min: MINIMUMS.Total },
    { label: 'Leverage', value: cap.leverage.value ?? 0, min: MINIMUMS.Leverage },
  ];

  return (
    <div className="panel">
      <h2>Capital adequacy vs regulatory minimum</h2>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 34, left: 4, bottom: 0 }}>
          <XAxis type="number" tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false} unit="%" />
          <YAxis type="category" dataKey="label" tick={{ fill: colors.muted, fontSize: 11 }}
            axisLine={{ stroke: colors.baseline }} tickLine={false} width={58} />
          <Tooltip content={<Tip />} cursor={{ fill: 'var(--surface-2)' }} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={22}>
            {data.map((d) => (
              <Cell key={d.label} fill={d.value >= d.min ? colors.good : colors.critical} />
            ))}
            <LabelList dataKey="value" position="right"
              formatter={(v: unknown) => `${Number(v).toFixed(1)}%`}
              style={{ fill: colors.muted, fontSize: 11 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="muted chart-caption">
        Minimums — CET1 {MINIMUMS.CET1}% · Tier1 {MINIMUMS['Tier 1']}% · Total {MINIMUMS.Total}% · Leverage {MINIMUMS.Leverage}%.
        Green clears the bar, red breaches it.
      </p>
    </div>
  );
}
