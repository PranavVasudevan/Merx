import type { BankProfile } from '../types';
import './StressPanel.css';

function fmtTrend(v: number | null): string {
  if (v === null) return 'n/a';
  return `${v >= 0 ? '+' : ''}${v.toFixed(3)}pp/qtr`;
}

export function CreditTrajectoryPanel({ profile }: { profile: BankProfile }) {
  const t = profile.credit_trajectory;
  return (
    <div className="panel">
      <h2>Credit-quality trajectory</h2>
      <p className="muted chart-caption stress-lab-cmp-caption">
        NPL, net charge-offs and allowance coverage are single-quarter snapshots elsewhere —
        this is the trend over this bank's own landed history ({t.trajectory_quarters} quarter
        {t.trajectory_quarters === 1 ? '' : 's'}). {t.deterioration_flag
          ? `${t.deterioration_signal_count} of ${t.deterioration_signals_available} signals moving adversely together.`
          : 'No multiple-signal deterioration detected.'}
      </p>
      <div className="stress-lab-cmp-grid">
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">NPL ratio</div>
          <div className="stress-lab-cmp-loss tabular">{t.npl_ratio_pct.value?.toFixed(2) ?? '—'}%</div>
          <div className="muted tabular" style={{ color: (t.npl_trend_pp_per_qtr ?? 0) > 0 ? 'var(--status-critical)' : 'var(--status-good)' }}>
            {fmtTrend(t.npl_trend_pp_per_qtr)}
          </div>
        </div>
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">Net charge-off rate</div>
          <div className="stress-lab-cmp-loss tabular">{t.net_charge_off_rate_pct.value?.toFixed(2) ?? '—'}%</div>
          <div className="muted tabular" style={{ color: (t.net_charge_off_trend_pp_per_qtr ?? 0) > 0 ? 'var(--status-critical)' : 'var(--status-good)' }}>
            {fmtTrend(t.net_charge_off_trend_pp_per_qtr)}
          </div>
        </div>
        <div className="stress-lab-cmp-col">
          <div className="stress-lab-cmp-label">Allowance / NPL coverage</div>
          <div className="stress-lab-cmp-loss tabular">{t.allowance_coverage_pct.value?.toFixed(0) ?? '—'}%</div>
          <div className="muted tabular" style={{ color: (t.allowance_coverage_trend_pp_per_qtr ?? 0) < 0 ? 'var(--status-critical)' : 'var(--status-good)' }}>
            {fmtTrend(t.allowance_coverage_trend_pp_per_qtr)}
          </div>
        </div>
      </div>
    </div>
  );
}
