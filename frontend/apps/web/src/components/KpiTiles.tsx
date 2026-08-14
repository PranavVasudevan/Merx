import { motion } from 'motion/react';
import type { BankProfile } from '../types';
import { MicroHistogram } from './MicroHistogram';
import { MetricLineageBadge } from './MetricLineageBadge';
import './KpiTiles.css';

function fmtPct(v: number | null): string {
  return v === null || v === undefined ? '—' : `${v.toFixed(1)}%`;
}

interface Tile {
  label: string;
  value: string;
  sub: string;
  wide?: boolean;
  // Population-position context: the Gold field name for /metric-distribution,
  // plus this bank's own value+percentile (already computed by peers.add_percentile_ranks,
  // just never surfaced on this page before) — never re-derived client-side.
  dist?: { metric: string; value: number | null; percentile: number | null };
  // G9 — "how is this computed?" badge, wired only where banklens_mcp.tools
  // ._METRIC_LINEAGE actually tracks the metric (a bounded subset of Gold).
  lineageMetric?: string;
}

export function KpiTiles({ profile }: { profile: BankProfile }) {
  const fp = profile.footprint;
  const tiles: Tile[] = [
    {
      label: 'Total assets', value: `$${profile.assets_b.toFixed(1)}B`, sub: profile.quarter,
      lineageMetric: 'total_assets',
    },
    {
      label: 'Uninsured deposits', value: fmtPct(profile.uninsured_deposit_pct), sub: 'run-risk signal',
      dist: {
        metric: 'uninsured_deposit_pct',
        value: profile.funding.uninsured_deposit_pct.value,
        percentile: profile.funding.uninsured_deposit_pct.percentile,
      },
      lineageMetric: 'uninsured_deposit_pct',
    },
    {
      label: 'CRE concentration', value: fmtPct(profile.cre_concentration_pct), sub: 'largest loan bucket?',
      dist: {
        metric: 'concentration_ratio_cre',
        value: profile.concentration.cre.value,
        percentile: profile.concentration.cre.percentile,
      },
    },
    {
      label: 'CET1 capital', value: fmtPct(profile.cet1_ratio), sub: 'min + buffer ~10.5%',
      dist: {
        metric: 'cet1_ratio',
        value: profile.capital.cet1.value,
        percentile: profile.capital.cet1.percentile,
      },
      lineageMetric: 'cet1_ratio',
    },
    { label: 'Peer cluster', value: profile.peer_cluster ?? '—', sub: 'behavioral, not size', wide: true },
    ...(fp ? [{
      label: 'Branch network', value: `${fp.branch_count} branches`,
      // B7: branch data is FDIC's annually-landed SOD, so it can be up to
      // ~18 months stale relative to `profile.quarter`'s financials.
      sub: `${fp.states.join(', ')} · $${(fp.total_deposits / 1e9).toFixed(1)}B deposits `
          + `· as of SOD ${fp.sod_vintage?.sod_year ?? '?'}`, wide: true,
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
          <div className="kpi-label">
            {t.label}
            {t.lineageMetric && <MetricLineageBadge cert={profile.cert} metric={t.lineageMetric} />}
          </div>
          <div className="kpi-value tabular">{t.value}</div>
          <div className="kpi-sub muted">{t.sub}</div>
          {t.dist && t.dist.value !== null && (
            <MicroHistogram metric={t.dist.metric} value={t.dist.value} percentile={t.dist.percentile} />
          )}
        </motion.div>
      ))}
    </div>
  );
}
