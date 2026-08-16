import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { chartColors } from '../colors';
import { RECHARTS_ENTRANCE } from '../chartMotion';
import type { BankProfile } from '../types';
import { CategoricalTooltip } from './ChartTooltip';
import './charts.css';

export function ConcentrationChart({ profile }: { profile: BankProfile }) {
  const c = profile.concentration;
  const colors = chartColors();
  const data = [
    { label: 'CRE', value: c.cre.value ?? 0, pctile: c.cre.percentile, color: colors.blue },
    { label: 'C&I', value: c.c_and_i.value ?? 0, pctile: c.c_and_i.percentile, color: colors.green },
    { label: 'Residential', value: c.residential_mortgage.value ?? 0, pctile: c.residential_mortgage.percentile, color: colors.magenta },
    { label: 'Consumer', value: c.consumer.value ?? 0, pctile: c.consumer.percentile, color: colors.yellow },
    { label: 'Agricultural', value: c.agricultural.value ?? 0, pctile: c.agricultural.percentile, color: colors.aqua },
  ];

  return (
    <div className="panel">
      <h2>Loan composition (% of gross loans)</h2>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fill: colors.muted, fontSize: 11 }}
            axisLine={{ stroke: colors.baseline }} tickLine={false} />
          <YAxis tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false}
            width={36} unit="%" />
          <Tooltip content={<CategoricalTooltip suffix="%" pctileKey="pctile" />} cursor={{ fill: 'var(--surface-2)' }} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={54} {...RECHARTS_ENTRANCE}>
            {data.map((d) => <Cell key={d.label} fill={d.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
