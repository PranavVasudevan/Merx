import type { BankProfile } from '../types';
import './KpiTiles.css';

function fmtPct(v: number | null): string {
  return v === null || v === undefined ? '—' : `${v.toFixed(1)}%`;
}

export function KpiTiles({ profile }: { profile: BankProfile }) {
  const tiles = [
    { label: 'Total assets', value: `$${profile.assets_b.toFixed(1)}B`, sub: profile.quarter },
    { label: 'Uninsured deposits', value: fmtPct(profile.uninsured_deposit_pct), sub: 'run-risk signal' },
    { label: 'CRE concentration', value: fmtPct(profile.cre_concentration_pct), sub: 'largest loan bucket?' },
    { label: 'CET1 capital', value: fmtPct(profile.cet1_ratio), sub: 'min + buffer ~10.5%' },
    { label: 'Peer cluster', value: profile.peer_cluster ?? '—', sub: 'behavioral, not size', wide: true },
  ];

  return (
    <div className="kpi-row">
      {tiles.map((t) => (
        <div className={`kpi-tile panel${t.wide ? ' kpi-wide' : ''}`} key={t.label}>
          <div className="kpi-label">{t.label}</div>
          <div className="kpi-value tabular">{t.value}</div>
          <div className="kpi-sub muted">{t.sub}</div>
        </div>
      ))}
    </div>
  );
}
