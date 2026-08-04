import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { EChart } from '../components/EChart';
import { baseEChartTheme, tooltipStyle } from '../echartsTheme';
import { api } from '../api';
import { chartColors } from '../colors';
import type { TreemapResult } from '../types';
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
  const [groupBy, setGroupBy] = useState<'peer_cluster_label' | 'state'>('peer_cluster_label');

  useEffect(() => {
    api.assetTreemap(groupBy)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [groupBy]);

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
          children: g.children.map((c) => ({
            name: c.name, value: c.value, cert: c.cert,
            itemStyle: { color: riskColor(c.overall_risk, colors) },
          })),
        })),
      }],
    };
    return opt;
  }, [result]);

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
          Every bank in the $1B–$250B slice, sized by assets, grouped by behavioral
          cluster or state, and colored by X-Ray severity. Click a bank to open it.
        </p>
        <div className="treemap-controls">
          <select
            className="treemap-select"
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as 'peer_cluster_label' | 'state')}
          >
            <option value="peer_cluster_label">Group by behavioral cluster</option>
            <option value="state">Group by state</option>
          </select>
          <div className="treemap-legend">
            <span className="treemap-legend-item"><i style={{ background: colors.good }} />Low risk</span>
            <span className="treemap-legend-item"><i style={{ background: colors.warning }} />Elevated</span>
            <span className="treemap-legend-item"><i style={{ background: colors.critical }} />High</span>
          </div>
        </div>
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
