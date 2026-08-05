import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { motion } from 'motion/react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { ClusterDiagnosticsResult } from '../types';
import '../components/charts.css';
import './ClustersPage.css';

const FEATURE_LABELS: Record<string, string> = {
  concentration_ratio_cre: 'CRE %',
  concentration_ratio_c_and_i: 'C&I %',
  concentration_ratio_residential_mortgage: 'Resi %',
  concentration_ratio_consumer: 'Consumer %',
  uninsured_deposit_pct: 'Uninsured %',
  core_deposit_pct: 'Core dep. %',
  loan_to_deposit_pct: 'LTD %',
};

function SilhouetteTip({ active, payload }: {
  active?: boolean; payload?: { payload: { k: number; silhouette: number; max_share: number } }[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <motion.div className="chart-tooltip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.12 }}>
      <div className="chart-tooltip-label">k = {d.k}</div>
      <div className="chart-tooltip-value tabular">silhouette {d.silhouette.toFixed(3)}</div>
      <div className="chart-tooltip-sub muted">largest cluster {(d.max_share * 100).toFixed(0)}% of population</div>
    </motion.div>
  );
}

export function ClustersPage() {
  const [diag, setDiag] = useState<ClusterDiagnosticsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const colors = chartColors();

  useEffect(() => {
    api.clusterDiagnostics()
      .then((r) => { setDiag(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, []);

  // "Best" excludes degenerate splits (one giant catch-all cluster) the same way
  // clustering.select_k() does server-side — k=2 usually "wins" on raw silhouette
  // only because it's one tight outlier group plus everything else in a single
  // 90%+ blob, not because it's a more useful clustering. Reporting that as a
  // plain silhouette win without the max_share context would misstate why k=7
  // is actually served.
  const nonDegenerate = diag?.silhouette_by_k.filter((s) => s.max_share <= 0.55) ?? [];
  const bestK = nonDegenerate.length > 0
    ? nonDegenerate.reduce((a, b) => (b.silhouette > a.silhouette ? b : a))
    : null;
  const servedRow = diag?.silhouette_by_k.find((s) => s.k === diag.served_k);
  const degenerateRows = diag?.silhouette_by_k.filter((s) => s.max_share > 0.55) ?? [];
  const features = diag?.centroids[0] ? Object.keys(diag.centroids[0].centroid) : [];

  return (
    <div className="clusters-page">
      <div className="panel">
        <h2>Behavioral clusters</h2>
        <p className="muted clusters-subtitle">
          Feature 14 governance — how the peer clustering every other page uses
          (loan mix + funding profile, k=7) was actually chosen, and where it
          disagrees with the asset-size "peer group" a bank would conventionally
          be compared against.
        </p>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {diag && (
        <>
          <div className="panel">
            <h2>Silhouette by k</h2>
            <p className="muted chart-caption clusters-k-caveat">
              The app serves k={diag.served_k} everywhere else (a fixed k is required
              for cluster ids to stay stable across quarters — see Trends and
              Briefing).{' '}
              {degenerateRows.length > 0 && (
                <>{degenerateRows.map((s) => `k=${s.k}`).join(', ')} score{degenerateRows.length === 1 ? 's' : ''} higher
                on raw silhouette but {degenerateRows.length === 1 ? 'is' : 'are'} degenerate — the largest cluster
                holds {Math.max(...degenerateRows.map((s) => s.max_share * 100)).toFixed(0)}% of the population
                (one tight group plus a giant catch-all blob), not a useful split. </>
              )}
              {bestK && bestK.k !== diag.served_k && servedRow && (
                <>Among non-degenerate options, k={bestK.k} scores highest
                ({bestK.silhouette.toFixed(3)} vs {servedRow.silhouette.toFixed(3)} at
                k={diag.served_k}) — interpretability/stability was chosen over that
                marginal gain, a real trade-off shown here rather than hidden.</>
              )}
            </p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={diag.silhouette_by_k} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <XAxis dataKey="k" tickFormatter={(k) => `k=${k}`} tick={{ fill: colors.muted, fontSize: 11 }}
                  axisLine={{ stroke: colors.baseline }} tickLine={false} />
                <YAxis tick={{ fill: colors.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={40} />
                <Tooltip content={<SilhouetteTip />} cursor={{ fill: 'var(--surface-2)' }} />
                <Bar dataKey="silhouette" radius={[3, 3, 0, 0]} animationDuration={600} animationEasing="ease-out">
                  {diag.silhouette_by_k.map((s) => (
                    <Cell key={s.k} fill={s.k === diag.served_k ? colors.blue : colors.muted}
                      fillOpacity={s.k === diag.served_k ? 1 : 0.45} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="clusters-legend">
              <span><i style={{ background: colors.blue }} /> served (k={diag.served_k})</span>
              <span><i style={{ background: colors.muted, opacity: 0.45 }} /> other k</span>
            </div>
          </div>

          <div className="panel">
            <h2>Cluster centroids — {diag.quarter}</h2>
            <div className="clusters-table-wrap">
              <table className="clusters-table">
                <thead>
                  <tr>
                    <th className="clusters-th">Cluster</th>
                    <th className="clusters-th clusters-th-right">Size</th>
                    {features.map((f) => <th key={f} className="clusters-th clusters-th-right">{FEATURE_LABELS[f] ?? f}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {diag.centroids.map((c) => (
                    <tr key={c.cluster_id}>
                      <td className="clusters-td-name">{c.label}</td>
                      <td className="tabular clusters-td-right">{c.size}</td>
                      {features.map((f) => (
                        <td key={f} className="tabular clusters-td-right">{c.centroid[f]?.toFixed(1)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <h2>Conventional (size) vs behavioral peer groups</h2>
            <p className="muted chart-caption">
              For each asset-size tier, the modal behavioral cluster is what a
              size-based peer group would implicitly assume every member looks
              like. Banks outside that modal cluster would be compared against
              peers that fund and lend very differently.
            </p>
            <div className="clusters-bucket-grid">
              {diag.size_bucket_summary.map((b) => (
                <div className="clusters-bucket" key={b.bucket}>
                  <div className="clusters-bucket-name">{b.bucket}</div>
                  <div className="muted clusters-bucket-modal">modal: {b.modal_behavioral_cluster}</div>
                  <div className="clusters-bucket-stats">
                    <span className="tabular">{b.size} banks</span>
                    <span className="tabular">{(b.modal_share * 100).toFixed(0)}% match modal</span>
                    <span className="tabular">{b.mismatch_count} mismatched</span>
                  </div>
                </div>
              ))}
            </div>

            {diag.sample_mismatches.length > 0 && (
              <>
                <h3 className="clusters-subhead">Largest mismatched banks</h3>
                <div className="clusters-mismatches">
                  {diag.sample_mismatches.map((m) => (
                    <Link className="clusters-mismatch-row" key={m.cert} to={`/bank/${m.cert}`}>
                      <span className="clusters-mismatch-name">{m.name}</span>
                      <span className="muted clusters-mismatch-detail">
                        {m.conventional_bucket} (expects {m.bucket_modal_cluster}) but behaves like{' '}
                        {m.behavioral_cluster}
                      </span>
                      <span className="tabular clusters-mismatch-assets">${m.assets_b.toFixed(1)}B</span>
                    </Link>
                  ))}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
