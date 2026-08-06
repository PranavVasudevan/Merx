import { motion } from 'motion/react';
import type { BankProfile } from '../types';
import './KpiTiles.css';

function fmtPct(v: number | null): string {
  return v === null || v === undefined ? '—' : `${v.toFixed(1)}%`;
}

export function KpiTiles({ profile }: { profile: BankProfile }) {
  const fp = profile.footprint;
  const tiles = [
    { label: 'Total assets', value: `$${profile.assets_b.toFixed(1)}B`, sub: profile.quarter },
    { label: 'Uninsured deposits', value: fmtPct(profile.uninsured_deposit_pct), sub: 'run-risk signal' },
    { label: 'CRE concentration', value: fmtPct(profile.cre_concentration_pct), sub: 'largest loan bucket?' },
    { label: 'CET1 capital', value: fmtPct(profile.cet1_ratio), sub: 'min + buffer ~10.5%' },
    { label: 'Peer cluster', value: profile.peer_cluster ?? '—', sub: 'behavioral, not size', wide: true },
    ...(fp ? [{
      label: 'Branch network', value: `${fp.branch_count} branches`,
      sub: `${fp.states.join(', ')} · $${(fp.total_deposits / 1e9).toFixed(1)}B deposits`, wide: true,
    }] : []),
  ];

  return (
    <div className="kpi-row">
      {tiles.map((t) => (
        <motion.div
          className={`kpi-tile panel${t.wide ? ' kpi-wide' : ''}`}
          key={t.label}
          whileHover={{ y: -2 }}
          transition={{ duration: 0.15, ease: [0.85, 0, 0.15, 1] }}
        >
          <div className="kpi-label">{t.label}</div>
          <div className="kpi-value tabular">{t.value}</div>
          <div className="kpi-sub muted">{t.sub}</div>
        </motion.div>
      ))}
    </div>
  );
}
