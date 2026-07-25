// SVG `fill`/`stroke` presentation attributes (as used by recharts) don't reliably
// resolve CSS var() across browsers, so chart color values are resolved here in JS,
// matching theme.css exactly (light default, dark override).

const LIGHT = {
  blue: '#2a78d6', green: '#008300', magenta: '#e87ba4', yellow: '#eda100',
  aqua: '#1baf7a', orange: '#eb6834', violet: '#4a3aa7', red: '#e34948',
  divNeg: '#2a78d6', divPos: '#e34948',
  good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b',
  gridline: '#e1e0d9', muted: '#898781', baseline: '#c3c2b7',
};

const DARK = {
  blue: '#3987e5', green: '#008300', magenta: '#d55181', yellow: '#c98500',
  aqua: '#199e70', orange: '#d95926', violet: '#9085e9', red: '#e66767',
  divNeg: '#3987e5', divPos: '#e66767',
  good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b',
  gridline: '#2c2c2a', muted: '#898781', baseline: '#383835',
};

export function isDarkMode(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches;
}

export function chartColors() {
  return isDarkMode() ? DARK : LIGHT;
}

export function severityColor(sev: 'low' | 'elevated' | 'high'): string {
  const c = chartColors();
  return sev === 'high' ? c.critical : sev === 'elevated' ? c.warning : c.good;
}
