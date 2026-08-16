import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { motion } from 'motion/react';
import { chartColors, resemblanceZone } from '../colors';
import { RECHARTS_ENTRANCE, EASE_ORGANIC, DURATION_SLOW_S } from '../chartMotion';
import { RISK_DISCLAIMER } from '../csvExport';
import { ChartTooltipShell } from './ChartTooltip';
import type { RiskScoreResult } from '../types';
import './RiskScorePanel.css';
import './charts.css';

function DriverTip({ active, payload }: { active?: boolean; payload?: { payload: { feature: string; value: number; contribution: number } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <ChartTooltipShell
      label={d.feature}
      lines={[
        { text: `value ${d.value}` },
        { text: `log-odds contribution ${d.contribution > 0 ? '+' : ''}${d.contribution}`, className: 'chart-tooltip-sub muted' },
      ]}
    />
  );
}

export function RiskScorePanel({ result }: { result: RiskScoreResult }) {
  const colors = chartColors();
  const pctile = result.resemblance_percentile;
  const zone = resemblanceZone(pctile);
  const data = [...result.drivers].sort((a, b) => a.contribution - b.contribution);

  return (
    <div className="panel">
      <h2>Feature 13 · Deposit-Flight Risk (model trained on {result.model_trained_on}, validated vs real bank failures)</h2>
      <div className="risk-gauge-row">
        <div className="risk-score-value tabular" style={{ color: zone.color }}>
          {pctile === null ? '—' : `${pctile.toFixed(0)}th pctile`}
        </div>
        <div className="risk-gauge-track">
          <motion.div
            className="risk-gauge-fill"
            style={{ background: zone.color }}
            initial={{ width: 0 }}
            animate={{ width: `${pctile ?? 0}%` }}
            transition={{ duration: DURATION_SLOW_S, ease: EASE_ORGANIC }}
          />
        </div>
        <span className="muted risk-zone-label">{zone.label}</span>
      </div>
      <p className="muted chart-caption">
        Decile {result.resemblance_decile ?? '—'} of 10 — rank among every bank scored this
        quarter, not a probability of failure (the model is not calibrated for that; see
        the calibration curve on <a href="/model">/model</a>).
      </p>

      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 0 }}>
          <XAxis type="number" tick={{ fill: colors.muted, fontSize: 10.5 }} axisLine={{ stroke: colors.baseline }} tickLine={false} />
          <YAxis type="category" dataKey="feature" tick={{ fill: colors.muted, fontSize: 10.5 }}
            axisLine={false} tickLine={false} width={130} />
          <Tooltip content={<DriverTip />} cursor={{ fill: 'var(--surface-2)' }} />
          <Bar dataKey="contribution" radius={3} maxBarSize={16} {...RECHARTS_ENTRANCE}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.contribution >= 0 ? colors.red : colors.blue} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="muted chart-caption">
        Red pushes risk up, blue pushes it down (log-odds contribution). {result.note}
      </p>
      <p className="muted chart-caption">{RISK_DISCLAIMER}</p>
    </div>
  );
}
