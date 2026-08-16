// E15 — the single source of truth for chart animation timing, mirroring
// theme.css's own `--duration-*` / `--ease-organic` custom properties.
//
// CSS `var()` isn't reachable from recharts' `animationDuration`/
// `animationEasing` props or ECharts' `animationDuration`/`animationEasing`
// option (both take plain JS numbers/strings, evaluated once, not living
// style bindings) — so unlike colors.ts's chartColors() there's no way to
// read the real computed value at runtime. These constants are instead
// hand-kept equal to theme.css's values; if theme.css's durations ever
// change, update these too.
//
// Before this file, every recharts chart in the app picked its own
// animationDuration (500/600/700ms, no shared reasoning) and every
// hand-rolled tooltip's motion.div used a bare `{ duration: 0.12 }` that
// didn't match ANY theme.css token (closest is --duration-fast at 140ms).
// Consolidated to two intentional speeds:
//   - TOOLTIP: a hover micro-interaction, tied to --duration-fast (140ms)
//   - CHART_ENTRANCE: a chart's initial draw-in, tied to --duration-slow
//     (520ms) — the middle of the old 500-700ms hand-picked range

/** theme.css --duration-fast, in seconds (for motion/react) */
export const DURATION_FAST_S = 0.14;
/** theme.css --duration-slow, in seconds (for motion/react) */
export const DURATION_SLOW_S = 0.52;
/** theme.css --duration-slow, in ms (for recharts' animationDuration / ECharts) */
export const DURATION_SLOW_MS = 520;
/** theme.css --duration-base, in ms */
export const DURATION_BASE_MS = 320;

/** theme.css --ease-organic, as a motion/react cubic-bezier array. */
export const EASE_ORGANIC = [0.85, 0, 0.15, 1] as const;

/** motion/react transition for every hover tooltip (recharts custom tooltips,
 *  the Figure/ChartTooltip family) — fade + small rise, tied to
 *  --duration-fast so it reads as the same "speed" as every other hover
 *  micro-interaction in the app (see .panel:hover, .chip in theme.css). */
export const TOOLTIP_TRANSITION = { duration: DURATION_FAST_S, ease: EASE_ORGANIC };

/** recharts' `animationDuration`/`animationEasing` props for a chart's
 *  initial draw-in (bars, lines, scatter points) — apply to every recharts
 *  series so entrance timing is consistent across the app. */
export const RECHARTS_ENTRANCE = { animationDuration: DURATION_SLOW_MS, animationEasing: 'ease-out' as const };

/** ECharts' top-level animation option, merged as a default under every
 *  chart's own option in EChart.tsx — individual charts can still override
 *  by setting their own `animationDuration`/`animationEasing`. */
export const ECHARTS_ANIMATION = {
  animation: true,
  animationDuration: DURATION_SLOW_MS,
  animationDurationUpdate: DURATION_BASE_MS,
  animationEasing: 'cubicOut' as const,
};
