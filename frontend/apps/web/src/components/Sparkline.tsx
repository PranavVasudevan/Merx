import { chartColors } from '../colors';
import './Sparkline.css';

export interface SparklineProps {
  /** Trailing series, oldest first — nulls (no landed row that quarter) are
   * skipped when drawing but keep their slot for x-position spacing. */
  values: (number | null | undefined)[];
  width?: number;
  height?: number;
  /** Marks the last non-null point with a filled dot. Default true. */
  showLastDot?: boolean;
  /** Stroke color override — defaults to a neutral chartColors() token since
   * this component has no per-metric notion of which direction is "good". */
  color?: string;
  title?: string;
}

/**
 * E12 — a minimal inline SVG sparkline for a table cell: no charting library,
 * just a `<polyline>` auto-scaled to the series' own min/max. Deliberately
 * NOT scaled against a shared/global range — the point of a table sparkline
 * is to show one row's own direction at a glance, not let two rows' glyphs be
 * compared pixel-for-pixel (a table of formatted values already does the
 * cross-row comparison).
 */
export function Sparkline({
  values, width = 56, height = 20, showLastDot = true, color, title,
}: SparklineProps) {
  const n = values.length;
  const points = values
    .map((v, i) => (v === null || v === undefined || !Number.isFinite(v) ? null : { i, v }))
    .filter((p): p is { i: number; v: number } => p !== null);

  if (points.length < 2) {
    // Not enough landed history to draw a line — an empty placeholder keeps
    // the column's width stable rather than collapsing the cell.
    return <span className="sparkline sparkline-empty" style={{ width, height }} aria-hidden="true" />;
  }

  const min = Math.min(...points.map((p) => p.v));
  const max = Math.max(...points.map((p) => p.v));
  const range = max - min || 1;
  const pad = 2;
  const x = (i: number) => (n <= 1 ? width / 2 : pad + (i / (n - 1)) * (width - pad * 2));
  const y = (v: number) => height - pad - ((v - min) / range) * (height - pad * 2);

  const path = points.map((p) => `${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
  const last = points[points.length - 1];
  const first = points[0];
  const stroke = color ?? chartColors().blue;
  const direction = last.v > first.v ? 'up' : last.v < first.v ? 'down' : 'flat';

  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={title ?? `trending ${direction}`}
    >
      {title && <title>{title}</title>}
      <polyline
        points={path}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {showLastDot && <circle cx={x(last.i)} cy={y(last.v)} r={1.8} fill={stroke} />}
    </svg>
  );
}
