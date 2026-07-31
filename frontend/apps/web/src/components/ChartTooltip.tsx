import { motion } from 'motion/react';
import './charts.css';

interface Props {
  active?: boolean;
  payload?: { payload: Record<string, unknown>; value?: number; name?: string; color?: string }[];
  label?: string;
  suffix?: string;
  pctileKey?: string;
}

/** A small, consistent tooltip: label, value, and (if present) a peer-percentile line.
    Every chart in the app renders its tooltip through here (or the same shape inline),
    so the quick fade+rise on mount is a single change that polishes every hover state
    in the dashboard at once. */
export function CategoricalTooltip({ active, payload, label, suffix = '', pctileKey }: Props) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  const pctile = pctileKey ? (p.payload[pctileKey] as number | null | undefined) : undefined;
  return (
    <motion.div
      className="chart-tooltip"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.12 }}
    >
      <div className="chart-tooltip-label">{label ?? p.name}</div>
      <div className="chart-tooltip-value tabular">{p.value}{suffix}</div>
      {pctile !== undefined && pctile !== null && (
        <div className="chart-tooltip-sub muted">{pctile}th percentile vs peers</div>
      )}
    </motion.div>
  );
}
