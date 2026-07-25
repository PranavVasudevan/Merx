import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { chartColors } from '../colors';
import type { RiskScoreResult } from '../types';
import './RiskScorePanel.css';
import './charts.css';

function riskZone(score: number, colors: ReturnType<typeof chartColors>): { color: string; label: string } {
  if (score >= 0.5) return { color: colors.critical, label: 'High resemblance' };
  if (score >= 0.15) return { color: colors.warning, label: 'Moderate resemblance' };
  return { color: colors.good, label: 'Low resemblance' };
}

function DriverTip({ active, payload }: { active?: boolean; payload?: { payload: { feature: string; value: number; contribution: number } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{d.feature}</div>
      <div className="chart-tooltip-value tabular">value {d.value}</div>
      <div className="chart-tooltip-sub muted">log-odds contribution {d.contribution > 0 ? '+' : ''}{d.contribution}</div>
    </div>
  );
}

export function RiskScorePanel({ result }: { result: RiskScoreResult }) {
  const colors = chartColors();
  const zone = riskZone(result.risk_score, colors);
  const data = [...result.drivers].sort((a, b) => a.contribution - b.contribution);

  return (
    <div className="panel">
      <h2>Feature 13 · Deposit-Flight Risk (model: 2022Q4, validated vs SVB/Signature/FRC)</h2>
      <div className="risk-gauge-row">
        <div className="risk-score-value tabular" style={{ color: zone.color }}>
          {(result.risk_score * 100).toFixed(1)}%
        </div>
        <div className="risk-gauge-track">
          <div className="risk-gauge-fill" style={{ width: `${Math.min(100, result.risk_score * 100)}%`, background: zone.color }} />
        </div>
        <span className="muted risk-zone-label">{zone.label}</span>
      </div>

      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 0 }}>
          <XAxis type="number" tick={{ fill: colors.muted, fontSize: 10.5 }} axisLine={{ stroke: colors.baseline }} tickLine={false} />
          <YAxis type="category" dataKey="feature" tick={{ fill: colors.muted, fontSize: 10.5 }}
            axisLine={false} tickLine={false} width={130} />
          <Tooltip content={<DriverTip />} cursor={{ fill: 'var(--surface-2)' }} />
          <Bar dataKey="contribution" radius={3} maxBarSize={16}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.contribution >= 0 ? colors.red : colors.blue} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="muted chart-caption">
        Red pushes risk up, blue pushes it down (log-odds contribution). {result.note}
      </p>
    </div>
  );
}
