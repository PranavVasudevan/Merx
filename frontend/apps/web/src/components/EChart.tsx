import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { GraphChart, HeatmapChart, TreemapChart } from 'echarts/charts';
import {
  GridComponent, LegendComponent, TitleComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsOption } from 'echarts';
import { onThemeChange } from '../colors';

// Tree-shaken registration. Importing the `echarts` barrel instead would pull ~1MB
// minified; registering only what's used keeps the vendor chunk to the charts this
// app actually renders. Anything new must be added here or it silently won't draw.
echarts.use([
  TreemapChart, HeatmapChart, GraphChart,
  GridComponent, TooltipComponent, VisualMapComponent, LegendComponent, TitleComponent,
  CanvasRenderer,
]);

export interface EChartProps {
  option: EChartsOption;
  height?: number;
  /** Re-created (not merged) when this changes — use for structural option swaps. */
  resetKey?: string | number;
  className?: string;
  ariaLabel?: string;
  /** ECharts event name -> handler, e.g. `{ click: (p) => ... }`. Re-bound on every
   * option/theme update so handlers always close over current props/state. */
  onEvents?: Record<string, (params: unknown) => void>;
}

/**
 * Minimal React wrapper over ECharts.
 *
 * Deliberately hand-written rather than pulling `echarts-for-react`: that package's
 * peer range caps at React 18 and it double-`init()`s under React 19 StrictMode's
 * mount->cleanup->remount, leaking a chart instance per mount. ~40 lines here avoids
 * a dependency that would fight the framework.
 *
 * Theme handling: ECharts is imperative canvas, so unlike recharts it does not pick up
 * new colors from a React re-render. It subscribes to `onThemeChange` and rebuilds on
 * an OS light/dark flip — otherwise a theme change leaves a dark canvas on a light page.
 */
export function EChart({ option, height = 420, resetKey, className, ariaLabel, onEvents }: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [themeTick, setThemeTick] = useState(0);
  // A ref, not a dependency: re-running the init effect just to rebind a handler
  // would tear down and recreate the whole chart instance on every parent render.
  const eventsRef = useRef(onEvents);
  eventsRef.current = onEvents;

  useEffect(() => onThemeChange(() => setThemeTick((t) => t + 1)), []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = echarts.init(el, undefined, { renderer: 'canvas' });
    chartRef.current = chart;
    // Bound once at init, dispatching through the ref so the latest handler always
    // runs without needing to re-init the chart when it changes identity.
    chart.on('click', (params) => eventsRef.current?.click?.(params));
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    // A panel can mount inside a collapsed/hidden container (a grid column that lays
    // out after paint), which leaves ECharts sized 0x0 with no way to recover on its
    // own. ResizeObserver catches that where the resize event can't.
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', onResize);
      chart.dispose();          // StrictMode remounts land here first — no leak
      chartRef.current = null;
    };
  }, [resetKey, themeTick]);

  useEffect(() => {
    // `true` = replace rather than merge, so removing a series actually removes it.
    chartRef.current?.setOption(option, true);
  }, [option, themeTick]);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: '100%', height }}
      role="img"
      aria-label={ariaLabel}
    />
  );
}
