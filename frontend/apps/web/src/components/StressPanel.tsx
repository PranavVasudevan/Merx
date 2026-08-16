import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { chartColors } from '../colors';
import { RECHARTS_ENTRANCE } from '../chartMotion';
import { usd } from '../metricFormat';
import { ChartError, ChartTooltipShell } from './ChartTooltip';
import type { StressResult } from '../types';
import './StressPanel.css';
import './charts.css';

function fmtB(v: number): string {
  return usd(v);
}

function WaterfallTip({ active, payload }: { active?: boolean; payload?: { payload: { label: string; delta: number; kind: string } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <ChartTooltipShell
      label={d.label}
      lines={[{ text: `${d.kind === 'loss' ? '−' : ''}${fmtB(Math.abs(d.delta))}` }]}
    />
  );
}

export function StressPanel({ cert }: { cert: number }) {
  const [loanLoss, setLoanLoss] = useState(3);
  const [outflow, setOutflow] = useState(15);
  const [rateBps, setRateBps] = useState(200);
  const [segmented, setSegmented] = useState(false);
  const [result, setResult] = useState<StressResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const colors = chartColors();

  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      const req = segmented
        ? api.segmentedStressTest(cert, 3.0, outflow, rateBps)
        : api.stressTest(cert, loanLoss, outflow, rateBps);
      req
        .then((r) => { setResult(r); setError(null); })
        .catch((e: Error) => { setResult(null); setError(e.message); })
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(t);
  }, [cert, loanLoss, outflow, rateBps, segmented]);

  const categoryLosses = useMemo(() => {
    const cats = result?.capital_waterfall.loan_loss_by_category ?? {};
    return Object.entries(cats).filter(([, v]) => v).sort((a, b) => b[1] - a[1]);
  }, [result]);

  const waterfall = useMemo(() => {
    if (!result) return [];
    const w = result.capital_waterfall;
    // reconstruct starting/ending Tier-1 capital in dollars from the ratio move (approx via rwa unknown here,
    // so show the loss components directly as a decomposition — clearer than a synthetic start/end).
    const steps = [
      { label: 'Loan losses', delta: w.loan_loss, kind: 'loss' },
      { label: 'AFS mark-to-market', delta: w.afs_mark_loss, kind: 'loss' },
      { label: 'HTM realized loss', delta: w.htm_realized_loss, kind: 'loss' },
    ];
    let base = 0;
    const rows = steps.map((s) => {
      const row = { ...s, base, };
      base += s.delta;
      return row;
    });
    rows.push({ label: 'Total capital hit', delta: w.total_capital_hit, kind: 'total', base: 0 });
    return rows;
  }, [result]);

  return (
    <div className="panel">
      <h2>Feature 16 · Capital Buffer Simulator</h2>
      <div className="stress-controls">
        <label className="stress-slider">
          <span>
            Loan losses{' '}
            {segmented
              ? <b className="tabular muted">by category (your own rate × 3)</b>
              : <b className="tabular">{loanLoss.toFixed(0)}%</b>}
          </span>
          <input type="range" min={0} max={15} step={1} value={loanLoss} disabled={segmented}
            onChange={(e) => setLoanLoss(Number(e.target.value))} />
        </label>
        <label className="stress-slider stress-segmented-toggle">
          <span>
            <input type="checkbox" checked={segmented} onChange={(e) => setSegmented(e.target.checked)} />
            {' '}Segment by loan category (C6) — this bank's own disclosed charge-off rate per
            category, 3x
          </span>
        </label>
        <label className="stress-slider">
          <span>Deposit outflow <b className="tabular">{outflow.toFixed(0)}%</b></span>
          <input type="range" min={0} max={90} step={5} value={outflow}
            onChange={(e) => setOutflow(Number(e.target.value))} />
        </label>
        <label className="stress-slider">
          <span>Rate shock <b className="tabular">+{rateBps.toFixed(0)}bps</b></span>
          <input type="range" min={0} max={500} step={25} value={rateBps}
            onChange={(e) => setRateBps(Number(e.target.value))} />
        </label>
      </div>

      {error && !result && (
        <ChartError>
          {error.includes('not permitted')
            ? 'Running the stress simulator requires the analyst role — sign in as analyst1 to use this panel.'
            : error}
        </ChartError>
      )}

      {result && (
        <>
          <div className={`stress-verdict ${
            result.passes_all === null ? 'stress-unknown' : result.passes_all ? 'stress-pass' : 'stress-fail'
          }`}>
            {result.passes_all === null
              ? 'NOT ASSESSED — no regulatory ratio could be computed for this bank (no disclosed denominator)'
              : result.passes_all
                ? (result.fully_covered
                    ? 'PASS — clears all regulatory minimums'
                    : 'PARTIAL PASS — clears minimums, but not all shocks could be applied')
                : 'FAIL — breaches a regulatory minimum'}
            {loading && <span className="muted"> · recalculating…</span>}
          </div>

          {result.legs_not_applied?.length > 0 && (
            <div className="stress-coverage-warning">
              <strong>
                {result.legs_not_applied.length === 1 ? 'One shock was' : 'Some shocks were'} not applied
                {' '}— this result is narrower than what you asked for:
              </strong>
              <ul>
                {result.legs_not_applied.map((l) => (
                  <li key={l.leg}>
                    <code>{l.leg.replace(/_/g, ' ')}</code>
                    {l.requested_pct !== undefined && ` (${l.requested_pct}% requested)`}
                    {l.requested_bps !== undefined && ` (${l.requested_bps} bps requested)`}
                    {' — '}{l.reason}
                  </li>
                ))}
              </ul>
              Unchanged ratios here mean <em>not measured</em>, not <em>unaffected</em>.
            </div>
          )}

          <div className="stress-ratio-grid">
            {(['cet1', 'tier1', 'total', 'leverage'] as const).map((k) => (
              <div className="stress-ratio" key={k}>
                <div className="stress-ratio-label muted">{k.toUpperCase()}</div>
                <div className="tabular stress-ratio-nums">
                  <span>{result.before[k] === null ? 'n/a' : `${result.before[k]}%`}</span>
                  <span className="muted"> → </span>
                  {result.after[k] === null ? (
                    <span className="muted" title="No disclosed denominator to compute this ratio against">n/a</span>
                  ) : (
                    <span className={result.passes[k] ? 'stress-good-text' : 'stress-bad-text'}>{result.after[k]}%</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={waterfall} layout="vertical" margin={{ top: 4, right: 24, left: 4, bottom: 0 }}>
              <XAxis type="number" tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false}
                tickFormatter={(v) => fmtB(v)} />
              <YAxis type="category" dataKey="label" tick={{ fill: colors.muted, fontSize: 11 }}
                axisLine={{ stroke: colors.baseline }} tickLine={false} width={130} />
              <Tooltip content={<WaterfallTip />} cursor={{ fill: 'var(--surface-2)' }} />
              <Bar dataKey="base" stackId="w" fill="transparent" />
              <Bar dataKey="delta" stackId="w" radius={[0, 4, 4, 0]} maxBarSize={20}
                {...RECHARTS_ENTRANCE}>
                {waterfall.map((d, i) => (
                  <Cell key={i} fill={d.kind === 'total' ? colors.violet : colors.critical} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

          {categoryLosses.length > 0 && (
            <div className="stress-category-breakdown">
              <div className="muted stress-category-breakdown-title">Loss decomposition by loan category</div>
              {categoryLosses.map(([label, v]) => (
                <div className="stress-category-row" key={label}>
                  <span className="stress-category-label">{label.replace(/_/g, ' ')}</span>
                  <span className="tabular stress-bad-text">{fmtB(v)}</span>
                </div>
              ))}
            </div>
          )}

          {result.liquidity.shortfall_forcing_htm_sales > 0 ? (
            <p className="stress-liq-note stress-bad-text">
              Deposit outflow ({fmtB(result.liquidity.deposit_outflow)}) exceeds available liquidity
              ({fmtB(result.liquidity.available_liquidity)}) — forces selling{' '}
              {(result.liquidity.htm_sold_fraction * 100).toFixed(0)}% of HTM securities, realizing the loss.
              This is the SVB chain.
            </p>
          ) : (
            <p className="muted stress-liq-note">
              Liquidity covers the outflow — HTM losses stay unrealized (memo: {fmtB(result.liquidity.htm_unrealized_loss_memo)} hidden).
            </p>
          )}
        </>
      )}
    </div>
  );
}
