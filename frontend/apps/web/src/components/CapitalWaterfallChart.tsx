import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { EChart } from './EChart';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { chartColors } from '../colors';
import type { StressResult } from '../types';

function fmtB(v: number): string {
  const sign = v < 0 ? '−' : '';
  return `${sign}$${(Math.abs(v) / 1e9).toFixed(2)}B`;
}

interface WaterfallStep {
  label: string;
  base: number;
  delta: number;
  kind: 'total' | 'loss';
}

/**
 * E3(a) — capital-bridge waterfall: starting CET1 CAPITAL (dollars) down to
 * stressed CET1 capital, via the real dollar loss legs `capital_waterfall`
 * already returns (loan_loss / afs_mark_loss / htm_realized_loss). The
 * dollar bookends (`capital_dollars.cet1_before/after`) are real numbers the
 * stress engine already computes internally — E3 is the first thing to
 * surface them, not a derived estimate.
 *
 * A leg that couldn't be applied for this bank (`legs_not_applied` — e.g. no
 * deposit total disclosed, so no forced HTM sale) draws NO segment rather
 * than a fabricated zero-height bar with no explanation.
 */
export function CapitalWaterfallChart({ result }: { result: StressResult }) {
  const steps = useMemo<WaterfallStep[] | null>(() => {
    const cd = result.capital_dollars;
    if (!cd) return null;
    const notApplied = (leg: string) =>
      result.legs_not_applied.some((l) => l.leg === leg || l.leg.startsWith(`${leg}:`));

    const legs: { label: string; value: number; leg: string }[] = [
      { label: 'Loan losses', value: result.capital_waterfall.loan_loss, leg: 'loan_loss' },
      { label: 'AFS mark-to-market', value: result.capital_waterfall.afs_mark_loss, leg: 'rate_shock' },
      { label: 'HTM realized loss', value: result.capital_waterfall.htm_realized_loss, leg: 'rate_shock' },
    ].filter((l) => l.value > 0 && !notApplied(l.leg));

    let running = cd.cet1_before;
    const out: WaterfallStep[] = [{ label: 'Starting CET1', base: 0, delta: cd.cet1_before, kind: 'total' }];
    for (const l of legs) {
      const next = Math.max(0, running - l.value);
      out.push({ label: l.label, base: next, delta: running - next, kind: 'loss' });
      running = next;
    }
    // The final bar always uses the REAL reported `cet1_after`, not the running
    // total above — they match exactly unless the shock floors capital at 0
    // (run_stress_test's own `max(0.0, ...)` clamp), in which case cet1_after
    // is the honest number and the naive running subtraction would overshoot.
    out.push({ label: 'Stressed CET1', base: 0, delta: cd.cet1_after, kind: 'total' });
    return out;
  }, [result]);

  const excludedLegs = useMemo(
    () => result.legs_not_applied.filter((l) => l.leg === 'loan_loss' || l.leg === 'rate_shock'),
    [result],
  );

  const option = useMemo<EChartsOption>(() => {
    if (!steps) return {};
    const theme = baseEChartTheme();
    const colors = chartColors();
    return {
      grid: { left: 90, right: 24, top: 24, bottom: 32, containLabel: true },
      tooltip: {
        ...tooltipStyle(),
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params];
          const bar = arr.find((p: { seriesName?: string }) => p.seriesName === 'value') as
            | { name: string; data: number; dataIndex: number }
            | undefined;
          if (!bar) return '';
          const step = steps[bar.dataIndex];
          return `<strong>${step.label}</strong><br/>${step.kind === 'total' ? fmtB(step.delta) : `−${fmtB(step.delta)}`}`;
        },
      },
      xAxis: {
        type: 'category',
        data: steps.map((s) => s.label),
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5, interval: 0 },
        axisLine: theme.axisLine,
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5, formatter: (v: number) => fmtB(v) },
        splitLine: theme.splitLine,
      },
      series: [
        {
          name: 'base',
          type: 'bar',
          stack: 'waterfall',
          silent: true,
          itemStyle: { color: 'transparent' },
          emphasis: { itemStyle: { color: 'transparent' } },
          data: steps.map((s) => s.base),
        },
        {
          name: 'value',
          type: 'bar',
          stack: 'waterfall',
          barMaxWidth: 56,
          data: steps.map((s) => s.delta),
          itemStyle: {
            color: (p: { dataIndex: number }) =>
              steps[p.dataIndex].kind === 'total' ? colors.violet : colors.critical,
            borderRadius: [3, 3, 3, 3],
          },
          label: {
            show: true,
            position: 'top',
            color: theme.textStyle.color,
            fontSize: 10.5,
            formatter: (p: { dataIndex: number }) => {
              const s = steps[p.dataIndex];
              return s.kind === 'total' ? fmtB(s.delta) : `−${fmtB(s.delta)}`;
            },
          },
        },
      ],
    };
  }, [steps]);

  if (!steps) {
    return <p className="muted stress-liq-note">Capital-dollar figures unavailable for this result.</p>;
  }

  return (
    <>
      <EChart option={option} height={260} resetKey={`${result.name}-${result.quarter}`}
        ariaLabel="Capital bridge waterfall from starting to stressed CET1" />
      {excludedLegs.length > 0 && (
        <p className="muted chart-caption">
          Not drawn — could not be applied to this bank: {excludedLegs.map((l) => l.leg.replace(/_/g, ' ')).join(', ')}.
        </p>
      )}
    </>
  );
}
