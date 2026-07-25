import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { chartColors } from '../colors';
import type { StressResult } from '../types';
import './StressPanel.css';
import './charts.css';

function fmtB(v: number): string {
  return `$${(v / 1e9).toFixed(1)}B`;
}

function WaterfallTip({ active, payload }: { active?: boolean; payload?: { payload: { label: string; delta: number; kind: string } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{d.label}</div>
      <div className="chart-tooltip-value tabular">
        {d.kind === 'loss' ? '−' : ''}{fmtB(Math.abs(d.delta))}
      </div>
    </div>
  );
}

export function StressPanel({ cert }: { cert: number }) {
  const [loanLoss, setLoanLoss] = useState(3);
  const [outflow, setOutflow] = useState(15);
  const [rateBps, setRateBps] = useState(200);
  const [result, setResult] = useState<StressResult | null>(null);
  const [loading, setLoading] = useState(false);
  const colors = chartColors();

  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      api.stressTest(cert, loanLoss, outflow, rateBps)
        .then(setResult)
        .catch(() => setResult(null))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(t);
  }, [cert, loanLoss, outflow, rateBps]);

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
          <span>Loan losses <b className="tabular">{loanLoss.toFixed(0)}%</b></span>
          <input type="range" min={0} max={15} step={1} value={loanLoss}
            onChange={(e) => setLoanLoss(Number(e.target.value))} />
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

      {result && (
        <>
          <div className={`stress-verdict ${result.passes_all ? 'stress-pass' : 'stress-fail'}`}>
            {result.passes_all ? 'PASS — clears all regulatory minimums' : 'FAIL — breaches a regulatory minimum'}
            {loading && <span className="muted"> · recalculating…</span>}
          </div>

          <div className="stress-ratio-grid">
            {(['cet1', 'tier1', 'total', 'leverage'] as const).map((k) => (
              <div className="stress-ratio" key={k}>
                <div className="stress-ratio-label muted">{k.toUpperCase()}</div>
                <div className="tabular stress-ratio-nums">
                  <span>{result.before[k]}%</span>
                  <span className="muted"> → </span>
                  <span className={result.passes[k] ? 'stress-good-text' : 'stress-bad-text'}>{result.after[k]}%</span>
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
              <Bar dataKey="delta" stackId="w" radius={[0, 4, 4, 0]} maxBarSize={20}>
                {waterfall.map((d, i) => (
                  <Cell key={i} fill={d.kind === 'total' ? colors.violet : colors.critical} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

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
