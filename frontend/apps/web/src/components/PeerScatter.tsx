import { useEffect, useState } from 'react';
import {
  CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import { motion } from 'motion/react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { PopulationBank } from '../types';
import './charts.css';

function Tip({ active, payload }: { active?: boolean; payload?: { payload: PopulationBank & { isTarget?: boolean } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">{d.name}{d.isTarget ? ' (selected)' : ''}</div>
      <div className="chart-tooltip-sub">CRE {d.cre_pct.toFixed(0)}% · Uninsured {d.uninsured_pct.toFixed(0)}%</div>
      <div className="chart-tooltip-sub muted">{d.cluster_label} · ${d.assets_b.toFixed(1)}B</div>
    </motion.div>
  );
}

export function PeerScatter({ cert }: { cert: number }) {
  const [banks, setBanks] = useState<PopulationBank[]>([]);
  const colors = chartColors();

  useEffect(() => {
    api.population().then((r) => setBanks(r.banks));
  }, []);

  const target = banks.find((b) => b.cert === cert);
  const others = banks.filter((b) => b.cert !== cert);

  return (
    <div className="panel">
      <h2>Peer position — CRE concentration vs uninsured deposits ({banks.length} peers)</h2>
      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 8, right: 16, left: -8, bottom: 4 }}>
          <CartesianGrid stroke={colors.gridline} />
          <XAxis type="number" dataKey="cre_pct" name="CRE %" unit="%"
            tick={{ fill: colors.muted, fontSize: 11 }} axisLine={{ stroke: colors.baseline }} tickLine={false}
            label={{ value: 'CRE concentration %', position: 'insideBottom', offset: -2, fill: colors.muted, fontSize: 11 }} />
          <YAxis type="number" dataKey="uninsured_pct" name="Uninsured %" unit="%"
            tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false}
            label={{ value: 'Uninsured deposit %', angle: -90, position: 'insideLeft', fill: colors.muted, fontSize: 11 }} />
          <ZAxis range={[24, 24]} />
          <Tooltip content={<Tip />} cursor={{ strokeDasharray: '3 3', stroke: colors.baseline }} />
          <Scatter name="Peer banks" data={others} fill={colors.muted} fillOpacity={0.45}
            animationDuration={600} animationEasing="ease-out" />
          {target && (
            <Scatter name={target.name} data={[{ ...target, isTarget: true }]} fill={colors.blue} shape="star"
              animationDuration={600} animationEasing="ease-out" />
          )}
        </ScatterChart>
      </ResponsiveContainer>
      <div className="scatter-legend">
        <span><i style={{ background: colors.muted, opacity: 0.6 }} /> Peer banks</span>
        <span><i style={{ background: colors.blue }} /> Selected bank</span>
      </div>
    </div>
  );
}
