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
