import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { EChart } from '../components/EChart';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { api } from '../api';
import { chartColors } from '../colors';
import type { TreemapResult } from '../types';
import { BankSearch } from '../components/BankSearch';
import './TreemapPage.css';

function riskColor(risk: string, colors: ReturnType<typeof chartColors>): string {
  return risk === 'high' ? colors.critical : risk === 'elevated' ? colors.warning : colors.good;
}

function fmtAssets(v: number): string {
  return v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${(v / 1e6).toFixed(0)}M`;
}

export function TreemapPage() {
  const navigate = useNavigate();
  const [result, setResult] = useState<TreemapResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<'peer_cluster_label' | 'state' | 'country'>('peer_cluster_label');
  const [selected, setSelected] = useState<{ cert: number; name: string } | null>(null);

  useEffect(() => {
    api.assetTreemap(groupBy)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [groupBy]);

  // Whether the selected bank actually landed anywhere in the currently-grouped
  // treemap — "state"/"peer_cluster_label" groupings are US-only, so an EU
  // selection under either would silently not appear.
  const selectedFound = useMemo(() => {
    if (!selected || !result) return false;
    return result.groups.some((g) => g.children.some((c) => c.cert === selected.cert));
  }, [result, selected]);

  const option = useMemo(() => {
    if (!result) return {} as EChartsOption;
    const theme = baseEChartTheme();
    const colors = chartColors();
    const opt: EChartsOption = {
      tooltip: {
        ...tooltipStyle(),
        formatter: (p: unknown) => {
          const node = (Array.isArray(p) ? p[0] : p) as { data?: { name?: string; value?: number } };
          const d = node.data;
          // The treemap's own invisible root (wrapping every top-level group, total =
          // the whole population's assets) is itself a hoverable node with no name —
          // verified live: without this guard it shows a tooltip reading literally
          // "undefined $9204.0B". Every real group/bank has a name; only the root doesn't.
          if (!d || d.value === undefined || !d.name) return '';
          return `<strong>${d.name}</strong><br/>${fmtAssets(d.value)}`;
        },
      },
      series: [{
        type: 'treemap',
        roam: 'move',
        nodeClick: 'link',
        breadcrumb: { show: true, itemStyle: { color: theme.tooltipBg, borderColor: theme.tooltipBorder } },
        label: { color: '#fff', fontSize: 11, overflow: 'truncate' },
        upperLabel: { show: true, height: 24, color: theme.textStyle.color },
        itemStyle: { borderColor: colors.surface, gapWidth: 1 },
        levels: [
          { itemStyle: { borderWidth: 0, gapWidth: 2 } },
          { itemStyle: { borderColor: colors.surface, borderWidth: 2, gapWidth: 1 } },
        ],
        data: result.groups.map((g) => ({
          name: g.name,
          value: g.children.reduce((s, c) => s + c.value, 0),
          itemStyle: { color: colors.baseline },
          children: g.children.map((c) => {
            const isSelected = selected != null && c.cert === selected.cert;
            return {
              name: c.name, value: c.value, cert: c.cert,
              // A distinct border + glow, not a fill-color change, so the cell
              // still communicates its risk color while standing out from every
              // other cell of the same color.
              itemStyle: isSelected
                ? {
                    color: riskColor(c.overall_risk, colors),
                    borderColor: colors.aqua, borderWidth: 3,
                    shadowColor: colors.aqua, shadowBlur: 14,
                  }
                : { color: riskColor(c.overall_risk, colors) },
            };
          }),
        })),
      }],
    };
    return opt;
  }, [result, selected]);

  const onEvents = useMemo(() => ({
    click: (params: unknown) => {
      const p = params as { data?: { cert?: number } };
      if (p.data?.cert) navigate(`/bank/${p.data.cert}`);
    },
  }), [navigate]);

  const colors = chartColors();

  return (
    <div className="treemap-page">
      <div className="panel">
        <h2>Population by assets</h2>
        <p className="muted treemap-subtitle">
          Every bank in the population (the full US FDIC population + EU significant
          institutions), sized by assets, colored by X-Ray severity where available.
          Click a bank to open it. Group by country for the full US+EU view — behavioral
          cluster and state are US-only groupings (EU banks land in one "Unclassified"
          box under either, since EBA doesn't disclose the loan-mix data clusters need).
        </p>
        <div className="treemap-controls">
          <div className="treemap-controls-left">
            <select
              className="treemap-select"
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value as 'peer_cluster_label' | 'state' | 'country')}
            >
              <option value="peer_cluster_label">Group by behavioral cluster (US only)</option>
              <option value="state">Group by state (US only)</option>
              <option value="country">Group by country (US + EU)</option>
            </select>
            <BankSearch onSelect={(cert, name) => setSelected({ cert, name })} />
            {selected && (
              <span className="treemap-bank-chip">
                <i style={{ background: colors.aqua }} />
                {selected.name}
                <button
                  type="button"
                  className="treemap-bank-chip-clear"
                  onClick={() => setSelected(null)}
                  aria-label="Clear selected bank"
                >
                  ×
                </button>
              </span>
            )}
          </div>
          <div className="treemap-legend">
            <span className="treemap-legend-item"><i style={{ background: colors.good }} />Low risk</span>
            <span className="treemap-legend-item"><i style={{ background: colors.warning }} />Elevated</span>
            <span className="treemap-legend-item"><i style={{ background: colors.critical }} />High</span>
            <span className="treemap-legend-item"><i className="treemap-legend-swatch-outline" style={{ borderColor: colors.aqua }} />Selected</span>
          </div>
        </div>
        {selected && !selectedFound && result && (
          <p className="muted treemap-bank-not-found">
            {selected.name} isn't in this view — it may have no reported assets, or "{
              groupBy === 'country' ? 'country' : groupBy === 'state' ? 'state' : 'behavioral cluster'
            }" grouping may not apply to it (EU banks only land under "country").
          </p>
        )}
        {error && <p className="app-banner-error">{error}</p>}
        {result && (
          <EChart
            option={option}
            height={560}
            resetKey={groupBy}
            ariaLabel="Bank population treemap sized by assets, colored by risk"
            onEvents={onEvents}
          />
        )}
      </div>
    </div>
  );
}
