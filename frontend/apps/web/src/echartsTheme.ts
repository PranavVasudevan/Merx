// ECharts styling derived from theme.css's own custom properties (via colors.ts),
// so there is no third hardcoded copy of the palette to drift.
//
// Separate from EChart.tsx purely so that file exports only its component — mixing
// components and helpers in one module breaks Vite's fast refresh.

import { chartColors } from './colors';

/** Axis/grid/tooltip values shared by every ECharts panel. */
export function baseEChartTheme() {
  const c = chartColors();
  return {
    textStyle: { color: c.muted, fontSize: 11 },
    axisLine: { lineStyle: { color: c.baseline } },
    splitLine: { lineStyle: { color: c.gridline } },
    tooltipBg: c.surface,
    tooltipBorder: c.border,
    tooltipText: c.text,
  };
}

/** Tooltip config matching the `.chart-tooltip` CSS the recharts panels use —
 *  same radius/padding/shadow, via `extraCssText`, so pairing this with
 *  `tooltipHtml()`'s markup renders pixel-equivalent to a recharts tooltip. */
export function tooltipStyle() {
  const t = baseEChartTheme();
  return {
    backgroundColor: t.tooltipBg,
    borderColor: t.tooltipBorder,
    borderWidth: 1,
    textStyle: { color: t.tooltipText, fontSize: 12 },
    extraCssText: 'border-radius:4px;padding:8px 12px;box-shadow:0 4px 12px rgba(0,0,0,.45),0 12px 28px rgba(0,0,0,.35);',
  };
}

/** Standard category/value axis styling. */
export function axisStyle(kind: 'category' | 'value' = 'value') {
  const t = baseEChartTheme();
  return {
    type: kind,
    axisLabel: { color: t.textStyle.color, fontSize: 11 },
    axisLine: { show: kind === 'category', lineStyle: t.axisLine.lineStyle },
    axisTick: { show: false },
    splitLine: { show: kind === 'value', lineStyle: t.splitLine.lineStyle },
  };
}

/**
 * E15 — the ECharts half of the shared tooltip contract (see ChartTooltip.tsx
 * for the full write-up). ECharts' `tooltip.formatter` takes a function that
 * returns an HTML STRING, not a React node, so it can't render
 * `ChartTooltipShell` directly — this builds the same markup (the same
 * `chart-tooltip-label` / `chart-tooltip-value tabular` / `chart-tooltip-sub
 * muted` classes `charts.css` styles once) as an HTML string instead, so an
 * ECharts tooltip looks identical to a recharts one. Before this, every
 * ECharts panel's formatter hand-built its own `<strong>...</strong><br/>...`
 * string with no shared markup or classing at all.
 */
export function tooltipHtml(label: string, lines: { text: string; muted?: boolean }[] = []): string {
  const body = lines
    .map((l) => `<div class="chart-tooltip-${l.muted ? 'sub muted' : 'value tabular'}">${l.text}</div>`)
    .join('');
  return `<div class="chart-tooltip-label">${label}</div>${body}`;
}
