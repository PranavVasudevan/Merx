// SVG `fill`/`stroke` presentation attributes (as used by recharts) and ECharts'
// canvas renderer don't resolve CSS `var()`, so chart colors have to reach them as
// concrete strings.
//
// This used to be a hand-maintained hex duplicate of theme.css — two themes x 17
// tokens. Adding ECharts would have made it three copies of 30+ tokens, with no
// mechanism keeping them honest. So the direction is inverted: read the real computed
// custom properties off :root at runtime, and derive BOTH chartColors() and the
// ECharts theme from that single source. theme.css is now the only place a color is
// written down.
//
// The literals below remain solely as a fallback for a non-DOM context (SSR, tests),
// and are never consulted in the browser.

const FALLBACK_LIGHT = {
  blue: '#2a78d6', green: '#008300', magenta: '#e87ba4', yellow: '#eda100',
  aqua: '#1baf7a', orange: '#eb6834', violet: '#4a3aa7', red: '#e34948',
  divNeg: '#2a78d6', divPos: '#e34948',
  good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b',
  gridline: '#e1e0d9', muted: '#898781', baseline: '#c3c2b7',
  seq100: '#cde2fb', seq300: '#6da7ec', seq450: '#2a78d6', seq600: '#184f95',
  surface: '#ffffff', surface2: '#f7f6f3', text: '#1a1a19', border: '#e1e0d9',
};

const FALLBACK_DARK = {
  ...FALLBACK_LIGHT,
  blue: '#3987e5', magenta: '#d55181', yellow: '#c98500', aqua: '#199e70',
  orange: '#d95926', violet: '#9085e9', red: '#e66767',
  divNeg: '#3987e5', divPos: '#e66767',
  gridline: '#2c2c2a', baseline: '#383835',
  surface: '#1c1c1b', surface2: '#232322', text: '#ecebe6', border: '#2c2c2a',
};

export type ChartColors = typeof FALLBACK_LIGHT;

// token name in theme.css -> key on the returned object
const TOKENS: Record<keyof ChartColors, string> = {
  blue: '--cat-blue', green: '--cat-green', magenta: '--cat-magenta',
  yellow: '--cat-yellow', aqua: '--cat-aqua', orange: '--cat-orange',
  violet: '--cat-violet', red: '--cat-red',
  divNeg: '--div-neg', divPos: '--div-pos',
  good: '--status-good', warning: '--status-warning',
  serious: '--status-serious', critical: '--status-critical',
  gridline: '--gridline', muted: '--text-muted', baseline: '--baseline',
  // NOTE: --seq-* are defined only in the light block of theme.css, with no dark
  // override, so these resolve to the same four blues in both themes. That was
  // already true of the old hardcoded table; reading them here at least makes it
  // visible rather than silently baked in.
  seq100: '--seq-100', seq300: '--seq-300', seq450: '--seq-450', seq600: '--seq-600',
  surface: '--surface', surface2: '--surface-2', text: '--text-primary',
  border: '--border',
};

let cached: ChartColors | null = null;

export function isDarkMode(): boolean {
  if (typeof window === 'undefined') return false;
  if (document.documentElement.dataset.skin === 'terminal') return true; // terminal skin is dark-only
  return !!window.matchMedia?.('(prefers-color-scheme: dark)').matches;
}

/** Concrete color values for chart libraries, read from theme.css's own tokens. */
export function chartColors(): ChartColors {
  if (cached) return cached;
  if (typeof window === 'undefined' || typeof getComputedStyle !== 'function') {
    return isDarkMode() ? FALLBACK_DARK : FALLBACK_LIGHT;
  }
  const style = getComputedStyle(document.documentElement);
  const fallback = isDarkMode() ? FALLBACK_DARK : FALLBACK_LIGHT;
  const out = {} as ChartColors;
  for (const [key, token] of Object.entries(TOKENS) as [keyof ChartColors, string][]) {
    out[key] = style.getPropertyValue(token).trim() || fallback[key];
  }
  cached = out;
  return out;
}

/**
 * Subscribe to theme flips — either the OS light/dark preference (classic skin) or
 * a manual skin switch (classic <-> terminal, see skin.ts). Returns an unsubscribe
 * function.
 *
 * Previously nothing listened: an OS theme change left recharts rendering stale
 * colors until something else happened to re-render. With ECharts drawing to canvas
 * that degrades from cosmetic to a dark chart sitting on a light page, so charts
 * subscribe and re-render. The skin-change listener is the same fix for the same
 * reason, for a second way the underlying CSS custom properties can change.
 */
export function onThemeChange(cb: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const handler = () => { cached = null; cb(); };
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
  mq?.addEventListener('change', handler);
  window.addEventListener('banklens:skinchange', handler);
  return () => {
    mq?.removeEventListener('change', handler);
    window.removeEventListener('banklens:skinchange', handler);
  };
}

export function severityColor(sev: 'low' | 'elevated' | 'high'): string {
  const c = chartColors();
  return sev === 'high' ? c.critical : sev === 'elevated' ? c.warning : c.good;
}

/**
 * C1: color/label zone for the deposit-flight model's resemblance PERCENTILE
 * (0-100, rank within this quarter's scored population) — never its raw
 * sigmoid output, which is not a calibrated probability of failure (see the
 * model card's calibration curve on /model, and
 * banklens_transforms.deposit_flight.population_percentile).
 */
export function resemblanceZone(percentile: number | null): { color: string; label: string } {
  const c = chartColors();
  if (percentile === null) return { color: c.muted, label: 'Not ranked' };
  if (percentile >= 90) return { color: c.critical, label: 'High resemblance' };
  if (percentile >= 70) return { color: c.warning, label: 'Moderate resemblance' };
  return { color: c.good, label: 'Low resemblance' };
}

/**
 * E14 colorblind-safety check (documented result, not just a claim):
 *
 * The 8 --cat-* tokens in theme.css/skin-terminal.css were run through a
 * throwaway Node script applying the standard Machado, Oliveira & Fluet
 * (2009) protanopia/deuteranopia simulation matrices (100% severity, linear-
 * RGB) to each color, then measuring every pairwise CIE76 Lab distance
 * (dE76) under normal vision and each simulated deficiency. No real
 * image-based simulator was run — this is a matrix-transform approximation,
 * documented as such rather than overclaimed.
 *
 * First pass (original tokens: aqua #4f8f8a, orange #b1653c,
 * violet #8a7f74) found three pairs that collapse below a dE76=10
 * "hard to tell apart at a glance" threshold:
 *   - protanopia:   aqua/violet   dE=8.6
 *   - deuteranopia: magenta/aqua  dE=8.7, magenta/violet dE=6.5,
 *                   orange/red    dE=7.1
 * Root cause: --cat-violet was barely saturated (Lab a=2.2, b=7.5 — nearly
 * neutral grey-brown), so it had little chroma in reserve on the axes
 * (lightness, blue-yellow) that survive red-green color-vision deficiency,
 * and orange/red sat close together in Lab space even under normal vision
 * (dE76=14).
 *
 * Fix: --cat-aqua -> #3d9494, --cat-orange -> #c8823f, --cat-violet ->
 * #5f6aa8 (applied in theme.css and skin-terminal.css; blue/green/magenta/
 * yellow/red unchanged). Re-running the same check against all 28 pairs
 * under normal vision, protanopia, and deuteranopia gives a worst-case
 * dE76 of 12.76 (blue vs violet, deuteranopia) — every pair now clears the
 * threshold with margin.
 *
 * Out of scope: FALLBACK_LIGHT/FALLBACK_DARK above are a separate, legacy
 * palette used only when no stylesheet is present (SSR / non-DOM test
 * contexts) — never seen by a real user in the browser, since the app is a
 * client-rendered SPA that always has theme.css loaded. They were left
 * unchecked; a colorblind-safety pass would need to cover them too if they
 * are ever pressed into a real rendering path.
 */
/** The categorical ramp, in the fixed order the dataviz tokens define. */
export function categoricalPalette(): string[] {
  const c = chartColors();
  return [c.blue, c.green, c.magenta, c.yellow, c.aqua, c.orange, c.violet, c.red];
}

/** Light-to-dark sequential ramp, for heatmaps and percentile shading. */
export function sequentialRamp(): string[] {
  const c = chartColors();
  return [c.seq100, c.seq300, c.seq450, c.seq600];
}

/**
 * Three-stop diverging ramp (low -> neutral midpoint -> high), for values with a
 * meaningful CENTER rather than a naturally-ordered low-to-high range — e.g. a
 * correlation matrix centered at 0 (see MarketPage's correlation heatmap) or a
 * percentile grid centered at the 50th percentile (see HeatmapPage). Reuses the
 * same `--div-neg`/`--div-pos` tokens theme.css already defines, rather than
 * adding a new pair — `divNeg`/`divPos` name the two ends by SIGN/DIRECTION
 * (below vs above the center), not by value judgment, so this is safe to reuse
 * for a metric like percentile standing where "low" isn't "bad."
 */
export function divergingRamp(): string[] {
  const c = chartColors();
  return [c.divNeg, c.surface2, c.divPos];
}

function hexToRgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) return [0, 0, 0];
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
}

/**
 * Continuous interpolation across an ordered ramp (e.g. `sequentialRamp()`) for a
 * choropleth or other mark where a value maps to a position on a scale, not a bucket
 * — `t` in [0,1], clamped. Linear RGB lerp between the two nearest stops; reuses
 * whichever ramp is passed in rather than defining new colors (see
 * MarketSharePage's CountyChoropleth, the first consumer that needs a genuinely
 * continuous fill instead of ECharts' own `visualMap` interpolation).
 */
export function interpolateRamp(ramp: string[], t: number): string {
  if (ramp.length === 0) return '#888888';
  const clamped = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  if (ramp.length === 1) return ramp[0];
  const scaled = clamped * (ramp.length - 1);
  const i0 = Math.floor(scaled);
  const i1 = Math.min(ramp.length - 1, i0 + 1);
  const frac = scaled - i0;
  const [r0, g0, b0] = hexToRgb(ramp[i0]);
  const [r1, g1, b1] = hexToRgb(ramp[i1]);
  const r = Math.round(r0 + (r1 - r0) * frac);
  const g = Math.round(g0 + (g1 - g0) * frac);
  const b = Math.round(b0 + (b1 - b0) * frac);
  return `rgb(${r}, ${g}, ${b})`;
}
