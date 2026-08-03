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

/** Tooltip config matching the `.chart-tooltip` CSS the recharts panels use. */
export function tooltipStyle() {
  const t = baseEChartTheme();
  return {
    backgroundColor: t.tooltipBg,
    borderColor: t.tooltipBorder,
    borderWidth: 1,
    textStyle: { color: t.tooltipText, fontSize: 12 },
    extraCssText: 'border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.12);',
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
