// Shared formatters for the population-metrics pages. Separate from
// MetricGroupPage.tsx purely so that component file exports only the component —
// mixing components and helpers in one module breaks Vite's fast refresh.

export function pct(v: number | string | null, decimals = 2): string {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number' ? `${v.toFixed(decimals)}%` : String(v);
}

export function usd(v: number | string | null): string {
  if (v === null || v === undefined || typeof v !== 'number') return '—';
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toLocaleString()}`;
}

export function fmtAssets(v: number | string | null): string {
  if (v === null || v === undefined || typeof v !== 'number') return '—';
  return v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${(v / 1e6).toFixed(0)}M`;
}

export function ratio(v: number | string | null, suffix = 'x'): string {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number' ? `${v.toFixed(2)}${suffix}` : String(v);
}

/**
 * E15 — a percentage that always shows its sign (`+1.20%` / `-3.50%`), for
 * deltas/returns where "up vs down" matters at a glance (market returns,
 * peer-relative moves) as opposed to `pct()`'s plain level formatting. Before
 * this, MarketPage.tsx and CandlestickChart.tsx each hand-rolled an
 * identical `v > 0 ? '+' : ''` helper under a different local name
 * (`fmtPct`) — consolidated here so both (and anything added later) share
 * one implementation.
 */
export function signedPct(v: number | string | null, decimals = 2): string {
  if (v === null || v === undefined) return '—';
  if (typeof v !== 'number') return String(v);
  return `${v > 0 ? '+' : ''}${v.toFixed(decimals)}%`;
}

/**
 * E15 — generic compact-number suffixing (K/M/B, no currency symbol), for
 * counts/volumes rather than dollars — e.g. CandlestickChart's trading
 * volume, or a branch/bank count. Dollar amounts should use `usd()` instead,
 * which shares the same K/M/B thresholds but adds the `$` and the (tested)
 * `$-2.50B`-style negative-sign convention.
 */
export function compactNumber(v: number | string | null, decimals = 1): string {
  if (v === null || v === undefined) return '—';
  if (typeof v !== 'number') return String(v);
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(decimals)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(decimals)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(decimals)}K`;
  return `${sign}${Math.round(abs).toLocaleString()}`;
}
