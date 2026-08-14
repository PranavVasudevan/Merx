import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { EChart } from './EChart';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { chartColors } from '../colors';
import type { StressSurfaceResult } from '../types';

/**
 * E3(c) — CET1 surface: every cell is a REAL run_stress_test() result from
 * the (deposit_outflow x rate_shock) grid `run_stress_surface` computes
 * server-side (see tools.py / bridge_server.py's /banks/stress-test-surface)
 * — no interpolation between cells, no fabricated values. The regulatory
 * CET1 minimum (stress.MINIMUMS['cet1'], the real Basel III floor incl. the
 * capital conservation buffer this app uses everywhere else) is drawn as a
 * hard color-band boundary via a piecewise visualMap, so the pass/fail
 * contour is the literal edge between two colors rather than a separately
 * interpolated line.
 */
export function StressSurfaceChart({ result }: { result: StressSurfaceResult }) {
  const option = useMemo<EChartsOption>(() => {
    const theme = baseEChartTheme();
    const colors = chartColors();
    const min = result.cet1_minimum_pct;
    const data: [number, number, number][] = result.cells.map((c) => [
      result.rate_shock_values.indexOf(c.rate_shock_bps),
      result.deposit_outflow_values.indexOf(c.deposit_outflow_pct),
      c.cet1_after,
    ]);
    const opt: EChartsOption = {
      grid: { left: 70, right: 24, top: 16, bottom: 90, containLabel: false },
      tooltip: {
        ...tooltipStyle(),
        formatter: (p: unknown) => {
          const cell = (Array.isArray(p) ? p[0] : p) as { data?: [number, number, number] };
          if (!cell.data) return '';
          const [x, y, v] = cell.data;
          const rate = result.rate_shock_values[x];
          const outflow = result.deposit_outflow_values[y];
          const pass = v >= min;
          return `Deposit outflow ${outflow}%, rate shock +${rate}bps<br/>`
            + `CET1 after: <strong>${v.toFixed(2)}%</strong> — ${pass ? 'clears' : 'breaches'} the ${min}% minimum`;
        },
      },
      xAxis: {
        type: 'category',
        name: 'Rate shock (bps)',
        nameLocation: 'middle', nameGap: 32, nameTextStyle: { color: theme.textStyle.color, fontSize: 11 },
        data: result.rate_shock_values.map((v) => `+${v}`),
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5 },
        axisLine: theme.axisLine, splitArea: { show: true },
      },
      yAxis: {
        type: 'category',
        name: 'Deposit outflow (%)',
        nameLocation: 'middle', nameGap: 48, nameTextStyle: { color: theme.textStyle.color, fontSize: 11 },
        data: result.deposit_outflow_values.map((v) => `${v}%`),
        axisLabel: { color: theme.textStyle.color, fontSize: 10.5 },
        axisLine: theme.axisLine, splitArea: { show: true },
      },
      visualMap: {
        type: 'piecewise',
        orient: 'horizontal',
        left: 'center', bottom: 0,
        textStyle: { color: theme.textStyle.color, fontSize: 10.5 },
        // The hard edge at `min` IS the regulatory-minimum contour: everything
        // below is unambiguously colored as a breach, everything above passes,
        // with one extra warning band just above the line for "close to it".
        pieces: [
          { min: 0, max: min, color: colors.critical, label: `< ${min}% (breach)` },
          { min: min, max: min + 2, color: colors.warning, label: `${min}–${min + 2}% (thin buffer)` },
          { min: min + 2, color: colors.good, label: `> ${min + 2}%` },
        ],
      },
      series: [{
        type: 'heatmap',
        data,
        emphasis: { itemStyle: { borderColor: colors.text, borderWidth: 1.5 } },
        itemStyle: { borderColor: colors.surface, borderWidth: 1 },
      }],
    };
    return opt;
  }, [result]);

  return (
    <>
      <EChart option={option} height={340}
        resetKey={`${result.cert}-${result.loan_loss_pct}-${result.steps}`}
        ariaLabel="Stressed CET1 surface across deposit outflow and rate shock" />
      <p className="muted chart-caption">
        Loan losses held fixed at {result.loan_loss_pct}% across the grid — only deposit
        outflow and rate shock vary. Regulatory minimum: CET1 ≥ {result.cet1_minimum_pct}%
        (Basel III, incl. capital conservation buffer).
        {result.fallback_duration_used && (
          <> This bank's AFS/HTM duration falls back to the 4y/6y default (no maturity-bucket
            data disclosed) — every cell's rate-shock leg carries that assumption.</>
        )}
      </p>
      {result.legs_not_applied.length > 0 && (
        <div className="stress-coverage-warning">
          <strong>Part of this grid reflects fewer shocks than requested:</strong>
          <ul>
            {result.legs_not_applied.map((l) => (
              <li key={l.leg}><code>{l.leg.replace(/_/g, ' ')}</code> — {l.reason}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
