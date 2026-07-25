import './charts.css';

interface Props {
  active?: boolean;
  payload?: { payload: Record<string, unknown>; value?: number; name?: string; color?: string }[];
  label?: string;
  suffix?: string;
  pctileKey?: string;
}

/** A small, consistent tooltip: label, value, and (if present) a peer-percentile line. */
export function CategoricalTooltip({ active, payload, label, suffix = '', pctileKey }: Props) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  const pctile = pctileKey ? (p.payload[pctileKey] as number | null | undefined) : undefined;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label ?? p.name}</div>
      <div className="chart-tooltip-value tabular">{p.value}{suffix}</div>
      {pctile !== undefined && pctile !== null && (
        <div className="chart-tooltip-sub muted">{pctile}th percentile vs peers</div>
      )}
    </div>
  );
}
