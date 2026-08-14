import { useEffect, useState } from 'react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { HistogramBin } from '../types';
import './MicroHistogram.css';

// Population histograms are the same for every bank viewed in the same quarter —
// only the marker position (this bank's own value) differs per bank. Caching by
// "metric" here avoids re-fetching the identical distribution every time a user
// browses from one bank page to the next.
const histogramCache = new Map<string, Promise<HistogramBin[]>>();

function fetchHistogram(metric: string): Promise<HistogramBin[]> {
  let cached = histogramCache.get(metric);
  if (!cached) {
    cached = api.metricDistribution(metric, 16).then((r) => r.histogram);
    cached.catch(() => histogramCache.delete(metric)); // don't cache a failure forever
    histogramCache.set(metric, cached);
  }
  return cached;
}

function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

export interface MicroHistogramProps {
  /** Gold field name — same key `/metric-distribution` and `percentile_rank_<metric>` use. */
  metric: string;
  /** This bank's own value for `metric`, from the same Gold row the percentile came from. */
  value: number | null;
  /** Precomputed `percentile_rank_<metric>` from the Gold layer — exact, not estimated. */
  percentile: number | null;
}

/**
 * Tiny inline sparkline-style histogram for a KPI tile: shows the population's
 * shape for this metric with a marker at the bank's own value, so a raw number
 * like "CET1 12.4%" isn't left to speak for itself — is that high, low, typical?
 */
export function MicroHistogram({ metric, value, percentile }: MicroHistogramProps) {
  const [hist, setHist] = useState<HistogramBin[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setHist(null);
    setFailed(false);
    fetchHistogram(metric)
      .then((h) => { if (live) setHist(h); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [metric]);

  if (value === null || value === undefined || failed) return null;
  if (!hist || hist.length === 0) {
    return <div className="micro-histogram-slot" aria-hidden="true" />;
  }

  const colors = chartColors();
  const max = Math.max(1, ...hist.map((b) => b.count));
  const w = 96;
  const h = 20;
  const gap = 1;
  const barW = (w - gap * (hist.length - 1)) / hist.length;
  const lo = hist[0].lower;
  const hi = hist[hist.length - 1].upper;
  const clamped = Math.min(Math.max(value, lo), hi);
  const markerX = hi > lo ? ((clamped - lo) / (hi - lo)) * w : w / 2;
  const pctLabel = percentile !== null ? `${ordinal(Math.round(percentile))} percentile` : null;

  return (
    <div className="micro-histogram">
      <svg
        viewBox={`0 0 ${w} ${h + 3}`}
        width={w}
        height={h + 3}
        role="img"
        aria-label={`Population distribution for this metric${pctLabel ? `; this bank is at the ${pctLabel}` : ''}`}
      >
        {hist.map((b, i) => {
          const barH = Math.max(1, (b.count / max) * h);
          return (
            <rect
              key={i}
              x={i * (barW + gap)}
              y={h - barH}
              width={barW}
              height={barH}
              fill={colors.baseline}
            />
          );
        })}
        <line x1={markerX} x2={markerX} y1={0} y2={h} stroke={colors.critical} strokeWidth={1.5} />
        <circle cx={markerX} cy={h + 1.5} r={1.5} fill={colors.critical} />
      </svg>
      {pctLabel && <span className="micro-histogram-label muted">{pctLabel}</span>}
    </div>
  );
}
