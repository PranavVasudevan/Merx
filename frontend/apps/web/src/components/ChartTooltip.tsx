import { motion } from 'motion/react';
import { TOOLTIP_TRANSITION } from '../chartMotion';
import './charts.css';

/**
 * ============================================================================
 * E15 — the chart contract. Read this before adding a new chart component.
 * ============================================================================
 *
 * BankLens deliberately uses THREE charting libraries (recharts for SVG line/
 * bar/scatter, ECharts for canvas heatmap/treemap/graph/sankey/boxplot,
 * lightweight-charts for the OHLCV candlestick), each the right tool for its
 * job — this file does NOT try to collapse them into one library. What it
 * does unify is the *contract* every chart honors, regardless of which
 * library renders it:
 *
 * 1. TOOLTIP — one presentational shell (`ChartTooltipShell` below), fed by
 *    each library's own adapter mechanism:
 *      - recharts: pass a `content` render-prop that returns
 *        `<ChartTooltipShell .../>` (or the `CategoricalTooltip` convenience
 *        wrapper for the common label+value(+peer-percentile) shape). See
 *        ConcentrationChart.tsx, CapitalChart.tsx, StressPanel.tsx.
 *      - ECharts: `tooltip.formatter` takes a function returning an HTML
 *        STRING, not a React node, so it can't call ChartTooltipShell
 *        directly — use `tooltipHtml()` from `echartsTheme.ts` instead, which
 *        builds a string with the exact same `chart-tooltip*` classes (styled
 *        once, in `charts.css`) so the rendered result matches pixel-for-
 *        pixel. See GroupComparisonChart.tsx, StressSurfaceChart.tsx.
 *      - lightweight-charts: has no tooltip primitive at all — it exposes a
 *        crosshair-move event and expects the caller to render whatever it
 *        wants. A floating tooltip that trails the cursor is also a poor fit
 *        for OHLCV specifically: a candle has 5 co-equal fields (O/H/L/C/Vol)
 *        that read better as a fixed row than a stacked label/value/sub
 *        tooltip. CandlestickChart.tsx's "crosshair readout" bar (a docked
 *        strip above the chart, `.candle-crosshair-readout`) is the
 *        deliberate adapter for this library — same `tabular` number styling
 *        as everywhere else, different layout because the data shape is
 *        different. Two ad hoc canvas+d3 maps (CountyChoropleth,
 *        BranchMapCanvas) that aren't one of the three libraries but still
 *        need a hover tooltip reuse `chart-tooltip`/`chart-tooltip-label`/
 *        `chart-tooltip-sub` directly with absolute positioning, rather than
 *        each keeping its own bespoke tooltip CSS.
 *
 * 2. NUMBER/PERCENT/CURRENCY FORMATTING — `metricFormat.ts`'s `pct()`,
 *    `usd()`, `fmtAssets()`, `ratio()`, `signedPct()`, `compactNumber()`. No
 *    chart should hand-roll `.toFixed()` + manual `%`/`$` string
 *    concatenation — several did before E15 (MarketPage's fmtPct/fmtRatio/
 *    fmtUsd, TreemapPage's fmtAssets, CandlestickChart's fmtVolume/fmtPct,
 *    three separate fmtB()s) and were switched over.
 *
 * 3. AXIS/CAPTION CONVENTION — axis ticks: `{ fill: colors.muted, fontSize:
 *    10.5-11 }` for recharts, `axisStyle()`/`baseEChartTheme()` (in
 *    echartsTheme.ts) for ECharts. Captions: a `<p className="muted
 *    chart-caption">` below the chart (`.chart-caption` in charts.css).
 *
 * 4. EMPTY/ERROR STATE — `<ChartEmpty>` / `<ChartError>` below, instead of
 *    each chart writing its own ad hoc "no data" `<p className="muted">`.
 *    `ChartError` also fixed a real bug in the process: `.app-banner-error`
 *    (used by ~30 page-level fetch-error banners) had lost its base CSS rule
 *    — only two page-scoped override rules referencing it survived — so
 *    those banners were rendering unstyled. Restored in theme.css.
 *
 * 5. ANIMATION — `chartMotion.ts`'s `TOOLTIP_TRANSITION` (hover
 *    micro-interactions), `RECHARTS_ENTRANCE` (recharts series draw-in) and
 *    `ECHARTS_ANIMATION` (merged as ECharts defaults in EChart.tsx) — all
 *    tied to theme.css's `--duration-fast`/`--duration-slow`/`--ease-organic`
 *    tokens rather than each chart picking its own ms value.
 * ============================================================================
 */

export interface TooltipLine {
  text: React.ReactNode;
  /** Defaults to the primary "value" line style; pass 'chart-tooltip-sub muted'
   *  (or 'chart-tooltip-sub' without muted) for a secondary/detail line. */
  className?: string;
  style?: React.CSSProperties;
}

/**
 * The universal presentational tooltip: a label line plus zero or more value/
 * detail lines, in the fixed `.chart-tooltip` shell every chart in the app
 * now shares. Each chart's own `content`/`formatter` adapter is responsible
 * only for picking WHAT to show (its own data shape) — never for the
 * motion/wrapper/class boilerplate, which lives here exactly once.
 */
export function ChartTooltipShell({ label, lines }: { label: React.ReactNode; lines?: TooltipLine[] }) {
  return (
    <motion.div
      className="chart-tooltip"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={TOOLTIP_TRANSITION}
    >
      <div className="chart-tooltip-label">{label}</div>
      {lines?.map((l, i) => (
        // eslint-disable-next-line react/no-array-index-key -- lines are a fixed, order-stable list per render
        <div key={i} className={l.className ?? 'chart-tooltip-value tabular'} style={l.style}>{l.text}</div>
      ))}
    </motion.div>
  );
}

interface CategoricalTooltipProps {
  active?: boolean;
  payload?: { payload: Record<string, unknown>; value?: number; name?: string; color?: string }[];
  label?: string;
  suffix?: string;
  pctileKey?: string;
}

/** Convenience wrapper over `ChartTooltipShell` for the common shape: a
 *  label, one value(+suffix), and (if present) a peer-percentile sub-line.
 *  Used directly as a recharts `<Tooltip content={<CategoricalTooltip .../>} />`
 *  by any bar/line chart whose tooltip needs nothing more chart-specific
 *  than that. See ConcentrationChart.tsx. */
export function CategoricalTooltip({ active, payload, label, suffix = '', pctileKey }: CategoricalTooltipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  const pctile = pctileKey ? (p.payload[pctileKey] as number | null | undefined) : undefined;
  const lines: TooltipLine[] = [{ text: `${p.value}${suffix}` }];
  if (pctile !== undefined && pctile !== null) {
    lines.push({ text: `${pctile}th percentile vs peers`, className: 'chart-tooltip-sub muted' });
  }
  return <ChartTooltipShell label={label ?? p.name} lines={lines} />;
}

/** A chart-local "nothing to show" message — the shared replacement for each
 *  chart's own ad hoc `<p className="muted">...</p>`. Use for a genuinely
 *  empty/insufficient result (not an error — see `ChartError`). */
export function ChartEmpty({ children }: { children: React.ReactNode }) {
  return <p className="muted chart-empty">{children}</p>;
}

/** A chart-local error message, styled the same as the app's page-level
 *  `.app-banner-error` fetch-error banners (restored in theme.css — see the
 *  contract note above) so a chart that fails to load reads as unambiguously
 *  an ERROR rather than blending into the surrounding muted copy. */
export function ChartError({ children }: { children: React.ReactNode }) {
  return <p className="app-banner-error chart-error">{children}</p>;
}
