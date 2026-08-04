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
